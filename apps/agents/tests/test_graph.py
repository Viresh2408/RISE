"""Tests for LangGraph State Machine Orchestrator."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver

from apps.agents.src.orchestrator.graph import (
    AgentState,
    create_orchestrator_graph,
    run_incident,
    run_node_with_retry_and_timeout,
)


def test_noop_end_to_end_completes():
    """Test graph completes auto-approved path from START to END."""
    app = create_orchestrator_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": thread_id,
        "decision": {"requires_approval": False, "risk_tier": "low"},
        "action_plan": {
            "action_type": "restart_pod",
            "action_steps": [{"tool": "restart_pod", "params": {"pod": "auth-1"}}],
            "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
        },
        "post_action_metrics": {"health_status": "200 OK", "error_rate": 0.0},
    }

    final_state = app.invoke(initial_state, config=config)

    assert final_state.get("status") == "completed"
    assert final_state.get("should_escalate") is False
    assert final_state.get("current_step") == "close"


def test_noop_needs_approval_then_approved():
    """Test approval branch when human approval is granted."""
    app = create_orchestrator_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": thread_id,
        "event_payload": {"alert": "High memory"},
        "decision": {"requires_approval": True, "status": "needs_approval"},
        "action_plan": {
            "action_type": "restart_pod",
            "action_steps": [{"tool": "restart_pod", "params": {"pod": "auth-1"}}],
            "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
        },
    }

    # Step 1: Pauses at await_human
    state_step1 = app.invoke(initial_state, config=config)
    assert state_step1.get("current_step") == "await_human"

    # Step 2: Resume with approval
    app.update_state(config, {"human_approval": "approved"})
    final_state = app.invoke(None, config=config)

    assert final_state.get("status") == "completed"
    assert final_state.get("human_approval") == "approved"
    assert final_state.get("current_step") == "close"


def test_noop_needs_approval_then_rejected():
    """Test rejection branch routes to manual_handoff -> END."""
    app = create_orchestrator_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": thread_id,
        "decision": {"requires_approval": True, "status": "needs_approval"},
        "action_plan": {
            "action_type": "restart_pod",
            "action_steps": [{"tool": "restart_pod", "params": {"pod": "auth-1"}}],
            "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
        },
    }

    # Step 1: Pauses at await_human
    state_step1 = app.invoke(initial_state, config=config)
    assert state_step1.get("current_step") == "await_human"

    # Step 2: Resume with rejection
    app.update_state(config, {"human_approval": "rejected"})
    final_state = app.invoke(None, config=config)

    assert final_state.get("status") == "manual_handoff"
    assert final_state.get("current_step") == "manual_handoff"


def test_noop_verify_fail_triggers_rollback():
    """Test verification failure routes to rollback -> await_human."""
    app = create_orchestrator_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": thread_id,
        "decision": {"requires_approval": False, "risk_tier": "low"},
        "action_plan": {
            "action_type": "restart_pod",
            "action_steps": [{"tool": "restart_pod", "params": {"pod": "auth-1"}}],
            "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
        },
        "post_action_metrics": {"health_status": "error", "error_rate": 50.0},
    }

    final_state = app.invoke(initial_state, config=config)

    assert final_state.get("await_human_reason") == "rollback_complete"
    assert final_state.get("current_step") == "await_human"


def test_node_exception_retries_once_then_escalates():
    """Test node throwing twice triggers 1 retry then escalates."""
    attempts = 0

    def faulty_node(state: AgentState) -> AgentState:
        nonlocal attempts
        attempts += 1
        raise ValueError(f"Simulated node error attempt {attempts}")

    state: AgentState = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": str(uuid.uuid4()),
        "retry_counts": {},
    }

    res = run_node_with_retry_and_timeout(faulty_node, "investigate", state)

    assert attempts == 2
    assert res.get("retry_counts", {}).get("investigate") == 2
    assert res.get("should_escalate") is True
    assert res.get("status") == "escalated"
    assert "Simulated node error attempt 2" in res.get("error", "")


def test_node_exception_retries_once_succeeds_on_retry():
    """Test node throwing once succeeds on second attempt without escalation."""
    attempts = 0

    def transient_faulty_node(state: AgentState) -> AgentState:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Temporary glitch")
        res = dict(state)
        res["recovered"] = True
        return res

    state: AgentState = {
        "tenant_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": str(uuid.uuid4()),
        "retry_counts": {},
    }

    res = run_node_with_retry_and_timeout(transient_faulty_node, "root_cause", state)

    assert attempts == 2
    assert res.get("retry_counts", {}).get("root_cause") == 1
    assert res.get("should_escalate") is not True
    assert res.get("recovered") is True


def test_full_graph_exception_escalates():
    """Test graph execution when a node raises exception escalates to END."""
    with patch("apps.agents.src.orchestrator.graph.node_investigate") as mock_node:
        mock_node.side_effect = RuntimeError("Persistent failure in investigate")

        app = create_orchestrator_graph()
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        initial_state: AgentState = {
            "tenant_id": str(uuid.uuid4()),
            "incident_id": str(uuid.uuid4()),
            "agent_run_id": thread_id,
        }

        final_state = app.invoke(initial_state, config=config)

        assert final_state.get("should_escalate") is True
        assert final_state.get("status") == "escalated"
        assert final_state.get("current_step") == "escalate"


@pytest.mark.integration
def test_postgres_checkpoint_resume():
    """Test Postgres checkpointer resumes state across restarts."""
    import os
    import socket
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool

    # Quick connectivity check to avoid 30s pool timeout if Postgres is offline
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    result = sock.connect_ex(("localhost", 5432))
    sock.close()
    if result != 0:
        pytest.skip("PostgreSQL is not reachable on localhost:5432")

    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rise_dev")

    with ConnectionPool(conninfo=db_url, max_size=5, kwargs={"autocommit": True}) as pool:
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()

        app = create_orchestrator_graph(checkpointer=checkpointer)
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        initial_state: AgentState = {
            "tenant_id": str(uuid.uuid4()),
            "incident_id": str(uuid.uuid4()),
            "agent_run_id": thread_id,
            "decision": {"requires_approval": False, "risk_tier": "low"},
            "action_plan": {
                "action_type": "restart_pod",
                "action_steps": [{"tool": "restart_pod", "params": {"pod": "auth-1"}}],
                "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
            },
            "post_action_metrics": {"health_status": "200 OK", "error_rate": 0.0},
        }

        final_state = app.invoke(initial_state, config=config)
        assert final_state.get("status") == "completed"

        checkpoint_state = app.get_state(config)
        assert checkpoint_state.values.get("status") == "completed"
