"""Unit and integration tests for Evidence Chain endpoint (GET /incidents/{id}/evidence-chain).

Verifies:
  1. GET /incidents/{id}/evidence-chain returns 404 for unknown incident.
  2. Returns full structured evidence items with file_path, commit_sha, line_start, line_end.
  3. Returns raw_evidence_summary from Context Builder AgentStepResult.
  4. Correctly reports fix_verified=True when verified code_fix_snippet exists, False with reason when manual.
"""

from __future__ import annotations

import os
import uuid
import datetime
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.pool import StaticPool

@compiles(JSONB, "sqlite")
def visit_JSONB(element, compiler, **kw):
    return "JSON"

@compiles(PG_UUID, "sqlite")
def visit_UUID(element, compiler, **kw):
    return "TEXT"


TEST_JWT_SECRET = "test-supabase-secret-rise-unit-tests"
os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
os.environ["RISE_TEST_MODE"] = "0"

# pyrefly: ignore [missing-import]
from db.base import Base
# pyrefly: ignore [missing-import]
from db.models import (
    AgentRun,
    AgentStepResult,
    Evidence,
    Incident,
    RemediationAction,
    RootCause,
    Service,
    Tenant,
    User,
)
# pyrefly: ignore [missing-import]
from apps.api.src.main import app
# pyrefly: ignore [missing-import]
from apps.api.src.deps.db import get_db


def _patch_metadata_for_sqlite(metadata):
    for table in metadata.tables.values():
        for col in table.columns:
            if col.server_default is None:
                continue
            try:
                raw = str(col.server_default.arg)
            except Exception:
                raw = ""
            if "gen_random_uuid" in raw:
                col.server_default = None


_patch_metadata_for_sqlite(Base.metadata)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


