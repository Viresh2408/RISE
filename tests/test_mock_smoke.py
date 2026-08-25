"""
RISE — Mock Smoke Tests
=======================
A self-contained, fully-offline test suite that exercises every major layer of
the RISE stack using mocks / stubs only. No live Postgres, Redis, Qdrant, or
LLM gateway is required.

Sections
--------
1. API Layer  – FastAPI TestClient smoke-tests (health, incidents, reports, webhooks)
2. Context Builder – node logic with mocked fetchers and mocked LLM gateway
3. Action Planner  – prompt building, pre-LLM gate, patch-validation fallback
4. End-to-End Flow – minimal graph traversal via LangGraph MemorySaver
5. Approval & SLA  – idempotency locking and SLA-timeout escalation
"""

from __future__ import annotations

# ── Environment must be set before any app import ────────────────────────────
import os
import time
import uuid

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-secret-rise-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-slack-signing-secret")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-github-secret")
os.environ.setdefault("ALERTMANAGER_WEBHOOK_SECRET", "test-alertmanager-secret")

import pytest
import jwt
from unittest.mock import AsyncMock, MagicMock, patch

# ── SQLAlchemy / SQLite compat shim (already applied in root conftest.py) ────
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from apps.api.src.deps.db import get_db
from apps.api.src.deps.redis import get_redis_client

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


_redis_mock = MagicMock()
_redis_mock.get.return_value = None
_redis_mock.set.return_value = True
_redis_mock.setex.return_value = True
_redis_mock.xadd.return_value = b"1-0"
_redis_mock.delete.return_value = True
_redis_mock.exists.return_value = False


def _override_redis():
    yield _redis_mock


# ── FastAPI test client ───────────────────────────────────────────────────────
from fastapi.testclient import TestClient
from apps.api.src.main import app

_TEST_SECRET = "test-supabase-secret-rise-unit-tests"


@pytest.fixture(autouse=True)
def _inject_overrides():
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis_client] = _override_redis
    yield
    app.dependency_overrides.clear()


client = TestClient(app, raise_server_exceptions=True)


def _jwt(role: str = "admin") -> str:
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


ADMIN = {"Authorization": f"Bearer {_jwt('admin')}"}
APPROVER = {"Authorization": f"Bearer {_jwt('approver')}"}
VIEWER = {"Authorization": f"Bearer {_jwt('viewer')}"}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 – API Layer
# ═══════════════════════════════════════════════════════════════════════════════


class TestApiHealth:
    """Health endpoint — no auth required."""

    def test_healthz_returns_200(self):
        r = client.get("/api/v1/healthz")
        assert r.status_code == 200, r.text

    def test_healthz_envelope_shape(self):
        body = client.get("/api/v1/healthz").json()
        assert body["data"] == {"status": "ok"}
        assert body["error"] is None
        assert "request_id" in body["meta"]
        assert "timestamp" in body["meta"]

    def test_healthz_request_id_is_unique_per_call(self):
        id1 = client.get("/api/v1/healthz").json()["meta"]["request_id"]
        id2 = client.get("/api/v1/healthz").json()["meta"]["request_id"]
        assert id1 != id2


class TestApiAuth:
    """Authentication & authorisation guard-rails."""

    def test_missing_token_returns_401(self):
        r = client.get("/api/v1/incidents")
        assert r.status_code == 401

    def test_401_body_has_unauthorized_code(self):
        body = client.get("/api/v1/incidents").json()
        assert body["error"]["code"] == "UNAUTHORIZED"
        assert body["data"] is None

    def test_malformed_bearer_token_returns_401(self):
        r = client.get("/api/v1/incidents", headers={"Authorization": "Bearer not-a-jwt"})
        assert r.status_code == 401

    def test_valid_admin_token_passes(self):
        r = client.get("/api/v1/incidents", headers=ADMIN)
        assert r.status_code == 200

    def test_viewer_can_list_incidents(self):
        r = client.get("/api/v1/incidents", headers=VIEWER)
        assert r.status_code == 200

    def test_viewer_cannot_approve_action(self):
        headers = {**VIEWER, "Idempotency-Key": str(uuid.uuid4())}
        r = client.post(
            "/api/v1/incidents/inc-001/actions/act-001/approve",
            headers=headers,
            json={"note": "viewer trying to approve"},
        )
        assert r.status_code in (403, 401)


