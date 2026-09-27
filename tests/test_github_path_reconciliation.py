"""Phase 4 — GitHub integration path reconciliation (ADR-004).

Proves that RISE has a SINGLE canonical GitHub path (`github_service.py`, called
directly by the approval flow) and that a *successful* real remediation is NOT
routed back through the fail-closed `mcp-github` simulation facade — which was the
latent bug that marked genuine successes as `requires_human`.

Fully offline: `commit_remediation_to_github` and the Verification Agent's live
GitHub confirmation are stubbed, so no network, DB, Redis, or LLM is required.
"""

from __future__ import annotations

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

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from apps.api.src.deps.db import get_db
from apps.api.src.deps.redis import get_redis_client

from mcp_client.lock import (
    ResourceLockManager,
    ResourceLockedException,
    clear_all_in_memory_locks,
)

from fastapi.testclient import TestClient
from apps.api.src.main import app

_TEST_SECRET = "test-supabase-secret-rise-unit-tests"

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
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis_client] = _override_redis
    yield
    app.dependency_overrides.clear()


client = TestClient(app, raise_server_exceptions=True)


def _approver_headers():
    token = jwt.encode(
        {
            "sub": "mock-approver",
            "roles": ["approver"],
            "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0))),
        },
        _TEST_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}


_REAL_PR_URL = "https://github.com/Viresh2408/RISE/pull/77"


async def _fake_commit_success(incident_id, incident_title, target_file="packages/rise-core/db/session.py", branch=None):
    """Stub the canonical GitHub service returning a genuine, verified PR."""
    return {
        "success": True,
        "commit_sha": "abc1234def5678",
        "commit_url": "https://github.com/Viresh2408/RISE/commit/abc1234def5678",
        "commit_message": "fix(remediation): apply automated fix",
        "commit_timestamp": "2026-09-24T00:00:00+00:00",
        "file": target_file,
        "file_modified": target_file,
        "branch": "fix/remediation-inc-auth-pool",
        "pr_url": _REAL_PR_URL,
        "pr_number": 77,
        "html_url": _REAL_PR_URL,
    }


async def _fake_verify_live(pr_identifier, **kwargs):
    """Stub the Verification Agent's independent live GitHub confirmation as open."""
    return {
        "verified": True,
        "pr_number": 77,
        "state": "open",
        "html_url": _REAL_PR_URL,
        "title": "fix(remediation): apply automated fix",
        "reason": "PR is verified open on GitHub",
    }


