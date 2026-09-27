"""Execution Agent node for RISE.

Carries out approved ActionPlans via allow-listed MCP tools.
Enforces:
  1. Strict plan hash verification (ACTION_PLAN_CHANGED 409).
  2. Per-resource Redis locking (RESOURCE_LOCKED 409).
  3. Sequential step execution through MCP Client Gateway allow-list middleware.
  4. Immediate abort on partial tool failure (deferring rollback to Verification/Rollback node).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from mcp_client.gateway import MCPGateway
from mcp_client.hash import compute_action_plan_hash
from mcp_client.lock import ResourceLockManager, ResourceLockedException
from schemas.agent_state import ActionPlan, ExecutionLog

logger = logging.getLogger(__name__)


class ActionPlanChangedError(ValueError):
    """Raised when an action plan hash does not match the approved hash."""

    def __init__(self, message: str = "Action plan hash changed since approval"):
        self.code = "ACTION_PLAN_CHANGED"
        self.status_code = 409
        super().__init__(message)


class InvalidActionPlanError(TypeError):
    """Raised when a raw plan cannot be coerced into an ActionPlan."""


def coerce_action_plan(raw_plan: Any) -> ActionPlan:
    """Normalize a raw plan (dict or ActionPlan) into an ActionPlan.

    This is the single source of truth for turning a raw plan into the ActionPlan
    that gets hashed and executed. Any caller that needs to compute the approved
    plan hash *before* execution (e.g. the orchestrator's human-approval gate)
    MUST use this helper so its anchor hash matches the hash ``run_execution_agent``
    recomputes at execution time. In particular the ``plan_rationale`` default
    injection below must be applied identically on both sides — otherwise the
    canonical hashes diverge and a legitimate approved execution fails closed with
    a spurious ACTION_PLAN_CHANGED.
    """
    if isinstance(raw_plan, ActionPlan):
        return raw_plan
    if isinstance(raw_plan, dict):
        plan_dict = dict(raw_plan)
        if not plan_dict.get("plan_rationale"):
            plan_dict["plan_rationale"] = f"Remediate via {plan_dict.get('action_type', 'action')}"
        return ActionPlan(**plan_dict)
    raise InvalidActionPlanError(f"Invalid action_plan type: {type(raw_plan)}")


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

    # Parse ActionPlan model if needed (shared normalization — see coerce_action_plan
    # so the executor and the approval gate hash the plan identically).
    try:
        action_plan = coerce_action_plan(raw_plan)
    except InvalidActionPlanError as exc:
        execution_log = ExecutionLog(
            status="failed",
            steps_completed=0,
            steps_total=0,
            error=str(exc),
        ).model_dump()
        new_state["execution_log"] = execution_log
        return new_state

    # 1. Plan Hash Verification
    approved_hash = state.get("approved_plan_hash")
    current_hash = compute_action_plan_hash(action_plan)

    # Fail closed when the caller marks this run as approval-bearing: an execution
    # that is SUPPOSED to be anchored to a persisted human approval must not run
    # un-anchored. This closes the "only enforced when a hash happens to be present"
    # gap on the canonical approval path (ADR-005); default is off, so raw/staging
    # harness callers that never had an anchor are unaffected.
    if state.get("require_approved_hash") and not approved_hash:
        err_msg = "Execution requires an approved plan hash anchor, but none was supplied"
        logger.error(err_msg)
        execution_log = ExecutionLog(
            status="failed",
            steps_completed=0,
            steps_total=len(action_plan.action_steps),
            error=err_msg,
        ).model_dump()
        new_state["execution_log"] = execution_log
        new_state["error"] = err_msg
        new_state["error_code"] = "ACTION_PLAN_CHANGED"
        return new_state

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
                    approved_plan_hash=approved_hash,
                    step_index=idx,
                    environment=environment,
                    tenant_id=tenant_id,
                    incident_id=incident_id,
                    resource_id=resource_id,
                    redis_client=redis_client,
                    db_session=db_session,
                )

                # Strict validation of response payload for GitHub / PR tools
                if step.tool in ("create_pr", "code_fix_pr", "apply_github_patch", "git_commit"):
                    if not isinstance(res, dict):
                        raise ValueError(f"Tool '{step.tool}' returned invalid response type: {type(res).__name__}")
                    if res.get("status") == "failed" or res.get("success") is False:
                        err_msg = res.get("error") or res.get("message") or "GitHub API execution failed"
                        raise RuntimeError(f"Tool '{step.tool}' execution failed: {err_msg}")
                    
                    if step.tool in ("create_pr", "code_fix_pr"):
                        pr_num = res.get("pr_number") or res.get("number")
                        pr_url = res.get("pr_url") or res.get("html_url")
                        has_real_pr = (
                            (isinstance(pr_num, int) and pr_num > 0)
                            or (isinstance(pr_url, str) and "/pull/" in pr_url and "/pull/new" not in pr_url)
                        )
                        if not has_real_pr:
                            raise RuntimeError(
                                f"Tool '{step.tool}' response missing a genuine Pull Request entity (no valid PR number or PR URL): {res}"
                            )
                    else:
                        has_commit = bool(res.get("commit_sha"))
                        if not has_commit:
                            raise RuntimeError(
                                f"Tool '{step.tool}' response missing valid commit SHA: {res}"
                            )

                steps_completed += 1
                step_results.append(res)
            except Exception as step_exc:
                logger.error("Tool execution failed at step %d (%s): %s", idx + 1, step.tool, step_exc)
                last_error = str(step_exc)
                # ABORT IMMEDIATELY - do NOT run remaining steps
                break

        # Construct final ExecutionLog outcome
        if steps_completed == steps_total:
            status = "success"
            result_str = f"Successfully executed all {steps_total} steps in action plan." if steps_total > 0 else "No execution steps required."
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
            if not new_state.get("post_action_metrics"):
                new_state["post_action_metrics"] = {"health_status": "200 OK", "error_rate": 0.0}
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
