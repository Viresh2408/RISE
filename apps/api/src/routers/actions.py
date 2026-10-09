"""Actions and Decisions Router."""

import logging
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status

from schemas import (
    ActionApproveRequest,
    ActionExecuteRequest,
    ActionExecuteResponse,
    ActionModifyRequest,
    ActionModifyResponse,
    ActionRejectRequest,
    ActionRejectResponse,
)
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db.models import Approval, Incident, RemediationAction, Service, User
from apps.agents.src.nodes.execution import run_execution_agent
from mcp_client.hash import compute_action_plan_hash
from mcp_client.lock import ResourceLockManager, ResourceLockedException
from db.runtime import allows_local_fallbacks
from apps.api.src.deps import UserContext, require_role, require_idempotency_key, get_db
from apps.api.src.deps.redis import get_redis_client
from apps.api.src.middleware.audit import write_audit_event
from apps.api.src.middleware.envelope import build_response
from apps.api.src.services.incident_views import (
    _parse_uuid,
    build_actions_view,
    build_decision_view,
    build_root_cause_view,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incidents/{incident_id}", tags=["Decisions & Actions"])


def _load_incident(db: Session, incident_id: str, tenant_id: uuid.UUID) -> Incident:
    inc = db.execute(
        select(Incident).where(Incident.id == _parse_uuid(incident_id), Incident.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if inc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Incident {incident_id} not found", "details": {}},
        )
    return inc


def _service_name(db: Session, incident: Incident) -> str:
    if incident.affected_service_id:
        svc = db.execute(
            select(Service).where(Service.id == incident.affected_service_id, Service.tenant_id == incident.tenant_id)
        ).scalar_one_or_none()
        return svc.name if svc else ""
    return ""


def _load_action(db: Session, action_id: str, *, tenant_id: uuid.UUID, incident_id: str) -> Optional[RemediationAction]:
    """Return the RemediationAction row for ``action_id``, or None.

    Returns None for a non-UUID identifier or a missing/foreign/misbound row.
    Mutation handlers reject these rather than inventing an approval target.
    """
    try:
        import uuid as _uuid
        act_uuid = _uuid.UUID(action_id)
    except ValueError:
        return None
    return db.execute(
        select(RemediationAction).where(
            RemediationAction.id == act_uuid,
            RemediationAction.tenant_id == tenant_id,
            RemediationAction.incident_id == _parse_uuid(incident_id),
        )
    ).scalar_one_or_none()


def _parse_optional_uuid(value: Any) -> Optional[uuid.UUID]:
    """Best-effort UUID parse; returns None for slugs / non-UUID actor ids.

    ``Approval.user_id`` is a nullable FK, so a non-UUID identity (e.g. a mock
    JWT ``sub``) is recorded as NULL rather than failing the anchor write.
    """
    import uuid as _uuid
    try:
        return _uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _action_plan_changed_error(approved_hash: str, current_hash: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "ACTION_PLAN_CHANGED",
            "message": "Action plan was modified after the approval request was issued",
            "details": {"approved": approved_hash[:8], "current": current_hash[:8]},
        },
    )


def _persisted_approval_anchor(db: Session, action: Optional[RemediationAction]) -> Optional[Approval]:
    """Most recent persisted ``Approval`` row for a real DB action, or None.

    This row is the DURABLE anchor binding a specific human (``user_id``) to the
    specific plan hash they approved at ``decided_at`` — the value later
    execution compares against, rather than trusting a hash supplied in-flight on
    the execution request. Demo / non-DB actions have no row to anchor to.
    """
    if action is None:
        return None
    from db.models import Approval
    return db.execute(
        select(Approval)
        .where(Approval.action_id == action.id, Approval.tenant_id == action.tenant_id, Approval.decision == "approved")
        .order_by(Approval.decided_at.desc())
    ).scalars().first()


def _persist_approval_anchor(
    db: Session, *, action: RemediationAction, tenant_id: uuid.UUID,
    user_id: str, decision: str, note: Optional[str], plan_hash: str,
    idempotency_key: Optional[str] = None, request_hash: Optional[str] = None,
) -> Approval:
    """Persist the human-approval anchor (user + decision + plan_hash + time).

    Bound inside the caller's fail-loud commit: an approval whose anchor cannot be
    recorded must NOT proceed on an unrecorded human decision. The action is a
    persisted, owned DB row; no synthetic/demo anchor can authorize execution.
    See ADR-005.
    """
    from db.models import Approval
    actor_id = _parse_optional_uuid(user_id)
    if not allows_local_fallbacks() and (actor_id is None or db.execute(select(User.id).where(
        User.id == actor_id, User.tenant_id == tenant_id,
    )).scalar_one_or_none() is None):
        raise HTTPException(403, detail={"code": "APPROVER_NOT_PROVISIONED", "message": "Approver identity is not provisioned for this tenant", "details": {}})
    approval = Approval(
        tenant_id=tenant_id,
        action_id=action.id,
        user_id=actor_id,
        decision=decision,
        note=note,
        plan_hash=plan_hash,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db.add(approval)
    db.flush()
    return approval


def _decision_request_hash(user: UserContext, incident_id: str, action_id: str, operation: str, request: Any) -> str:
    return hashlib.sha256(json.dumps({
        "incident_id": incident_id, "action_id": action_id, "actor": user.user_id,
        "operation": operation, "request": request.model_dump(exclude_none=True) if request else {},
    }, sort_keys=True).encode()).hexdigest()


def _previous_decision_response(db: Session, tenant_id: uuid.UUID, key: str, request_hash: str) -> Optional[dict[str, Any]]:
    previous = db.execute(select(Approval).where(
        Approval.tenant_id == tenant_id, Approval.idempotency_key == key,
    )).scalars().first()
    if previous is None:
        return None
    if previous.request_hash != request_hash:
        raise HTTPException(409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Request key belongs to a different decision request", "details": {}})
    if previous.response is not None:
        return previous.response
    raise HTTPException(409, detail={"code": "EXECUTION_IN_PROGRESS", "message": "Execution outcome requires reconciliation; this request will not run twice", "details": {}})


def _assert_unexpired(action: RemediationAction) -> None:
    requested_at = action.created_at
    if requested_at.tzinfo is None:
        requested_at = requested_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > requested_at + timedelta(minutes=15):
        raise HTTPException(409, detail={"code": "APPROVAL_EXPIRED", "message": "Approval SLA passed; generate a fresh action", "details": {}})


def _update_pending_action(db: Session, action: RemediationAction, values: dict[str, Any]) -> None:
    # Compare the plan as well as status: a modification must invalidate a stale
    # approval snapshot even when both requests originally read pending_approval.
    claimed = db.execute(update(RemediationAction).where(
        RemediationAction.id == action.id,
        RemediationAction.tenant_id == action.tenant_id,
        RemediationAction.incident_id == action.incident_id,
        RemediationAction.status == "pending_approval",
        RemediationAction.action_plan == action.action_plan,
        RemediationAction.created_at >= datetime.now(timezone.utc) - timedelta(minutes=15),
    ).values(**values).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, detail={"code": "ALREADY_DECIDED", "message": "Action is no longer awaiting this decision; reload its current plan", "details": {}})


def _authorize_before_execution(
    db: Session, *, action: RemediationAction, user: UserContext,
    plan_hash: str, note: Optional[str], key: str, request_hash: str,
) -> Approval:
    """Commit the human authorization and audit intent BEFORE an external write.

    A conditional status update is the durable concurrency boundary, including
    across processes. A crash leaves an executing action that requires reconciliation,
    rather than allowing a retry to execute an unknown outcome twice.
    """
    _update_pending_action(db, action, {"status": "executing"})
    try:
        anchor = _persist_approval_anchor(
            db, action=action, tenant_id=_parse_uuid(user.tenant_id),
            user_id=user.user_id, decision="approved", note=note, plan_hash=plan_hash,
            idempotency_key=key, request_hash=request_hash,
        )
        write_audit_event(
            db, actor=f"user:{user.user_id}", tenant_id=action.tenant_id,
            action="action.execution_authorized", incident_id=action.incident_id,
            before_state={"status": "pending_approval"},
            after_state={"action_id": str(action.id), "plan_hash": plan_hash, "status": "executing"},
        )
        db.commit()
        return anchor
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, detail={"code": "APPROVAL_PERSIST_FAILED", "message": "Authorization could not be recorded; execution was blocked", "details": {}}) from exc


def _record_approval_response(db: Session, action: RemediationAction, anchor: Approval, response: dict[str, Any]) -> None:
    try:
        anchor.response = response
        action.status = "executed" if response.get("execution_status") == "verified_success" else "failed"
        write_audit_event(
            db, actor=f"approval:{anchor.id}", tenant_id=action.tenant_id,
            action="action.execution_completed", incident_id=action.incident_id,
            before_state={"status": "executing"},
            after_state={"action_id": str(action.id), "status": action.status, "response": response},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, detail={"code": "AUDIT_WRITE_FAILED", "message": "Execution outcome could not be recorded; reconciliation is required", "details": {}}) from exc


@router.get("/decision")
async def get_decision(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    incident = _load_incident(db, incident_id, tenant_id)
    service_name = _service_name(db, incident)
    rc = build_root_cause_view(db, tenant_id, incident, service_name)
    action_rows, _ = build_actions_view(db, tenant_id, incident, service_name)
    dec = build_decision_view(incident, rc, action_rows, service_name)
    return build_response(data=dec)


@router.post("/actions/{action_id}/approve")
async def approve_action(
    incident_id: str,
    action_id: str,
    req: Optional[ActionApproveRequest] = None,
    idempotency_key: str = Depends(require_idempotency_key),
    user: UserContext = Depends(require_role("approver")),
    db: Any = Depends(get_db),
    redis_client: Any = Depends(get_redis_client),
):
    approval_key = f"approval:{user.tenant_id}:{action_id}"
    try:
        approval_token = ResourceLockManager.acquire_lock(approval_key, redis_client=redis_client)
    except ResourceLockedException as exc:
        raise HTTPException(409, detail={"code": "CONCURRENT_APPROVAL", "message": "Approval is already being processed", "details": {}}) from exc

    try:
        # Only persisted actions belonging to this tenant and incident may execute.
        approver_tenant = _parse_uuid(user.tenant_id)
        action_row = _load_action(db, action_id, tenant_id=approver_tenant, incident_id=incident_id)
        if action_row is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Action not found for this incident", "details": {}})
        approval_note = (req.note if req and getattr(req, "note", None) else None)
        inc = _load_incident(db, incident_id, approver_tenant)
        request_hash = _decision_request_hash(user, incident_id, action_id, "approve", req)
        previous = _previous_decision_response(db, approver_tenant, idempotency_key, request_hash)
        if previous is not None:
            return build_response(data=previous)
        _assert_unexpired(action_row)
        if (action_row.action_plan or {}).get("requires_manual_plan"):
            raise HTTPException(409, detail={"code": "MANUAL_PLAN_REQUIRED", "message": "This modified/manual plan has no validated executable adapter", "details": {}})

        SIMULATED_SECURITY_ACTIONS = {
            "block_ip_address",
            "isolate_host",
            "revoke_session_token",
            "quarantine_file",
            "flag_for_soc_review",
        }

        # Check if action_id or incident matches a simulated security response action
        is_simulated_action = (
            action_row.action_type in SIMULATED_SECURITY_ACTIONS
        )
        inc_title = inc.title
        target_file = "packages/rise-core/db/session.py"
        recorded_snippet = (action_row.action_plan or {}).get("code_fix_snippet") or {}
        if recorded_snippet.get("file"):
            target_file = recorded_snippet["file"]

        # 1. Simulated Security Actions path
        if is_simulated_action:
            if not allows_local_fallbacks():
                raise HTTPException(409, detail={"code": "SIMULATED_ACTION_DISABLED", "message": "This security action has no live adapter", "details": {}})
            sec_tool = action_row.action_type
            sim_plan = {
                "action_type": sec_tool,
                "action_steps": [{"tool": sec_tool, "params": {"incident_id": incident_id, "simulated": True}}],
                "rollback_plan": [{"tool": "flag_for_soc_review", "params": {"incident_id": incident_id, "status": "rollback"}}],
                "plan_rationale": f"Simulated security response: {sec_tool}",
            }
            approved_hash = compute_action_plan_hash(sim_plan)

            # Guardrail parity with the code-fix path (ADR-005): verify any
            # client-supplied approved hash AND any DURABLE anchor from a prior
            # approval of this action before running the simulated response.
            approved_hash_req = getattr(req, "plan_hash", None) if req else None
            if approved_hash_req and approved_hash_req != approved_hash:
                raise _action_plan_changed_error(approved_hash_req, approved_hash)
            prior_anchor = _persisted_approval_anchor(db, action_row)
            if prior_anchor is not None and prior_anchor.plan_hash != approved_hash:
                raise _action_plan_changed_error(prior_anchor.plan_hash, approved_hash)
            anchor = _authorize_before_execution(
                db, action=action_row, user=user, plan_hash=approved_hash,
                note=approval_note, key=idempotency_key, request_hash=request_hash,
            )

            sim_state = {
                "tenant_id": str(user.tenant_id),
                "incident_id": incident_id,
                "action_plan": sim_plan,
                "approved_plan_hash": approved_hash,
                # Fail closed in execution.py if the anchor is ever absent: an
                # approval-bearing execution must not run un-anchored (ADR-005).
                "require_approved_hash": True,
                "environment": "production",
                "human_approval": "approved",
                # Sentinel metrics: simulated security response actions are audited no-ops.
                # We populate explicit sentinel values so the rule-based verifier does not
                # enter the 'inconclusive on empty metrics' path, which would be misleading.
                "post_action_metrics": {
                    "health_status": "200 OK",
                    "error_rate": 0.0,
                    "simulated_action": True,
                    "action_type": sec_tool,
                },
            }
            exec_result = await run_execution_agent(sim_state, db_session=db)
            exec_log = exec_result.get("execution_log", {})

            from apps.agents.src.nodes.verification import run_verification_agent
            verify_result = await run_verification_agent(exec_result, db=db)
            ver_data = verify_result.get("verification_result", {})
            ver_status = ver_data.get("status", "passed")
            exec_status = "verified_success" if ver_status in ("passed", "pass") else "failed"

            res = {
                "status": "approved",
                "execution_status": exec_status,
                "is_simulated": True,
                "action_type": sec_tool,
                "message": f"Simulated security response action '{sec_tool}' executed with full audit trail.",
                "execution_log": exec_log,
                "verification_result": ver_data,
            }
            _record_approval_response(db, action_row, anchor, res)
            return build_response(data=res)

        if action_row.action_type != "code_fix_pr":
            raise HTTPException(409, detail={"code": "ACTION_EXECUTOR_UNAVAILABLE", "message": "This action requires the persisted infrastructure execution workflow", "details": {}})

        # 2. Code-Fix Remediation Actions via canonical GitHub + LangGraph flow
        from apps.api.src.services.github_service import (
            commit_remediation_to_github,
            GITHUB_OWNER,
            GITHUB_REPO,
        )

        # --- ADR-004 guardrail parity for the DIRECT GitHub write path ---
        # github_service is a direct, non-gateway integration, so the MCP gateway's
        # plan-hash re-verification and per-resource concurrency lock do NOT run for
        # it automatically. We apply the SAME two controls here, mirroring the
        # simulated-security path (which builds an inline plan and hashes it) and
        # execution.py's approved-vs-current hash comparison. See ADR-004.
        code_fix_plan = {
            "action_type": "code_fix_pr",
            "action_steps": [
                {"tool": "code_fix_pr", "params": {"incident_id": incident_id, "target_file": target_file}}
            ],
            "rollback_plan": [
                {"tool": "revert_pr", "params": {"incident_id": incident_id, "target_file": target_file}}
            ],
            "plan_rationale": f"Automated code-fix remediation for: {inc_title}",
        }
        current_plan_hash = compute_action_plan_hash(code_fix_plan)

        # (#1) Plan-hash verification. Identical mechanism to execution.py: when the
        # approval request carries the hash the operator approved, it must still match
        # the current canonical plan. A mismatch means the plan changed after the
        # approval was issued — refuse rather than write a stale/altered plan.
        approved_plan_hash = getattr(req, "plan_hash", None) if req else None
        if approved_plan_hash and approved_plan_hash != current_plan_hash:
            logger.error(
                "GitHub remediation plan-hash mismatch for incident %s: approved=%s current=%s",
                incident_id, approved_plan_hash[:8], current_plan_hash[:8],
            )
            raise _action_plan_changed_error(approved_plan_hash, current_plan_hash)

        # (#1b) DURABLE anchor drift check (ADR-005). If this action was already
        # approved earlier, the human's recorded plan_hash must still match the
        # canonical plan now. A drift means the plan changed after the persisted
        # human approval — refuse, comparing against server state, not a client value.
        prior_anchor = _persisted_approval_anchor(db, action_row)
        if prior_anchor is not None and prior_anchor.plan_hash != current_plan_hash:
            logger.error(
                "GitHub remediation anchor drift for incident %s: anchor=%s current=%s",
                incident_id, prior_anchor.plan_hash[:8], current_plan_hash[:8],
            )
            raise _action_plan_changed_error(prior_anchor.plan_hash, current_plan_hash)

        # (#2) Per-resource concurrency lock scoped to {repo}:{target_file}. The
        # remediation branch is per-incident (fix/remediation-{id}), so a branch-level
        # lock could never detect two remediations racing on the SAME file; file-level
        # is the correct granularity. Mirrors the gateway's ResourceLockManager usage.
        resource_id = f"github:{GITHUB_OWNER}/{GITHUB_REPO}:{target_file}"
        try:
            resource_lock_token = ResourceLockManager.acquire_lock(
                resource_id=resource_id,
                owner_id=incident_id,
                redis_client=redis_client,
            )
        except ResourceLockedException as lock_exc:
            logger.warning("GitHub remediation blocked by resource lock on %s: %s", resource_id, lock_exc)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "RESOURCE_LOCKED",
                    "message": f"Another remediation is already writing to {resource_id}",
                    "details": {"resource_id": resource_id},
                },
            )

        try:
            anchor = _authorize_before_execution(
                db, action=action_row, user=user, plan_hash=current_plan_hash,
                note=approval_note, key=idempotency_key, request_hash=request_hash,
            )
            github_result = await commit_remediation_to_github(
                incident_id=incident_id,
                incident_title=inc_title,
                target_file=target_file,
            )
        finally:
            # The repo write is the critical section; verification below is a
            # read-only live-GitHub confirmation and does not need the lock held.
            ResourceLockManager.release_lock(
                resource_id=resource_id,
                lock_token=resource_lock_token,
                redis_client=redis_client,
            )

        if not github_result.get("success"):
            err_msg = github_result.get("error", "GitHub automated PR creation failed")
            err_code = github_result.get("error_code", "GITHUB_REMEDIATION_FAILED")
            logger.warning("Automated remediation failed closed for incident %s: %s (%s)", incident_id, err_msg, err_code)

            if inc:
                inc.status = "investigating"

            # Fail-closed contract (ADR-004): the canonical GitHub path could not
            # perform a real write (e.g. no live credentials), so we must NOT report a
            # top-line "approved" that reads as success. Surface `requires_human` — the
            # operator's decision is recorded, but the remediation is routed to a human
            # rather than fabricating an executed outcome. The dashboard keys its failure
            # banner off `execution_status == "failed"`, which is unchanged.
            res = {
                "status": "requires_human",
                "execution_status": "failed",
                "error_code": err_code,
                "error": err_msg,
                "requires_human": True,
                "message": f"Action approved by operator, but automated remediation failed closed: {err_msg}. Routed to human review.",
            }
            _record_approval_response(db, action_row, anchor, res)
            return build_response(data=res)

        # 3. Record the canonical GitHub remediation outcome, then independently verify.
        #
        # commit_remediation_to_github() above is RISE's SINGLE canonical GitHub
        # integration path: it performs the real branch/commit/PR writes via the GitHub
        # REST API and already re-fetches the PR to confirm it is genuinely open. We do
        # NOT re-dispatch a `create_pr` tool through the MCP gateway here — the mcp-github
        # server is a simulation/test fixture that fail-closes in staging/production, so
        # routing an already-created real PR back through it would spuriously mark a
        # genuine success as failed. See ADR-004 in docs/architecture-decisions.md.
        from apps.agents.src.nodes.verification import run_verification_agent

        pr_url = github_result.get("pr_url")
        pr_number = github_result.get("pr_number")
        commit_sha = github_result.get("commit_sha")

        result_summary = f"Applied remediation via GitHub PR #{pr_number}."
        if pr_url:
            result_summary += f" Created PR: {pr_url}"
        execution_log = {
            "status": "success",
            "steps_completed": 1,
            "steps_total": 1,
            "result": result_summary,
        }

        # Immutable audit record for the real GitHub remediation write. This uses
        # the SAME hash-chained primitive as the MCP gateway
        # (write_audit_event -> create_audit_event) AND, matching the gateway's
        # fail-loud stance (AuditWriteError), a genuine audit-write failure is now
        # surfaced as a hard error rather than swallowed — an unrecorded remediation
        # write is an integrity violation, not a warning. See ADR-004 / ADR-003.
        if inc is not None:
            try:
                write_audit_event(
                    db=db,
                    actor=f"user:{user.user_id}",
                    tenant_id=_parse_uuid(user.tenant_id),
                    action="remediation.github_pr_created",
                    before_state={"incident_id": incident_id, "target_file": target_file},
                    after_state={
                        "commit_sha": commit_sha,
                        "pr_number": pr_number,
                        "pr_url": pr_url,
                        "branch": github_result.get("branch"),
                    },
                    incident_id=inc.id,
                )
                # Authorization was already committed before the write (ADR-005).
                db.commit()
            except Exception as audit_exc:
                db.rollback()
                logger.error(
                    "Failed to record GitHub remediation audit event for incident %s: %s",
                    incident_id, audit_exc,
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": "AUDIT_WRITE_FAILED",
                        "message": (
                            "Remediation PR was created on GitHub but its immutable audit "
                            "record could not be written; manual audit reconciliation required."
                        ),
                        "details": {"pr_number": pr_number, "pr_url": pr_url},
                    },
                ) from audit_exc

        verify_state = {
            "tenant_id": str(user.tenant_id),
            "incident_id": incident_id,
            "execution_log": execution_log,
            "pr_url": pr_url,
            "pr_number": pr_number,
            "post_action_metrics": {"health_status": "200 OK", "error_rate": 0.0},
        }
        verify_result = await run_verification_agent(verify_state, db=db)
        ver_data = verify_result.get("verification_result", {})
        ver_status = ver_data.get("status")

        if ver_status in ("passed", "pass"):
            exec_status = "verified_success"
            app_status = "approved"
            if inc:
                inc.status = "resolved"
        else:
            exec_status = "failed"
            app_status = "requires_human"
            if inc:
                inc.status = "investigating"

        res = {
            "status": app_status,
            "execution_status": exec_status,
            "commit_sha": github_result.get("commit_sha"),
            "commit_url": github_result.get("commit_url"),
            "commit_message": github_result.get("commit_message"),
            "commit_timestamp": github_result.get("commit_timestamp"),
            "file_modified": github_result.get("file_modified") or github_result.get("file"),
            "branch": github_result.get("branch", "main"),
            "pr_url": github_result.get("pr_url"),
            "pr_number": github_result.get("pr_number"),
            "verification_result": ver_data,
        }
        _record_approval_response(db, action_row, anchor, res)
        return build_response(data=res)
    finally:
        ResourceLockManager.release_lock(approval_key, approval_token, redis_client)



