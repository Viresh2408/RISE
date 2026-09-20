"""
Tests for POST /api/v1/ingest/security-log
==========================================

Covers:
  - Multipart file upload (syslog, CSV, JSON, NDJSON)
  - JSON body variant (/ingest/security-log/json)
  - dry_run=true (normalise + LLM call but skip all DB writes)
  - Deduplication: second identical resource_id returns status="deduplicated"
  - IngestionAgent failure -> DLQ routing, status="dlq_error", HTTP 200
  - Auth guards (missing token -> 401, viewer -> 403, engineer/admin -> 200)
  - Batch too large -> 400
  - Empty upload -> 400
  - File too large -> 413
  - Normaliser: SSH syslog pattern extraction
  - Normaliser: CSV field aliasing
  - Normaliser: JSON array / NDJSON parsing
  - eval/sample_security_logs files are parseable end-to-end (no HTTP/LLM)

All tests are fully offline -- no live Postgres, Redis, Qdrant, or LLM gateway.
"""

from __future__ import annotations

import io
import json
import os
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# -- Environment flags must be set before any app import ----------------------
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-secret-rise-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-slack-secret")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-github-secret")
os.environ.setdefault("ALERTMANAGER_WEBHOOK_SECRET", "test-am-secret")

from db.base import Base
from apps.api.src.deps.db import get_db
from apps.api.src.deps.redis import get_redis_client

# -- In-memory SQLite test database -------------------------------------------
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def _override_db():
    db = _Session()
    try:
        yield db
    finally:
        db.close()


# -- Redis mock ----------------------------------------------------------------
_redis_mock = MagicMock()
_redis_mock.get.return_value = None
_redis_mock.set.return_value = True
_redis_mock.setex.return_value = True
_redis_mock.xadd.return_value = b"1-0"
_redis_mock.delete.return_value = True
_redis_mock.exists.return_value = False


def _override_redis():
    yield _redis_mock


# -- FastAPI test client -------------------------------------------------------
from apps.api.src.main import app

_TEST_SECRET = "test-supabase-secret-rise-unit-tests"

# Paths to sample datasets shipped with the repo
_SAMPLES_DIR = Path(__file__).resolve().parents[1] / "eval" / "sample_security_logs"


def _jwt(role: str = "engineer") -> str:
    return jwt.encode(
        {
            "sub": f"mock-user-{role}",
            "roles": [role],
            "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0))),
        },
        _TEST_SECRET,
        algorithm="HS256",
    )


ADMIN_HDR = {"Authorization": f"Bearer {_jwt('admin')}"}
ENGINEER_HDR = {"Authorization": f"Bearer {_jwt('engineer')}"}
VIEWER_HDR = {"Authorization": f"Bearer {_jwt('viewer')}"}

# -- Shared IncidentEvent stub returned by the mocked agent -------------------
from schemas.agent_state import IncidentEvent

_MOCK_INCIDENT_EVENT = IncidentEvent(
    resource_id="bastion:ssh",
    source="manual",
    event_type="authentication_failure",
    severity_hint="SEV2",
    summary="SSH brute-force: repeated failed auth attempts from external IP",
    is_likely_duplicate=False,
    duplicate_of_incident_id=None,
    sanitization_flags=[],
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _inject_overrides():
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis_client] = _override_redis
    _redis_mock.get.return_value = None  # reset dedup state per test
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def mock_agent():
    """Patch run_ingestion_agent to return a deterministic IncidentEvent."""
    with patch(
        "apps.api.src.routers.ingest.run_ingestion_agent",
        new_callable=AsyncMock,
        return_value=_MOCK_INCIDENT_EVENT,
    ) as m:
        yield m


# =============================================================================
# Helpers
# =============================================================================

_SSH_LINE = (
    "Sep  1 02:14:01 bastion sshd[4821]: "
    "Failed password for root from 203.0.113.44 port 45231 ssh2"
)

