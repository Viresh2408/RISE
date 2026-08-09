"""Decision Engine for RISE Decision & Plan Agent.

Final gate combining Similarity Engine, Confidence Engine, Risk Engine, and Action Planner
into a concrete Decision (auto-approve vs. require-approval).

SYSTEM BOUNDARY & ARCHITECTURAL NOTE:
- Rollback Plan Presence vs. Validity: Decision Engine strictly verifies rollback plan PRESENCE
  (non-empty list of steps when requires_manual_plan is False). Rollback plan VALIDITY (whether the
  remediation/rollback steps actually succeed when executed) is outside the static scope of this
  layer and is backed up post-execution by the Verification Agent's health-check checks (which trigger
  auto-rollback or human escalation on verification failure).
- Confidence Threshold Justification: Default 0.70 confidence threshold is derived from
  agents-and-orchestration.md §7 ("Any Root Cause confidence < 0.7 -> mandatory approval").
- SimilarityEngine Role: Informational and plan-assisting metadata. High similarity score reinforces
  plan construction but NEVER overrides hardcoded safety guardrails (such as critical risk or missing rollback).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from schemas.agent_state import ActionPlan, Decision
from .action_planner import ActionPlanner
from .confidence_engine import ConfidenceEngine, ConfidenceEvaluation, RiskPolicy
from .risk_engine import RiskEngine, RiskEvaluation
from .similarity_engine import SimilarityEngine, SimilarityResult

logger = logging.getLogger(__name__)


class DecisionEngine:
    """Combines analytical engines to make the final auto-approve vs. human-approval decision."""

    def __init__(
        self,
        similarity_engine: Optional[SimilarityEngine] = None,
        confidence_engine: Optional[ConfidenceEngine] = None,
        risk_engine: Optional[RiskEngine] = None,
        action_planner: Optional[ActionPlanner] = None,
    ) -> None:
        self.similarity_engine = similarity_engine or SimilarityEngine()
        self.confidence_engine = confidence_engine or ConfidenceEngine()
        self.risk_engine = risk_engine or RiskEngine()
        self.action_planner = action_planner or ActionPlanner()

    async def evaluate_and_plan(
        self,
        state: Dict[str, Any],
        *,
        gateway: Any = None,
        opa_client: Optional[httpx.AsyncClient] = None,
        db: Any = None,
        use_local_risk_fallback: bool = False,
    ) -> Decision:
        """Execute full decision pipeline across all sub-engines."""
        root_cause = state.get("root_cause") or {}
        impact_assessment = state.get("impact_assessment") or {}
        incident_context = state.get("incident_context") or state.get("context") or {}

        # 1. Similarity Engine: find relevant past incident resolutions
        sim_result: SimilarityResult = self.similarity_engine.evaluate_similarity(state)
        similar_resolutions = sim_result.matched_resolutions

        # 2. Action Planner: generate candidate action plan
        action_plan: ActionPlan = await self.action_planner.generate_plan(
            root_cause=root_cause,
            impact_assessment=impact_assessment,
            similar_resolutions=similar_resolutions,
            gateway=gateway,
            db=db,
        )

        # Extract parameters for Risk and Confidence evaluation
        confidence = float(root_cause.get("confidence", 0.0))
        action_type = action_plan.action_type
        environment = state.get("environment") or (state.get("event_payload") or {}).get("environment") or (state.get("context") or {}).get("environment") or "production"

        blast_radius_services = impact_assessment.get("blast_radius_services") or state.get("blast_radius_services") or []
        blast_radius_count = len(blast_radius_services)
        service_criticality = state.get("service_criticality", "normal")

        # 3. Risk Engine: evaluate risk tier and approval rules against OPA
        if use_local_risk_fallback:
            risk_eval: RiskEvaluation = self.risk_engine.evaluate_risk_local_fallback(
                action_type=action_type,
                environment=environment,
                blast_radius_count=blast_radius_count,
                confidence=confidence,
                service_criticality=service_criticality,
            )
        else:
            risk_eval = await self.risk_engine.evaluate_risk(
                action_type=action_type,
                environment=environment,
                blast_radius_count=blast_radius_count,
                confidence=confidence,
                service_criticality=service_criticality,
                opa_client=opa_client,
            )

        # 4. Confidence Engine: evaluate confidence against risk policy threshold
        conf_eval: ConfidenceEvaluation = self.confidence_engine.evaluate(
            confidence=confidence,
            risk_tier=risk_eval.risk_tier,
        )

        # 5. Final Decision Synthesis & Hardcoded Code-Level Guardrail Enforcement
        requires_approval = risk_eval.requires_approval

        # Guardrail 1: Critical Risk Tier ALWAYS requires approval (code-level enforcement)
        if risk_eval.risk_tier == "critical":
            requires_approval = True

        # Guardrail 2: Missing rollback plan forces requires_approval=True
        # (Rollback presence check; validity is backed up post-execution by Verification Agent)
        if not action_plan.requires_manual_plan and len(action_plan.rollback_plan) == 0:
            requires_approval = True
            logger.warning("GUARDRAIL: Action plan missing rollback_plan -> forcing requires_approval=True")

        # Guardrail 3: Manual plan requested forces requires_approval=True
        if action_plan.requires_manual_plan:
            requires_approval = True

        # Guardrail 4: Insufficient confidence forces requires_approval=True
        if not conf_eval.is_sufficient:
            requires_approval = True

        # Guardrail 5: OPA unreachable or malformed response forces requires_approval=True
        if not risk_eval.opa_reachable:
            requires_approval = True

        # Guardrail 6: Code fix PR requires mandatory human merge review
        if action_type == "code_fix_pr":
            requires_approval = True

        return Decision(
            risk_tier=risk_eval.risk_tier,
            requires_approval=requires_approval,
            action_plan=action_plan,
        )
