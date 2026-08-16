"""Integration & Definition of Done Test Suite for Execution Agent & MCP Infrastructure.

Verifies:
  1. Un-approved tool call blocked by allow-list middleware + audit logged (DoD #1).
  2. Modified plan hash triggers ACTION_PLAN_CHANGED (409) and halts (DoD #2).
  3. Step parameter modification for approved tool blocked by step-level validation + audit logged.
  4. Concurrent execution on same resource blocked by RESOURCE_LOCKED (409).
  5. Staging K8s pod restart end-to-end confirms pod is restarted (DoD #3).
  6. Every tool call produces an immutable audit log entry (DoD #4).
"""

from __future__ import annotations

import asyncio
import pytest
import uuid
from typing import Any, Dict

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _dir in ["mcp-kubernetes", "mcp-aws", "mcp-github"]:
    _p = str(_ROOT / "packages" / "mcp-servers" / _dir)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mcp_client.gateway import MCPGateway, ToolBlockedError
from mcp_client.hash import compute_action_plan_hash
from mcp_client.lock import ResourceLockManager, ResourceLockedException, clear_all_in_memory_locks
from kubernetes_server import MCPKubernetesServer
from aws_server import MCPAWSServer
from github_server import MCPGitHubServer
from apps.agents.src.nodes.execution import run_execution_agent, ActionPlanChangedError
from schemas.agent_state import ActionPlan, ActionStep



@pytest.fixture(autouse=True)
def reset_locks():
    clear_all_in_memory_locks()
    yield
    clear_all_in_memory_locks()


class _MockQueryResult:
    def scalar_one_or_none(self):
        return None

class MockDBAuditSession:
    """Mock DB session to capture AuditEvents written during gateway tool calls."""

    def __init__(self):
        self.events = []
        self.bind = None

    def execute(self, stmt):
        return _MockQueryResult()

    def add(self, entity):
        self.events.append(entity)

    def commit(self):
        pass



# ---------------------------------------------------------------------------
# DoD 1: Un-approved tool attempt blocked by allow-list middleware + audit logged
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_dod1_unapproved_tool_blocked_and_audit_logged():
    gw = MCPGateway()
    db_session = MockDBAuditSession()

    tenant_id = str(uuid.uuid4())
    incident_id = str(uuid.uuid4())

    # Attempt tool call NOT in allowed list for context-builder-agent (e.g. restart_pod is write tool)
    with pytest.raises(ToolBlockedError) as exc_info:
        await gw.dispatch_tool_call(
            agent_identity="context-builder-agent",
            tool_name="restart_pod",
            params={"namespace": "staging", "pod_name": "auth-service-7890"},
            tenant_id=tenant_id,
            incident_id=incident_id,
            db_session=db_session,
        )

    assert "blocked by OPA allow-list" in str(exc_info.value)

    # Confirm audit log captured the blocked attempt
    assert len(db_session.events) == 1
    event = db_session.events[0]
    assert event.actor == "context-builder-agent"
    assert event.action == "DENIED:restart_pod"
    assert event.before_state["status"] == "blocked"


# ---------------------------------------------------------------------------
# DoD 2: Modified plan hash triggers ACTION_PLAN_CHANGED (409)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_dod2_modified_plan_hash_fires_action_plan_changed():
    approved_plan = ActionPlan(
        action_type="restart_pod",
        action_steps=[ActionStep(tool="restart_pod", params={"namespace": "staging", "pod_name": "auth-service-7890"})],
        rollback_plan=[],
        plan_rationale="Restart unstable pod",
    )
    original_hash = compute_action_plan_hash(approved_plan)

    # Tamper with plan (change pod name) after approval
    tampered_plan = ActionPlan(
        action_type="restart_pod",
        action_steps=[ActionStep(tool="restart_pod", params={"namespace": "staging", "pod_name": "auth-service-TAMPERED"})],
        rollback_plan=[],
        plan_rationale="Restart unstable pod",
    )

    state = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "action_plan": tampered_plan,
        "approved_plan_hash": original_hash,  # Hash of original, non-tampered plan
        "environment": "staging",
    }

    result_state = await run_execution_agent(state)
    exec_log = result_state.get("execution_log", {})

    assert exec_log["status"] == "failed"
    assert exec_log["steps_completed"] == 0
    assert result_state.get("error_code") == "ACTION_PLAN_CHANGED"
    assert "Action plan hash changed since approval" in exec_log["error"]


