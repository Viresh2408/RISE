"""Orchestrator approval-anchor enforcement (ADR-005, Phase 1 security).

Closes the "human-approval path executed un-anchored" gap in the LangGraph
orchestrator. These tests prove:

  1. node_await_human binds the approved plan to a hash anchor and requires it,
     and an UNCHANGED plan still executes to completion (no false positive).
  2. A plan mutated AFTER approval fails closed (ACTION_PLAN_CHANGED) — no tool
     step runs.
  3. The auto-rollback sub-execution deliberately runs UN-anchored and is not
     blocked by the forward anchor the approval gate set (node_rollback clears it).
  4. The auto-execute path (requires_approval False) never hits the approval gate,
     so autonomous low-risk remediation remains un-anchored and unaffected.
"""

import asyncio
import uuid

from apps.agents.src.orchestrator.graph import (
    create_orchestrator_graph,
    node_await_human,
)
from apps.agents.src.nodes.execution import run_execution_agent


def _approval_plan():
    return {
        "action_type": "restart_pod",
        "action_steps": [{"tool": "restart_pod", "params": {"pod": "auth-1"}}],
        "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
    }


def test_approval_gate_anchors_plan_and_unchanged_plan_completes():
    """(1) The approval gate anchors the plan; an unchanged plan runs to close."""
    app = create_orchestrator_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": thread_id,
        "decision": {"requires_approval": True, "status": "needs_approval"},
        "action_plan": _approval_plan(),
        "post_action_metrics": {"health_status": "200 OK", "error_rate": 0.0},
    }

    paused = app.invoke(initial_state, config=config)
    assert paused.get("current_step") == "await_human"
    # NEW: the approval gate wrote a durable anchor into the checkpointed state.
    assert paused.get("require_approved_hash") is True
    anchor = paused.get("approved_plan_hash")
    assert isinstance(anchor, str) and len(anchor) == 64

    app.update_state(config, {"human_approval": "approved"})
    final = app.invoke(None, config=config)

    assert final.get("status") == "completed"
    assert final.get("current_step") == "close"


def test_await_human_anchor_blocks_tampered_execution():
    """(2) A plan mutated after approval fails closed; no step executes."""
    state = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "decision": {"requires_approval": True, "status": "needs_approval"},
        "action_plan": _approval_plan(),
    }

    gated = node_await_human(state)
    assert gated.get("require_approved_hash") is True
    anchor = gated.get("approved_plan_hash")
    assert anchor and len(anchor) == 64

    # Human approved the plan they saw, but the plan is mutated afterwards
    # (e.g. tampered checkpoint / re-entrant node) before execution.
    tampered = dict(gated)
    tampered["human_approval"] = "approved"
    tampered["action_plan"] = {
        "action_type": "restart_pod",
        "action_steps": [{"tool": "restart_pod", "params": {"pod": "auth-EVIL"}}],
        "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
    }

    result = asyncio.run(run_execution_agent(tampered))
    assert result["execution_log"]["status"] == "failed"
    assert result["execution_log"]["steps_completed"] == 0
    assert result.get("error_code") == "ACTION_PLAN_CHANGED"
    assert "hash changed" in result["execution_log"]["error"].lower()


def test_auto_rollback_runs_unanchored_after_approved_execution():
    """(3) Auto-rollback after an approved execution is NOT blocked by the anchor."""
    app = create_orchestrator_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": thread_id,
        "decision": {"requires_approval": True, "status": "needs_approval"},
        "action_plan": _approval_plan(),
        # Unhealthy metrics force verification failure -> auto-rollback.
        "post_action_metrics": {"health_status": "error", "error_rate": 50.0},
    }

    paused = app.invoke(initial_state, config=config)
    assert paused.get("current_step") == "await_human"
    assert paused.get("require_approved_hash") is True

    app.update_state(config, {"human_approval": "approved"})
    final = app.invoke(None, config=config)

    # Forward (anchored) execution ran, verification failed on bad metrics, and the
    # auto-rollback (un-anchored) fired without tripping the inherited anchor.
    assert final.get("rollback_count") == 1
    assert final.get("await_human_reason") == "rollback_complete"
    rb = final.get("rollback_execution_log") or {}
    assert rb.get("error_code") != "ACTION_PLAN_CHANGED"
    assert "hash changed" not in (rb.get("error") or "").lower()
    assert rb.get("status") == "success"


def test_auto_execute_path_is_not_anchored():
    """(4) The auto-execute path never hits the approval gate; stays un-anchored."""
    app = create_orchestrator_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": thread_id,
        "decision": {"requires_approval": False, "risk_tier": "low"},
        "action_plan": _approval_plan(),
        "post_action_metrics": {"health_status": "200 OK", "error_rate": 0.0},
    }

    final = app.invoke(initial_state, config=config)
    assert final.get("status") == "completed"
    # No human approval exists to anchor to on the autonomous path.
    assert not final.get("require_approved_hash")