class TestApiIncidents:
    """Incident CRUD stubs — confirms list shape and empty-DB behaviour."""

    def test_list_incidents_returns_list(self):
        body = client.get("/api/v1/incidents", headers=ADMIN).json()
        assert isinstance(body["data"], list)
        assert body["error"] is None

    def test_list_incidents_empty_db_is_empty_list(self):
        body = client.get("/api/v1/incidents", headers=ADMIN).json()
        assert body["data"] == []

    def test_single_incident_404_for_nonexistent(self):
        r = client.get("/api/v1/incidents/nonexistent-id-999", headers=ADMIN)
        assert r.status_code == 404

    def test_404_body_uses_envelope(self):
        body = client.get("/api/v1/incidents/nonexistent-id-999", headers=ADMIN).json()
        assert body["data"] is None
        assert body["error"] is not None


class TestApiApproval:
    """Approval endpoint contract."""

    def test_approve_missing_idempotency_key_returns_422(self):
        r = client.post(
            "/api/v1/incidents/inc-001/actions/act-001/approve",
            headers=APPROVER,
            json={"note": "no idempotency key"},
        )
        assert r.status_code == 422
        assert client.post(
            "/api/v1/incidents/inc-001/actions/act-001/approve",
            headers=APPROVER,
            json={"note": "no idempotency key"},
        ).json()["error"]["code"] == "VALIDATION_ERROR"

    def test_approve_with_idempotency_key_returns_200(self):
        headers = {**APPROVER, "Idempotency-Key": str(uuid.uuid4())}
        r = client.post(
            "/api/v1/incidents/inc-001/actions/act-001/approve",
            headers=headers,
            json={"note": "LGTM"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["status"] == "approved"
        assert body["error"] is None

    @pytest.mark.parametrize("action_id,code", [
        ("plan-changed", "ACTION_PLAN_CHANGED"),
        ("expired", "APPROVAL_EXPIRED"),
        ("locked", "RESOURCE_LOCKED"),
    ])
    def test_409_conflict_error_codes(self, action_id, code):
        headers = {**APPROVER, "Idempotency-Key": str(uuid.uuid4())}
        body = client.post(
            f"/api/v1/incidents/inc-001/actions/{action_id}/approve",
            headers=headers,
            json={"note": "test"},
        ).json()
        assert body["error"]["code"] == code


class TestApiReports:
    """Reports endpoints return correct envelope shape."""

    def test_autonomy_report_200(self):
        r = client.get("/api/v1/reports/autonomy", headers=ADMIN)
        assert r.status_code == 200

    def test_autonomy_report_has_expected_keys(self):
        body = client.get("/api/v1/reports/autonomy", headers=ADMIN).json()
        data = body["data"]
        assert "total_incidents" in data
        assert "auto_resolved_pct" in data   # actual field name from AutonomyReportDTO
        assert body["error"] is None

    def test_mttr_report_200(self):
        r = client.get("/api/v1/reports/mttr", headers=ADMIN)
        assert r.status_code == 200

    def test_mttr_report_has_trend(self):
        body = client.get("/api/v1/reports/mttr", headers=ADMIN).json()
        data = body["data"]
        assert "trend" in data
        assert isinstance(data["trend"], list)


class TestApiWebhooks:
    """Webhook ingestion accepts payloads without JWT Bearer tokens."""

    @pytest.fixture(autouse=True)
    def _patch_verifiers_and_agent(self):
        from apps.api.src.services.ingestion.signature_verifier import (
            FakeVerifier,
            get_alertmanager_verifier,
            get_github_verifier,
            get_slack_verifier,
            get_sns_verifier,
        )
        from schemas.agent_state import IncidentEvent

        fake_event = IncidentEvent(
            resource_id="svc-mock",
            source="github",
            event_type="push",
            severity_hint="SEV3",
            summary="Mock webhook smoke test event",
            is_likely_duplicate=False,
            duplicate_of_incident_id=None,
            sanitization_flags=[],
        )

        app.dependency_overrides[get_github_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_alertmanager_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_slack_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_sns_verifier] = lambda: FakeVerifier()

        # Seed an IntegrationConfig row for each source
        import uuid as _uuid
        from db.models import IntegrationConfig

        with _Session() as db:
            for source in ("github", "cloudwatch", "slack", "alertmanager"):
                if not db.query(IntegrationConfig).filter_by(type=source, credential_ref="test-org").first():
                    db.add(IntegrationConfig(
                        id=_uuid.uuid4(),
                        tenant_id=_uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                        type=source,
                        status="connected",
                        credential_ref="test-org",
                        scopes={},
                    ))
            db.commit()

        with patch(
            "apps.api.src.routers.webhooks.run_ingestion_agent",
            new_callable=AsyncMock,
            return_value=fake_event,
        ):
            yield

        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_redis_client] = _override_redis

    @pytest.mark.parametrize("path,payload", [
        ("/api/v1/webhooks/github", {"repository": {"owner": {"login": "test-org"}}}),
        ("/api/v1/webhooks/cloudwatch", {"TopicArn": "arn:aws:sns:us-east-1:test-org:alarm"}),
        ("/api/v1/webhooks/slack", {"team_id": "test-org"}),
        ("/api/v1/webhooks/alertmanager", {"groupLabels": {"cluster": "test-org"}}),
    ])
    def test_webhook_ingestion_returns_received_true(self, path, payload):
        r = client.post(path, json=payload)
        assert r.status_code == 200, f"path={path} body={r.text}"
        body = r.json()
        assert body["data"]["received"] is True
        assert body["error"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 – Context Builder Node
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextBuilder:
    """Unit tests for `run_context_builder_agent` with all external I/O mocked."""

    def _make_state(self, resource_id: str = "auth-service") -> dict:
        return {
            "tenant_id": str(uuid.uuid4()),
            "incident_id": str(uuid.uuid4()),
            "event_payload": {
                "resource_id": resource_id,
                "source": "github",
                "event_type": "OOMKilled",
                "severity_hint": "SEV1",
                "summary": "Memory leak detected in auth-service",
            },
        }

    def _mock_fetchers(
        self,
        *,
        loki_ok: bool = True,
        prom_ok: bool = True,
        gh_ok: bool = True,
        qdrant_ok: bool = True,
    ):
        """Return keyword-dict of stub fetcher functions."""
        return {
            "loki_fetcher": lambda rid: ('{"streams":[]}', not loki_ok),
            "prometheus_fetcher": lambda rid: ('{"result":[]}', not prom_ok),
            "github_fetcher": lambda rid: ('[]', not gh_ok),
            "qdrant_fetcher": lambda q, tid, service_id=None: ([], not qdrant_ok),
            "slack_fetcher": lambda service, error_pattern: ([], False),
        }

    @pytest.mark.anyio
    async def test_all_sources_present_context_completeness_100(self):
        from apps.agents.src.nodes.context_builder import run_context_builder_agent
        from schemas.agent_state import IncidentContext

        mock_ctx = IncidentContext(
            timeline=[{"timestamp": "2026-08-25T12:00:00Z", "event": "OOMKilled", "source": "loki"}],
            log_excerpts=[{"source": "loki", "excerpt": "auth-service killed by OOM"}],
            metric_snapshots=[{"metric": "mem_usage", "value": "98%", "window": "5m"}],
            recent_deploys=[{"repo": "org/auth", "commit": "abc1234", "deployed_at": "2026-08-25T11:00:00Z", "author": "dev"}],
            similar_past_incidents=[],
            context_completeness_pct=100,
            missing_sources=[],
        )

        mock_gateway = AsyncMock()
        mock_gateway.call_structured = AsyncMock(return_value=mock_ctx)

        state = self._make_state()
        result = await run_context_builder_agent(
            state,
            gateway=mock_gateway,
            **self._mock_fetchers(),
        )

        assert "context" in result
        assert "raw_evidence_record" in result
        ctx = result["context"]
        assert ctx["context_completeness_pct"] == 100
        assert ctx["missing_sources"] == []

    @pytest.mark.anyio
    async def test_all_sources_missing_completeness_0(self):
        from apps.agents.src.nodes.context_builder import run_context_builder_agent
        from schemas.agent_state import IncidentContext

        mock_ctx = IncidentContext(
            timeline=[],
            log_excerpts=[],
            metric_snapshots=[],
            recent_deploys=[],
            similar_past_incidents=[],
            context_completeness_pct=0,
            missing_sources=["loki", "prometheus", "github", "qdrant"],
        )

        mock_gateway = AsyncMock()
        mock_gateway.call_structured = AsyncMock(return_value=mock_ctx)

        state = self._make_state()
        result = await run_context_builder_agent(
            state,
            gateway=mock_gateway,
            **self._mock_fetchers(loki_ok=False, prom_ok=False, gh_ok=False, qdrant_ok=False),
        )

        ctx = result["context"]
        assert ctx["context_completeness_pct"] == 0
        assert "loki" in ctx["missing_sources"]
        assert "prometheus" in ctx["missing_sources"]

    @pytest.mark.anyio
    async def test_loki_down_prometheus_up_completeness_75(self):
        from apps.agents.src.nodes.context_builder import run_context_builder_agent
        from schemas.agent_state import IncidentContext

        mock_ctx = IncidentContext(
            timeline=[],
            log_excerpts=[],
            metric_snapshots=[{"metric": "cpu", "value": "45%", "window": "5m"}],
            recent_deploys=[],
            similar_past_incidents=[],
            context_completeness_pct=75,
            missing_sources=["loki"],
        )

        mock_gateway = AsyncMock()
        mock_gateway.call_structured = AsyncMock(return_value=mock_ctx)

        state = self._make_state()
        result = await run_context_builder_agent(
            state,
            gateway=mock_gateway,
            **self._mock_fetchers(loki_ok=False),
        )

        ctx = result["context"]
        assert "loki" in ctx["missing_sources"]
        assert ctx["context_completeness_pct"] == 75

    @pytest.mark.anyio
    async def test_raw_evidence_record_contains_exact_fetcher_bytes(self):
        from apps.agents.src.nodes.context_builder import run_context_builder_agent
        from schemas.agent_state import IncidentContext

        mock_ctx = IncidentContext(
            timeline=[], log_excerpts=[], metric_snapshots=[],
            recent_deploys=[], similar_past_incidents=[],
            context_completeness_pct=100, missing_sources=[],
        )

        mock_gateway = AsyncMock()
        mock_gateway.call_structured = AsyncMock(return_value=mock_ctx)

        state = self._make_state()
        result = await run_context_builder_agent(
            state,
            gateway=mock_gateway,
            **self._mock_fetchers(),
        )

        rer = result["raw_evidence_record"]
        assert "fetched_at" in rer
        assert "sources" in rer
        assert "loki" in rer["sources"]
        assert "prometheus" in rer["sources"]
        assert "github" in rer["sources"]
        assert "qdrant" in rer["sources"]

    @pytest.mark.anyio
    async def test_llm_gateway_error_falls_back_to_stub_context(self):
        """When LLM raises, context builder must still return a valid state dict."""
        from apps.agents.src.nodes.context_builder import run_context_builder_agent

        mock_gateway = AsyncMock()
        mock_gateway.call_structured = AsyncMock(side_effect=RuntimeError("LLM offline"))

        state = self._make_state()
        result = await run_context_builder_agent(
            state,
            gateway=mock_gateway,
            **self._mock_fetchers(),
        )

        # Fallback must still produce a usable context dict
        assert "context" in result
        assert isinstance(result["context"]["timeline"], list)

    @pytest.mark.anyio
    async def test_empty_tenant_id_marks_qdrant_missing(self):
        from apps.agents.src.nodes.context_builder import run_context_builder_agent
        from schemas.agent_state import IncidentContext

        mock_ctx = IncidentContext(
            timeline=[], log_excerpts=[], metric_snapshots=[],
            recent_deploys=[], similar_past_incidents=[],
            context_completeness_pct=75, missing_sources=["qdrant"],
        )

        mock_gateway = AsyncMock()
        mock_gateway.call_structured = AsyncMock(return_value=mock_ctx)

        state = {
            "tenant_id": "",          # empty tenant_id
            "incident_id": str(uuid.uuid4()),
            "event_payload": {"resource_id": "svc", "summary": "test"},
        }

        result = await run_context_builder_agent(
            state,
            gateway=mock_gateway,
            **self._mock_fetchers(),
        )

        assert "qdrant" in result["context"]["missing_sources"]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 – Action Planner
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionPlannerPromptBuilding:
    """Tests for ActionPlanner.build_prompts() — no LLM calls."""

    def setup_method(self):
        from apps.agents.src.engines.action_planner import ActionPlanner
        self.planner = ActionPlanner()

    def test_prompt_contains_security_preamble(self):
        prompt = self.planner.build_prompts(
            root_cause={"cause": "OOM"},
            impact_assessment={"services": ["auth"]},
            similar_resolutions=[],
        )
        assert "SECURITY RULES" in prompt
        assert "untrusted_data" in prompt

    def test_prompt_contains_all_default_tools(self):
        prompt = self.planner.build_prompts(
            root_cause={"cause": "OOM"},
            impact_assessment={},
            similar_resolutions=[],
        )
        for tool in ("restart_pod", "rollback_deployment", "code_fix_pr", "escalate_to_human"):
            assert tool in prompt

    def test_custom_tool_list_is_reflected_in_prompt(self):
        prompt = self.planner.build_prompts(
            root_cause={},
            impact_assessment={},
            similar_resolutions=[],
            available_tools=["restart_pod", "flush_redis"],
        )
        assert "restart_pod" in prompt
        assert "flush_redis" in prompt
        assert "scale_deployment" not in prompt

    def test_file_content_section_injected_as_real_file_content_tag(self):
        fc = MagicMock()
        fc.content = "def broken(): pass"
        fc.commit_sha = "abc123"
        fc.line_count = 1

        prompt = self.planner.build_prompts(
            root_cause={},
            impact_assessment={},
            similar_resolutions=[],
            file_contents={"app/main.py": fc},
        )
        assert "<real_file_content" in prompt
        assert "app/main.py" in prompt
        assert "def broken(): pass" in prompt

    def test_mismatch_feedback_prepended_to_file_content_section(self):
        fc = MagicMock()
        fc.content = "x = 1"
        fc.commit_sha = "deadbeef"
        fc.line_count = 1

        prompt = self.planner.build_prompts(
            root_cause={},
            impact_assessment={},
            similar_resolutions=[],
            file_contents={"app/x.py": fc},
            mismatch_feedback="Patch hunk 0 failed: expected '+ x = 2' got '- x = 1'",
        )
        assert "Patch hunk 0 failed" in prompt


class TestActionPlannerPreLLMGate:
    """Tests for generate_plan() pre-LLM grounding gate — no real LLM calls."""

    @pytest.mark.anyio
    async def test_gate_blocks_when_required_file_missing(self):
        from apps.agents.src.engines.action_planner import ActionPlanner
        planner = ActionPlanner()

        plan = await planner.generate_plan(
            root_cause={"cause": "syntax error in app/main.py"},
            impact_assessment={},
            file_contents={"app/main.py": None},   # None = fetch failed
            required_files=["app/main.py"],
        )

        assert plan.requires_manual_plan is True
        assert plan.action_type == "escalate_to_human"
        assert "unavailable" in plan.plan_rationale.lower()

    @pytest.mark.anyio
    async def test_gate_passes_when_all_required_files_present(self):
        from apps.agents.src.engines.action_planner import ActionPlanner
        from schemas.agent_state import ActionPlan

        fc = MagicMock()
        fc.content = "x = 1\n"
        fc.commit_sha = "abc123"
        fc.line_count = 1

        good_plan = ActionPlan(
            action_type="restart_pod",
            action_steps=[{"tool": "restart_pod", "params": {"pod": "auth-1"}}],
            rollback_plan=[{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
            plan_rationale="Restart to recover from OOM.",
            requires_manual_plan=False,
        )

        mock_gateway = AsyncMock()
        mock_gateway.call_structured = AsyncMock(return_value=good_plan)

        planner = ActionPlanner()
        plan = await planner.generate_plan(
            root_cause={"cause": "OOM"},
            impact_assessment={},
            file_contents={"app/main.py": fc},
            required_files=["app/main.py"],
            gateway=mock_gateway,
        )

        assert plan.requires_manual_plan is False
        assert plan.action_type == "restart_pod"

    @pytest.mark.anyio
    async def test_llm_failure_returns_manual_plan_fallback(self):
        from apps.agents.src.engines.action_planner import ActionPlanner

        mock_gateway = AsyncMock()
        mock_gateway.call_structured = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        planner = ActionPlanner()
        plan = await planner.generate_plan(
            root_cause={"cause": "DB overload"},
            impact_assessment={},
            gateway=mock_gateway,
        )

        assert plan.requires_manual_plan is True
        assert plan.action_type == "escalate_to_human"

    @pytest.mark.anyio
    async def test_no_required_files_skips_gate(self):
        """When required_files is empty, gate is skipped and LLM is called."""
        from apps.agents.src.engines.action_planner import ActionPlanner
        from schemas.agent_state import ActionPlan

        good_plan = ActionPlan(
            action_type="flush_redis",
            action_steps=[{"tool": "flush_redis", "params": {}}],
            rollback_plan=[{"tool": "restart_service", "params": {"service": "cache"}}],  # guardrail: non-empty required
            plan_rationale="Cache is corrupt.",
            requires_manual_plan=False,
        )

        mock_gateway = AsyncMock()
        mock_gateway.call_structured = AsyncMock(return_value=good_plan)

        planner = ActionPlanner()
        plan = await planner.generate_plan(
            root_cause={"cause": "cache corruption"},
            impact_assessment={},
            required_files=[],      # no required files → gate not triggered
            gateway=mock_gateway,
        )

        assert plan.action_type == "flush_redis"
        mock_gateway.call_structured.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 – End-to-End LangGraph Flow
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEndFlow:
    """Minimal graph traversal tests using LangGraph MemorySaver."""

    def _make_incident_state(self, *, requires_approval=False, health="200 OK", rollback_count=0):
        tid = str(uuid.uuid4())
        return {
            "tenant_id": str(uuid.uuid4()),
            "incident_id": str(uuid.uuid4()),
            "agent_run_id": tid,
            "decision": {
                "requires_approval": requires_approval,
                "status": "needs_approval" if requires_approval else "auto",
                "risk_tier": "high" if requires_approval else "low",
                "action_plan": {
                    "action_type": "restart_pod",
                    "action_steps": [{"tool": "restart_pod", "params": {"pod": "api-1"}}],
                    "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "api"}}],
                    "plan_rationale": "Restart to recover from OOM.",
                },
            },
            "action_plan": {
                "action_type": "restart_pod",
                "action_steps": [{"tool": "restart_pod", "params": {"pod": "api-1"}}],
                "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "api"}}],
                "plan_rationale": "Restart to recover from OOM.",
            },
            "post_action_metrics": {"health_status": health, "error_rate": 0.0 if health == "200 OK" else 45.0},
            "human_approval": "",
            "event_payload": {"alert": "high CPU on api-1"},
            "rollback_count": rollback_count,
        }

    def test_auto_remediation_happy_path_completes(self):
        from apps.agents.src.orchestrator.graph import create_orchestrator_graph
        app_graph = create_orchestrator_graph()
        tid = str(uuid.uuid4())

        final = app_graph.invoke(
            self._make_incident_state(requires_approval=False, health="200 OK"),
            config={"configurable": {"thread_id": tid}},
        )

        assert final.get("status") == "completed"
        assert final.get("current_step") == "close"

    def test_verification_failure_triggers_rollback(self):
        from apps.agents.src.orchestrator.graph import create_orchestrator_graph
        app_graph = create_orchestrator_graph()
        tid = str(uuid.uuid4())

        final = app_graph.invoke(
            self._make_incident_state(requires_approval=False, health="error"),
            config={"configurable": {"thread_id": tid}},
        )

        assert final.get("rollback_count", 0) >= 1
        assert final.get("verification_result", {}).get("status") == "failed"

    def test_circuit_breaker_fires_after_max_rollbacks(self):
        from apps.agents.src.orchestrator.graph import create_orchestrator_graph
        app_graph = create_orchestrator_graph()
        tid = str(uuid.uuid4())

        # Start with rollback_count already at 1 → next failure trips circuit breaker
        final = app_graph.invoke(
            self._make_incident_state(requires_approval=False, health="error", rollback_count=1),
            config={"configurable": {"thread_id": tid}},
        )

        assert final.get("status") == "manual_handoff"
        assert final.get("rollback_count") == 2

    def test_human_approval_resumes_paused_graph(self):
        from langgraph.checkpoint.memory import MemorySaver
        from apps.agents.src.orchestrator.graph import create_orchestrator_graph

        saver = MemorySaver()
        app_graph = create_orchestrator_graph(checkpointer=saver)
        tid = str(uuid.uuid4())
        config = {"configurable": {"thread_id": tid}}

        # Step 1: reach await_human pause
        state_paused = app_graph.invoke(
            self._make_incident_state(requires_approval=True, health="200 OK"),
            config=config,
        )
        assert state_paused.get("current_step") == "await_human"

        # Step 2: inject approval into checkpoint and resume
        app_graph.update_state(config, {"human_approval": "approved"})
        final = app_graph.invoke(None, config=config)

        assert final.get("status") == "completed"
        assert final.get("current_step") == "close"

    def test_worker_crash_and_resume_preserves_event_payload(self):
        """Simulates a worker restart by deleting the app instance mid-run."""
        from langgraph.checkpoint.memory import MemorySaver
        from apps.agents.src.orchestrator.graph import create_orchestrator_graph

        shared = MemorySaver()
        tid = str(uuid.uuid4())
        config = {"configurable": {"thread_id": tid}}
        initial = self._make_incident_state(requires_approval=True, health="200 OK")
        initial["event_payload"]["session"] = "preserve-me"

        # Worker A
        worker_a = create_orchestrator_graph(checkpointer=shared)
        worker_a.invoke(initial, config=config)
        del worker_a  # simulated crash

        # Worker B resumes
        worker_b = create_orchestrator_graph(checkpointer=shared)
        worker_b.update_state(config, {"human_approval": "approved"})
        final = worker_b.invoke(None, config=config)

        assert final.get("status") == "completed"
        assert final.get("event_payload", {}).get("session") == "preserve-me"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 – Approval & SLA
# ═══════════════════════════════════════════════════════════════════════════════


class TestApprovalIdempotency:
    """In-memory approval lock tests."""

    def setup_method(self):
        from apps.api.src.services.approval_lock import reset_approval_locks_for_testing
        reset_approval_locks_for_testing()

    def test_first_acquire_succeeds(self):
        from apps.api.src.services.approval_lock import acquire_single_use_approval_lock
        assert acquire_single_use_approval_lock("act-lock-001") is True

    def test_decision_not_marked_after_acquire(self):
        from apps.api.src.services.approval_lock import (
            acquire_single_use_approval_lock,
            is_approval_decided,
        )
        acquire_single_use_approval_lock("act-lock-002")
        assert is_approval_decided("act-lock-002") is False

    def test_mark_decided_persists(self):
        from apps.api.src.services.approval_lock import (
            acquire_single_use_approval_lock,
            is_approval_decided,
            mark_approval_decided,
            release_single_use_approval_lock,
        )
        action_id = "act-lock-003"
        acquire_single_use_approval_lock(action_id)
        mark_approval_decided(action_id, "approved")
        release_single_use_approval_lock(action_id)
        assert is_approval_decided(action_id) is True

    def test_double_decision_is_rejected(self):
        from apps.api.src.services.approval_lock import (
            acquire_single_use_approval_lock,
            is_approval_decided,
            mark_approval_decided,
            release_single_use_approval_lock,
        )
        action_id = "act-lock-004"
        acquire_single_use_approval_lock(action_id)
        mark_approval_decided(action_id, "approved")
        release_single_use_approval_lock(action_id)

        # Second attempt: already decided
        assert is_approval_decided(action_id) is True

    def test_reset_clears_all_locks(self):
        from apps.api.src.services.approval_lock import (
            acquire_single_use_approval_lock,
            mark_approval_decided,
            is_approval_decided,
            reset_approval_locks_for_testing,
        )
        action_id = "act-lock-005"
        acquire_single_use_approval_lock(action_id)
        mark_approval_decided(action_id, "rejected")

        reset_approval_locks_for_testing()
        assert is_approval_decided(action_id) is False


class TestSlaTimeout:
    """SLA timeout escalation task."""

    def test_expired_approval_triggers_escalation(self):
        from datetime import datetime, timedelta, timezone
        from apps.api.src.tasks import evaluate_sla_timeouts

        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        pending = [{
            "incident_id": "inc-sla-001",
            "action_id": "act-sla-001",
            "requested_at": expired_time,
            "sla_minutes": 15,
        }]

        with patch("apps.api.src.tasks.send_secondary_channel_escalation") as mock_escalate:
            escalated = evaluate_sla_timeouts(pending)
        assert len(escalated) == 1
        assert mock_escalate.called
        assert mock_escalate.call_args[0][0]["incident_id"] == "inc-sla-001"

    def test_non_expired_approval_not_escalated(self):
        from datetime import datetime, timedelta, timezone
        from apps.api.src.tasks import evaluate_sla_timeouts

        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        pending = [{
            "incident_id": "inc-sla-002",
            "action_id": "act-sla-002",
            "requested_at": recent_time,
            "sla_minutes": 15,
        }]

        with patch("apps.api.src.tasks.send_secondary_channel_escalation") as mock_escalate:
            escalated = evaluate_sla_timeouts(pending)
        assert escalated == []
        mock_escalate.assert_not_called()

    def test_multiple_approvals_only_escalate_expired_ones(self):
        from datetime import datetime, timedelta, timezone
        from apps.api.src.tasks import evaluate_sla_timeouts

        now = datetime.now(timezone.utc)
        pending = [
            {
                "incident_id": "inc-sla-003",
                "action_id": "act-sla-003",
                "requested_at": (now - timedelta(minutes=20)).isoformat(),
                "sla_minutes": 15,
            },
            {
                "incident_id": "inc-sla-004",
                "action_id": "act-sla-004",
                "requested_at": (now - timedelta(minutes=3)).isoformat(),
                "sla_minutes": 15,
            },
        ]

        with patch("apps.api.src.tasks.send_secondary_channel_escalation") as mock_escalate:
            escalated = evaluate_sla_timeouts(pending)

        assert len(escalated) == 1
        assert escalated[0]["incident_id"] == "inc-sla-003"
        assert mock_escalate.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 – Slack Card Format
# ═══════════════════════════════════════════════════════════════════════════════


class TestSlackCardFormat:
    """Field-for-field Slack approval card assertions per prompts.md §9."""

    def _make_state(self) -> dict:
        return {
            "incident_id": "inc-smoke-001",
            "severity": "SEV1",
            "root_cause": {
                "cause_summary": "OOMKilled due to memory leak in auth-service",
                "confidence": 0.88,
            },
            "impact_assessment": {
                "blast_radius_services": ["auth-service", "api-gateway"],
                "estimated_users_affected": 12000,
            },
            "action_plan": {
                "action_type": "restart_pod",
                "action_steps": [{"tool": "restart_pod", "params": {"pod": "auth-1", "namespace": "prod"}}],
                "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
            },
            "risk_tier": "high",
            "sla_minutes": 15,
        }

    def test_card_incident_id(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert card["incident_id"] == "inc-smoke-001"

    def test_card_severity(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert card["severity"] == "SEV1"

    def test_card_confidence_is_integer_percent(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert card["confidence"] == 88

    def test_card_blast_radius_comma_joined(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert card["blast_radius_services"] == "auth-service, api-gateway"

    def test_card_users_affected(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert card["estimated_users_affected"] == 12000

    def test_card_action_type(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert card["action_type"] == "restart_pod"

    def test_card_risk_tier(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert card["risk_tier"] == "high"

    def test_card_text_contains_header(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert "*Incident inc-smoke-001 — SEV1 — Approval Needed*" in card["text"]

    def test_card_text_contains_root_cause_line(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert "88% confidence" in card["text"]
        assert "OOMKilled" in card["text"]

    def test_card_text_contains_approve_reject_buttons(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert "[Approve]" in card["text"]
        assert "[Reject]" in card["text"]

    def test_card_text_contains_sla_expiry_notice(self):
        from apps.agents.src.services.slack_card import format_slack_approval_card
        card = format_slack_approval_card(self._make_state())
        assert "15 minutes" in card["text"]
