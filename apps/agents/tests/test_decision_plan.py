"""Policy-Matrix Test Suite for RISE Decision & Plan Agent.

Tests 12 core scenarios covering 100% routing accuracy, Definition of Done criteria,
and specific edge cases including default-deny posture and malformed OPA responses.
"""

import pytest
import unittest.mock as mock
from typing import Any, Dict
import httpx

from schemas.agent_state import ActionPlan, ActionStep, Decision
from apps.agents.src.engines.similarity_engine import SimilarityEngine, SimilarityResult
from apps.agents.src.engines.confidence_engine import ConfidenceEngine, RiskPolicy
from apps.agents.src.engines.risk_engine import RiskEngine, RiskEvaluation
from apps.agents.src.engines.action_planner import ActionPlanner
from apps.agents.src.engines.decision_engine import DecisionEngine
from apps.agents.src.nodes.decision_plan import run_decision_plan_agent


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------

def make_sample_state(
    *,
    action_type: str = "restart_pod",
    environment: str = "production",
    confidence: float = 0.90,
    blast_radius_services: list = None,
    rollback_plan: list = None,
    requires_manual_plan: bool = False,
    similar_past_incidents: list = None,
    service_criticality: str = "normal",
) -> Dict[str, Any]:
    if blast_radius_services is None:
        blast_radius_services = ["api-service"]
    if rollback_plan is None:
        rollback_plan = [ActionStep(tool="restart_pod", params={"service": "api-service", "state": "previous"})]

    return {
        "tenant_id": "tenant-123",
        "incident_id": "inc-456",
        "environment": environment,
        "service_criticality": service_criticality,
        "root_cause": {
            "cause_summary": "Memory leak in pod",
            "confidence": confidence,
            "confidence_rationale": "High memory usage in Loki logs",
            "evidence": [],
        },
        "impact_assessment": {
            "blast_radius_services": blast_radius_services,
            "severity": "SEV3",
            "business_impact_notes": "Minor latency spike",
        },
        "incident_context": {
            "similar_past_incidents": similar_past_incidents or [],
        },
        "_mock_action_plan": ActionPlan(
            action_type=action_type,
            action_steps=[ActionStep(tool=action_type, params={"target": "api-service"})],
            rollback_plan=rollback_plan,
            plan_rationale="Restart target service pod to clear memory",
            requires_manual_plan=requires_manual_plan,
        ),
    }


