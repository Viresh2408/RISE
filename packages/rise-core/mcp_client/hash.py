"""Canonical hashing module for ActionPlans in RISE."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Union

from schemas.agent_state import ActionPlan, ActionStep


def normalize_action_plan_dict(plan: Union[ActionPlan, Dict[str, Any]]) -> Dict[str, Any]:
    """Convert an ActionPlan model or dict into a canonical dictionary representation."""
    if isinstance(plan, ActionPlan):
        raw = plan.model_dump()
    elif isinstance(plan, dict):
        raw = dict(plan)
    else:
        raise TypeError(f"Expected ActionPlan or dict, got {type(plan)}")

    def _clean_step(step: Any) -> Dict[str, Any]:
        if isinstance(step, ActionStep):
            return {"tool": step.tool, "params": step.params}
        elif isinstance(step, dict):
            return {"tool": step.get("tool", ""), "params": step.get("params", {})}
        return {"tool": str(step), "params": {}}

    action_steps = [_clean_step(s) for s in raw.get("action_steps", [])]
    rollback_steps = [_clean_step(s) for s in raw.get("rollback_plan", [])]

    return {
        "action_type": raw.get("action_type", ""),
        "action_steps": action_steps,
        "rollback_plan": rollback_steps,
        "plan_rationale": raw.get("plan_rationale", ""),
        "requires_manual_plan": bool(raw.get("requires_manual_plan", False)),
    }


def compute_action_plan_hash(plan: Union[ActionPlan, Dict[str, Any]]) -> str:
    """Compute deterministic SHA-256 hash of an ActionPlan."""
    canonical_dict = normalize_action_plan_dict(plan)
    canonical_json = json.dumps(canonical_dict, sort_keys=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
