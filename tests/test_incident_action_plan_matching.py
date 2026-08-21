"""Tests for Incident Detail Action Plan resolution and matching.

Verifies that the dashboard/API always returns the actual ActionPlan record
tied to the specific incident_id (from catalog or DB-recorded remediation actions),
preventing any mismatch or stale fallback.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Generator
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi.testclient import TestClient

TEST_JWT_SECRET = "test-supabase-secret-rise-unit-tests"
os.environ.setdefault("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
os.environ.setdefault("ENVIRONMENT", "test")

sys.path.insert(0, "packages/rise-core")

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

from db.base import Base
from db.models import Incident, RemediationAction, Service, Tenant
from apps.api.src.deps.db import get_db
from apps.api.src.deps.redis import get_redis_client
from apps.api.src.main import app

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

@pytest.fixture(autouse=True)
def setup_api_overrides():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis_client] = override_get_redis
    yield
    app.dependency_overrides.clear()

def _make_jwt(role: str = "viewer", tenant_id: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") -> str:
    return jwt.encode(
        {
            "sub": f"test-user-{role}",
            "roles": [role],
            "tenant_id": tenant_id,
            "exp": int(time.time()) + 3600,
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_inc_redis_pool_09_catalog_plan_matching(client: TestClient):
    """Confirm inc-redis-pool-09 returns Redis ConnectionPool action plan, not JWKS/auth."""
    headers = {"Authorization": f"Bearer {_make_jwt('viewer')}"}
    resp = client.get("/api/v1/incidents/inc-redis-pool-09", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["id"] == "inc-redis-pool-09"
    assert "Redis" in data["title"]
    assert data["affected_service"] == "api-gateway"

    rec_action = data["decision"]["recommended_action"]
    assert "Redis" in rec_action["description"] or "ConnectionPool" in rec_action["description"]
    assert any("redis.py" in step for step in rec_action["steps"])
    assert rec_action["code_fix_snippet"]["file"] == "apps/api/src/deps/redis.py"
    assert "ConnectionPool" in rec_action["code_fix_snippet"]["diff"]


def test_db_recorded_action_plan_rendered_in_incident_detail(client: TestClient):
    """Confirm that an incident with an executed/saved ActionPlan in DB returns the exact recorded steps."""
    db = TestingSessionLocal()
    tenant_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    try:
        tenant = Tenant(id=tenant_id, name="Test Tenant Plan")
        db.add(tenant)
        db.flush()

        svc = Service(id=uuid.uuid4(), tenant_id=tenant_id, name="payment-service", environment="production")
        db.add(svc)
        db.flush()

        inc = Incident(
            id=incident_id,
            tenant_id=tenant_id,
            title="Redis Connection Leak in Payment Ledger",
            description="Exhausted pool sockets on checkout ledger transactions",
            status="investigating",
            severity="SEV1",
            affected_service_id=svc.id,
        )
        db.add(inc)
        db.flush()

        # Recorded Action Plan from remediation / execution agent
        custom_steps = [
            "code_fix_pr: {'file': 'apps/payment/src/pool.py', 'branch': 'fix/remediation-pool-leak'}",
            "deploy_canary: {'service': 'payment-service', 'weight': 10}",
            "verify_health: {'endpoint': '/health', 'expected_status': 200}"
        ]
        action_plan_data = {
            "plan_rationale": "Apply specialized connection pool mutex and leak guard to payment ledger",
            "action_steps": custom_steps,
            "rollback_plan": "kubectl rollout undo deployment payment-service",
            "code_fix_snippet": {
                "file": "apps/payment/src/pool.py",
                "github_url": "https://github.com/Viresh2408/RISE/blob/main/apps/payment/src/pool.py#L10-L25",
                "lines": "L10-L25",
                "commit_id": "c98f12a4",
                "diff": "@@ -10,3 +10,6 @@\n+_PAYMENT_POOL = ConnectionPool(max=20)\n"
            }
        }

        action = RemediationAction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            incident_id=incident_id,
            action_type="code_fix_pr",
            action_plan=action_plan_data,
            risk_tier="high",
            status="pending_approval",
        )
        db.add(action)
        db.commit()

        # Query incident detail via API with a token scoped to this tenant
        tenant_token = _make_jwt(role="viewer", tenant_id=str(tenant_id))
        resp = client.get(f"/api/v1/incidents/{incident_id}", headers={"Authorization": f"Bearer {tenant_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]

        rec_action = data["decision"]["recommended_action"]
        assert rec_action["description"] == "Apply specialized connection pool mutex and leak guard to payment ledger"
        assert rec_action["steps"] == custom_steps
        assert rec_action["rollback_plan"] == "kubectl rollout undo deployment payment-service"
        assert rec_action["code_fix_snippet"]["file"] == "apps/payment/src/pool.py"

    finally:
        db.close()
