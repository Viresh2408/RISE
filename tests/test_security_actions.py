"""Tests for Simulated Security Response Actions across Action Planner, Risk Engine, MCP Gateway, and Execution pipeline."""

import pytest
import uuid
from unittest.mock import MagicMock

from apps.agents.src.engines.action_planner import ActionPlanner
from apps.agents.src.engines.risk_engine import RiskEngine
from apps.agents.src.nodes.execution import run_execution_agent
from mcp_client.gateway import MCPGateway
from mcp_client.hash import compute_action_plan_hash
from schemas.agent_state import ActionPlan, ActionStep


SIMULATED_SECURITY_ACTIONS = [
    "block_ip_address",
    "isolate_host",
    "revoke_session_token",
    "quarantine_file",
    "flag_for_soc_review",
]


def test_action_planner_default_tools_contains_security_actions():
    """Verify ActionPlanner includes all simulated security response and rollback actions."""
    planner = ActionPlanner()
    for action in SIMULATED_SECURITY_ACTIONS:
        assert action in planner.default_tools, f"Expected {action} in ActionPlanner.default_tools"

    # Verify rollback tools are also registered
    for rollback_tool in ("unblock_ip_address", "reconnect_host", "restore_file", "restore_session_token"):
        assert rollback_tool in planner.default_tools, f"Expected {rollback_tool} in ActionPlanner.default_tools"


def test_action_planner_builds_prompt_with_security_tools():
    """Verify ActionPlanner injects security actions into system prompt tools list."""
    planner = ActionPlanner()
    prompt = planner.build_prompts(
        root_cause={"cause": "SSH brute force detected", "confidence": 0.95},
        impact_assessment={"severity": "SEV1", "blast_radius_services": ["auth-service"]},
        similar_resolutions=[],
    )
    for action in SIMULATED_SECURITY_ACTIONS:
        assert action in prompt, f"Expected {action} in built prompt"


def test_risk_engine_evaluates_security_actions_risk_tiers():
    """Verify RiskEngine evaluates risk tiers for security response actions."""
    risk_engine = RiskEngine()

    # isolate_host in production with blast radius 1 -> high
    res_isolate = risk_engine.evaluate_risk_local_fallback(
        action_type="isolate_host",
        environment="production",
        blast_radius_count=1,
    )
    assert res_isolate.risk_tier == "high"
    assert res_isolate.requires_approval is True

    # block_ip_address in production -> high
    res_block = risk_engine.evaluate_risk_local_fallback(
        action_type="block_ip_address",
        environment="production",
        blast_radius_count=1,
    )
    assert res_block.risk_tier == "high"

    # quarantine_file in production with low blast radius -> medium
    res_quarantine_prod = risk_engine.evaluate_risk_local_fallback(
        action_type="quarantine_file",
        environment="production",
        blast_radius_count=1,
    )
    assert res_quarantine_prod.risk_tier == "medium"

    # isolate_host in staging with low blast radius -> medium
    res_isolate_staging = risk_engine.evaluate_risk_local_fallback(
        action_type="isolate_host",
        environment="staging",
        blast_radius_count=1,
    )
    assert res_isolate_staging.risk_tier == "medium"

    # flag_for_soc_review in staging with confidence >= 0.7 -> low risk auto-approvable in staging
    res_soc = risk_engine.evaluate_risk_local_fallback(
        action_type="flag_for_soc_review",
        environment="staging",
        blast_radius_count=1,
        confidence=0.9,
    )
    assert res_soc.risk_tier == "low"
    assert res_soc.requires_approval is False


@pytest.mark.anyio
async def test_mcp_gateway_dispatches_simulated_security_actions():
    """Verify MCPGateway allow-lists and executes simulated security actions with no-op status."""
    gw = MCPGateway()
    mock_db = MagicMock()

    for action_name in SIMULATED_SECURITY_ACTIONS:
        params = {"target": "10.0.0.42", "reason": "DDoS mitigation test"}
        plan = ActionPlan(
            action_type=action_name,
            action_steps=[ActionStep(tool=action_name, params=params)],
            rollback_plan=[ActionStep(tool="flag_for_soc_review", params={"status": "rollback"})],
            plan_rationale=f"Simulated test for {action_name}",
            is_simulated=True,
        )

        res = await gw.dispatch_tool_call(
            agent_identity="execution-agent",
            tool_name=action_name,
            params=params,
            approved_plan=plan,
            step_index=0,
            environment="production",
            tenant_id="00000000-0000-0000-0000-000000000001",
            incident_id="inc-test-sec-01",
            db_session=mock_db,
        )

        assert res["status"] == "success"
        assert res["simulated"] is True
        assert res["tool"] == action_name


@pytest.mark.anyio
async def test_execution_agent_simulated_security_action_pipeline():
    """Verify Execution Agent node completes full pipeline for a simulated security action plan."""
    gw = MCPGateway()
    plan = ActionPlan(
        action_type="block_ip_address",
        action_steps=[ActionStep(tool="block_ip_address", params={"ip_address": "203.0.113.195", "reason": "credential stuffing"})],
        rollback_plan=[ActionStep(tool="unblock_ip_address", params={"ip_address": "203.0.113.195"})],
        plan_rationale="Simulated IP block for credential stuffing attempt",
        is_simulated=True,
    )
    plan_hash = compute_action_plan_hash(plan)

    state = {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "incident_id": "inc-sec-ip-block-01",
        "action_plan": plan,
        "approved_plan_hash": plan_hash,
        "environment": "production",
        "human_approval": "approved",
    }

    result_state = await run_execution_agent(state, gateway=gw)
    exec_log = result_state.get("execution_log")
    assert exec_log is not None
    assert exec_log["status"] == "success"
    assert exec_log["steps_completed"] == 1
    assert exec_log["steps_total"] == 1


def test_api_approve_simulated_security_action():
    """Verify POST /actions/{action_id}/approve executes simulated security action and returns is_simulated=True."""
    import os
    import time
    import jwt
    from fastapi.testclient import TestClient
    from apps.api.src.main import app

    test_secret = os.environ.get("SUPABASE_JWT_SECRET", "test-supabase-secret-rise-unit-tests")
    token = jwt.encode(
        {
            "sub": "test-approver",
            "roles": ["approver"],
            "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "exp": int(time.time()) + 3600,
        },
        test_secret,
        algorithm="HS256",
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/incidents/inc-sec-demo-01/actions/block_ip_address/approve",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())},
        json={"note": "Approved simulated IP block for threat mitigation demo"},
    )
    assert response.status_code == 200
    data = response.json().get("data", {})
    assert data.get("status") == "approved"
    assert data.get("execution_status") == "executed"
    assert data.get("is_simulated") is True
    assert data.get("action_type") == "block_ip_address"

