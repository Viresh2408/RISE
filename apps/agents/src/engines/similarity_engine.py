"""Similarity Engine for RISE Decision & Plan Agent.

Matches current incident context and root cause against past incident resolutions.
Provides resolution patterns to the Action Planner and informational context to Decision Engine.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SimilarityResult(BaseModel):
    """Result of past incident similarity matching."""

    matched_incident_id: Optional[str] = Field(
        default=None,
        description="ID of top matching past incident, if any.",
    )
    similarity_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Similarity score of top match (0.0 to 1.0).",
    )
    resolution_summary: Optional[str] = Field(
        default=None,
        description="Resolution summary of matched past incident.",
    )
    has_known_pattern: bool = Field(
        default=False,
        description="True if top match similarity score is at or above the threshold.",
    )
    matched_resolutions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="All matching past resolutions above threshold.",
    )


class SimilarityEngine:
    """Matches current incident against historical incident resolutions.

    Role in Decision Pipeline:
    1. Informs ActionPlanner with proven historical resolution steps.
    2. Provides `has_known_pattern` and `similarity_score` to DecisionEngine as metadata.
    3. Note: High similarity score reinforces rationale, but NEVER overrides hardcoded safety
       guardrails (such as critical risk tier or missing rollback plan requiring human approval).
    """

    def __init__(self, default_threshold: float = 0.75) -> None:
        self.default_threshold = default_threshold

    def evaluate_similarity(
        self,
        state_or_context: Dict[str, Any],
        threshold: Optional[float] = None,
    ) -> SimilarityResult:
        """Evaluate similarity against past incidents present in incident context or state."""
        cutoff = threshold if threshold is not None else self.default_threshold

        context = state_or_context.get("incident_context") or state_or_context.get("context") or state_or_context
        if isinstance(context, dict):
            similar_incidents = context.get("similar_past_incidents") or []
        else:
            similar_incidents = []

        if not similar_incidents and isinstance(state_or_context, dict):
            similar_incidents = state_or_context.get("similar_past_incidents") or []

        if not similar_incidents:
            return SimilarityResult(has_known_pattern=False)

        normalized_items: List[Dict[str, Any]] = []
        for item in similar_incidents:
            if isinstance(item, dict):
                score = float(item.get("similarity_score", 0.0))
                inc_id = str(item.get("incident_id", ""))
                res_sum = item.get("resolution_summary") or item.get("resolution") or ""
            else:
                score = getattr(item, "similarity_score", 0.0)
                inc_id = getattr(item, "incident_id", "")
                res_sum = getattr(item, "resolution_summary", "")

            normalized_items.append({
                "incident_id": inc_id,
                "similarity_score": score,
                "resolution_summary": res_sum,
            })

        # Sort descending by similarity_score
        normalized_items.sort(key=lambda x: x["similarity_score"], reverse=True)

        matches_above_cutoff = [x for x in normalized_items if x["similarity_score"] >= cutoff]

        if matches_above_cutoff:
            top_match = matches_above_cutoff[0]
            return SimilarityResult(
                matched_incident_id=top_match["incident_id"],
                similarity_score=top_match["similarity_score"],
                resolution_summary=top_match["resolution_summary"],
                has_known_pattern=True,
                matched_resolutions=matches_above_cutoff,
            )
        elif normalized_items:
            top_match = normalized_items[0]
            return SimilarityResult(
                matched_incident_id=top_match["incident_id"],
                similarity_score=top_match["similarity_score"],
                resolution_summary=top_match["resolution_summary"],
                has_known_pattern=False,
                matched_resolutions=[],
            )

        return SimilarityResult(has_known_pattern=False)