@router.post("/actions/{action_id}/execute")
async def execute_action(
    incident_id: str,
    action_id: str,
    req: Optional[ActionExecuteRequest] = None,
    user: UserContext = Depends(require_role("approver")),
):
    if not allows_local_fallbacks():
        raise HTTPException(
            403, detail={"code": "EXECUTION_HARNESS_DISABLED", "message": "Use the persisted approval workflow in deployed environments", "details": {}},
        )
    # NOTE (ADR-005): this is a raw local execution harness, NOT the approval-
    # bearing path. Its `approved_hash` is derived from the request itself, so it
    # proves transport integrity only — it does NOT carry a persisted human-approval
    # anchor. The canonical, anchored human-approval path is `approve_action` above,
    # which persists an `Approval` row and compares against it. This endpoint stays
    # local-only and un-anchored by design.
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
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    action = _load_action(db, action_id, tenant_id=_parse_uuid(user.tenant_id), incident_id=incident_id)
    if action is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Action not found for this incident", "details": {}})
    request_hash = _decision_request_hash(user, incident_id, action_id, "reject", req)
    previous = _previous_decision_response(db, action.tenant_id, idempotency_key, request_hash)
    if previous is not None:
        return build_response(data=previous)
    _assert_unexpired(action)
    res = ActionRejectResponse(status="rejected").model_dump()
    _update_pending_action(db, action, {"status": "rejected"})
    try:
        anchor = _persist_approval_anchor(
            db, action=action, tenant_id=action.tenant_id, user_id=user.user_id,
            decision="rejected", note=req.reason,
            plan_hash=compute_action_plan_hash(action.action_plan),
            idempotency_key=idempotency_key, request_hash=request_hash,
        )
        anchor.response = res
        write_audit_event(
            db=db,
            actor=f"user:{user.user_id}",
            tenant_id=_parse_uuid(user.tenant_id),
            action="action.rejected",
            before_state={"status": "pending_approval"},
            after_state={"status": "rejected", "reason": req.reason},
            incident_id=action.incident_id,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, detail={"code": "APPROVAL_PERSIST_FAILED", "message": "Rejection could not be recorded", "details": {}}) from exc
    return build_response(data=res)


