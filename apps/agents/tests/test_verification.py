"""Tests for Verification Agent (prompts.md §7).

Enforces:
1. Valid health metrics -> status="passed", recommendation="close".
2. Health check endpoint error / metric threshold breach -> status="failed", recommendation="rollback".
3. Genuinely ambiguous data -> status="inconclusive", never false "passed".
"""

import pytest
from apps.agents.src.nodes.verification import (
    evaluate_rule_based_verification,
    run_verification_agent,
)


@pytest.mark.asyncio
async def test_verification_agent_passes_on_healthy_metrics():
    """Test verification passes when metrics are healthy and execution succeeded."""
    state = {
        "execution_log": {"status": "success", "steps_completed": 1, "steps_total": 1},
        "post_action_metrics": {"health_status": "200 OK", "error_rate": 0.05},
        "baseline_metrics": {"error_rate": 0.05},
    }

    res_state = await run_verification_agent(state)
    ver = res_state.get("verification_result") or {}

    assert ver.get("status") == "passed"
    assert ver.get("recommendation") == "close"
    assert any(c["name"] == "health_check_endpoint" and c["result"] == "pass" for c in ver.get("checks", []))


@pytest.mark.asyncio
async def test_verification_agent_fails_on_health_check_error():
    """Test verification fails and recommends rollback when health check returns error."""
    state = {
        "execution_log": {"status": "success", "steps_completed": 1, "steps_total": 1},
        "post_action_metrics": {"health_status": "error", "error_rate": 45.2},
        "baseline_metrics": {"error_rate": 0.05},
    }

    res_state = await run_verification_agent(state)
    ver = res_state.get("verification_result") or {}

    assert ver.get("status") == "failed"
    assert ver.get("recommendation") == "rollback"
    assert any(c["name"] == "health_check_endpoint" and c["result"] == "fail" for c in ver.get("checks", []))


@pytest.mark.asyncio
async def test_verification_agent_inconclusive_on_ambiguous_data():
    """Test verification returns inconclusive on ambiguous or incomplete metrics — never false passed."""
    state_ambiguous = {
        "execution_log": {"status": "success", "steps_completed": 1, "steps_total": 1},
        "post_action_metrics": {"ambiguous": True},
    }

    res_ambiguous = await run_verification_agent(state_ambiguous)
    ver_ambiguous = res_ambiguous.get("verification_result") or {}

    assert ver_ambiguous.get("status") == "inconclusive"
    assert ver_ambiguous.get("recommendation") == "rollback"
    assert ver_ambiguous.get("status") != "passed"

    state_empty = {
        "execution_log": {"status": "success", "steps_completed": 1, "steps_total": 1},
        "post_action_metrics": {},
    }

    res_empty = await run_verification_agent(state_empty)
    ver_empty = res_empty.get("verification_result") or {}

    assert ver_empty.get("status") == "inconclusive"
    assert ver_empty.get("status") != "passed"


@pytest.mark.asyncio
async def test_verification_agent_fails_on_execution_failure():
    """Test verification fails if execution log reports partial or failed execution."""
    state = {
        "execution_log": {"status": "failed", "steps_completed": 0, "steps_total": 1, "error": "Tool timeout"},
        "post_action_metrics": {"health_status": "200 OK"},
    }

    res_state = await run_verification_agent(state)
    ver = res_state.get("verification_result") or {}

    assert ver.get("status") == "failed"
    assert ver.get("recommendation") == "rollback"