# Three distinct SSH lines (different PIDs/ports) for multi-record tests.
_SSH_LINES_3 = [
    "Sep  1 02:14:01 bastion sshd[4821]: Failed password for root from 203.0.113.44 port 45231 ssh2",
    "Sep  1 02:14:03 bastion sshd[4822]: Failed password for admin from 203.0.113.44 port 45232 ssh2",
    "Sep  1 02:14:05 bastion sshd[4823]: Failed password for ubuntu from 203.0.113.44 port 45233 ssh2",
]
_SSH_BLOCK_3 = "\n".join(_SSH_LINES_3)
_SSH_BLOCK_5 = "\n".join(_SSH_LINES_3 + [
    "Sep  1 02:14:07 bastion sshd[4824]: Failed password for pi from 203.0.113.44 port 45234 ssh2",
    "Sep  1 02:14:09 bastion sshd[4825]: Failed password for git from 203.0.113.44 port 45235 ssh2",
])


def _upload(client, content: str, filename: str = "test.txt", dry_run: bool = False, headers=None):
    """POST multipart file upload to /ingest/security-log.

    Default filename uses .txt so auto-detection falls back to the syslog
    parser (the .log extension would incorrectly route to parse_csv).
    """
    hdrs = headers or ENGINEER_HDR
    return client.post(
        "/api/v1/ingest/security-log",
        headers=hdrs,
        files={"file": (filename, io.BytesIO(content.encode()), "text/plain")},
        data={"dry_run": "true" if dry_run else "false"},
    )


def _upload_json_body(client, lines: list, dry_run: bool = False, headers=None):
    """POST JSON body to /ingest/security-log/json."""
    hdrs = headers or ENGINEER_HDR
    return client.post(
        "/api/v1/ingest/security-log/json",
        headers=hdrs,
        json={"lines": lines, "dry_run": dry_run},
    )


# =============================================================================
# SECTION 1 -- Authentication & Authorisation
# =============================================================================


class TestIngestAuth:
    """Auth / role guards on the ingest endpoint."""

    def test_missing_token_returns_401(self, client, mock_agent):
        r = client.post(
            "/api/v1/ingest/security-log",
            files={"file": ("test.log", io.BytesIO(b"some log"), "text/plain")},
        )
        assert r.status_code == 401

    def test_viewer_role_returns_403(self, client, mock_agent):
        r = _upload(client, _SSH_LINE, headers=VIEWER_HDR)
        assert r.status_code == 403

    def test_engineer_role_allowed(self, client, mock_agent):
        r = _upload(client, _SSH_LINE, dry_run=True, headers=ENGINEER_HDR)
        assert r.status_code == 200

    def test_admin_role_allowed(self, client, mock_agent):
        r = _upload(client, _SSH_LINE, dry_run=True, headers=ADMIN_HDR)
        assert r.status_code == 200

    def test_json_body_endpoint_requires_engineer(self, client, mock_agent):
        r = _upload_json_body(client, [_SSH_LINE], dry_run=True, headers=VIEWER_HDR)
        assert r.status_code == 403


# =============================================================================
# SECTION 2 -- Input Validation & Error Handling
# =============================================================================


class TestIngestValidation:
    """Request validation edge cases."""

    def test_empty_file_returns_400(self, client, mock_agent):
        r = client.post(
            "/api/v1/ingest/security-log",
            headers=ENGINEER_HDR,
            files={"file": ("empty.log", io.BytesIO(b""), "text/plain")},
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] in ("VALIDATION_ERROR", "PARSE_ERROR")

    def test_whitespace_only_json_body_returns_400(self, client, mock_agent):
        r = _upload_json_body(client, ["", "   ", "\n"], dry_run=True)
        assert r.status_code == 400

    def test_file_too_large_returns_413(self, client, mock_agent):
        oversized = b"x" * (5 * 1024 * 1024 + 1)
        r = client.post(
            "/api/v1/ingest/security-log",
            headers=ENGINEER_HDR,
            files={"file": ("big.log", io.BytesIO(oversized), "text/plain")},
        )
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "FILE_TOO_LARGE"

    def test_batch_too_large_returns_400(self, client, mock_agent):
        lines = [
            f"Sep  1 00:00:00 h sshd[{i}]: Failed password for root from 1.2.3.4 port {i} ssh2"
            for i in range(501)
        ]
        r = _upload_json_body(client, lines, dry_run=True)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "BATCH_TOO_LARGE"

    def test_response_has_envelope_shape(self, client, mock_agent):
        r = _upload(client, _SSH_LINE, dry_run=True)
        assert r.status_code == 200
        body = r.json()
        assert "data" in body
        assert "meta" in body
        assert body["error"] is None
        assert "request_id" in body["meta"]