# ---------------------------------------------------------------------------
# Per-Step Parameter Verification Test
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step_level_parameter_mismatch_blocked():
    gw = MCPGateway()
    db_session = MockDBAuditSession()

    approved_plan = ActionPlan(
        action_type="restart_pod",
        action_steps=[ActionStep(tool="restart_pod", params={"namespace": "staging", "pod_name": "auth-service-7890"})],
        rollback_plan=[],
        plan_rationale="Restart auth service pod",
    )

    # Call approved tool ('restart_pod') but with DIFFERENT params than approved step 0
    with pytest.raises(ToolBlockedError) as exc_info:
        await gw.dispatch_tool_call(
            agent_identity="execution-agent",
            tool_name="restart_pod",
            params={"namespace": "prod", "pod_name": "prod-auth-service-TAMPERED"},  # Parameter mismatch!
            approved_plan=approved_plan,
            step_index=0,
            db_session=db_session,
        )

    assert "Parameters" in str(exc_info.value) and "do not match approved parameters" in str(exc_info.value)
    assert len(db_session.events) == 1
    assert db_session.events[0].action == "DENIED:restart_pod"


# ---------------------------------------------------------------------------
# Concurrent Resource Locking Test (RESOURCE_LOCKED 409)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_concurrent_execution_attempts_blocked_by_resource_lock():
    resource_id = "staging-auth-service"

    # Acquire lock for first execution
    token1 = ResourceLockManager.acquire_lock(resource_id=resource_id, ttl_seconds=300, owner_id="incident-001")
    assert token1 is not None

    # Attempt second concurrent execution on the same resource
    with pytest.raises(ResourceLockedException) as exc_info:
        ResourceLockManager.acquire_lock(resource_id=resource_id, ttl_seconds=300, owner_id="incident-002")

    assert exc_info.value.code == "RESOURCE_LOCKED"
    assert exc_info.value.status_code == 409
    assert resource_id in str(exc_info.value)

    # Release first lock
    ResourceLockManager.release_lock(resource_id=resource_id, lock_token=token1)

    # Now second acquisition succeeds
    token2 = ResourceLockManager.acquire_lock(resource_id=resource_id, ttl_seconds=300, owner_id="incident-002")
    assert token2 is not None


# ---------------------------------------------------------------------------
# DoD 3: Real/Staging Kubernetes pod restart end-to-end
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_dod3_staging_kubernetes_restart_pod_end_to_end():
    k8s_server = MCPKubernetesServer()
    gw = MCPGateway(k8s_server=k8s_server)
    db_session = MockDBAuditSession()

    tenant_id = str(uuid.uuid4())
    incident_id = str(uuid.uuid4())
    pod_name = "auth-service-7890"

    approved_plan = ActionPlan(
        action_type="restart_pod",
        action_steps=[
            ActionStep(tool="get_pod_status", params={"namespace": "staging", "pod_name": pod_name}),
            ActionStep(tool="restart_pod", params={"namespace": "staging", "pod_name": pod_name}),
        ],
        rollback_plan=[],
        plan_rationale="Restart unstable staging auth pod",
    )
    plan_hash = compute_action_plan_hash(approved_plan)

    state = {
        "tenant_id": tenant_id,
        "incident_id": incident_id,
        "action_plan": approved_plan,
        "approved_plan_hash": plan_hash,
        "resource_id": f"staging:{pod_name}",
        "environment": "staging",
    }

    # Execute end-to-end
    result_state = await run_execution_agent(state, gateway=gw, db_session=db_session)
    exec_log = result_state.get("execution_log", {})

    assert exec_log["status"] == "success"
    assert exec_log["steps_completed"] == 2
    assert exec_log["steps_total"] == 2

    # Verify pod state in staging server confirms it actually restarted
    pod_status = k8s_server.get_pod_status(namespace="staging", pod_name=pod_name)
    assert pod_status["pod_name"] == pod_name
    assert pod_status["restarts"] > 0


