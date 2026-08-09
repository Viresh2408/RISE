"""Execution Agent node for RISE.

Carries out approved ActionPlans via allow-listed MCP tools.
Enforces:
  1. Strict plan hash verification (ACTION_PLAN_CHANGED 409).
  2. Per-resource Redis locking (RESOURCE_LOCKED 409).
  3. Sequential step execution through MCP Client Gateway allow-list middleware.
  4. Immediate abort on partial tool failure (deferring rollback to Verification/Rollback node).
"""

from __future__ import annotations

import logging, uuid
from typing import Any, Dict, Optional

from mcp_client.gateway import MCPGateway, ToolBlockedError, MCPToolTimeoutError
from mcp_client.hash import compute_action_plan_hash
from mcp_client.lock import ResourceLockManager, ResourceLockedException
from schemas.agent_state import ActionPlan, ActionStep, ExecutionLog

logger = logging.getLogger(__name__)


class ActionPlanChangedError(ValueError):
    """Raised when an action plan hash does not match the approved hash."""

    def __init__(self, message: str = "Action plan hash changed since approval"):
        self.code = "ACTION_PLAN_CHANGED"
        self.status_code = 409
        super().__init__(message)


async def run_execution_agent(
    state: Dict[str, Any],
    *,
    gateway: Optional[MCPGateway] = None,
    redis_client: Optional[Any] = None,
    db_session: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute the Execution Agent node logic."""
    new_state = dict(state)

    raw_plan = state.get("action_plan") or (state.get("decision") or {}).get("action_plan")
    if not raw_plan:
        err_msg = "No action_plan present in state for Execution Agent"
        logger.error(err_msg)
        execution_log = ExecutionLog(
            status="failed",
            steps_completed=0,
            steps_total=0,
            error=err_msg,
        ).model_dump()
        new_state["execution_log"] = execution_log
        return new_state

    # Parse ActionPlan model if needed
    if isinstance(raw_plan, dict):
        action_plan = ActionPlan(**raw_plan)
    elif isinstance(raw_plan, ActionPlan):
        action_plan = raw_plan
    else:
        err_msg = f"Invalid action_plan type: {type(raw_plan)}"
        execution_log = ExecutionLog(
            status="failed",
            steps_completed=0,
            steps_total=0,
            error=err_msg,
        ).model_dump()
        new_state["execution_log"] = execution_log
        return new_state

    # 1. Plan Hash Verification
    approved_hash = state.get("approved_plan_hash")
    current_hash = compute_action_plan_hash(action_plan)

    if approved_hash and approved_hash != current_hash:
        logger.error("Plan hash mismatch: approved=%s, current=%s", approved_hash, current_hash)
        err = ActionPlanChangedError(
            f"Action plan hash changed since approval (approved: {approved_hash[:8]}, current: {current_hash[:8]})"
        )
        execution_log = ExecutionLog(
            status="failed",
            steps_completed=0,
            steps_total=len(action_plan.action_steps),
            error=str(err),
        ).model_dump()
        new_state["execution_log"] = execution_log
        new_state["error"] = str(err)
        new_state["error_code"] = "ACTION_PLAN_CHANGED"
        return new_state

    # 2. Per-Resource Redis Locking
    resource_id = state.get("resource_id") or state.get("affected_service") or "default-resource"
    lock_token: Optional[str] = None

    try:
        lock_token = ResourceLockManager.acquire_lock(
            resource_id=resource_id,
            redis_client=redis_client,
            owner_id=state.get("incident_id"),
        )
    except ResourceLockedException as rle:
        logger.error("Resource lock failed for '%s': %s", resource_id, rle)
        execution_log = ExecutionLog(
            status="failed",
            steps_completed=0,
            steps_total=len(action_plan.action_steps),
            error=str(rle),
        ).model_dump()
        new_state["execution_log"] = execution_log
        new_state["error"] = str(rle)
        new_state["error_code"] = "RESOURCE_LOCKED"
        return new_state

    # 3. Execute plan steps sequentially via MCP Gateway
    gw = gateway or MCPGateway()
    tenant_id = state.get("tenant_id", "00000000-0000-0000-0000-000000000001")
    incident_id = state.get("incident_id")
    environment = state.get("environment", "staging")

    steps_completed = 0
    steps_total = len(action_plan.action_steps)
    step_results = []
    last_error: Optional[str] = None

    try:
        for idx, step in enumerate(action_plan.action_steps):
            logger.info("Execution Agent running step %d/%d: %s", idx + 1, steps_total, step.tool)
            try:
                res = await gw.dispatch_tool_call(
                    agent_identity="execution-agent",
                    tool_name=step.tool,
                    params=step.params,
                    approved_plan=action_plan,
                    step_index=idx,
                    environment=environment,
                    tenant_id=tenant_id,
                    incident_id=incident_id,
                    db_session=db_session,
                )
                steps_completed += 1
                step_results.append(res)
            except Exception as step_exc:
                logger.error("Tool execution failed at step %d (%s): %s", idx + 1, step.tool, step_exc)
                last_error = str(step_exc)
                # ABORT IMMEDIATELY - do NOT run remaining steps
                break

        # Construct final ExecutionLog outcome
        if steps_completed == steps_total and steps_total > 0:
            status = "success"
            result_str = f"Successfully executed all {steps_total} steps in action plan."
            # Check if any PR was created
            for r in step_results:
                if isinstance(r, dict) and "pr_url" in r:
                    result_str += f" Created PR: {r['pr_url']}"
            execution_log = ExecutionLog(
                status="success",
                steps_completed=steps_completed,
                steps_total=steps_total,
                result=result_str,
            )
        elif steps_completed > 0:
            status = "partial"
            execution_log = ExecutionLog(
                status="partial",
                steps_completed=steps_completed,
                steps_total=steps_total,
                error=last_error or "Partial execution aborted on tool failure",
            )
        else:
            status = "failed"
            execution_log = ExecutionLog(
                status="failed",
                steps_completed=0,
                steps_total=steps_total,
                error=last_error or "First step failed execution",
            )

        new_state["execution_log"] = execution_log.model_dump()
        return new_state

    finally:
        # Release resource lock when execution completes
        if lock_token:
            try:
                ResourceLockManager.release_lock(
                    resource_id=resource_id,
                    lock_token=lock_token,
                    redis_client=redis_client,
                )
            except Exception as release_exc:
                logger.warning("Failed to release lock for '%s': %s", resource_id, release_exc)