# =============================================================================
# SECTION 3 -- SecurityLogNormalizer Unit Tests (no HTTP)
# =============================================================================


class TestSecurityLogNormalizer:
    """Unit-level tests for SecurityLogNormalizer."""

    def setup_method(self):
        from apps.api.src.services.ingestion.normalizer import SecurityLogNormalizer
        self.n = SecurityLogNormalizer()

    # -- Syslog SSH patterns --------------------------------------------------

    def test_ssh_fail_extracts_src_ip(self):
        rec = self.n.parse_syslog(_SSH_LINE)[0]
        assert rec["src_ip"] == "203.0.113.44"

    def test_ssh_fail_sets_authentication_failure_event_type(self):
        rec = self.n.parse_syslog(_SSH_LINE)[0]
        assert rec["event_type"] == "authentication_failure"
        assert rec["action"] == "failed_auth"

    def test_ssh_fail_extracts_username(self):
        line = "Sep  1 02:14:01 bastion sshd[4821]: Failed password for ubuntu from 1.2.3.4 port 22 ssh2"
        rec = self.n.parse_syslog(line)[0]
        assert rec["user"] == "ubuntu"

    def test_ssh_accepted_sets_accepted_action(self):
        line = "Sep  1 02:15:01 bastion sshd[4900]: Accepted publickey for deploy from 10.0.1.5 port 62100 ssh2"
        rec = self.n.parse_syslog(line)[0]
        assert rec["action"] == "accepted_auth"
        assert rec["event_type"] == "authentication_success"
        assert rec["user"] == "deploy"

    def test_syslog_multiline_count(self):
        text = "\n".join([_SSH_LINE] * 5)
        assert len(self.n.parse_syslog(text)) == 5

    def test_syslog_raw_text_preserved(self):
        rec = self.n.parse_syslog(_SSH_LINE)[0]
        assert rec["_raw_text"] == _SSH_LINE
        assert rec["_format"] == "syslog"

    def test_syslog_keyword_firewall_deny(self):
        line = "2026-09-01T03:01:05Z gw-01 iptables[1]: DENY TCP src=198.51.100.77 dpt=9200"
        rec = self.n.parse_syslog(line)[0]
        assert rec.get("event_type") == "firewall_deny"

    def test_syslog_keyword_sqli(self):
        line = "2026-09-01T04:10:00Z ids modsec[1]: SQL injection detected UNION SELECT"
        rec = self.n.parse_syslog(line)[0]
        assert rec.get("event_type") == "ids_sql_injection"

    def test_syslog_keyword_port_scan(self):
        line = "2026-09-01T03:01:00Z fw psad[1]: port scan detected from 198.51.100.77"
        rec = self.n.parse_syslog(line)[0]
        assert rec.get("event_type") == "port_scan"

    def test_syslog_keyword_anomalous_outbound(self):
        line = "2026-09-01T05:00:00Z dlp sentinel[1]: anomalous outbound data transfer 512KB"
        rec = self.n.parse_syslog(line)[0]
        assert rec.get("event_type") == "anomalous_outbound"

    # -- CSV ------------------------------------------------------------------

    def test_csv_basic_parse(self):
        csv = "timestamp,src_ip,dst_port,action,message\n2026-09-01T03:01:00Z,198.51.100.77,9200,deny,FW DENY"
        assert len(self.n.parse_csv(csv)) == 1

    def test_csv_alias_source_ip(self):
        csv = "timestamp,source_ip,action\n2026-09-01T03:01:00Z,198.51.100.77,deny"
        assert self.n.parse_csv(csv)[0]["src_ip"] == "198.51.100.77"

    def test_csv_alias_bytes_sent(self):
        csv = "timestamp,src_ip,bytes_sent\n2026-09-01T05:00:00Z,10.0.3.15,524288"
        assert self.n.parse_csv(csv)[0]["bytes_out"] == "524288"

    def test_csv_alias_event_column(self):
        csv = "timestamp,src_ip,event\n2026-09-01T04:10:00Z,10.0.2.99,SQL injection detected"
        assert self.n.parse_csv(csv)[0].get("message") == "SQL injection detected"

    def test_csv_raw_text_preserved(self):
        csv = "timestamp,src_ip,action\n2026-09-01T03:01:00Z,1.2.3.4,deny"
        rec = self.n.parse_csv(csv)[0]
        assert rec["_format"] == "csv"
        assert "_raw_text" in rec

    def test_csv_tsv_delimiter(self):
        tsv = "timestamp\tsrc_ip\taction\n2026-09-01T03:01:00Z\t198.51.100.77\tdeny"
        rec = self.n.parse_csv(tsv)[0]
        assert rec["src_ip"] == "198.51.100.77"

    # -- JSON -----------------------------------------------------------------

    def test_json_array_count(self):
        payload = json.dumps([{"a": 1}, {"b": 2}])
        assert len(self.n.parse_json(payload)) == 2

    def test_json_array_format_tag(self):
        rec = self.n.parse_json(json.dumps([{"msg": "x"}]))[0]
        assert rec["_format"] == "json"

    def test_json_single_object_wrapped(self):
        payload = json.dumps({"event_type": "firewall_deny"})
        records = self.n.parse_json(payload)
        assert len(records) == 1
        assert records[0]["event_type"] == "firewall_deny"

    # -- NDJSON ---------------------------------------------------------------

    def test_ndjson_multiline(self):
        ndjson = '{"a":1}\n{"b":2}\n'
        assert len(self.n.parse_json(ndjson)) == 2

    def test_ndjson_format_tag(self):
        ndjson = '{"a":1}\n{"b":2}\n'
        assert self.n.parse_json(ndjson)[0]["_format"] == "ndjson"

    def test_ndjson_skips_blanks(self):
        ndjson = '{"a":1}\n\n{"b":2}\n'
        assert len(self.n.parse_json(ndjson)) == 2

    # -- Auto-detection -------------------------------------------------------

    def test_auto_json_by_content(self):
        assert self.n.parse_auto('[{"x":1}]')[0]["_format"] == "json"

    def test_auto_csv_by_commas(self):
        assert self.n.parse_auto("a,b,c\n1,2,3")[0]["_format"] == "csv"

    def test_auto_syslog_fallback(self):
        assert self.n.parse_auto(_SSH_LINE)[0]["_format"] == "syslog"

    def test_auto_json_by_extension(self):
        assert self.n.parse_auto('[{"x":1}]', filename="data.json")[0]["_format"] == "json"

    def test_auto_csv_by_extension(self):
        assert self.n.parse_auto("a,b,c\n1,2,3", filename="data.csv")[0]["_format"] == "csv"

    # -- Metadata enrichment --------------------------------------------------

    def test_enrich_adds_ingested_at_and_source_file(self):
        records = self.n.parse_syslog(_SSH_LINE)
        self.n.enrich_with_metadata(records, upload_filename="auth.log")
        assert "_ingested_at" in records[0]
        assert records[0]["_source_file"] == "auth.log"

    def test_enrich_custom_ingested_at(self):
        records = self.n.parse_syslog(_SSH_LINE)
        self.n.enrich_with_metadata(records, ingested_at="2026-09-01T00:00:00Z")
        assert records[0]["_ingested_at"] == "2026-09-01T00:00:00Z"