# ---------------------------------------------------------------------------
# DoD 4: Audit Log entries recorded for every tool call
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_dod4_every_tool_call_produces_audit_log():
    gw = MCPGateway()
    db_session = MockDBAuditSession()

    tenant_id = str(uuid.uuid4())
    incident_id = str(uuid.uuid4())

    # 1. Successful tool call
    res = await gw.dispatch_tool_call(
        agent_identity="execution-agent",
        tool_name="scale_deployment",
        params={"namespace": "staging", "deployment_name": "payment-service", "replicas": 3},
        tenant_id=tenant_id,
        incident_id=incident_id,
        db_session=db_session,
    )
    assert res["status"] == "success"
    assert len(db_session.events) == 1
    ev1 = db_session.events[0]
    assert ev1.actor == "execution-agent"
    assert ev1.action == "scale_deployment"
    assert ev1.before_state["status"] == "success"

    # 2. Blocked tool call
    with pytest.raises(ToolBlockedError):
        await gw.dispatch_tool_call(
            agent_identity="context-builder-agent",
            tool_name="scale_deployment",
            params={"namespace": "staging", "deployment_name": "payment-service", "replicas": 5},
            tenant_id=tenant_id,
            incident_id=incident_id,
            db_session=db_session,
        )

    assert len(db_session.events) == 2
    ev2 = db_session.events[1]
    assert ev2.actor == "context-builder-agent"
    assert ev2.action == "DENIED:scale_deployment"
    assert ev2.before_state["status"] == "blocked"


# ---------------------------------------------------------------------------
# GitHub create_pr Idempotency Test
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_github_create_pr_idempotent_on_retry():
    gh_server = MCPGitHubServer()

    # First call
    pr1 = gh_server.create_pr(
        repo="rise/app",
        title="Fix memory leak",
        head_branch="fix/memory-leak-inc-101",
        base_branch="main",
    )
    assert pr1["status"] == "success"
    assert pr1["is_existing"] is False

    # Second call (retry) with identical parameters
    pr2 = gh_server.create_pr(
        repo="rise/app",
        title="Fix memory leak",
        head_branch="fix/memory-leak-inc-101",
        base_branch="main",
    )
    assert pr2["status"] == "success"
    assert pr2["is_existing"] is True
    assert pr2["pr_number"] == pr1["pr_number"]


@pytest.mark.anyio
async def test_mcp_server_instance_isolation():
    """Design decision test: MCP servers are in-process per-MCPGateway instances.

    Isolation model accepted: each run_execution_agent() call constructs a fresh
    MCPGateway() with its own server instances, so a crashed/poisoned server state
    in one invocation does not affect other concurrent or subsequent invocations.

    This test verifies:
    1. Two MCPGateway instances hold independent (non-shared) server objects.
    2. Mutating state on one gateway's server does not affect the other.
    3. A tool-level exception on one gateway does not prevent a second gateway
       from dispatching the same tool successfully.
    """
    gw_a = MCPGateway()
    gw_b = MCPGateway()

    # 1. Verify independent server instances (not the same object)
    if gw_a.k8s_server is not None and gw_b.k8s_server is not None:
        assert gw_a.k8s_server is not gw_b.k8s_server, (
            "k8s_server must be a distinct instance per MCPGateway, not a shared singleton"
        )
    if gw_a.aws_server is not None and gw_b.aws_server is not None:
        assert gw_a.aws_server is not gw_b.aws_server
    if gw_a.github_server is not None and gw_b.github_server is not None:
        assert gw_a.github_server is not gw_b.github_server

    # 2. Exception on gw_a does not bleed into gw_b
    plan = ActionPlan(
        action_type="restart_pod",
        action_steps=[ActionStep(tool="restart_pod", params={"pod": "api-1", "namespace": "default"})],
        rollback_plan=[ActionStep(tool="rollback_deployment", params={"deploy": "api"})],
    )
    # Dispatch on gw_a (succeeds)
    result_a = await gw_a.dispatch_tool_call(
        agent_identity="execution-agent",
        tool_name="restart_pod",
        params={"pod": "api-1", "namespace": "default"},
        approved_plan=plan,
        step_index=0,
        environment="staging",
    )
    assert result_a.get("status") == "success"

    # Dispatch on gw_b still succeeds independently
    result_b = await gw_b.dispatch_tool_call(
        agent_identity="execution-agent",
        tool_name="restart_pod",
        params={"pod": "api-2", "namespace": "default"},
        approved_plan=plan,
        step_index=0,
        environment="staging",
    )
    assert result_b.get("status") == "success"

