"""Regression coverage for tenant isolation and pre-execution authorization."""

import asyncio
from datetime import datetime, timedelta, timezone
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import Approval, AuditEvent, Incident, RemediationAction, RiskPolicy, Tenant, User
from apps.api.src.deps.db import get_db
from apps.api.src.deps.redis import get_redis_client
from apps.api.src.main import app
from apps.agents.src.engines.decision_engine import DecisionEngine
from apps.agents.src.engines.risk_engine import RiskEngine
from mcp_client.lock import ResourceLockManager, ResourceLockedException, ResourceLockUnavailableError

SECRET = "test-supabase-secret-rise-unit-tests"
ACTOR_ID = uuid.uuid5(uuid.NAMESPACE_URL, "phase1-approver")


@pytest.fixture
def store():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    owner, foreign = uuid.uuid4(), uuid.uuid4()
    incident_id, foreign_incident, action_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with sessions() as db:
        db.add_all([Tenant(id=owner, name="owner"), Tenant(id=foreign, name="foreign")])
        db.flush()
        db.add(User(id=ACTOR_ID, tenant_id=owner, email="phase1@unit.invalid", role="admin"))
        db.add_all([
            Incident(id=incident_id, tenant_id=owner, title="Own incident", status="investigating", severity="SEV2"),
            Incident(id=foreign_incident, tenant_id=foreign, title="Foreign incident", status="investigating", severity="SEV1"),
        ])
        db.flush()
        db.add(RemediationAction(
            id=action_id, tenant_id=owner, incident_id=incident_id,
            action_type="code_fix_pr", action_plan={"action_type": "code_fix_pr"},
            risk_tier="critical", status="pending_approval",
        ))
        db.commit()

    def database():
        with sessions() as db:
            yield db

    def redis():
        yield None

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_redis_client] = redis
    yield sessions, owner, foreign, incident_id, foreign_incident, action_id
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
    engine.dispose()


def headers(tenant_id, *, key=None, subject=str(ACTOR_ID)):
    token = jwt.encode({
        "sub": subject, "roles": ["admin"], "tenant_id": str(tenant_id),
        "exp": int(time.time()) + 300,
    }, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key or str(uuid.uuid4())}


@pytest.mark.parametrize("facet", ["root-cause", "impact", "decision", "actions", "verification"])
def test_foreign_incident_facets_are_not_disclosed(store, facet):
    _, owner, _, _, foreign_incident, _ = store
    response = TestClient(app).get(f"/api/v1/incidents/{foreign_incident}/{facet}", headers=headers(owner))
    assert response.status_code == 404


@pytest.mark.parametrize("operation,body", [
    ("approve", {}), ("reject", {"reason": "no"}),
    ("modify", {"modified_plan": {"id": "p", "description": "d", "steps": []}}),
])
def test_foreign_or_misbound_action_cannot_be_mutated(store, operation, body, monkeypatch):
    sessions, owner, foreign, incident, _, action = store
    write = AsyncMock(side_effect=AssertionError("must not write"))
    monkeypatch.setattr("apps.api.src.services.github_service.commit_remediation_to_github", write)
    response = TestClient(app).post(
        f"/api/v1/incidents/{incident}/actions/{action}/{operation}", headers=headers(foreign), json=body,
    )
    assert response.status_code == 404
    response = TestClient(app).post(
        f"/api/v1/incidents/{uuid.uuid4()}/actions/{action}/{operation}", headers=headers(owner), json=body,
    )
    assert response.status_code == 404
    write.assert_not_called()
    with sessions() as db:
        assert db.get(RemediationAction, action).status == "pending_approval"
        assert db.execute(select(Approval)).scalars().all() == []


@pytest.mark.parametrize("environment", ["staging", "production", "unknown-deployment"])
def test_raw_execution_cannot_be_enabled_by_request_environment(store, monkeypatch, environment):
    _, owner, _, incident, _, action = store
    monkeypatch.setenv("ENVIRONMENT", environment)
    execute = AsyncMock()
    monkeypatch.setattr("apps.api.src.routers.actions.run_execution_agent", execute)
    response = TestClient(app).post(
        f"/api/v1/incidents/{incident}/actions/{action}/execute", headers=headers(owner),
        json={"action_plan": {"environment": "staging"}},
    )
    assert response.status_code == 403
    execute.assert_not_called()