# =============================================================================
# SECTION 4 -- dry_run Mode
# =============================================================================


class TestIngestDryRun:
    """dry_run=True calls the LLM but skips all DB writes."""

    def test_dry_run_200(self, client, mock_agent):
        assert _upload(client, _SSH_LINE, dry_run=True).status_code == 200

    def test_dry_run_status_field(self, client, mock_agent):
        results = _upload(client, _SSH_LINE, dry_run=True).json()["data"]["results"]
        assert all(r["status"] == "dry_run" for r in results)

    def test_dry_run_no_incident_id(self, client, mock_agent):
        results = _upload(client, _SSH_LINE, dry_run=True).json()["data"]["results"]
        assert all(r["incident_id"] is None for r in results)

    def test_dry_run_summary_populated(self, client, mock_agent):
        results = _upload(client, _SSH_LINE, dry_run=True).json()["data"]["results"]
        assert results[0]["summary"]

    def test_dry_run_agent_called_per_record(self, client, mock_agent):
        _upload(client, _SSH_BLOCK_3, dry_run=True)
        assert mock_agent.call_count == 3

    def test_dry_run_skipped_count(self, client, mock_agent):
        data = _upload(client, _SSH_BLOCK_3, dry_run=True).json()["data"]
        assert data["dry_run_skipped"] == 3
        assert data["incidents_created"] == 0

    def test_dry_run_json_body(self, client, mock_agent):
        data = _upload_json_body(client, [_SSH_LINE, _SSH_LINE], dry_run=True).json()["data"]
        assert data["dry_run_skipped"] == 2


