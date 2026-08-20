"""Tests for RISE API FastAPI Endpoints and Envelope Standard.

This file covers basic endpoint availability, envelope format,
and specific error conditions.  Role/RBAC coverage lives in
test_auth_rbac.py.

JWT setup: tests set SUPABASE_JWT_SECRET so the production HS256 path is
exercised; tokens are minted with the same secret using _make_jwt().
"""

from __future__ import annotations

import os
import time

import jwt
import pytest
from fastapi.testclient import TestClient

# ── Set env BEFORE importing app so settings are picked up at module load ────
TEST_JWT_SECRET = "test-supabase-secret-rise-unit-tests"
os.environ.setdefault("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
os.environ.setdefault("ENVIRONMENT", "test")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

@compiles(JSONB, "sqlite")
def visit_JSONB(element, compiler, **kw):
    return "JSON"

@compiles(PG_UUID, "sqlite")
def visit_UUID(element, compiler, **kw):
    return "TEXT"

from unittest.mock import MagicMock

from db.base import Base
from apps.api.src.deps.db import get_db
from apps.api.src.deps.redis import get_redis_client

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
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

def override_get_redis():
    yield _redis_mock

from apps.api.src.main import app

@pytest.fixture(autouse=True)
def setup_api_overrides():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis_client] = override_get_redis
    yield
    app.dependency_overrides.clear()


client = TestClient(app, raise_server_exceptions=True)


def _make_jwt(role: str = "admin") -> str:
    return jwt.encode(
        {
            "sub": f"test-user-{role}",
            "roles": [role],
            "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0))),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


AUTH_HEADERS = {"Authorization": f"Bearer {_make_jwt('admin')}"}
APPROVER_HEADERS = {"Authorization": f"Bearer {_make_jwt('approver')}"}


def test_healthz_endpoint():
    response = client.get("/api/v1/healthz")
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["data"] == {"status": "ok"}
    assert "request_id" in json_data["meta"]
    assert "timestamp" in json_data["meta"]
    assert json_data["error"] is None


def test_unauthenticated_request_returns_401_envelope():
    response = client.get("/api/v1/incidents")
    assert response.status_code == 401
    json_data = response.json()
    assert json_data["data"] is None
    assert "request_id" in json_data["meta"]
    assert "timestamp" in json_data["meta"]
    assert json_data["error"]["code"] == "UNAUTHORIZED"
    assert "Missing or invalid authorization token" in json_data["error"]["message"]


def test_authenticated_list_incidents():
    response = client.get("/api/v1/incidents", headers=AUTH_HEADERS)
    assert response.status_code == 200
    json_data = response.json()
    assert isinstance(json_data["data"], list)
    assert json_data["error"] is None


def test_approve_action_missing_idempotency_key():
    response = client.post(
        "/api/v1/incidents/inc-001/actions/act-001/approve",
        headers=APPROVER_HEADERS,
        json={"note": "Looks good"},
    )
    assert response.status_code == 422
    json_data = response.json()
    assert json_data["data"] is None
    assert json_data["error"]["code"] == "VALIDATION_ERROR"


def test_approve_action_success_with_idempotency_key():
    headers = {**APPROVER_HEADERS, "Idempotency-Key": "idempotency-uuid-12345"}
    response = client.post(
        "/api/v1/incidents/inc-001/actions/act-001/approve",
        headers=headers,
        json={"note": "Approved by engineering lead"},
    )
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["data"]["status"] == "approved"
    assert json_data["data"]["execution_status"] == "queued"
    assert json_data["error"] is None


@pytest.mark.parametrize(
    "action_id, expected_code",
    [
        ("plan-changed", "ACTION_PLAN_CHANGED"),
        ("expired", "APPROVAL_EXPIRED"),
        ("locked", "RESOURCE_LOCKED"),
    ],
)
def test_approve_action_409_conflict_error_codes(action_id: str, expected_code: str):
    headers = {**APPROVER_HEADERS, "Idempotency-Key": "idempotency-uuid-12345"}
    response = client.post(
        f"/api/v1/incidents/inc-001/actions/{action_id}/approve",
        headers=headers,
        json={"note": "Test approval"},
    )
    assert response.status_code == 409
    json_data = response.json()
    assert json_data["data"] is None
    assert json_data["error"]["code"] == expected_code


@pytest.mark.parametrize(
    "webhook_path",
    [
        "/api/v1/webhooks/cloudwatch",
        "/api/v1/webhooks/alertmanager",
        "/api/v1/webhooks/github",
        "/api/v1/webhooks/slack",
    ],
)
def test_webhooks_without_jwt_auth(webhook_path: str):
    # Webhooks use signature verification, not Supabase JWT Bearer token
    from apps.api.src.services.ingestion.signature_verifier import (
        FakeVerifier,
        get_alertmanager_verifier,
        get_github_verifier,
        get_slack_verifier,
        get_sns_verifier,
    )
    from db.models import IntegrationConfig
    import uuid

    app.dependency_overrides[get_github_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[get_alertmanager_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[get_slack_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[get_sns_verifier] = lambda: FakeVerifier()

    source = webhook_path.split("/")[-1]
    with TestingSessionLocal() as db:
        if not db.query(IntegrationConfig).filter_by(type=source, credential_ref="test-org").first():
            db.add(IntegrationConfig(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                type=source,
                status="connected",
                credential_ref="test-org",
                scopes={}
            ))
            db.commit()

    payloads = {
        "github": {"repository": {"owner": {"login": "test-org"}}},
        "cloudwatch": {"TopicArn": "arn:aws:sns:us-east-1:test-org:alarm"},
        "slack": {"team_id": "test-org"},
        "alertmanager": {"groupLabels": {"cluster": "test-org"}},
    }

    from schemas.agent_state import IncidentEvent
    from unittest.mock import patch, AsyncMock
    fake_event = IncidentEvent(
        resource_id="svc-test",
        source=source,
        event_type="test_event",
        severity_hint="SEV2",
        summary="Test webhook event",
        is_likely_duplicate=False,
        duplicate_of_incident_id=None,
        sanitization_flags=[],
    )

    with patch("apps.api.src.routers.webhooks.run_ingestion_agent", new_callable=AsyncMock, return_value=fake_event):
        response = client.post(webhook_path, json=payloads[source])

    assert response.status_code == 200, f"Error body: {response.text}"
    json_data = response.json()
    assert json_data["data"]["received"] is True
    assert json_data["error"] is None

