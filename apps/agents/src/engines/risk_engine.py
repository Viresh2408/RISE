"""Risk Engine for RISE Decision & Plan Agent.

Evaluates risk tier and approval rules against OPA (Open Policy Agent) policies.
Implements fail-closed behavior on OPA unreachability or malformed responses,
and code-level override for critical risk tier.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RiskEvaluation(BaseModel):
    """Result of risk evaluation."""

    risk_tier: str = Field(
        default="critical",
        description="Assigned risk tier ('low', 'medium', 'high', 'critical'). Defaults to 'critical'.",
    )
    requires_approval: bool = Field(
        default=True,
        description="True if human approval is required. Defaults to True (fail-closed posture).",
    )
    reasons: List[str] = Field(
        default_factory=list,
        description="List of reasons for approval requirement or risk assignment.",
    )
    opa_reachable: bool = Field(
        default=True,
        description="True if OPA policy engine was successfully queried and returned valid response.",
    )
    raw_opa_response: Optional[Dict[str, Any]] = Field(default=None)


class RiskEngine:
    """Evaluates proposed actions against OPA policies and enforces hardcoded code-level safety guardrails."""

    def __init__(
        self,
        opa_base_url: str = "http://localhost:8181",
        timeout: float = 2.0,
    ) -> None:
        self.opa_base_url = opa_base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def is_shadow_mode_active(active_policies: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Read-only derived indicator: shadow mode is active when no policy in production permits auto-approval."""
        if not active_policies:
            return True
        return not any(
            p.get("environment") == "production" and not p.get("requires_approval", True)
            for p in active_policies
        )

    async def evaluate_risk(
        self,
        action_type: str,
        environment: str = "production",
        blast_radius_count: int = 1,
        confidence: float = 1.0,
        min_confidence: float = 0.70,
        max_blast_radius: int = 2,
        service_criticality: str = "normal",
        active_policies: Optional[List[Dict[str, Any]]] = None,
        opa_client: Optional[httpx.AsyncClient] = None,
    ) -> RiskEvaluation:
        """Evaluate risk and approval requirements via OPA policy engine or fallback.

        Enforces strict fail-closed posture:
        1. If OPA is unreachable -> fails closed (critical risk, requires approval).
        2. If OPA returns 200 with malformed JSON body -> fails closed (critical risk, requires approval).
        3. If risk_tier == 'critical' -> python code forces requires_approval=True (un-overridable by policy config).
        """
        payload = {
            "input": {
                "action_type": action_type,
                "environment": environment,
                "blast_radius_count": blast_radius_count,
                "confidence": confidence,
                "min_confidence": min_confidence,
                "max_blast_radius": max_blast_radius,
                "service_criticality": service_criticality,
                "policies": active_policies or [],
            }
        }

        # 1. Query OPA
        try:
            if opa_client is not None:
                resp = await opa_client.post(
                    f"{self.opa_base_url}/v1/data/rise/policies",
                    json=payload,
                    timeout=self.timeout,
                )
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{self.opa_base_url}/v1/data/rise/policies",
                        json=payload,
                        timeout=self.timeout,
                    )

            if resp.status_code != 200:
                logger.error("OPA returned non-200 status code: %d", resp.status_code)
                return self._fail_closed(f"OPA HTTP error: status code {resp.status_code}")

            try:
                data = resp.json()
            except Exception as parse_exc:
                logger.error("Failed to parse OPA JSON response: %s", parse_exc)
                return self._fail_closed("OPA response was not valid JSON")

            # Validate response shape: OPA Data API returns {"result": {...}}
            if not isinstance(data, dict) or "result" not in data or not isinstance(data["result"], dict):
                logger.error("OPA response malformed/unexpected shape: %s", data)
                return self._fail_closed("OPA returned malformed/unexpected-shape response body")

            result_data = data["result"]
            risk_tiers_res = result_data.get("risk_tiers", {})
            approval_rules_res = result_data.get("approval_rules", {})

            if not isinstance(risk_tiers_res, dict) or not isinstance(approval_rules_res, dict):
                logger.error("OPA result missing policy packages: %s", result_data)
                return self._fail_closed("OPA response missing policy packages")

            risk_tier = str(risk_tiers_res.get("risk_level", "critical")).lower()
            requires_approval = bool(approval_rules_res.get("requires_approval", True))
            reasons = list(approval_rules_res.get("reasons", []))

            # Code-level un-overridable guardrail: risk_tier=critical ALWAYS forces requires_approval=True
            if risk_tier == "critical":
                if not requires_approval:
                    logger.warning(
                        "SECURITY GUARDRAIL TRIGGERED: Policy attempted to auto-approve critical risk_tier. "
                        "Overriding to requires_approval=True at code level."
                    )
                requires_approval = True
                if "Risk tier is critical - mandatory human approval required" not in reasons:
                    reasons.append("Risk tier is critical - mandatory human approval required (hardcoded code guardrail)")

            return RiskEvaluation(
                risk_tier=risk_tier,
                requires_approval=requires_approval,
                reasons=reasons,
                opa_reachable=True,
                raw_opa_response=data,
            )

        except Exception as exc:
            logger.warning("OPA request failed: %s", exc)
            return self._fail_closed(f"OPA unreachable: {exc}")

    def evaluate_risk_local_fallback(
        self,
        action_type: str,
        environment: str = "production",
        blast_radius_count: int = 1,
        confidence: float = 1.0,
        min_confidence: float = 0.70,
        max_blast_radius: int = 2,
        service_criticality: str = "normal",
        active_policies: Optional[List[Dict[str, Any]]] = None,
    ) -> RiskEvaluation:
        """Local pure-Python fallback evaluation matching OPA Rego rules when OPA service is not running in local test environment."""
        critical_actions = {"delete_database", "drop_table", "force_destroy", "code_fix_pr", "destroy_cluster"}
        high_actions = {"rollback_deployment", "failover_database", "modify_traffic", "scale_deployment"}
        medium_actions = {"restart_service", "clear_cache", "flush_redis", "restart_pod", "config_update", "scale", "rollback"}
        low_actions = {"restart_pod", "clear_cache", "flush_redis", "scale_deployment", "config_update", "scale", "rollback"}

        is_critical = (
            action_type in critical_actions
            or blast_radius_count > 3
            or service_criticality in ("tier0", "mission_critical")
        )

        is_high = not is_critical and (
            (action_type in high_actions and environment == "production")
            or (blast_radius_count >= 2 and environment == "production")
        )

        is_medium = not is_critical and not is_high and (
            (action_type in medium_actions and environment == "production")
            or (action_type in high_actions and environment in ("staging", "dev"))
        )

        is_low = not is_critical and not is_high and not is_medium and (
            action_type in low_actions
            and environment in ("staging", "dev")
            and blast_radius_count <= 1
        )

        if is_critical:
            risk_tier = "critical"
        elif is_high:
            risk_tier = "high"
        elif is_medium:
            risk_tier = "medium"
        elif is_low:
            risk_tier = "low"
        else:
            # Unmapped action types default to critical (default-deny)
            risk_tier = "critical"

        # Evaluate approval rules
        reasons = []
        requires_approval = True

        has_matching_prod_auto_approval_policy = False
        if active_policies:
            for pol in active_policies:
                pol_action = pol.get("action_pattern") or pol.get("action_type")
                pol_env = pol.get("environment")
                pol_req_appr = pol.get("requires_approval", True)
                pol_max_blast = pol.get("max_blast_radius", max_blast_radius)
                if pol_action == action_type and pol_env == "production" and not pol_req_appr:
                    if blast_radius_count <= pol_max_blast:
                        has_matching_prod_auto_approval_policy = True
                        break

        if environment != "production":
            if risk_tier == "low" and confidence >= min_confidence and blast_radius_count <= max_blast_radius:
                requires_approval = False
            elif risk_tier == "medium" and confidence >= min_confidence and blast_radius_count <= max_blast_radius:
                requires_approval = False
        else:
            if has_matching_prod_auto_approval_policy and risk_tier not in ("critical", "high") and confidence >= min_confidence and blast_radius_count <= max_blast_radius:
                requires_approval = False
            else:
                requires_approval = True
                if not has_matching_prod_auto_approval_policy:
                    reasons.append("Production auto-remediation locked in shadow mode — no active policy permits auto-approval for this action type")

        if risk_tier == "critical":
            requires_approval = True
            if "Risk tier is critical - mandatory human approval required" not in reasons:
                reasons.append("Risk tier is critical - mandatory human approval required")

        if confidence < min_confidence:
            requires_approval = True
            reasons.append(f"Root cause confidence ({confidence:.2f}) below required threshold ({min_confidence:.2f})")

        if blast_radius_count > max_blast_radius:
            requires_approval = True
            reasons.append(f"Blast radius services count ({blast_radius_count}) exceeds maximum allowed ({max_blast_radius})")

        if environment == "production" and risk_tier == "high":
            requires_approval = True
            if "High-risk action in production requires human approval" not in reasons:
                reasons.append("High-risk action in production requires human approval")

        if action_type == "code_fix_pr":
            requires_approval = True
            if "Code fix PR requires mandatory human merge review" not in reasons:
                reasons.append("Code fix PR requires mandatory human merge review")

        return RiskEvaluation(
            risk_tier=risk_tier,
            requires_approval=requires_approval,
            reasons=reasons,
            opa_reachable=True,
        )

    def _fail_closed(self, reason: str) -> RiskEvaluation:
        """Construct fail-closed risk evaluation."""
        return RiskEvaluation(
            risk_tier="critical",
            requires_approval=True,
            reasons=[f"Fail-closed safety default: {reason}"],
            opa_reachable=False,
        )
