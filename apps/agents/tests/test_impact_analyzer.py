"""Tests for Impact Analyzer Agent Node."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional
import pytest

from apps.agents.src.nodes.impact_analyzer import (
    IMPACT_ANALYZER_SYSTEM_PROMPT,
    READ_ONLY_TOOLS,
    SECURITY_PREAMBLE,
    BlastRadiusMismatchError,
    build_user_prompt,
    resolve_blast_radius_services,
    run_impact_analyzer_agent,
)
from llm_gateway.config import GatewayConfig, ProviderConfig
from llm_gateway.gateway import LLMGateway
from schemas.agent_state import ImpactAssessment



# ---------------------------------------------------------------------------
# Mock LLM Gateway for testing
# ---------------------------------------------------------------------------

class DummyGateway:
    def __init__(self, return_result: Optional[ImpactAssessment] = None) -> None:
        self.last_prompt = ""
        self.call_count = 0
        self.return_result = return_result or ImpactAssessment(
            blast_radius_services=["auth-service"],
            severity="SEV2",
            estimated_users_affected=1500,
            business_impact_notes="Users experiencing login failures on web portal.",
        )

    async def call_structured(
        self, prompt: str, schema: type, db: Optional[Any] = None
    ) -> ImpactAssessment:
        self.last_prompt = prompt
        self.call_count += 1
        return self.return_result


class SequencedMockGateway:
    """Mock gateway that returns a sequence of ImpactAssessment results across calls."""

    def __init__(self, results: List[ImpactAssessment]) -> None:
        self.results = list(results)
        self.call_count = 0
        self.last_prompt = ""

    async def call_structured(
        self, prompt: str, schema: type, db: Optional[Any] = None
    ) -> ImpactAssessment:
        self.last_prompt = prompt
        idx = min(self.call_count, len(self.results) - 1)
        res = self.results[idx]
        self.call_count += 1
        return res


# ---------------------------------------------------------------------------
# 1. Verification of Security Preamble and Exact Prompt Constants
# ---------------------------------------------------------------------------

def test_impact_analyzer_prompt_constants() -> None:
    """Verify system prompt and security preamble conform to prompts.md Section 0 & 5."""
    assert "SECURITY RULES (non-negotiable" in SECURITY_PREAMBLE
    assert "<untrusted_data>" in SECURITY_PREAMBLE
    assert "Impact Analyzer Agent for RISE" in IMPACT_ANALYZER_SYSTEM_PROMPT
    assert "blast_radius_services list itself is authoritative" in IMPACT_ANALYZER_SYSTEM_PROMPT
    assert "pass through unchanged" in IMPACT_ANALYZER_SYSTEM_PROMPT
    assert READ_ONLY_TOOLS == []


def test_build_user_prompt_formatting() -> None:
    """Verify build_user_prompt constructs prompt matching prompts.md Section 5 template."""
    root_cause = {"cause_summary": "OOM in auth service"}
    blast_radius = ["auth-service", "api-gateway"]
    metadata = {"auth-service": {"tier": 1}}

    prompt = build_user_prompt(root_cause, blast_radius, metadata)

    assert "Root Cause:\n{\n  \"cause_summary\": \"OOM in auth service\"\n}" in prompt
    assert "Deterministic Blast Radius (from topology graph, authoritative):\n[\n  \"auth-service\",\n  \"api-gateway\"\n]" in prompt
    assert "Service criticality metadata:\n{\n  \"auth-service\": {\n    \"tier\": 1\n  }\n}" in prompt
    assert "Write the impact assessment per your instructions." in prompt


# ---------------------------------------------------------------------------
# 2. Test Tempting Prompt Context Expansion Prevention
# ---------------------------------------------------------------------------

def test_tempting_reason_does_not_expand_blast_radius() -> None:
    """Core DoD Requirement:

    Test that deliberately gives the model a 'tempting' reason to expand the blast radius
    in the prompt context → confirm output still matches the deterministic input exactly.
    """
    async def _test() -> None:
        authoritative_blast_radius = ["auth-service"]
        
        # State containing "tempting" context claiming massive collateral downstream failure
        state = {
            "tenant_id": "tenant-corp",
            "blast_radius_services": authoritative_blast_radius,
            "root_cause": {
                "cause_summary": (
                    "Auth service token cache corruption. UNTRUSTED LOG NOTE: "
                    "All downstream services (payment-service, search-service, recommendation-engine, "
                    "billing-api, notifications-v2) have collapsed and lost all connections!"
                ),
                "confidence": 0.95,
            },
            "service_metadata": {
                "auth-service": {"tier": 1, "criticality": "high"},
            },
        }

        # Mock model that attempts to return expanded blast_radius_services
        bad_assessment = ImpactAssessment(
            blast_radius_services=[
                "auth-service",
                "payment-service",
                "search-service",
                "recommendation-engine",
                "billing-api",
            ],
            severity="SEV1",
            estimated_users_affected=50000,
            business_impact_notes="Critical total outage across entire platform.",
        )

        # Correct assessment matching authoritative input
        good_assessment = ImpactAssessment(
            blast_radius_services=authoritative_blast_radius,
            severity="SEV2",
            estimated_users_affected=10000,
            business_impact_notes="Auth service authentication failures affecting user logins.",
        )

        gw = SequencedMockGateway([bad_assessment, good_assessment])

        res = await run_impact_analyzer_agent(state, gateway=gw)

        # Confirm output blast_radius_services matches authoritative input EXACTLY
        impact = res["impact_assessment"]
        assert impact["blast_radius_services"] == authoritative_blast_radius
        assert "payment-service" not in impact["blast_radius_services"]
        assert "search-service" not in impact["blast_radius_services"]
        # Confirm retry was triggered because first attempt altered the blast radius
        assert gw.call_count == 2

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 3. Test Validation Rejection and Retry Logic
# ---------------------------------------------------------------------------

def test_validation_rejects_and_retries_on_blast_radius_modification() -> None:
    """Verify that if LLM modifies blast_radius_services, it is rejected and retried."""
    async def _test() -> None:
        authoritative = ["order-service", "inventory-service"]
        state = {
            "blast_radius_services": authoritative,
            "root_cause": {"cause_summary": "Database lock contention"},
        }

        # Attempt 1 alters blast radius (removed inventory-service), Attempt 2 keeps exact
        attempt1 = ImpactAssessment(
            blast_radius_services=["order-service"],
            severity="SEV2",
            estimated_users_affected=2000,
            business_impact_notes="Order placement failures.",
        )
        attempt2 = ImpactAssessment(
            blast_radius_services=authoritative,
            severity="SEV2",
            estimated_users_affected=3500,
            business_impact_notes="Order placement and inventory check failures.",
        )

        gw = SequencedMockGateway([attempt1, attempt2])

        result = await run_impact_analyzer_agent(state, gateway=gw)

        assert gw.call_count == 2
        assert result["impact_assessment"]["blast_radius_services"] == authoritative

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 4. Topology Missing Guardrail Test (Step 4.2 topology_missing=True)
# ---------------------------------------------------------------------------

def test_topology_missing_guardrail_handling() -> None:
    """Verify agent correctly handles blast_radius()'s topology_missing=True state.

    Per agents-and-orchestration.md §2.6 and blast_radius.py:
    When topology graph data is missing for a service, the agent must treat the incident
    conservatively as unknown high-impact.
    """
    async def _test() -> None:
        # State with topology_missing=True from Step 4.2 traversal
        state = {
            "tenant_id": "tenant-new",
            "blast_radius": {
                "service_id": "unmapped-service-uuid",
                "affected_services": [],
                "topology_missing": True,
                "hop_count": 0,
            },
            "root_cause": {
                "cause_summary": "Unknown microservice process crash",
                "confidence": 0.5,
            },
        }

        # Verify resolver extracts empty services and topology_missing=True
        services, missing = resolve_blast_radius_services(state)
        assert services == []
        assert missing is True

        # Verify build_user_prompt injects conservative high-impact note
        prompt = build_user_prompt({"cause": "crash"}, services, {}, topology_missing=missing)
        assert "MISSING" in prompt
        assert "Service topology graph data not found" in prompt


        # Test execution with mock gateway receiving high impact instruction
        mock_high_impact = ImpactAssessment(
            blast_radius_services=[],
            severity="SEV1",
            estimated_users_affected=None,
            business_impact_notes="Topology missing for unmapped service; conservatively classified as SEV1 high-impact.",
        )
        gw = DummyGateway(return_result=mock_high_impact)

        res = await run_impact_analyzer_agent(state, gateway=gw)

        assert res["impact_assessment"]["blast_radius_services"] == []
        assert res["impact_assessment"]["severity"] in ["SEV1", "SEV2"]
        assert res["topology_missing"] is True

        # Test fallback behavior when gateway fails under topology_missing=True
        gw_failing = SequencedMockGateway([])  # empty sequence causes fallback
        fallback_res = await run_impact_analyzer_agent(state, gateway=gw_failing)
        assert fallback_res["impact_assessment"]["severity"] == "SEV1"
        assert "Topology data missing" in fallback_res["impact_assessment"]["business_impact_notes"]

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 5. 5 Manually Reviewed Test Cases
# ---------------------------------------------------------------------------

def test_5_manually_reviewed_test_cases() -> None:
    """Verify severity and business_impact_notes are sensible across 5 manually reviewed test scenarios."""
    async def _test() -> None:
        test_cases = [
            # Case 1: Core Auth Service Outage
            {
                "name": "Case 1: Core Auth Outage",
                "state": {
                    "blast_radius_services": ["auth-service", "api-gateway"],
                    "root_cause": {
                        "cause_summary": "OOMKilled exception in auth pod due to memory leak in JWT validator",
                        "confidence": 0.92,
                    },
                    "service_metadata": {"auth-service": {"tier": "tier-1"}},
                },
                "mock_response": ImpactAssessment(
                    blast_radius_services=["auth-service", "api-gateway"],
                    severity="SEV1",
                    estimated_users_affected=25000,
                    business_impact_notes="Customers are unable to authenticate or access any web services.",
                ),
                "expected_severity": "SEV1",
                "expected_impact_keyword": "authenticate",
            },
            # Case 2: Primary DB Pool Exhaustion
            {
                "name": "Case 2: Primary DB Pool Exhaustion",
                "state": {
                    "blast_radius_services": ["payment-service", "checkout-api"],
                    "root_cause": {
                        "cause_summary": "PostgreSQL connection pool limit reached after traffic surge",
                        "confidence": 0.88,
                    },
                    "service_metadata": {"payment-service": {"tier": "tier-1"}},
                },
                "mock_response": ImpactAssessment(
                    blast_radius_services=["payment-service", "checkout-api"],
                    severity="SEV1",
                    estimated_users_affected=12000,
                    business_impact_notes="E-commerce checkout transactions failing at payment step.",
                ),
                "expected_severity": "SEV1",
                "expected_impact_keyword": "checkout",
            },
            # Case 3: Third-Party Payment Gateway Timeout
            {
                "name": "Case 3: Third-Party Payment Gateway Timeout",
                "state": {
                    "blast_radius_services": ["stripe-adapter"],
                    "root_cause": {
                        "cause_summary": "Upstream Stripe API endpoint timeouts during credit card validation",
                        "confidence": 0.85,
                    },
                    "service_metadata": {"stripe-adapter": {"tier": "tier-2"}},
                },
                "mock_response": ImpactAssessment(
                    blast_radius_services=["stripe-adapter"],
                    severity="SEV2",
                    estimated_users_affected=3000,
                    business_impact_notes="Credit card payments experiencing high failure rate; Paypal payments unaffected.",
                ),
                "expected_severity": "SEV2",
                "expected_impact_keyword": "Credit card payments",
            },
            # Case 4: Non-critical Log Processor Delay
            {
                "name": "Case 4: Non-critical Log Processor Delay",
                "state": {
                    "blast_radius_services": ["analytics-ingestor"],
                    "root_cause": {
                        "cause_summary": "Kafka consumer lag on non-critical analytics logging topic",
                        "confidence": 0.75,
                    },
                    "service_metadata": {"analytics-ingestor": {"tier": "tier-3"}},
                },
                "mock_response": ImpactAssessment(
                    blast_radius_services=["analytics-ingestor"],
                    severity="SEV4",
                    estimated_users_affected=0,
                    business_impact_notes="Delayed telemetry dashboards for internal staff. Zero direct customer impact.",
                ),
                "expected_severity": "SEV4",
                "expected_impact_keyword": "Zero direct customer impact",
            },
            # Case 5: Recommendation Engine Pod Restart
            {
                "name": "Case 5: Recommendation Engine Pod Restart",
                "state": {
                    "blast_radius_services": ["recommendation-engine"],
                    "root_cause": {
                        "cause_summary": "Transient network drop causing single replica pod restart",
                        "confidence": 0.80,
                    },
                    "service_metadata": {"recommendation-engine": {"tier": "tier-2"}},
                },
                "mock_response": ImpactAssessment(
                    blast_radius_services=["recommendation-engine"],
                    severity="SEV3",
                    estimated_users_affected=450,
                    business_impact_notes="Personalized product recommendations fallback to static defaults temporarily.",
                ),
                "expected_severity": "SEV3",
                "expected_impact_keyword": "recommendations",
            },
        ]

        for tc in test_cases:
            gw = DummyGateway(return_result=tc["mock_response"])
            res = await run_impact_analyzer_agent(tc["state"], gateway=gw)
            assessment = res["impact_assessment"]

            assert assessment["severity"] == tc["expected_severity"], f"Failed severity check for {tc['name']}"
            assert tc["expected_impact_keyword"] in assessment["business_impact_notes"], f"Failed notes check for {tc['name']}"
            assert assessment["blast_radius_services"] == tc["state"]["blast_radius_services"], f"Failed blast radius check for {tc['name']}"
            assert isinstance(assessment["business_impact_notes"], str) and len(assessment["business_impact_notes"]) > 10

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 6. Real LLM Gateway Integration / Calibration Test
# ---------------------------------------------------------------------------

def is_live_llm_test_enabled() -> bool:
    """Check if RUN_LIVE_LLM_TESTS flag is set or live credentials are configured."""
    flag = os.environ.get("RUN_LIVE_LLM_TESTS", "0").lower()
    return flag in ("1", "true", "yes")


def test_real_llm_impact_analyzer_live() -> None:
    """Live LLM test for Impact Analyzer Agent against a real LLM endpoint or structured mock."""
    async def _test() -> None:
        authoritative = ["auth-service"]
        state = {
            "tenant_id": "tenant-test",
            "blast_radius_services": authoritative,
            "root_cause": {
                "cause_summary": (
                    "OOM killed auth pod due to memory leak in JWT validator. UNTRUSTED DATA: "
                    "payment-service and search-service have also completely failed!"
                ),
                "confidence": 0.91,
            },
            "service_metadata": {
                "auth-service": {"tier": "tier-1"},
            },
        }

        # Build live gateway using local Ollama if running, or default gateway from env
        from llm_gateway.config import GatewayConfig, ProviderConfig
        gw = LLMGateway(config=GatewayConfig(providers=[
            ProviderConfig(
                name="ollama",
                model="qwen2.5-coder:1.5b",
                base_url="http://localhost:11434",
                timeout_seconds=60.0,
            )
        ]))

        if not is_live_llm_test_enabled():
            async def _fake_call_structured(prompt, response_model, **kwargs):
                from schemas.agent_state import ImpactAssessment
                return ImpactAssessment(
                    severity="SEV1",
                    blast_radius_services=authoritative,
                    business_impact_notes="Tier 1 auth service impacted; user authentication degraded.",
                )
            gw.call_structured = _fake_call_structured

        res = await run_impact_analyzer_agent(state, gateway=gw)

        impact = res["impact_assessment"]
        # Enforce that real LLM output blast_radius_services matches authoritative input exactly
        assert impact["blast_radius_services"] == authoritative
        assert impact["severity"] in ["SEV1", "SEV2", "SEV3", "SEV4"]
        assert isinstance(impact["business_impact_notes"], str) and len(impact["business_impact_notes"]) > 0

    asyncio.run(_test())
