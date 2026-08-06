"""Tests for Investigation Agent Node."""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
from unittest.mock import MagicMock, patch
import pytest

from pydantic import ValidationError

from apps.agents.src.nodes.investigation import (
    READ_ONLY_TOOLS,
    build_user_prompt,
    run_investigation_agent,
    NoPlausibleHypothesisError,
)
from schemas.agent_state import Hypothesis, InvestigationResult


# ---------------------------------------------------------------------------
# Mock LLM Gateway for testing
# ---------------------------------------------------------------------------

class DummyGateway:
    def __init__(self, return_result: InvestigationResult | None = None) -> None:
        self.last_prompt = ""
        self.return_result = return_result or InvestigationResult(
            hypotheses=[
                Hypothesis(
                    rank=1,
                    hypothesis="Runbook steps for memory leak.",
                    plausibility_score=0.85,
                    evidence_refs=["loki:error"],
                    source="runbook",
                )
            ]
        )

    async def call_structured(self, prompt: str, schema: type, db: None = None) -> InvestigationResult:
        self.last_prompt = prompt
        return self.return_result


# ---------------------------------------------------------------------------
# 1. Empty & Mixed Validity evidence_refs Tests
# ---------------------------------------------------------------------------

def test_hypothesis_empty_evidence_refs_rejected() -> None:
    """Core guardrail: hypotheses with zero evidence_refs must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Hypothesis(
            rank=1,
            hypothesis="Memory leak.",
            plausibility_score=0.9,
            evidence_refs=[],
            source="inferred",
        )
    assert "evidence_refs" in str(exc_info.value)


def test_hypothesis_mixed_validity_evidence_refs_rejected() -> None:
    """Core guardrail: hypotheses containing empty or whitespace-only evidence refs must be rejected."""
    # List containing empty string
    with pytest.raises(ValidationError) as exc_info:
        Hypothesis(
            rank=1,
            hypothesis="Memory leak.",
            plausibility_score=0.9,
            evidence_refs=["ref1", ""],
            source="inferred",
        )
    assert "evidence_refs" in str(exc_info.value)

    # List containing whitespace-only string
    with pytest.raises(ValidationError) as exc_info:
        Hypothesis(
            rank=1,
            hypothesis="Memory leak.",
            plausibility_score=0.9,
            evidence_refs=["   "],
            source="inferred",
        )
    assert "evidence_refs" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. Injection-Compliance Test for RAG Runbook Content
# ---------------------------------------------------------------------------

def test_runbook_content_injection_compliance() -> None:
    """Assert RAG runbook content is enclosed in <untrusted_data source="runbook_rag"> tags."""
    context = {"timeline": []}
    runbook_text = "Standard runbook content for CPU alert."
    prompt = build_user_prompt(context, runbook_text)

    # Verify that the untrusted data tags wrap the runbook text
    assert '<untrusted_data source="runbook_rag">\nStandard runbook content for CPU alert.\n</untrusted_data>' in prompt


# ---------------------------------------------------------------------------
# 3. LLM Gateway Mock Calling
# ---------------------------------------------------------------------------

def test_run_investigation_agent_success() -> None:
    """Test successful run of run_investigation_agent with mock LLM gateway."""
    async def _test():
        state = {
            "tenant_id": "tenant-1",
            "context": {"timeline": []},
            "event_payload": {"resource_id": "payment-service", "summary": "Payment failure"},
        }
        mock_fetcher = MagicMock(return_value=("Mock runbook content", False))
        gw = DummyGateway()

        res = await run_investigation_agent(
            state,
            gateway=gw,
            runbook_fetcher=mock_fetcher,
        )

        assert len(res["hypotheses"]) == 1
        assert res["hypotheses"][0]["rank"] == 1
        assert res["hypotheses"][0]["hypothesis"] == "Runbook steps for memory leak."
        assert '<untrusted_data source="runbook_rag">' in gw.last_prompt
        assert "SECURITY RULES (non-negotiable" in gw.last_prompt

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 4. Zero-Hypothesis-Clears-Threshold Escalation Test
# ---------------------------------------------------------------------------

def test_run_investigation_agent_threshold_escalation() -> None:
    """Test run_investigation_agent raises NoPlausibleHypothesisError when no hypothesis clears threshold."""
    async def _test():
        state = {
            "tenant_id": "tenant-1",
            "context": {"timeline": []},
            "event_payload": {"resource_id": "payment-service", "summary": "Payment failure"},
        }
        mock_fetcher = MagicMock(return_value=("Mock runbook content", False))

        # Return hypothesis with plausibility score of 0.25 (below default 0.3 threshold)
        gw = DummyGateway(
            return_result=InvestigationResult(
                hypotheses=[
                    Hypothesis(
                        rank=1,
                        hypothesis="Low plausibility cause.",
                        plausibility_score=0.25,
                        evidence_refs=["loki:error"],
                        source="inferred",
                    )
                ]
            )
        )

        with pytest.raises(NoPlausibleHypothesisError):
            await run_investigation_agent(
                state,
                gateway=gw,
                runbook_fetcher=mock_fetcher,
            )

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 5. AST Import Scan Test (Zero Write-Capable Imports)
# ---------------------------------------------------------------------------

def test_ast_scan_no_write_capable_imports() -> None:
    """Parse investigation.py with AST to assert zero write-capable imports."""
    import apps.agents.src.nodes.investigation as inv_mod

    source = inspect.getsource(inv_mod)
    tree = ast.parse(source)

    forbidden_modules = [
        "mcp_execution",
        "kubernetes",
        "boto3",
        "github_write",
        "subprocess",
    ]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for f in forbidden_modules:
                    assert f not in alias.name, f"investigation.py imports write-capable module '{alias.name}'"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for f in forbidden_modules:
                assert f not in module, f"investigation.py imports from write-capable module '{module}'"

    assert set(READ_ONLY_TOOLS) == {
        "query_knowledge_base",
    }