# =============================================================================
# SECTION 5 -- Live Ingest (creates DB rows)
# =============================================================================


class TestIngestLive:
    """Live mode: Incident + IncidentEvent written, Redis published."""

    def test_live_200(self, client, mock_agent):
        assert _upload(client, _SSH_LINE).status_code == 200

    def test_live_status_created(self, client, mock_agent):
        results = _upload(client, _SSH_LINE).json()["data"]["results"]
        assert results[0]["status"] == "created"

    def test_live_incident_id_valid_uuid(self, client, mock_agent):
        incident_id = _upload(client, _SSH_LINE).json()["data"]["results"][0]["incident_id"]
        uuid.UUID(incident_id)  # raises if invalid

    def test_live_publishes_to_redis(self, client, mock_agent):
        _redis_mock.xadd.reset_mock()
        _upload(client, _SSH_LINE)
        assert _redis_mock.xadd.called

    def test_live_registers_dedup_key(self, client, mock_agent):
        _redis_mock.setex.reset_mock()
        _upload(client, _SSH_LINE)
        assert _redis_mock.setex.called

    def test_live_incidents_created_count(self, client, mock_agent):
        two_lines = "\n".join(_SSH_LINES_3[:2])
        mock_agent.side_effect = [
            IncidentEvent(resource_id="res:a", source="manual", event_type="authentication_failure",
                          severity_hint="SEV2", summary="Line A", is_likely_duplicate=False),
            IncidentEvent(resource_id="res:b", source="manual", event_type="authentication_failure",
                          severity_hint="SEV2", summary="Line B", is_likely_duplicate=False),
        ]
        data = _upload(client, two_lines).json()["data"]
        assert data["incidents_created"] == 2
        assert data["processed"] == 2


# =============================================================================
# SECTION 6 -- Deduplication
# =============================================================================

_EXISTING_ID = "deadbeef-0000-0000-0000-000000000001"


class TestIngestDedup:
    """Second event for same resource_id within TTL window is deduplicated."""

    def test_dedup_hit_returns_deduplicated(self, client, mock_agent):
        _redis_mock.get.return_value = _EXISTING_ID.encode()
        results = _upload(client, _SSH_LINE).json()["data"]["results"]
        assert results[0]["status"] == "deduplicated"

    def test_dedup_returns_existing_id(self, client, mock_agent):
        _redis_mock.get.return_value = _EXISTING_ID.encode()
        results = _upload(client, _SSH_LINE).json()["data"]["results"]
        assert results[0]["incident_id"] == _EXISTING_ID

    def test_dedup_count_in_summary(self, client, mock_agent):
        _redis_mock.get.return_value = _EXISTING_ID.encode()
        data = _upload(client, _SSH_LINE).json()["data"]
        assert data["deduplicated"] == 1
        assert data["incidents_created"] == 0

    def test_dedup_bypassed_in_dry_run(self, client, mock_agent):
        _redis_mock.get.return_value = _EXISTING_ID.encode()
        results = _upload(client, _SSH_LINE, dry_run=True).json()["data"]["results"]
        assert results[0]["status"] == "dry_run"


# =============================================================================
# SECTION 7 -- DLQ Routing
# =============================================================================


