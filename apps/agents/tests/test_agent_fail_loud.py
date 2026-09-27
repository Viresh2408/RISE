"""A0 regression: agents fail loud on LLM failure only when the caller opts in.

Proves the surgical fail-loud contract added for the RCA benchmark (Phase 5):
  - Default (`raise_on_llm_failure=False`) preserves production graceful
    degradation — an LLM/infra failure yields the canned low-confidence
    fallback so the live orchestrator keeps running.
  - Eval/benchmark callers pass `raise_on_llm_failure=True`, and an LLM/infra
    failure then raises `AgentLLMError` instead of being masked as a diagnostic
    answer (which the RCA judge would otherwise mis-score as a diagnostic FAIL).
"""

from __future__ import annotations

import asyncio

import pytest

from apps.agents.src.nodes.errors import AgentLLMError
from apps.agents.src.nodes.investigation import run_investigation_agent
from apps.agents.src.nodes.root_cause import run_root_cause_agent


class _RaisingGateway:
    """Gateway whose structured call always fails (simulates provider outage)."""

    async def call_structured(self, prompt: str, schema: type, db=None):
        raise RuntimeError("all providers failed: simulated outage")


def _root_cause_state():
    return {
        "tenant_id": "tenant-1",
        "context": {"timeline": []},
        "hypotheses": [
            {
                "rank": 1,
                "hypothesis": "Possible network glitch.",
                "plausibility_score": 0.4,
                "evidence_refs": ["unknown:source"],
                "source": "inferred",
            }
        ],
    }


def _investigation_state():
    return {
        "tenant_id": "tenant-1",
        "context": {"timeline": []},
        "event_payload": {"resource_id": "payment-service", "summary": "Payment failure"},
    }


def _null_fetcher(query, tenant_id, service_id=None):
    return "No runbook available.", False


def test_root_cause_default_returns_fallback_on_failure() -> None:
    """Production default: LLM failure degrades gracefully to a fallback RootCause."""
    res = asyncio.run(run_root_cause_agent(_root_cause_state(), gateway=_RaisingGateway()))
    rc = res["root_cause"]
    assert rc["cause_summary"] == "Fallback root cause: LLM Gateway call failed"
    assert rc["insufficient_evidence"] is True


def test_root_cause_fail_loud_raises_agent_llm_error() -> None:
    """Eval mode: LLM failure raises AgentLLMError, never a masked fallback answer."""
    with pytest.raises(AgentLLMError, match="Root Cause Agent LLM call failed"):
        asyncio.run(
            run_root_cause_agent(
                _root_cause_state(),
                gateway=_RaisingGateway(),
                raise_on_llm_failure=True,
            )
        )


def test_investigation_default_returns_fallback_on_failure() -> None:
    """Production default: LLM failure degrades gracefully to a single inferred hypothesis."""
    res = asyncio.run(
        run_investigation_agent(
            _investigation_state(),
            gateway=_RaisingGateway(),
            runbook_fetcher=_null_fetcher,
        )
    )
    assert len(res["hypotheses"]) == 1
    assert res["hypotheses"][0]["source"] == "inferred"


def test_investigation_fail_loud_raises_agent_llm_error() -> None:
    """Eval mode: LLM failure raises AgentLLMError, never a fabricated hypothesis."""
    with pytest.raises(AgentLLMError, match="Investigation Agent LLM call failed"):
        asyncio.run(
            run_investigation_agent(
                _investigation_state(),
                gateway=_RaisingGateway(),
                runbook_fetcher=_null_fetcher,
                raise_on_llm_failure=True,
            )
        )