def make_token(tenant_id: str, user_id: str, role: str = "engineer") -> str:
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "user_roles": [role],
        "aud": "authenticated",
        "exp": 9999999999,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def test_evidence_chain_404_for_missing_incident() -> None:
    client = TestClient(app)
    t_id = str(uuid.uuid4())
    u_id = str(uuid.uuid4())
    token = make_token(t_id, u_id, "viewer")

    res = client.get(
        f"/api/v1/incidents/{uuid.uuid4()}/evidence-chain",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


def test_evidence_chain_returns_grounded_evidence_and_context() -> None:
    db = TestingSessionLocal()
    t_id = uuid.uuid4()
    u_id = uuid.uuid4()

    tenant = Tenant(id=t_id, name="Test Corp")
    db.add(tenant)

    svc = Service(id=uuid.uuid4(), tenant_id=t_id, name="api-gateway", environment="production")
    db.add(svc)

    inc_id = uuid.uuid4()
    inc = Incident(
        id=inc_id,
        tenant_id=t_id,
        title="Redis connection churn in api-gateway",
        description="500 errors spike",
        status="open",
        severity="SEV1",
        affected_service_id=svc.id,
    )
    db.add(inc)

    rc = RootCause(
        id=uuid.uuid4(),
        tenant_id=t_id,
        incident_id=inc_id,
        cause_summary="Unpooled redis client in redis.py",
        confidence=0.92,
    )
    db.add(rc)

    now = datetime.datetime.now(datetime.timezone.utc)
    ev = Evidence(
        id=uuid.uuid4(),
        tenant_id=t_id,
        root_cause_id=rc.id,
        type="code_file",
        reference="apps/api/src/deps/redis.py",
        excerpt="client = redis.from_url(_REDIS_URL)",
        commit_sha="a8f3b29c1234567890abcdef1234567890abcdef",
        file_path="apps/api/src/deps/redis.py",
        line_start=20,
        line_end=33,
        fetched_at=now,
    )
    db.add(ev)

    run = AgentRun(
        id=uuid.uuid4(),
        tenant_id=t_id,
        incident_id=inc_id,
        trigger_type="incident_created",
        status="completed",
    )
    db.add(run)

    step = AgentStepResult(
        id=uuid.uuid4(),
        tenant_id=t_id,
        agent_run_id=run.id,
        agent_name="context_builder",
        input={},
        output={},
        confidence=0.9,
        duration_ms=120,
        raw_evidence_record={
            "fetched_at": now.isoformat(),
            "sources": {
                "loki": {"content": "error log bytes", "is_missing": False},
                "github": {
                    "content": "deploy bytes",
                    "is_missing": False,
                    "file_contents": {
                        "apps/api/src/deps/redis.py": {
                            "commit_sha": "a8f3b29c",
                            "line_count": 40,
                        }
                    },
                },
                "slack": {
                    "threads": [
                        {
                            "channel": "dev-ops",
                            "snippet": "Redis spike discussion",
                            "permalink": "https://slack.com/archives/1",
                        }
                    ],
                    "is_missing": False,
                },
            },
        },
    )
    db.add(step)

    act = RemediationAction(
        id=uuid.uuid4(),
        tenant_id=t_id,
        incident_id=inc_id,
        action_type="code_fix_pr",
        risk_tier="high",
        status="pending_approval",
        action_plan={
            "action_type": "code_fix_pr",
            "action_steps": [{"tool": "code_fix_pr", "params": {"file": "apps/api/src/deps/redis.py"}}],
            "code_fix_snippet": {
                "file": "apps/api/src/deps/redis.py",
                "diff": "@@ -20,4 +20,4 @@\n-old\n+new",
            },
            "requires_manual_plan": False,
        },
    )
    db.add(act)

    db.commit()
    db.close()

    client = TestClient(app)
    token = make_token(str(t_id), str(u_id), "viewer")

    res = client.get(
        f"/api/v1/incidents/{inc_id}/evidence-chain",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()["data"]

    assert data["incident_id"] == str(inc_id)
    assert data["root_cause_summary"] == "Unpooled redis client in redis.py"
    assert data["confidence"] == 0.92
    assert len(data["evidence_items"]) == 1
    ev_item = data["evidence_items"][0]
    assert ev_item["file_path"] == "apps/api/src/deps/redis.py"
    assert ev_item["commit_sha"] == "a8f3b29c1234567890abcdef1234567890abcdef"
    assert ev_item["line_start"] == 20
    assert ev_item["line_end"] == 33
    assert data["fix_verified"] is True
    assert len(data["files_fetched"]) == 1
    assert len(data["slack_threads"]) == 1
    assert data["slack_threads"][0]["permalink"] == "https://slack.com/archives/1"


def test_ast_confirm_no_fabricated_code_fix_in_incidents_router() -> None:
    """Assertion (2): Confirm _generate_code_fix_snippet and KNOWN_INCIDENTS_CATALOG do not exist in incidents.py."""
    import ast
    import inspect
    import apps.api.src.routers.incidents as inc_mod

    source = inspect.getsource(inc_mod)
    tree = ast.parse(source)

    # AST check: no function named _generate_code_fix_snippet
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            assert node.name != "_generate_code_fix_snippet", (
                "Found prohibited _generate_code_fix_snippet function in incidents.py!"
            )
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assert target.id != "KNOWN_INCIDENTS_CATALOG", (
                        "Found prohibited KNOWN_INCIDENTS_CATALOG in incidents.py!"
                    )

    # Text check: no hardcoded fake commit SHAs or fabricated snippets
    assert "_generate_code_fix_snippet" not in source
    assert "KNOWN_INCIDENTS_CATALOG" not in source
    assert "a8f3b29c" not in source


def test_missing_raw_evidence_or_unverified_fix_returns_unavailable_reason_never_diff() -> None:
    """Assertion (5): Missing raw evidence or unverified plan returns fix_verified=False and non-empty fix_unavailable_reason."""
    db = TestingSessionLocal()
    t_id = uuid.uuid4()
    u_id = uuid.uuid4()

    tenant = Tenant(id=t_id, name="Test Corp Unverified")
    db.add(tenant)

    svc = Service(id=uuid.uuid4(), tenant_id=t_id, name="auth-service", environment="production")
    db.add(svc)

    inc_id = uuid.uuid4()
    inc = Incident(
        id=inc_id,
        tenant_id=t_id,
        title="Unverified Incident",
        description="Degradation with no file access",
        status="open",
        severity="SEV2",
        affected_service_id=svc.id,
    )
    db.add(inc)

    # Escalated / manual remediation action with NO code_fix_snippet
    act = RemediationAction(
        id=uuid.uuid4(),
        tenant_id=t_id,
        incident_id=inc_id,
        action_type="escalate_to_human",
        risk_tier="high",
        status="pending_approval",
        action_plan={
            "action_type": "escalate_to_human",
            "action_steps": [],
            "rollback_plan": [],
            "plan_rationale": "Real file content unavailable for auth-service; manual plan required.",
            "requires_manual_plan": True,
            "fix_unavailable_reason": "Cannot generate verified code fix: real file content unavailable.",
        },
    )
    db.add(act)

    db.commit()
    db.close()

    client = TestClient(app)
    token = make_token(str(t_id), str(u_id), "viewer")

    # 1. Check GET /evidence-chain
    res_chain = client.get(
        f"/api/v1/incidents/{inc_id}/evidence-chain",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_chain.status_code == 200
    chain_data = res_chain.json()["data"]

    assert chain_data["fix_verified"] is False
    assert chain_data["fix_unavailable_reason"] is not None
    assert "unavailable" in chain_data["fix_unavailable_reason"].lower()

    # 2. Check GET /incidents/{id}
    res_inc = client.get(
        f"/api/v1/incidents/{inc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_inc.status_code == 200
    inc_data = res_inc.json()["data"]

    rec_action = inc_data["decision"]["recommended_action"]
    assert rec_action.get("code_fix_snippet") is None, "code_fix_snippet must be None when unverified!"
    assert rec_action.get("fix_unavailable_reason") is not None
    assert "unavailable" in rec_action["fix_unavailable_reason"].lower()