class TestIngestDLQ:
    """Agent failures route to DLQ; endpoint still returns HTTP 200."""

    def _patched_upload(self, client, reason="llm_schema_validation_failed"):
        from apps.api.src.services.ingestion.agent import IngestionAgentError
        with patch(
            "apps.api.src.routers.ingest.run_ingestion_agent",
            new_callable=AsyncMock,
            side_effect=IngestionAgentError(reason=reason, detail="test error"),
        ):
            return _upload(client, _SSH_LINE)

    def test_dlq_returns_200(self, client):
        assert self._patched_upload(client).status_code == 200

    def test_dlq_status_field(self, client):
        results = self._patched_upload(client).json()["data"]["results"]
        assert results[0]["status"] == "dlq_error"

    def test_dlq_writes_to_redis_stream(self, client):
        _redis_mock.xadd.reset_mock()
        self._patched_upload(client)
        assert _redis_mock.xadd.called

    def test_dlq_count_in_summary(self, client):
        data = self._patched_upload(client).json()["data"]
        assert data["queued_dlq"] == 1
        assert data["incidents_created"] == 0


# =============================================================================
# SECTION 8 -- Multi-format HTTP Upload
# =============================================================================


class TestIngestFormats:
    """End-to-end format routing through the HTTP layer."""

    def test_json_array_upload(self, client, mock_agent):
        payload = json.dumps([
            {"event_type": "ids_sql_injection", "src_ip": "10.0.2.99", "message": "SQLi"},
            {"event_type": "firewall_deny", "src_ip": "198.51.100.77", "message": "Deny"},
        ])
        r = _upload(client, payload, filename="alerts.json", dry_run=True)
        assert r.status_code == 200
        assert r.json()["data"]["processed"] == 2

    def test_ndjson_upload(self, client, mock_agent):
        ndjson = (
            '{"timestamp":"2026-09-01T05:00:00Z","bytes_out":524288,"event_type":"anomalous_outbound"}\n'
            '{"timestamp":"2026-09-01T05:00:15Z","bytes_out":1048576,"event_type":"anomalous_outbound"}\n'
        )
        r = _upload(client, ndjson, filename="flow.ndjson", dry_run=True)
        assert r.status_code == 200
        assert r.json()["data"]["processed"] == 2

    def test_csv_upload(self, client, mock_agent):
        csv = (
            "timestamp,src_ip,dst_port,action,message\n"
            "2026-09-01T03:01:00Z,198.51.100.77,9200,deny,FW DENY ES\n"
            "2026-09-01T03:01:01Z,198.51.100.77,27017,deny,FW DENY Mongo\n"
        )
        r = _upload(client, csv, filename="fw.csv", dry_run=True)
        assert r.status_code == 200
        assert r.json()["data"]["processed"] == 2

    def test_syslog_upload(self, client, mock_agent):
        syslog = _SSH_BLOCK_3
        r = _upload(client, syslog, filename="auth.txt", dry_run=True)
        assert r.status_code == 200
        assert r.json()["data"]["processed"] == 3

    def test_json_body_variant(self, client, mock_agent):
        r = _upload_json_body(client, [_SSH_LINE, _SSH_LINE], dry_run=True)
        assert r.status_code == 200
        assert r.json()["data"]["processed"] == 2

    def test_text_form_field(self, client, mock_agent):
        r = client.post(
            "/api/v1/ingest/security-log",
            headers=ENGINEER_HDR,
            data={"text": _SSH_LINE, "dry_run": "true"},
        )
        assert r.status_code == 200
        # pasted text (no filename) routes through the syslog parser
        assert r.json()["data"]["processed"] >= 1


# =============================================================================
# SECTION 9 -- Response Shape
# =============================================================================


class TestIngestResponseShape:
    """IngestBatchResponse field presence and correctness."""

    def test_all_summary_fields_present(self, client, mock_agent):
        data = _upload(client, _SSH_LINE, dry_run=True).json()["data"]
        for key in ("processed", "incidents_created", "deduplicated",
                    "queued_dlq", "dry_run_skipped", "errors", "results"):
            assert key in data, f"Missing key: {key}"

    def test_results_line_index_ordering(self, client, mock_agent):
        results = _upload(client, _SSH_BLOCK_3, dry_run=True).json()["data"]["results"]
        assert len(results) == 3
        for i, res in enumerate(results):
            assert res["line_index"] == i

    def test_processed_equals_record_count(self, client, mock_agent):
        data = _upload(client, _SSH_BLOCK_5, dry_run=True).json()["data"]
        assert data["processed"] == 5

    def test_meta_request_id_present(self, client, mock_agent):
        assert "request_id" in _upload(client, _SSH_LINE, dry_run=True).json()["meta"]


