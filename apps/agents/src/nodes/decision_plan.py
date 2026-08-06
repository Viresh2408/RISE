"""Decision & Plan Agent node for RISE.

Combines Similarity Engine, Confidence Engine, Risk Engine (backed by OPA),
Action Planner, and Decision Engine into the Decision & Plan graph node.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx
from apps.agents.src.engines.decision_engine import DecisionEngine
from llm_gateway.gateway import LLMGateway
from schemas.agent_state import Decision

logger = logging.getLogger(__name__)


async def run_decision_plan_agent(
    state: Dict[str, Any],
    *,
    gateway: Optional[LLMGateway] = None,
    opa_client: Optional[httpx.AsyncClient] = None,
    db: Any = None,
    use_local_risk_fallback: bool = False,
    decision_engine: Optional[DecisionEngine] = None,
) -> Dict[str, Any]:
    """Execute the Decision & Plan Agent node logic."""
    engine = decision_engine or DecisionEngine()

    decision: Decision = await engine.evaluate_and_plan(
        state=state,
        gateway=gateway,
        opa_client=opa_client,
        db=db,
        use_local_risk_fallback=use_local_risk_fallback,
    )

    new_state = dict(state)
    decision_dict = decision.model_dump()

    new_state["decision"] = decision_dict
    new_state["requires_approval"] = decision.requires_approval
    new_state["risk_tier"] = decision.risk_tier
    new_state["action_plan"] = decision_dict["action_plan"]

    return new_state
