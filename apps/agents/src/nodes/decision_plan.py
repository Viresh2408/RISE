"""Decision & Plan Agent node for RISE.

Combines Similarity Engine, Confidence Engine, Risk Engine (backed by OPA),
Action Planner, and Decision Engine into the Decision & Plan graph node.

Grounding: fetches real file content from GitHub before calling the Action Planner.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from apps.agents.src.engines.decision_engine import DecisionEngine
from apps.agents.src.nodes.github_file_fetcher import fetch_files_for_action_plan
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
    # Injectable for testing
    file_fetcher: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute the Decision & Plan Agent node logic.

    Grounding step:
        Before evaluate_and_plan is called, fetch the real content of all files
        referenced in the root cause evidence. The result (file_contents) is
        stored in state and passed to the ActionPlanner. The ActionPlanner's
        pre-LLM gate will escalate to requires_manual_plan=True if any fetch
        returned None.
    """
    engine = decision_engine or DecisionEngine()

    # ── Grounding: fetch real file content before any planning ──────────────
    root_cause = state.get("root_cause") or {}
    _fetcher = file_fetcher or fetch_files_for_action_plan
    file_contents: Dict[str, Optional[Any]] = {}

    try:
        file_contents = _fetcher(root_cause=root_cause)
    except Exception as exc:
        logger.warning(
            "run_decision_plan_agent: file fetcher raised unexpectedly: %s — "
            "continuing without file content (pre-LLM gate will escalate if files are required)",
            exc,
        )

    required_files: List[str] = list(file_contents.keys())

    # Store in state so the evidence chain can reference what was fetched
    new_state = dict(state)
    new_state["file_contents"] = file_contents
    new_state["required_files"] = required_files

    # ── Planning ─────────────────────────────────────────────────────────────
    decision: Decision = await engine.evaluate_and_plan(
        state=new_state,
        gateway=gateway,
        opa_client=opa_client,
        db=db,
        use_local_risk_fallback=use_local_risk_fallback,
        file_contents=file_contents,
        required_files=required_files,
    )

    decision_dict = decision.model_dump()
    new_state["decision"] = decision_dict
    new_state["requires_approval"] = decision.requires_approval
    new_state["risk_tier"] = decision.risk_tier
    new_state["action_plan"] = decision_dict["action_plan"]

    return new_state