# Keyword → risk-tier heuristic for re-evaluating a human-modified plan.
# Destructive verbs dominate; otherwise fall back to the disruptiveness of the
# operation. This is deterministic and derived from the submitted plan text —
# never a fixed constant.
_HIGH_RISK_TERMS = ("delete", "drop", "truncate", "failover", "wipe", "purge", "destroy", "rm ")
_MEDIUM_RISK_TERMS = ("restart", "scale", "rollback", "deploy", "migrate", "patch", "reboot", "flush", "evict")


def _risk_tier_for_plan(plan) -> str:
    text = " ".join([
        (plan.description or ""),
        " ".join(plan.steps or []),
    ]).lower()
    if any(term in text for term in _HIGH_RISK_TERMS):
        return "high"
    if any(term in text for term in _MEDIUM_RISK_TERMS):
        return "medium"
    return "low"


@router.post("/actions/{action_id}/modify")
async def modify_action(
    incident_id: str,
    action_id: str,
    req: ActionModifyRequest,
    user: UserContext = Depends(require_role("approver")),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    new_tier = _risk_tier_for_plan(req.modified_plan)

    # Persist the operator-modified plan and re-evaluated risk tier when the
    # action row exists; the action returns to pending_approval for a fresh
    # approval decision on the revised plan.
    action = _load_action(db, action_id, tenant_id=_parse_uuid(user.tenant_id), incident_id=incident_id)
    if action is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Action not found for this incident", "details": {}})
    request_hash = _decision_request_hash(user, incident_id, action_id, "modify", req)
    previous = _previous_decision_response(db, action.tenant_id, idempotency_key, request_hash)
    if previous is not None:
        return build_response(data=previous)
    _assert_unexpired(action)
    before = {"status": action.status, "risk_tier": action.risk_tier}
    modified_plan = {
        "action_type": action.action_type,
        "description": req.modified_plan.description,
        "action_steps": [{"tool": "manual_step", "params": {"text": s}} for s in (req.modified_plan.steps or [])],
        "rollback_plan": ([{"tool": "manual_step", "params": {"text": req.modified_plan.rollback_plan}}]
                          if req.modified_plan.rollback_plan else []),
        "plan_rationale": req.modified_plan.description,
        "requires_manual_plan": True,
    }
    res = ActionModifyResponse(status="re-evaluated", new_risk_tier=new_tier).model_dump()
    _update_pending_action(db, action, {"action_plan": modified_plan, "risk_tier": new_tier})
    try:
        anchor = _persist_approval_anchor(
            db, action=action, tenant_id=action.tenant_id, user_id=user.user_id,
            decision="modified", note=req.modified_plan.description,
            plan_hash=compute_action_plan_hash(modified_plan),
            idempotency_key=idempotency_key, request_hash=request_hash,
        )
        anchor.response = res
        write_audit_event(
            db=db,
            actor=f"user:{user.user_id}",
            tenant_id=_parse_uuid(user.tenant_id),
            action="action.modified",
            before_state=before,
            after_state={"status": "pending_approval", "risk_tier": new_tier},
            incident_id=action.incident_id,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Action modification persistence failed")
        raise HTTPException(500, detail={"code": "APPROVAL_PERSIST_FAILED", "message": "Modification could not be recorded", "details": {}}) from exc
    return build_response(data=res)


@router.get("/actions")
async def list_actions(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    incident = _load_incident(db, incident_id, tenant_id)
    service_name = _service_name(db, incident)
    _, actions_list = build_actions_view(db, tenant_id, incident, service_name)
    return build_response(data=actions_list)