def test_approval_is_durable_before_write_and_retries_do_not_write_twice(store, monkeypatch):
    sessions, owner, _, incident, _, action = store
    calls = []

    async def write(**kwargs):
        with sessions() as db:
            anchor = db.execute(select(Approval).where(Approval.action_id == action)).scalar_one()
            assert anchor.plan_hash
            assert anchor.user_id == ACTOR_ID
            assert anchor.idempotency_key == "approval-retry-key"
            assert db.get(RemediationAction, action).status == "executing"
        calls.append(kwargs)
        return {"success": True, "pr_number": 123, "pr_url": "https://github.com/Viresh2408/RISE/pull/123", "commit_sha": "a" * 40}

    monkeypatch.setattr("apps.api.src.services.github_service.commit_remediation_to_github", write)
    monkeypatch.setattr("apps.agents.src.nodes.verification.verify_github_pr_live", AsyncMock(return_value={"verified": True, "reason": "confirmed"}))
    monkeypatch.setattr("apps.agents.src.nodes.verification.call_structured", AsyncMock(side_effect=RuntimeError("offline")))
    client = TestClient(app)
    path = f"/api/v1/incidents/{incident}/actions/{action}/approve"
    auth = headers(owner, key="approval-retry-key")
    first = client.post(path, headers=auth, json={"note": "reviewed"})
    assert first.status_code == 200, first.text
    retry = client.post(path, headers=auth, json={"note": "reviewed"})
    assert retry.status_code == 200
    assert retry.json()["data"] == first.json()["data"]
    assert len(calls) == 1
    changed = client.post(path, headers=auth, json={"note": "different request"})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    fresh_key = client.post(path, headers=headers(owner), json={})
    assert fresh_key.status_code == 409
    assert len(calls) == 1