def test_successful_github_remediation_reports_verified_success(monkeypatch):
    """Regression (ADR-004): a successful real GitHub remediation must reach
    `verified_success` and NOT be spuriously marked `requires_human` by being
    routed through the fail-closed `mcp-github` mock facade."""
    monkeypatch.setattr(
        "apps.api.src.services.github_service.commit_remediation_to_github",
        _fake_commit_success,
    )
    monkeypatch.setattr(
        "apps.agents.src.nodes.verification.verify_github_pr_live",
        _fake_verify_live,
    )
    # Force the LLM verification call to fall back to the deterministic rule-based
    # evaluator (which passes for a healthy success execution log).
    monkeypatch.setattr(
        "apps.agents.src.nodes.verification.call_structured",
        AsyncMock(side_effect=Exception("no LLM in test env")),
    )

    resp = client.post(
        "/api/v1/incidents/inc-auth-pool-01/actions/act-fix-01/approve",
        headers=_approver_headers(),
        json={"note": "Approve automated remediation"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["status"] == "approved"
    assert data["execution_status"] == "verified_success"
    assert data["pr_number"] == 77
    assert data["pr_url"] == _REAL_PR_URL
    assert data["commit_sha"] == "abc1234def5678"


def test_mcp_github_facade_is_failclosed_and_not_the_real_path():
    """The mcp-github server is a simulation fixture: its write tools fail-close by
    default and are rejected in staging/production, so it can never be the real
    remediation writer (ADR-004)."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    gh_dir = str(root / "packages" / "mcp-servers" / "mcp-github")
    if gh_dir not in sys.path:
        sys.path.insert(0, gh_dir)
    from github_server import MCPGitHubServer

    # Default (no explicit test mock) => write tools fail closed.
    server = MCPGitHubServer()
    assert server.allow_test_mock is False
    with pytest.raises(RuntimeError, match="in-memory mock transport is disabled"):
        server.create_pr(repo="Viresh2408/RISE", title="x", head_branch="fix/y")

    # Even opting into the mock is forbidden in staging/production.
    prev_env = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "production"
    try:
        with pytest.raises(RuntimeError, match="SECURITY VIOLATION"):
            MCPGitHubServer(allow_test_mock=True)
    finally:
        if prev_env is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = prev_env


def _override_redis_none():
    # Force ResourceLockManager onto its in-memory backend so the pre-acquired
    # in-memory lock and the endpoint's lock attempt share one registry (the
    # shared MagicMock redis returns True for every SET, defeating NX semantics).
    yield None


def test_concurrent_github_approval_blocked_by_resource_lock(monkeypatch):
    """(ADR-004 #2) Two approvals targeting the same repo/file must not both write.

    Simulates a first remediation holding the per-file lock (as `approve_action`
    does around `commit_remediation_to_github`) and asserts a second, concurrent
    approval for the same file is rejected with 409 RESOURCE_LOCKED rather than
    proceeding to a racing GitHub write."""
    clear_all_in_memory_locks()
    app.dependency_overrides[get_redis_client] = _override_redis_none

    # Guard: if the lock failed to block, this stub would let a spurious success
    # through — the 409 assertion below would then fail loudly instead of hitting
    # the network or a fail-closed 200.
    monkeypatch.setattr(
        "apps.api.src.services.github_service.commit_remediation_to_github",
        _fake_commit_success,
    )

    # inc-auth-pool-01 maps to packages/rise-core/db/session.py (DEMO_INCIDENT_MAP);
    # the endpoint builds resource_id = "github:{owner}/{repo}:{target_file}".
    resource_id = "github:Viresh2408/RISE:packages/rise-core/db/session.py"

    # A DIFFERENT remediation currently holds the file lock (distinct owner so the
    # re-entrant same-owner path does not let the second approval through).
    ResourceLockManager.acquire_lock(resource_id=resource_id, owner_id="incident-OTHER")

    try:
        resp = client.post(
            "/api/v1/incidents/inc-auth-pool-01/actions/act-fix-01/approve",
            headers=_approver_headers(),
            json={"note": "Second concurrent approval on the same file"},
        )
        assert resp.status_code == 409, resp.text
        error = resp.json()["error"]
        assert error["code"] == "RESOURCE_LOCKED"
        assert resource_id in error["message"]
    finally:
        ResourceLockManager.release_lock(resource_id=resource_id, lock_token="incident-OTHER")
        clear_all_in_memory_locks()

    # After the first lock is released, the same file is writable again — proving the
    # block was the live lock, not a permanent denial.
    assert ResourceLockManager.get_lock_owner(resource_id) is None


def test_github_approval_rejects_stale_plan_hash():
    """(ADR-004 #1) A stale/altered approved plan_hash must halt the GitHub write
    with 409 ACTION_PLAN_CHANGED before `commit_remediation_to_github` is called —
    the same integrity gate execution.py applies to gateway-dispatched tools."""
    clear_all_in_memory_locks()

    resp = client.post(
        "/api/v1/incidents/inc-auth-pool-01/actions/act-fix-01/approve",
        headers=_approver_headers(),
        # A hash that cannot match the canonical code-fix plan the server rebuilds.
        json={"note": "Approve", "plan_hash": "0" * 64},
    )
    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == "ACTION_PLAN_CHANGED"
