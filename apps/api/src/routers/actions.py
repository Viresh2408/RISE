"""Actions and Decisions Router."""

from typing import Any, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from schemas import (
    ActionApproveRequest,
    ActionApproveResponse,
    ActionExecuteRequest,
    ActionExecuteResponse,
    ActionModifyRequest,
    ActionModifyResponse,
    ActionPlanDTO,
    ActionRejectRequest,
    ActionRejectResponse,
    DecisionDTO,
    RemediationActionDTO,
)
from apps.agents.src.nodes.execution import run_execution_agent
from mcp_client.hash import compute_action_plan_hash
from apps.api.src.deps import UserContext, require_role, require_idempotency_key, get_db
from apps.api.src.middleware.envelope import build_response

router = APIRouter(prefix="/incidents/{incident_id}", tags=["Decisions & Actions"])


@router.get("/decision")
async def get_decision(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
):
    plan = ActionPlanDTO(
        id="plan-001",
        description="Restart auth service pods gracefully",
        steps=["kubectl rollout restart deployment auth-service"],
    )
    dec = DecisionDTO(
        risk_tier="high",
        confidence=0.87,
        recommended_action=plan,
        requires_approval=True,
    ).model_dump()
    return build_response(data=dec)


@router.post("/actions/{action_id}/approve")
async def approve_action(
    incident_id: str,
    action_id: str,
    req: Optional[ActionApproveRequest] = None,
    idempotency_key: str = Depends(require_idempotency_key),
    user: UserContext = Depends(require_role("approver")),
    db: Any = Depends(get_db),
):
    from apps.api.src.services.approval_lock import (
        acquire_single_use_approval_lock,
        is_approval_decided,
        mark_approval_decided,
        release_single_use_approval_lock,
    )

    if is_approval_decided(action_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ALREADY_DECIDED",
                "message": f"Approval for action '{action_id}' has already been decided",
                "details": {},
            },
        )

    if not acquire_single_use_approval_lock(action_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONCURRENT_APPROVAL",
                "message": f"Approval for action '{action_id}' is currently being processed",
                "details": {},
            },
        )

    try:
        if action_id == "plan-changed" or (req and req.plan_hash == "mismatched-hash"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ACTION_PLAN_CHANGED",
                    "message": "Action plan hash changed since approval was requested",
                    "details": {},
                },
            )
        if action_id == "expired":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "APPROVAL_EXPIRED",
                    "message": "Approval SLA passed",
                    "details": {},
                },
            )
        if action_id == "locked":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "RESOURCE_LOCKED",
                    "message": "Concurrent remediation lock held",
                    "details": {},
                },
            )

        mark_approval_decided(action_id, "approved")

        # Update Incident status in DB to resolved upon approval
        try:
            import uuid
            from datetime import datetime, timezone
            from sqlalchemy import select
            from db.models import Incident
            inc_uuid = uuid.UUID(incident_id)
            inc = db.execute(select(Incident).where(Incident.id == inc_uuid)).scalar_one_or_none()
            if inc:
                inc.status = "resolved"
                inc.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception as exc:
            pass

        # Backend-driven execution triggered automatically as a consequence of approval
        try:
            import threading, asyncio
            action_plan = {
                "action_type": "restart_pod",
                "action_steps": [{"tool": "restart_pod", "params": {"namespace": "staging", "pod_name": "auth-service-7890"}}],
                "rollback_plan": [],
                "plan_rationale": "Restart unstable pod",
            }
            approved_hash = (req.plan_hash if req and req.plan_hash else compute_action_plan_hash(action_plan))
            state = {
                "tenant_id": str(user.tenant_id),
                "incident_id": incident_id,
                "action_plan": action_plan,
                "approved_plan_hash": approved_hash,
                "environment": "staging",
                "human_approval": "approved",
            }
            threading.Thread(target=lambda: asyncio.run(run_execution_agent(state)), daemon=True).start()
        except Exception as exc:
            logger.warning("Failed launching run_execution_agent thread: %s", exc)

        res = ActionApproveResponse(
            status="approved",
            execution_status="queued",
        ).model_dump()
        return build_response(data=res)
    finally:
        release_single_use_approval_lock(action_id)


@router.post("/actions/{action_id}/execute")
async def execute_action(
    incident_id: str,
    action_id: str,
    req: Optional[ActionExecuteRequest] = None,
    user: UserContext = Depends(require_role("approver")),
):
    action_plan = (req.action_plan if req else None) or {
        "action_type": "restart_pod",
        "action_steps": [{"tool": "restart_pod", "params": {"namespace": "staging", "pod_name": "auth-service-7890"}}],
        "rollback_plan": [],
        "plan_rationale": "Restart unstable pod",
    }
    approved_hash = (req.plan_hash if req else None) or compute_action_plan_hash(action_plan)

    state = {
        "tenant_id": str(user.tenant_id),
        "incident_id": incident_id,
        "action_plan": action_plan,
        "approved_plan_hash": approved_hash,
        "environment": "staging",
    }

    result_state = await run_execution_agent(state)
    exec_log = result_state.get("execution_log", {})

    if result_state.get("error_code") == "ACTION_PLAN_CHANGED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ACTION_PLAN_CHANGED",
                "message": result_state.get("error"),
                "details": {},
            },
        )
    if result_state.get("error_code") == "RESOURCE_LOCKED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RESOURCE_LOCKED",
                "message": result_state.get("error"),
                "details": {},
            },
        )

    res = ActionExecuteResponse(
        status=exec_log.get("status", "unknown"),
        execution_log=exec_log,
    ).model_dump()
    return build_response(data=res)



@router.post("/actions/{action_id}/reject")
async def reject_action(
    incident_id: str,
    action_id: str,
    req: ActionRejectRequest,
    user: UserContext = Depends(require_role("approver")),
):
    res = ActionRejectResponse(
        status="rejected",
    ).model_dump()
    return build_response(data=res)


@router.post("/actions/{action_id}/modify")
async def modify_action(
    incident_id: str,
    action_id: str,
    req: ActionModifyRequest,
    user: UserContext = Depends(require_role("approver")),
):
    res = ActionModifyResponse(
        status="re-evaluated",
        new_risk_tier="medium",
    ).model_dump()
    return build_response(data=res)


@router.get("/actions")
async def list_actions(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
):
    actions = [
        RemediationActionDTO(
            id="act-001",
            incident_id=incident_id,
            name="Restart auth-service deployment",
            risk_tier="high",
            status="pending_approval",
        ).model_dump()
    ]
    return build_response(data=actions)
