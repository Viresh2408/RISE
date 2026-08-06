"""Confidence Engine for RISE Decision & Plan Agent.

Evaluates RootCause confidence against global default and per-risk-tier policy thresholds.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RiskPolicy(BaseModel):
    """Configuration policy for confidence thresholds per risk tier.

    Justification for 0.70 default threshold:
    Per agents-and-orchestration.md §7: "Any Root Cause confidence < 0.7 (configurable) -> mandatory
    approval even if action itself is low-risk." This ensures actions are only automated when evidence
    for the underlying root cause is clear and calibrated.
    """

    global_min_confidence: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Global minimum confidence floor (default 0.70).",
    )
    tier_min_confidence: Dict[str, float] = Field(
        default_factory=lambda: {
            "low": 0.70,
            "medium": 0.80,
            "high": 0.90,
            "critical": 1.00,
        },
        description="Minimum confidence required for auto-approval per risk tier.",
    )


class ConfidenceEvaluation(BaseModel):
    """Result of confidence threshold evaluation."""

    is_sufficient: bool = Field(
        description="True if actual confidence meets or exceeds required threshold.",
    )
    actual_confidence: float = Field(ge=0.0, le=1.0)
    required_confidence: float = Field(ge=0.0, le=1.0)
    risk_tier: str
    reason: str


class ConfidenceEngine:
    """Thresholds RCA confidence against policy minimums."""

    def __init__(self, policy: Optional[RiskPolicy] = None) -> None:
        self.policy = policy or RiskPolicy()

    def evaluate(
        self,
        confidence: float,
        risk_tier: str = "low",
        policy: Optional[RiskPolicy] = None,
    ) -> ConfidenceEvaluation:
        """Evaluate whether confidence meets required threshold for the given risk tier."""
        pol = policy or self.policy
        risk_tier_lower = (risk_tier or "low").lower()

        required = pol.tier_min_confidence.get(
            risk_tier_lower, pol.global_min_confidence
        )

        # Enforce global minimum floor regardless of per-tier override
        required = max(required, pol.global_min_confidence)

        is_sufficient = confidence >= required

        if is_sufficient:
            reason = (
                f"Confidence ({confidence:.2f}) meets required threshold "
                f"({required:.2f}) for risk tier '{risk_tier}'."
            )
        else:
            reason = (
                f"Confidence ({confidence:.2f}) is below required threshold "
                f"({required:.2f}) for risk tier '{risk_tier}'."
            )

        return ConfidenceEvaluation(
            is_sufficient=is_sufficient,
            actual_confidence=confidence,
            required_confidence=required,
            risk_tier=risk_tier,
            reason=reason,
        )