# ---------------------------------------------------------------------------
# DoD & Policy-Matrix 12 Scenarios
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_scenario_1_auto_approve_low_risk():
    """Scenario 1: Low risk, high confidence, valid rollback in staging -> Auto-approved."""
    state = make_sample_state(
        action_type="restart_pod",
        environment="staging",
        confidence=0.90,
        blast_radius_services=["api-service"],
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    assert decision.risk_tier == "low"
    assert decision.requires_approval is False


@pytest.mark.anyio
async def test_scenario_2_auto_approve_medium_risk_staging():
    """Scenario 2: Medium risk in staging, high confidence -> Auto-approved."""
    state = make_sample_state(
        action_type="rollback_deployment",
        environment="staging",
        confidence=0.85,
        blast_radius_services=["api-service"],
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    assert decision.risk_tier == "medium"
    assert decision.requires_approval is False


@pytest.mark.anyio
async def test_scenario_3_high_risk_production_requires_approval():
    """Scenario 3: High risk (rollback_deployment) in production -> Mandatory approval."""
    state = make_sample_state(
        action_type="rollback_deployment",
        environment="production",
        confidence=0.95,
        blast_radius_services=["api-service"],
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    assert decision.risk_tier == "high"
    assert decision.requires_approval is True


@pytest.mark.anyio
async def test_scenario_4_low_confidence_requires_approval():
    """Scenario 4: Low-risk action, but confidence 0.50 (< 0.70 threshold) -> Mandatory approval."""
    state = make_sample_state(
        action_type="restart_pod",
        environment="staging",
        confidence=0.50,
        blast_radius_services=["api-service"],
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    assert decision.requires_approval is True


@pytest.mark.anyio
async def test_scenario_5_excessive_blast_radius_requires_approval():
    """Scenario 5: Low risk action, but blast radius = 4 (> 3) -> Critical risk, mandatory approval."""
    state = make_sample_state(
        action_type="restart_pod",
        environment="staging",
        confidence=0.90,
        blast_radius_services=["svc1", "svc2", "svc3", "svc4"],
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    assert decision.risk_tier == "critical"
    assert decision.requires_approval is True


@pytest.mark.anyio
async def test_scenario_6_critical_action_type_requires_approval():
    """Scenario 6: Critical action type (delete_database) -> Critical risk, mandatory approval."""
    state = make_sample_state(
        action_type="delete_database",
        environment="staging",
        confidence=0.99,
        blast_radius_services=["db-service"],
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    assert decision.risk_tier == "critical"
    assert decision.requires_approval is True


@pytest.mark.anyio
async def test_scenario_7_dod2_policy_override_critical_rejected():
    """Scenario 7 (DoD 2): Policy attempts to auto-approve critical action -> Code overrides and forces approval."""
    state = make_sample_state(
        action_type="delete_database",
        environment="staging",
        confidence=0.99,
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    # Mock RiskEngine so OPA returns risk_tier="critical" but requires_approval=False
    mock_risk_engine = mock.AsyncMock()
    mock_risk_engine.evaluate_risk.return_value = RiskEvaluation(
        risk_tier="critical",
        requires_approval=False,  # Rogue policy attempt
        reasons=["Rogue policy approved"],
        opa_reachable=True,
    )

    engine = DecisionEngine(action_planner=mock_planner, risk_engine=mock_risk_engine)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=False)

    assert decision.risk_tier == "critical"
    assert decision.requires_approval is True  # Code-level un-overridable guardrail enforced


@pytest.mark.anyio
async def test_scenario_8_dod3_missing_rollback_plan_forces_approval():
    """Scenario 8 (DoD 3): Action plan with no rollback plan -> Forced to human approval regardless of confidence."""
    # Construct ActionPlan with empty rollback_plan (and requires_manual_plan=True or bypassed model validator)
    action_plan_no_rollback = ActionPlan.model_construct(
        action_type="restart_pod",
        action_steps=[ActionStep(tool="restart_pod", params={})],
        rollback_plan=[],
        plan_rationale="Plan without rollback",
        requires_manual_plan=False,
    )

    state = make_sample_state(
        action_type="restart_pod",
        environment="staging",
        confidence=0.99,
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = action_plan_no_rollback

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    assert decision.requires_approval is True


@pytest.mark.anyio
async def test_scenario_9_dod4_opa_unreachable_fails_closed():
    """Scenario 9 (DoD 4): OPA unreachable -> Fails closed (requires_approval=True, zero auto-actions)."""
    state = make_sample_state(
        action_type="restart_pod",
        environment="staging",
        confidence=0.99,
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    # Mock AsyncClient to raise HTTP connection error
    mock_client = mock.AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, opa_client=mock_client, use_local_risk_fallback=False)

    assert decision.risk_tier == "critical"
    assert decision.requires_approval is True


@pytest.mark.anyio
async def test_scenario_10_code_fix_pr_mandatory_approval():
    """Scenario 10: Action type code_fix_pr -> Mandatory human approval."""
    state = make_sample_state(
        action_type="code_fix_pr",
        environment="staging",
        confidence=0.99,
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    assert decision.requires_approval is True


@pytest.mark.anyio
async def test_scenario_11_manual_plan_requested():
    """Scenario 11: ActionPlanner sets requires_manual_plan=True -> Mandatory human approval."""
    state = make_sample_state(
        action_type="escalate_to_human",
        environment="staging",
        confidence=0.99,
        requires_manual_plan=True,
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    assert decision.requires_approval is True


@pytest.mark.anyio
async def test_scenario_12_known_similarity_pattern_match():
    """Scenario 12: Past similarity resolution match -> Metadata passed to planner and decision."""
    similar_incidents = [
        {"incident_id": "inc-prev-101", "similarity_score": 0.92, "resolution_summary": "Restarted pod to clear memory deadlock"}
    ]
    state = make_sample_state(
        action_type="restart_pod",
        environment="staging",
        confidence=0.90,
        similar_past_incidents=similar_incidents,
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    engine = DecisionEngine(action_planner=mock_planner)
    decision = await engine.evaluate_and_plan(state, use_local_risk_fallback=True)

    # Verify similarity engine evaluated match
    sim_res = engine.similarity_engine.evaluate_similarity(state)
    assert sim_res.has_known_pattern is True
    assert sim_res.matched_incident_id == "inc-prev-101"
    assert sim_res.similarity_score == 0.92
    assert decision.requires_approval is False


# ---------------------------------------------------------------------------
# Independent Required Edge-Case Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_unrecognized_action_type_defaults_to_critical_default_deny():
    """Test: Send an unrecognized/unmapped action_type through RiskEngine.

    Verifies Rego default-deny posture: defaults to critical risk tier and requires_approval=True.
    """
    risk_engine = RiskEngine()
    eval_result = risk_engine.evaluate_risk_local_fallback(
        action_type="unknown_custom_script_123",
        environment="production",
        blast_radius_count=1,
        confidence=0.99,
    )

    assert eval_result.risk_tier == "critical"
    assert eval_result.requires_approval is True


@pytest.mark.anyio
async def test_opa_malformed_response_fails_closed():
    """Test: OPA returns 200 OK with malformed/unexpected JSON body.

    Verifies fail-closed behavior (critical risk, requires_approval=True, opa_reachable=False).
    """
    risk_engine = RiskEngine()

    mock_client = mock.AsyncMock(spec=httpx.AsyncClient)
    # Return 200 OK but with unexpected/garbage body structure (missing 'result' key)
    mock_response = mock.MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"error_or_garbage": "unexpected structure"}
    mock_client.post.return_value = mock_response

    eval_result = await risk_engine.evaluate_risk(
        action_type="restart_pod",
        environment="staging",
        opa_client=mock_client,
    )

    assert eval_result.risk_tier == "critical"
    assert eval_result.requires_approval is True
    assert eval_result.opa_reachable is False
    assert "malformed" in eval_result.reasons[0].lower()


@pytest.mark.anyio
async def test_run_decision_plan_agent_node_entrypoint():
    """Test full decision_plan agent node function returns updated state."""
    state = make_sample_state(
        action_type="restart_pod",
        environment="staging",
        confidence=0.90,
    )
    mock_planner = mock.AsyncMock()
    mock_planner.generate_plan.return_value = state["_mock_action_plan"]

    mock_engine = DecisionEngine(action_planner=mock_planner)
    updated_state = await run_decision_plan_agent(
        state,
        use_local_risk_fallback=True,
        decision_engine=mock_engine,
    )

    assert "decision" in updated_state
    assert updated_state["requires_approval"] is False
    assert updated_state["risk_tier"] == "low"
    assert updated_state["action_plan"]["action_type"] == "restart_pod"


@pytest.mark.anyio
async def test_action_planner_pre_llm_gate_blocks_when_file_missing():
    """Test: When required file fetch returns None, pre-LLM gate blocks LLM call.

    Returns requires_manual_plan=True immediately.
    """
    planner = ActionPlanner()
    mock_gateway = mock.AsyncMock()

    plan = await planner.generate_plan(
        root_cause={"cause_summary": "Bug in redis.py"},
        impact_assessment={"blast_radius_services": ["api-service"], "severity": "SEV2"},
        gateway=mock_gateway,
        required_files=["apps/api/src/deps/redis.py"],
        file_contents={"apps/api/src/deps/redis.py": None},
    )

    # LLM must NOT have been called
    mock_gateway.call_structured.assert_not_called()
    assert plan.requires_manual_plan is True
    assert plan.action_type == "escalate_to_human"
    assert "real file content unavailable" in plan.plan_rationale


@pytest.mark.anyio
async def test_action_planner_includes_real_file_content_when_present():
    """Test: When file content is present, prompt contains <real_file_content> block."""
    from apps.agents.src.nodes.github_file_fetcher import GitHubFileContent

    planner = ActionPlanner()
    mock_gateway = mock.AsyncMock()
    mock_gateway.call_structured.return_value = ActionPlan(
        action_type="code_fix_pr",
        action_steps=[ActionStep(tool="code_fix_pr", params={"file": "apps/api/src/deps/redis.py"})],
        rollback_plan=[ActionStep(tool="rollback_deployment", params={"service": "api"})],
        plan_rationale="Applied grounded patch",
        requires_manual_plan=False,
    )

    fc = GitHubFileContent(
        path="apps/api/src/deps/redis.py",
        content="line1\nline2\n",
        sha="sha1",
        commit_sha="csha1",
        line_count=2,
        ref="main",
        repo="Viresh2408/RISE",
    )

    plan = await planner.generate_plan(
        root_cause={"cause_summary": "Bug in redis.py"},
        impact_assessment={"blast_radius_services": ["api-service"], "severity": "SEV2"},
        gateway=mock_gateway,
        required_files=["apps/api/src/deps/redis.py"],
        file_contents={"apps/api/src/deps/redis.py": fc},
    )

    mock_gateway.call_structured.assert_called_once()
    called_prompt = mock_gateway.call_structured.call_args[0][0]
    assert '<real_file_content path="apps/api/src/deps/redis.py"' in called_prompt
    assert "line1\nline2" in called_prompt
    assert plan.requires_manual_plan is False

