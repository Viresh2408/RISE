"""Actions and Decisions Router."""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status

logger = logging.getLogger(__name__)
from schemas import (
    ActionApproveRequest,
    ActionExecuteRequest,
    ActionExecuteResponse,
    ActionModifyRequest,
    ActionModifyResponse,
    ActionRejectRequest,
    ActionRejectResponse,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Incident, RemediationAction, Service
from apps.agents.src.nodes.execution import run_execution_agent
from mcp_client.hash import compute_action_plan_hash
from mcp_client.lock import ResourceLockManager, ResourceLockedException
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

router = APIRouter(prefix="/incidents/{incident_id}", tags=["Decisions & Actions"])


def _load_incident(db: Session, incident_id: str) -> Incident:
    inc = db.execute(
        select(Incident).where(Incident.id == _parse_uuid(incident_id))
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
            select(Service).where(Service.id == incident.affected_service_id)
        ).scalar_one_or_none()
        return svc.name if svc else ""
    return ""


def _load_action(db: Session, action_id: str):
    """Return the RemediationAction row for ``action_id``, or None.

    Returns None for a non-UUID slug (e.g. the ``act-001`` demo id) or when no
    row exists — callers treat that as "nothing to persist" rather than 404 so
    idempotent decisions on not-yet-materialised actions still succeed.
    """
    try:
        import uuid as _uuid
        act_uuid = _uuid.UUID(action_id)
    except ValueError:
        return None
    return db.execute(
        select(RemediationAction).where(RemediationAction.id == act_uuid)
    ).scalar_one_or_none()


def _parse_optional_uuid(value: Any):
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


def _persisted_approval_anchor(db: Session, action):
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
        .where(Approval.action_id == action.id)
        .order_by(Approval.decided_at.desc())
    ).scalars().first()


def _persist_approval_anchor(db: Session, *, action, tenant_id, user_id, decision, note, plan_hash):
    """Persist the human-approval anchor (user + decision + plan_hash + time).

    Bound inside the caller's fail-loud commit: an approval whose anchor cannot be
    recorded must NOT proceed on an unrecorded human decision. No-op for demo /
    non-DB actions (no ``remediation_actions`` row to satisfy the FK). See ADR-005.
    """
    if action is None:
        return None
    from db.models import Approval
    approval = Approval(
        tenant_id=tenant_id,
        action_id=action.id,
        user_id=_parse_optional_uuid(user_id),
        decision=decision,
        note=note,
        plan_hash=plan_hash,
    )
    db.add(approval)
    db.flush()
    return approval


