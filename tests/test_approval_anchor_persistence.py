"""Phase 4 — Persisted human-approval anchor (ADR-005).

Proves that RISE binds a specific human approver to the specific plan hash they
approved, DURABLY (a persisted ``Approval`` row), rather than trusting a hash
supplied in-flight on the execution request:

  1. A successful DB-backed remediation persists exactly one ``Approval`` anchor
     whose ``plan_hash`` is the canonical code-fix plan hash.
  2. A plan that has drifted from a previously persisted anchor is rejected with
     409 ``ACTION_PLAN_CHANGED`` BEFORE any GitHub write occurs.
  3. ``run_execution_agent`` fails closed when ``require_approved_hash`` is set
     but no anchor is present (the "only enforced when present" gap).

Fully offline: the GitHub write and the Verification Agent's live confirmation
are stubbed, so no network, Redis, or LLM is required.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-secret-rise-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-slack-signing-secret")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-github-secret")
os.environ.setdefault("ALERTMANAGER_WEBHOOK_SECRET", "test-alertmanager-secret")

import jwt
import pytest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import Approval, Incident, RemediationAction
from mcp_client.hash import compute_action_plan_hash

from apps.api.src.deps.db import get_db
from apps.api.src.deps.redis import get_redis_client
from apps.api.src.services.approval_lock import reset_approval_locks_for_testing

from fastapi.testclient import TestClient
from apps.api.src.main import app

_TEST_SECRET = "test-supabase-secret-rise-unit-tests"
_TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
# Real DB-backed incidents (not in DEMO_INCIDENT_MAP) with no affected service
# resolve to this default target file inside approve_action.
_DEFAULT_TARGET_FILE = "packages/rise-core/db/session.py"
_REAL_PR_URL = "https://github.com/Viresh2408/RISE/pull/91"

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
_redis_mock.delete.return_value = True
_redis_mock.exists.return_value = False


def _override_redis():
    yield _redis_mock


@pytest.fixture(autouse=True)
def _inject_overrides():
    reset_approval_locks_for_testing()
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis_client] = _override_redis
    yield
    app.dependency_overrides.clear()
    reset_approval_locks_for_testing()


client = TestClient(app, raise_server_exceptions=True)


def _approver_headers():
    token = jwt.encode(
        {
            "sub": "mock-approver",
            "roles": ["approver"],
            "tenant_id": str(_TENANT_ID),
            "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0))),
        },
        _TEST_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}


def _seed_incident_and_action(title="Real DB-backed remediation incident"):
    """Insert a real Incident + code-fix RemediationAction and return their ids."""
    db = _Session()
    try:
        incident = Incident(
            id=uuid.uuid4(),
            tenant_id=_TENANT_ID,
            title=title,
            status="investigating",
            severity="high",
        )
        action = RemediationAction(
            id=uuid.uuid4(),
            tenant_id=_TENANT_ID,
            incident_id=incident.id,
            action_type="code_fix_pr",
            action_plan={"action_type": "code_fix_pr", "plan_rationale": "seed"},
            risk_tier="high",
            status="pending_approval",
        )
        db.add(incident)
        db.add(action)
        db.commit()
        return str(incident.id), str(action.id), title
    finally:
        db.close()


def _canonical_code_fix_hash(incident_id: str, inc_title: str, target_file=_DEFAULT_TARGET_FILE):
    """Recompute the exact canonical plan hash approve_action builds for a code fix."""
    plan = {
        "action_type": "code_fix_pr",
        "action_steps": [
            {"tool": "code_fix_pr", "params": {"incident_id": incident_id, "target_file": target_file}}
        ],
        "rollback_plan": [
            {"tool": "revert_pr", "params": {"incident_id": incident_id, "target_file": target_file}}
        ],
        "plan_rationale": f"Automated code-fix remediation for: {inc_title}",
    }
    return compute_action_plan_hash(plan)


async def _fake_commit_success(incident_id, incident_title, target_file=_DEFAULT_TARGET_FILE, branch=None):
    return {
        "success": True,
        "commit_sha": "sha91feed",
        "commit_url": "https://github.com/Viresh2408/RISE/commit/sha91feed",
        "commit_message": "fix(remediation): apply automated fix",
        "commit_timestamp": "2026-09-25T00:00:00+00:00",
        "file": target_file,
        "file_modified": target_file,
        "branch": "fix/remediation-real-01",
        "pr_url": _REAL_PR_URL,
        "pr_number": 91,
        "html_url": _REAL_PR_URL,
    }


async def _fake_verify_live(pr_identifier, **kwargs):
    return {
        "verified": True,
        "pr_number": 91,
        "state": "open",
        "html_url": _REAL_PR_URL,
        "title": "fix(remediation): apply automated fix",
        "reason": "PR is verified open on GitHub",
    }


def test_approval_persists_durable_anchor(monkeypatch):
    """(ADR-005 #1) A successful DB-backed remediation writes exactly one persisted
    ``Approval`` anchor whose ``plan_hash`` equals the canonical code-fix plan hash,
    binding the approver + decision to the specific plan that executed."""
    monkeypatch.setattr(
        "apps.api.src.services.github_service.commit_remediation_to_github",
        _fake_commit_success,
    )
    monkeypatch.setattr(
        "apps.agents.src.nodes.verification.verify_github_pr_live",
        _fake_verify_live,
    )
    monkeypatch.setattr(
        "apps.agents.src.nodes.verification.call_structured",
        AsyncMock(side_effect=Exception("no LLM in test env")),
    )

    incident_id, action_id, title = _seed_incident_and_action()

    resp = client.post(
        f"/api/v1/incidents/{incident_id}/actions/{action_id}/approve",
        headers=_approver_headers(),
        json={"note": "Approve real DB-backed remediation"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "approved"
    assert data["execution_status"] == "verified_success"

    expected_hash = _canonical_code_fix_hash(incident_id, title)

    db = _Session()
    try:
        anchors = db.execute(
            select(Approval).where(Approval.action_id == uuid.UUID(action_id))
        ).scalars().all()
    finally:
        db.close()

    assert len(anchors) == 1, "exactly one persisted approval anchor expected"
    anchor = anchors[0]
    assert anchor.decision == "approved"
    assert anchor.note == "Approve real DB-backed remediation"
    assert anchor.plan_hash == expected_hash, (
        "persisted anchor must bind the exact canonical plan hash that executed"
    )


def test_approval_rejected_when_plan_drifts_from_persisted_anchor(monkeypatch):
    """(ADR-005 #2) When a prior persisted ``Approval`` anchor no longer matches the
    current canonical plan, the write is refused with 409 ACTION_PLAN_CHANGED BEFORE
    ``commit_remediation_to_github`` is ever called — compared against server state,
    not a client-supplied hash."""

    async def _must_not_write(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("GitHub write must not run once anchor drift is detected")

    monkeypatch.setattr(
        "apps.api.src.services.github_service.commit_remediation_to_github",
        _must_not_write,
    )

    incident_id, action_id, _ = _seed_incident_and_action(title="Drifted incident")

    # A previously recorded human approval bound to a DIFFERENT (now stale) plan hash.
    db = _Session()
    try:
        db.add(Approval(
            tenant_id=_TENANT_ID,
            action_id=uuid.UUID(action_id),
            user_id=None,
            decision="approved",
            note="Earlier approval of a now-superseded plan",
            plan_hash="f" * 64,
        ))
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"/api/v1/incidents/{incident_id}/actions/{action_id}/approve",
        headers=_approver_headers(),
        json={"note": "Re-approval after plan drift"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "ACTION_PLAN_CHANGED"


def test_execution_agent_fails_closed_without_anchor():
    """(ADR-005 #4) An approval-bearing execution must refuse to run un-anchored:
    ``require_approved_hash`` set with no ``approved_plan_hash`` => ACTION_PLAN_CHANGED."""
    from apps.agents.src.nodes.execution import run_execution_agent

    state = {
        "tenant_id": str(_TENANT_ID),
        "incident_id": "inc-anchor-test",
        "action_plan": {
            "action_type": "restart_pod",
            "action_steps": [{"tool": "restart_pod", "params": {"namespace": "staging", "pod_name": "p"}}],
            "rollback_plan": [{"tool": "restart_pod", "params": {"namespace": "staging", "pod_name": "p"}}],
            "plan_rationale": "restart",
        },
        # No approved_plan_hash, but the run is marked as requiring an anchor.
        "require_approved_hash": True,
        "environment": "staging",
    }

    result = asyncio.run(run_execution_agent(state))
    assert result.get("error_code") == "ACTION_PLAN_CHANGED"
    assert result["execution_log"]["status"] == "failed"
    assert result["execution_log"]["steps_completed"] == 0