def test_expired_action_is_refused_before_write(store, monkeypatch):
    sessions, owner, _, incident, _, action = store
    with sessions() as db:
        db.get(RemediationAction, action).created_at = datetime.now(timezone.utc) - timedelta(minutes=16)
        db.commit()
    write = AsyncMock()
    monkeypatch.setattr("apps.api.src.services.github_service.commit_remediation_to_github", write)
    response = TestClient(app).post(f"/api/v1/incidents/{incident}/actions/{action}/approve", headers=headers(owner), json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVAL_EXPIRED"
    write.assert_not_called()


def test_authorization_audit_failure_prevents_any_external_write(store, monkeypatch):
    sessions, owner, _, incident, _, action = store
    write = AsyncMock()
    monkeypatch.setattr("apps.api.src.services.github_service.commit_remediation_to_github", write)
    monkeypatch.setattr("apps.api.src.routers.actions.write_audit_event", MagicMock(side_effect=RuntimeError("audit unavailable")))
    response = TestClient(app).post(f"/api/v1/incidents/{incident}/actions/{action}/approve", headers=headers(owner), json={})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "APPROVAL_PERSIST_FAILED"
    write.assert_not_called()
    with sessions() as db:
        assert db.get(RemediationAction, action).status == "pending_approval"
        assert db.execute(select(Approval)).scalars().all() == []


def test_user_editable_metadata_cannot_grant_tenant_access():
    token = jwt.encode({"sub": "user", "roles": ["admin"], "user_metadata": {"tenant_id": str(uuid.uuid4())}, "exp": int(time.time()) + 300}, SECRET, algorithm="HS256")
    response = TestClient(app).post("/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize("redis", [None, "unavailable"])
def test_deployed_lock_does_not_fall_back_to_process_memory(monkeypatch, redis):
    monkeypatch.setenv("ENVIRONMENT", "production")
    if redis is not None:
        redis = MagicMock()
        redis.set.side_effect = ConnectionError("offline")
    with pytest.raises(ResourceLockUnavailableError):
        ResourceLockManager.acquire_lock(str(uuid.uuid4()), redis_client=redis)


def test_deployed_database_does_not_fall_back_to_sqlite(monkeypatch):
    from db import session
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(session, "DATABASE_URL", "postgresql://unavailable")
    factory = MagicMock()
    factory.return_value.connect.side_effect = ConnectionError("offline")
    monkeypatch.setattr(session, "create_engine", factory)
    with pytest.raises(RuntimeError, match="DATABASE_UNAVAILABLE"):
        session._init_engine()
    assert factory.call_count == 1


def test_real_opa_auto_decision_requires_matching_persisted_policy(store):
    sessions, owner, foreign, _, _, _ = store
    state = {
        "tenant_id": str(owner), "environment": "staging", "root_cause": {"confidence": 0.95},
        "impact_assessment": {"blast_radius_services": ["service"]},
        "action_plan": {"action_type": "restart_pod", "action_steps": [{"tool": "restart_pod", "params": {"pod_name": "p"}}], "rollback_plan": [{"tool": "restart_pod", "params": {"pod_name": "p"}}], "plan_rationale": "restart"},
    }
    opa = AsyncMock(spec=httpx.AsyncClient)
    opa.post.return_value = httpx.Response(200, json={"result": {"risk_tiers": {"risk_level": "low"}, "approval_rules": {"requires_approval": False, "reasons": []}}})
    with sessions() as db:
        db.add(RiskPolicy(tenant_id=foreign, action_pattern="restart_pod", environment="staging", risk_tier="low", requires_approval=False))
        db.commit()
        engine = DecisionEngine()
        assert asyncio.run(engine.evaluate_and_plan(state, db=db, opa_client=opa)).requires_approval is True
        policy = RiskPolicy(tenant_id=owner, action_pattern="restart_pod", environment="staging", risk_tier="low", requires_approval=False, min_confidence=0.90, max_blast_radius=1)
        db.add(policy)
        db.commit()
        assert asyncio.run(engine.evaluate_and_plan(state, db=db, opa_client=opa)).requires_approval is False
        policy.requires_approval = True
        db.commit()
        assert asyncio.run(engine.evaluate_and_plan(state, db=db, opa_client=opa)).requires_approval is True


def test_local_policy_fixture_is_not_a_production_opa_fallback(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    result = RiskEngine().evaluate_risk_local_fallback("restart_pod", environment="staging", confidence=1.0)
    assert result.requires_approval is True
    assert result.opa_reachable is False


@pytest.mark.parametrize("operation,body", [
    ("reject", {"reason": "too risky"}),
    ("modify", {"modified_plan": {"id": "p", "description": "Manual restart", "steps": ["restart safely"]}}),
])
@pytest.mark.parametrize("status", ["executing", "executed", "rejected", "failed"])
def test_decisions_cannot_resurrect_or_change_a_claimed_action(store, operation, body, status):
    sessions, owner, _, incident, _, action = store
    with sessions() as db:
        db.get(RemediationAction, action).status = status
        db.commit()
    response = TestClient(app).post(
        f"/api/v1/incidents/{incident}/actions/{action}/{operation}", headers=headers(owner), json=body,
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ALREADY_DECIDED"
    with sessions() as db:
        assert db.get(RemediationAction, action).status == status
        assert db.execute(select(Approval)).scalars().all() == []


@pytest.mark.parametrize("operation,body", [
    ("reject", {"reason": "too risky"}),
    ("modify", {"modified_plan": {"id": "p", "description": "Manual restart", "steps": ["restart safely"]}}),
])
def test_nonexecuting_decisions_have_durable_idempotent_results(store, operation, body):
    sessions, owner, _, incident, _, action = store
    auth = headers(owner, key=f"{operation}-retry-key")
    path = f"/api/v1/incidents/{incident}/actions/{action}/{operation}"
    client = TestClient(app)
    first = client.post(path, headers=auth, json=body)
    assert first.status_code == 200, first.text
    retry = client.post(path, headers=auth, json=body)
    assert retry.status_code == 200
    assert retry.json()["data"] == first.json()["data"]
    with sessions() as db:
        anchor = db.execute(select(Approval)).scalar_one()
        assert anchor.decision == {"reject": "rejected", "modify": "modified"}[operation]
        assert anchor.request_hash
        assert anchor.response == first.json()["data"]
    # A key is bound to the operation, not merely an action or identical JSON.
    conflict = client.post(
        f"/api/v1/incidents/{incident}/actions/{action}/approve", headers=auth, json={},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize("operation,body", [
    ("reject", {"reason": "too risky"}),
    ("modify", {"modified_plan": {"id": "p", "description": "Manual restart", "steps": []}}),
])
def test_decision_audit_failure_rolls_back_status_plan_and_request(store, operation, body, monkeypatch):
    sessions, owner, _, incident, _, action = store
    monkeypatch.setattr("apps.api.src.routers.actions.write_audit_event", MagicMock(side_effect=RuntimeError("audit unavailable")))
    response = TestClient(app).post(
        f"/api/v1/incidents/{incident}/actions/{action}/{operation}", headers=headers(owner), json=body,
    )
    assert response.status_code == 500
    with sessions() as db:
        persisted = db.get(RemediationAction, action)
        assert persisted.status == "pending_approval"
        assert persisted.action_plan == {"action_type": "code_fix_pr"}
        assert db.execute(select(Approval)).scalars().all() == []


def test_manual_modification_is_not_replaced_with_a_templated_executable_plan(store, monkeypatch):
    _, owner, _, incident, _, action = store
    client = TestClient(app)
    base = f"/api/v1/incidents/{incident}/actions/{action}"
    modified = client.post(f"{base}/modify", headers=headers(owner), json={
        "modified_plan": {"id": "p", "description": "review this custom fix", "steps": ["perform manual checks"]},
    })
    assert modified.status_code == 200, modified.text
    write = AsyncMock()
    monkeypatch.setattr("apps.api.src.services.github_service.commit_remediation_to_github", write)
    approved = client.post(f"{base}/approve", headers=headers(owner), json={})
    assert approved.status_code == 409
    assert approved.json()["error"]["code"] == "MANUAL_PLAN_REQUIRED"
    write.assert_not_called()


def test_stale_pending_snapshot_cannot_claim_a_revised_plan(store):
    from apps.api.src.routers.actions import _update_pending_action
    from fastapi import HTTPException
    sessions, _, _, _, _, action_id = store
    with sessions() as stale:
        action = stale.get(RemediationAction, action_id)
        with sessions() as editor:
            editor.get(RemediationAction, action_id).action_plan = {"action_type": "code_fix_pr", "requires_manual_plan": True}
            editor.commit()
        with pytest.raises(HTTPException) as error:
            _update_pending_action(stale, action, {"status": "executing"})
        assert error.value.status_code == 409
    with sessions() as db:
        assert db.get(RemediationAction, action_id).status == "pending_approval"


def test_deployed_approval_reports_redis_unavailability_without_a_write(store, monkeypatch):
    _, owner, _, incident, _, action = store
    monkeypatch.setenv("ENVIRONMENT", "staging")
    write = AsyncMock()
    monkeypatch.setattr("apps.api.src.services.github_service.commit_remediation_to_github", write)
    response = TestClient(app).post(
        f"/api/v1/incidents/{incident}/actions/{action}/approve", headers=headers(owner), json={},
    )
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "REDIS_UNAVAILABLE"
    write.assert_not_called()


def test_real_resource_lock_conflict_prevents_github_write(store, monkeypatch):
    from apps.api.src.services.github_service import GITHUB_OWNER, GITHUB_REPO
    _, owner, _, incident, _, action = store
    resource = f"github:{GITHUB_OWNER}/{GITHUB_REPO}:packages/rise-core/db/session.py"
    token = ResourceLockManager.acquire_lock(resource)
    write = AsyncMock()
    monkeypatch.setattr("apps.api.src.services.github_service.commit_remediation_to_github", write)
    try:
        response = TestClient(app).post(
            f"/api/v1/incidents/{incident}/actions/{action}/approve", headers=headers(owner), json={},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "RESOURCE_LOCKED"
        write.assert_not_called()
    finally:
        ResourceLockManager.release_lock(resource, token)


@pytest.mark.parametrize("operation,body", [
    ("approve", {}), ("reject", {"reason": "no"}),
    ("modify", {"modified_plan": {"id": "p", "description": "d", "steps": []}}),
])
@pytest.mark.parametrize("subject", ["unmapped-slug", str(uuid.uuid5(uuid.NAMESPACE_URL, "unprovisioned-approver"))])
def test_deployed_decisions_require_a_persistable_tenant_bound_actor(store, monkeypatch, operation, body, subject):
    sessions, owner, _, incident, _, action = store
    redis = MagicMock()
    redis.set.return_value = True
    app.dependency_overrides[get_redis_client] = lambda: redis
    monkeypatch.setenv("ENVIRONMENT", "staging")
    write = AsyncMock()
    monkeypatch.setattr("apps.api.src.services.github_service.commit_remediation_to_github", write)
    response = TestClient(app).post(
        f"/api/v1/incidents/{incident}/actions/{action}/{operation}",
        headers=headers(owner, subject=subject), json=body,
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "APPROVER_NOT_PROVISIONED"
    write.assert_not_called()
    with sessions() as db:
        assert db.get(RemediationAction, action).status == "pending_approval"
        assert db.execute(select(Approval)).scalars().all() == []


@pytest.mark.parametrize("deployment", ["production", "prod", "unknown-deployment"])
@pytest.mark.parametrize("include_plan", [False, True])
def test_gateway_production_boundary_cannot_be_bypassed_by_staging_parameters(store, monkeypatch, deployment, include_plan):
    from mcp_client.gateway import MCPGateway, ToolBlockedError
    sessions, owner, _, incident, _, _ = store
    server = MagicMock()
    gateway = MCPGateway(k8s_server=server)
    monkeypatch.setenv("ENVIRONMENT", deployment)
    params = {"pod_name": "p"}
    plan = {"action_type": "restart_pod", "action_steps": [{"tool": "restart_pod", "params": params}]}
    with sessions() as db:
        with pytest.raises(ToolBlockedError) as error:
            asyncio.run(gateway.dispatch_tool_call(
                agent_identity="execution-agent", tool_name="restart_pod", params=params,
                environment="staging", tenant_id=owner, incident_id=incident, db_session=db,
                approved_plan=plan if include_plan else None, step_index=0 if include_plan else None,
            ))
        assert error.value.reason == "isolation_required"
        event = db.execute(select(AuditEvent)).scalar_one()
        assert event.action == "DENIED:restart_pod"
    server.handle_tool_call.assert_not_called()


def test_deployed_gateway_audit_failure_blocks_dispatch_before_side_effect(store, monkeypatch):
    from mcp_client.gateway import AuditWriteError, MCPGateway
    sessions, owner, _, incident, _, _ = store
    server = MagicMock()
    github = MagicMock()
    github.allow_test_mock = False
    gateway = MCPGateway(k8s_server=server, github_server=github)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setattr("db.models.create_audit_event", MagicMock(side_effect=RuntimeError("audit database unavailable")))
    with sessions() as db:
        with pytest.raises(AuditWriteError):
            asyncio.run(gateway.dispatch_tool_call(
                agent_identity="execution-agent", tool_name="restart_pod", params={"pod_name": "p"},
                environment="staging", tenant_id=owner, incident_id=incident, db_session=db,
            ))
    server.handle_tool_call.assert_not_called()


def test_existing_plan_does_not_fabricate_confidence_for_auto_execution(store):
    sessions, owner, _, _, _, _ = store
    state = {
        "tenant_id": str(owner), "environment": "staging", "root_cause": {},
        "impact_assessment": {"blast_radius_services": ["service"]},
        "action_plan": {"action_type": "restart_pod", "action_steps": [{"tool": "restart_pod", "params": {"pod_name": "p"}}],
                        "rollback_plan": [{"tool": "restart_pod", "params": {"pod_name": "p"}}], "plan_rationale": "restart"},
    }
    opa = AsyncMock(spec=httpx.AsyncClient)
    opa.post.return_value = httpx.Response(200, json={"result": {
        "risk_tiers": {"risk_level": "low"}, "approval_rules": {"requires_approval": False, "reasons": []},
    }})
    with sessions() as db:
        db.add(RiskPolicy(tenant_id=owner, action_pattern="restart_pod", environment="staging", risk_tier="low", requires_approval=False))
        db.commit()
        decision = asyncio.run(DecisionEngine().evaluate_and_plan(state, db=db, opa_client=opa))
        assert decision.requires_approval is True
        assert opa.post.call_args.kwargs["json"]["input"]["confidence"] == 0.0


def test_expired_lease_release_cannot_delete_successor_with_the_same_owner(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("mcp_client.lock.time.time", lambda: clock[0])
    resource, owner = str(uuid.uuid4()), "same-incident"
    stale = ResourceLockManager.acquire_lock(resource, ttl_seconds=1, owner_id=owner)
    clock[0] += 2
    successor = ResourceLockManager.acquire_lock(resource, owner_id=owner)
    try:
        ResourceLockManager.release_lock(resource, stale)
        with pytest.raises(ResourceLockedException):
            ResourceLockManager.acquire_lock(resource, owner_id="different-incident")
        assert ResourceLockManager.get_lock_owner(resource) == owner
    finally:
        ResourceLockManager.release_lock(resource, successor)