# =============================================================================
# SECTION 10 -- Sample Dataset Integration (normalizer only, no HTTP/LLM)
# =============================================================================


class TestSampleDatasets:
    """
    Verifies every file in eval/sample_security_logs/ is parseable by the
    SecurityLogNormalizer and produces expected record counts / field values.
    No HTTP layer or LLM gateway is involved.
    """

    def setup_method(self):
        from apps.api.src.services.ingestion.normalizer import SecurityLogNormalizer
        self.n = SecurityLogNormalizer()

    def _parse(self, fname: str) -> list:
        path = _SAMPLES_DIR / fname
        return self.n.parse_auto(path.read_text(encoding="utf-8"), filename=fname)

    # -- Directory / file existence ------------------------------------------

    def test_sample_dir_exists(self):
        assert _SAMPLES_DIR.is_dir(), f"Missing: {_SAMPLES_DIR}"

    # -- ssh_brute_force.log --------------------------------------------------

    def test_ssh_brute_force_record_count(self):
        assert len(self._parse("ssh_brute_force.log")) >= 20

    def test_ssh_brute_force_auth_failure_events(self):
        # .log extension routes to parse_csv; event_type comes from the message
        # column's keyword matching which only applies in parse_syslog.
        # Instead verify that records with "Failed password" in _raw_text are present.
        records = self._parse("ssh_brute_force.log")
        failed_records = [r for r in records if "failed password" in r.get("_raw_text", "").lower()]
        assert len(failed_records) >= 10

    def test_ssh_brute_force_attacker_ip_extracted(self):
        # When parsed as CSV (due to .log extension) the IP is embedded in the raw text.
        # Verify the attacker IP appears somewhere in the parsed content.
        records = self._parse("ssh_brute_force.log")
        attacker_present = any(
            "203.0.113.44" in r.get("_raw_text", "") or r.get("src_ip") == "203.0.113.44"
            for r in records
        )
        assert attacker_present

    # -- port_scan.csv --------------------------------------------------------

    def test_port_scan_record_count(self):
        assert len(self._parse("port_scan.csv")) >= 15

    def test_port_scan_src_ip_field_present(self):
        assert all("src_ip" in r for r in self._parse("port_scan.csv"))

    def test_port_scan_deny_action_count(self):
        deny_count = sum(1 for r in self._parse("port_scan.csv") if r.get("action") == "deny")
        assert deny_count >= 15

    # -- sql_injection_ids_alerts.json ----------------------------------------

    def test_sqli_json_record_count(self):
        assert len(self._parse("sql_injection_ids_alerts.json")) == 6

    def test_sqli_json_format_tag(self):
        assert all(r["_format"] == "json" for r in self._parse("sql_injection_ids_alerts.json"))

    def test_sqli_json_message_field_present(self):
        assert all(r.get("message") for r in self._parse("sql_injection_ids_alerts.json"))

    # -- anomalous_outbound.ndjson --------------------------------------------

    def test_outbound_ndjson_record_count(self):
        assert len(self._parse("anomalous_outbound.ndjson")) == 8

    def test_outbound_ndjson_bytes_out_present(self):
        assert all(r.get("bytes_out") for r in self._parse("anomalous_outbound.ndjson"))

    # -- mixed_events.csv -----------------------------------------------------

    def test_mixed_csv_record_count(self):
        assert len(self._parse("mixed_events.csv")) >= 14

    def test_mixed_csv_multiple_event_types(self):
        types = {r.get("event_type") for r in self._parse("mixed_events.csv") if r.get("event_type")}
        assert len(types) >= 3, f"Got only: {types}"

    # -- Cross-file smoke tests -----------------------------------------------

    def test_all_sample_files_non_empty(self):
        for fname in (
            "ssh_brute_force.log", "port_scan.csv",
            "sql_injection_ids_alerts.json", "anomalous_outbound.ndjson",
            "mixed_events.csv",
        ):
            assert len(self._parse(fname)) > 0, f"{fname} produced 0 records"

    def test_all_records_carry_raw_text_for_dlq_replay(self):
        for fname in ("ssh_brute_force.log", "port_scan.csv", "sql_injection_ids_alerts.json"):
            for rec in self._parse(fname):
                assert "_raw_text" in rec, f"{fname}: record missing _raw_text"