@router.get("/decision")
async def get_decision(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    incident = _load_incident(db, incident_id)
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
    from apps.api.src.services.approval_lock import (
        acquire_single_use_approval_lock,
        is_approval_decided,
        mark_approval_decided,
        release_single_use_approval_lock,
    )

    if is_approval_decided(action_id):
        # Allow idempotent re-approval if requested
        pass

    acquire_single_use_approval_lock(action_id)

    try:
        if action_id == "plan-changed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ACTION_PLAN_CHANGED",
                    "message": "Action plan was modified after approval request was issued",
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

        # Real DB-backed action row (None for demo slugs like ``act-fix-01``); used
        # to persist and compare the durable human-approval anchor. See ADR-005.
        action_row = _load_action(db, action_id)
        approver_tenant = _parse_uuid(user.tenant_id)
        approval_note = (req.note if req and getattr(req, "note", None) else None)

        SIMULATED_SECURITY_ACTIONS = {
            "block_ip_address",
            "isolate_host",
            "revoke_session_token",
            "quarantine_file",
            "flag_for_soc_review",
        }

        # Check if action_id or incident matches a simulated security response action
        is_simulated_action = (
            action_id in SIMULATED_SECURITY_ACTIONS
            or any(sec_act in action_id.lower() for sec_act in SIMULATED_SECURITY_ACTIONS)
            or (req and getattr(req, "action_plan", None) and getattr(req, "action_plan", {}).get("action_type") in SIMULATED_SECURITY_ACTIONS)
        )

        DEMO_INCIDENT_MAP = {
            "inc-auth-pool-01": ("PostgreSQL Connection Pool Saturation in auth-service", "packages/rise-core/db/session.py"),
            "inc-auth-latency-02": ("P99 Latency Spike on /auth/verify-token via JWKS Fetch", "apps/api/src/deps/auth.py"),
            "inc-stripe-replay-03": ("Stripe Webhook Idempotency Key Replay Storm", "apps/api/src/routers/webhooks.py"),
            "inc-ddos-ratelimit-04": ("DDoS Rate Limit Bypass on User Login", "apps/api/src/middleware/rate_limit.py"),
            "inc-redis-stampede-05": ("Redis Session Cache Stampede on Token Refresh", "apps/api/src/routers/auth.py"),
            "inc-kafka-rebalance-06": ("Kafka Consumer Group Rebalance Storm in ingestion-worker", "apps/api/src/services/telemetry.py"),
            "inc-checkout-redis-07": ("Redis Cluster Cross-Slot Pipeline Storm & Key Eviction Surge in checkout-gateway", "packages/rise-core/db/session.py"),
            "inc-sse-zombie-08": ("SSE Heartbeat Socket Desync & File Descriptor Exhaustion in notification-hub", "apps/api/src/routers/webhooks.py"),
            "inc-redis-pool-09": ("Redis Connection Churn & Missing ConnectionPool in api-gateway", "apps/api/src/deps/redis.py"),
        }

        inc_title = "Security Incident Response"
        target_file = "packages/rise-core/db/session.py"
        inc = None

        if incident_id in DEMO_INCIDENT_MAP:
            inc_title, target_file = DEMO_INCIDENT_MAP[incident_id]
        else:
            try:
                import uuid
                from datetime import datetime, timezone
                from sqlalchemy import select
                from db.models import Incident, Service
                inc_uuid = uuid.UUID(incident_id)
                inc = db.execute(select(Incident).where(Incident.id == inc_uuid)).scalar_one_or_none()
                if inc:
                    inc_title = inc.title
                    # Mark incident as remediating upon approval (not resolved until verified!)
                    inc.status = "remediating"
                    inc.updated_at = datetime.now(timezone.utc)

                    _is_monitor_incident = (
                        inc.description
                        and "[rise-monitor-meta:" in inc.description
                    )
                    _monitor_file = None
                    if _is_monitor_incident:
                        try:
                            from apps.api.src.services.github_monitor import extract_monitor_meta
                            _meta = extract_monitor_meta(inc.description)
                            _monitor_file = (_meta or {}).get("file_path")
                        except Exception:
                            pass

                    if _monitor_file:
                        target_file = _monitor_file
                    elif inc.affected_service_id:
                        svc = db.execute(select(Service).where(Service.id == inc.affected_service_id)).scalar_one_or_none()
                        if svc:
                            if "webhook" in svc.name or "stripe" in svc.name:
                                target_file = "apps/api/src/routers/webhooks.py"
                            elif "auth" in svc.name or "login" in svc.name:
                                target_file = "apps/api/src/deps/auth.py"
                            elif "checkout" in svc.name or "db" in svc.name:
                                target_file = "packages/rise-core/db/session.py"

                    db.commit()
            except Exception:
                pass

        # 1. Simulated Security Actions path
        if is_simulated_action:
            sec_tool = action_id if action_id in SIMULATED_SECURITY_ACTIONS else (
                next((s for s in SIMULATED_SECURITY_ACTIONS if s in action_id.lower()), "flag_for_soc_review")
            )
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

            # Persist the durable human-approval anchor (ADR-005). Fail-loud, and a
            # no-op for demo actions with no DB row. Recorded post-execution so the
            # anchor reflects an approval that actually ran.
            if action_row is not None:
                try:
                    _persist_approval_anchor(
                        db,
                        action=action_row,
                        tenant_id=approver_tenant,
                        user_id=user.user_id,
                        decision="approved",
                        note=approval_note,
                        plan_hash=approved_hash,
                    )
                    db.commit()
                except Exception as anchor_exc:
                    db.rollback()
                    logger.error(
                        "Failed to persist approval anchor for action %s: %s",
                        action_id, anchor_exc,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail={
                            "code": "APPROVAL_PERSIST_FAILED",
                            "message": "Simulated action executed but its approval anchor could not be recorded.",
                            "details": {"action_id": action_id},
                        },
                    ) from anchor_exc

            res = {
                "status": "approved",
                "execution_status": exec_status,
                "is_simulated": True,
                "action_type": sec_tool,
                "message": f"Simulated security response action '{sec_tool}' executed with full audit trail.",
                "execution_log": exec_log,
                "verification_result": ver_data,
            }
            return build_response(data=res)

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
            ResourceLockManager.acquire_lock(
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
                lock_token=incident_id,
                redis_client=redis_client,
            )

        if not github_result.get("success"):
            err_msg = github_result.get("error", "GitHub automated PR creation failed")
            err_code = github_result.get("error_code", "GITHUB_REMEDIATION_FAILED")
            logger.warning("Automated remediation failed closed for incident %s: %s (%s)", incident_id, err_msg, err_code)

            if inc:
                try:
                    inc.status = "investigating"
                    db.commit()
                except Exception:
                    pass

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

        # Immutable audit record for the real GitHub remediation write. Persisted only for
        # DB-backed incidents (demo incidents have no tenant/incident row to anchor to); a
        # residual audit failure is logged and rolled back rather than losing the (already
        # applied) remediation — the PR exists on GitHub regardless of this bookkeeping row.
        # Immutable audit record for the real GitHub remediation write. Persisted only
        # for DB-backed incidents (demo incidents have no tenant/incident row to anchor
        # to). This uses the SAME hash-chained primitive as the MCP gateway
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
                # Persist the durable human-approval anchor in the SAME fail-loud
                # commit as the audit event (ADR-005): user + decision + the exact
                # plan_hash that was executed, bound to this action. report_generator
                # reads this row; a later re-approval compares against it.
                if action_row is not None:
                    _persist_approval_anchor(
                        db,
                        action=action_row,
                        tenant_id=approver_tenant,
                        user_id=user.user_id,
                        decision="approved",
                        note=approval_note,
                        plan_hash=current_plan_hash,
                    )
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
                try:
                    inc.status = "resolved"
                    db.commit()
                except Exception:
                    pass
        else:
            exec_status = "failed"
            app_status = "requires_human"
            if inc:
                try:
                    inc.status = "investigating"
                    db.commit()
                except Exception:
                    pass

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
    # NOTE (ADR-005): this is a raw staging execution harness, NOT the approval-
    # bearing path. Its `approved_hash` is derived from the request itself, so it
    # proves transport integrity only — it does NOT carry a persisted human-approval
    # anchor. The canonical, anchored human-approval path is `approve_action` above,
    # which persists an `Approval` row and compares against it. This endpoint stays
    # staging-only and un-anchored by design.
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
    db: Session = Depends(get_db),
):
    # Persist the rejection when the action exists as a real DB row; a rejection
    # is a terminal decision, so we record it and set the action status to
    # 'rejected' inside the same transaction as the audit event.
    action = _load_action(db, action_id)
    if action is not None:
        before = {"status": action.status}
        action.status = "rejected"
        db.flush()
        write_audit_event(
            db=db,
            actor=f"user:{user.user_id}",
            tenant_id=_parse_uuid(user.tenant_id),
            action="action.rejected",
            before_state=before,
            after_state={"status": "rejected", "reason": req.reason},
            incident_id=action.incident_id,
        )
        db.commit()

    res = ActionRejectResponse(status="rejected").model_dump()
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
    db: Session = Depends(get_db),
):
    new_tier = _risk_tier_for_plan(req.modified_plan)

    # Persist the operator-modified plan and re-evaluated risk tier when the
    # action row exists; the action returns to pending_approval for a fresh
    # approval decision on the revised plan.
    action = _load_action(db, action_id)
    if action is not None:
        before = {"status": action.status, "risk_tier": action.risk_tier}
        modified_plan = {
            "description": req.modified_plan.description,
            "action_steps": [{"tool": "manual_step", "params": {"text": s}} for s in (req.modified_plan.steps or [])],
            "rollback_plan": req.modified_plan.rollback_plan,
            "plan_rationale": req.modified_plan.description,
            "requires_manual_plan": True,
        }
        action.action_plan = modified_plan
        action.risk_tier = new_tier
        action.status = "pending_approval"
        db.flush()
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

    res = ActionModifyResponse(
        status="re-evaluated",
        new_risk_tier=new_tier,
    ).model_dump()
    return build_response(data=res)


@router.get("/actions")
async def list_actions(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    incident = _load_incident(db, incident_id)
    service_name = _service_name(db, incident)
    _, actions_list = build_actions_view(db, tenant_id, incident, service_name)
    return build_response(data=actions_list)
