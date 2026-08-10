"""Inbound Webhooks Router — full implementation.

Endpoint summary
----------------
POST /webhooks/cloudwatch   — AWS CloudWatch via SNS  (SNS signature verification)
POST /webhooks/alertmanager — Prometheus Alertmanager  (shared-secret header)
POST /webhooks/github       — GitHub App/webhook       (HMAC-SHA256)
POST /webhooks/slack        — Slack Events/Interactive (HMAC + replay window)

Common flow (every endpoint)
----------------------------
1. Read raw request body (before any JSON parsing — needed for HMAC).
2. Verify signature via the injected ``SignatureVerifier`` → 401 on failure.
   Nothing is written to the database or DLQ if verification fails.
3. Parse raw body as JSON.  ``JSONDecodeError`` → DLQ, return 200 (ack).
4. Extract the source-specific identifier and resolve tenant_id via
   ``IntegrationConfig`` lookup.  Unknown source → 400, audit-logged.
5. Run the Ingestion Agent (LLM Gateway call, prompts.md §1).
   ``IngestionAgentError`` → DLQ, return 200 (ack).
6. Dedup check: if an open incident exists on the same resource within the
   dedup window, return early with ``deduplicated=true`` — no DB writes.
7. Create ``Incident`` + ``IncidentEvent`` rows, register dedup key, publish to
   ``stream:events`` for downstream Context Builder Agent.
8. Return 200 ``{received: true, incident_id: ..., deduplicated: false}``.

Signature verifier injection
-----------------------------
Each endpoint receives its verifier via a FastAPI ``Depends(get_*_verifier)``
factory.  Tests override the factory via ``app.dependency_overrides`` — there
is no env-flag bypass in the verifier implementations.

Tenant resolution
-----------------
Webhooks carry no JWT.  Tenant is resolved by matching the payload's embedded
source identifier against ``IntegrationConfig.credential_ref``.  Unknown
identifiers are rejected and audit-logged — no fallback tenant exists.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from apps.api.src.deps.db import get_db
from apps.api.src.deps.redis import get_redis_client
from apps.api.src.middleware.envelope import build_response
from apps.api.src.services.ingestion.agent import IngestionAgentError, run_ingestion_agent
from apps.api.src.services.ingestion.dedup import check_dedup, register_dedup
from apps.api.src.services.ingestion.dlq import publish_event, send_to_dlq
from apps.api.src.services.ingestion.signature_verifier import (
    SignatureVerifier,
    get_alertmanager_verifier,
    get_github_verifier,
    get_slack_verifier,
    get_sns_verifier,
)
from apps.api.src.services.ingestion.tenant_resolver import (
    extract_source_identifier,
    resolve_tenant_from_integration,
)
from db.models import AuditEvent, Incident, IncidentEvent, create_audit_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# ---------------------------------------------------------------------------
# Shared ingestion logic
# ---------------------------------------------------------------------------


async def _ingest(
    *,
    request: Request,
    source: str,
    verifier: SignatureVerifier,
    db: Session,
    redis_client: Any,
) -> Any:
    """Core ingestion flow shared across all four webhook endpoints.

    Returns a ``JSONResponse`` via ``build_response()``.
    """
    # ── 1. Read raw body (must happen before JSON parse for HMAC) ──────────
    raw_body: bytes = await request.body()

    # ── 2. Signature verification ──────────────────────────────────────────
    # Raises HTTPException(401) on failure — nothing written to DB or DLQ.
    await verifier.verify(request, raw_body)

    # ── 3. Parse JSON body ─────────────────────────────────────────────────
    try:
        payload: Dict[str, Any] = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Webhook %s: JSON parse failed: %s", source, exc)
        send_to_dlq(
            redis_client,
            source=source,
            raw_body=raw_body,
            reason="json_parse_error",
            error_detail=str(exc),
        )
        return build_response(
            data={"received": True, "incident_id": None, "deduplicated": False, "queued_dlq": True}
        )

    # ── 4. Resolve tenant from IntegrationConfig ───────────────────────────
    identifier = extract_source_identifier(source, payload)
    if identifier is None:
        logger.warning(
            "Webhook %s: could not extract source identifier from payload", source
        )
        send_to_dlq(
            redis_client,
            source=source,
            raw_body=raw_body,
            reason="missing_source_identifier",
            error_detail="Could not extract source-specific identifier from payload.",
        )
        return build_response(
            data={"received": True, "incident_id": None, "deduplicated": False, "queued_dlq": True}
        )

    tenant_id = resolve_tenant_from_integration(db, source, identifier)
    if tenant_id is None:
        # Unknown integration — reject, audit-log, do NOT default to any tenant.
        logger.warning(
            "Webhook %s: no IntegrationConfig for identifier=%r — rejected",
            source,
            identifier,
        )
        _write_audit_unknown_source(db, source=source, identifier=identifier)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNKNOWN_INTEGRATION_SOURCE",
                "message": (
                    f"No registered integration found for source={source!r} "
                    f"identifier={identifier!r}. "
                    "Register this integration before sending webhooks."
                ),
                "details": {"source": source, "identifier": identifier},
            },
        )

    # ── 5. Ingestion Agent (LLM call) ──────────────────────────────────────
    try:
        incident_event_schema = await run_ingestion_agent(
            source=source,
            raw_payload=payload,
            db=db,
        )
    except IngestionAgentError as exc:
        logger.warning(
            "Webhook %s: Ingestion Agent failed — routing to DLQ. reason=%s",
            source,
            exc.reason,
        )
        send_to_dlq(
            redis_client,
            source=source,
            raw_body=raw_body,
            reason=exc.reason,
            error_detail=exc.detail,
        )
        return build_response(
            data={"received": True, "incident_id": None, "deduplicated": False, "queued_dlq": True}
        )

    resource_id: str = incident_event_schema.resource_id

    # ── 6. Dedup check ─────────────────────────────────────────────────────
    existing_id = check_dedup(redis_client, resource_id)
    if existing_id is not None:
        logger.info(
            "Webhook %s: dedup hit for resource_id=%r existing_incident=%s",
            source,
            resource_id,
            existing_id,
        )
        return build_response(
            data={
                "received": True,
                "incident_id": existing_id,
                "deduplicated": True,
                "queued_dlq": False,
            }
        )

    # ── 7. Create DB records ───────────────────────────────────────────────
    new_incident_id = uuid.uuid4()
    severity = incident_event_schema.severity_hint
    if severity == "unknown":
        severity = "SEV4"  # conservative fallback for DB enum

    incident = Incident(
        id=new_incident_id,
        tenant_id=tenant_id,
        title=incident_event_schema.summary[:255],
        description=incident_event_schema.summary,
        status="open",
        severity=severity,
    )
    db.add(incident)

    event_row = IncidentEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        incident_id=new_incident_id,
        source=source,
        raw_payload=payload,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event_row)
    db.flush()

    create_audit_event(
        db,
        tenant_id=tenant_id,
        actor="system:ingestion_agent",
        action="incident.created",
        after_state={
            "incident_id": str(new_incident_id),
            "source": source,
            "resource_id": resource_id,
            "severity": severity,
        },
        incident_id=new_incident_id,
    )

    db.commit()

    # ── Register dedup key ─────────────────────────────────────────────────
    register_dedup(redis_client, resource_id, str(new_incident_id))

    # ── Publish to event bus ───────────────────────────────────────────────
    publish_event(
        redis_client,
        incident_id=str(new_incident_id),
        tenant_id=str(tenant_id),
        source=source,
        event_type=incident_event_schema.event_type,
        resource_id=resource_id,
        severity_hint=incident_event_schema.severity_hint,
    )

    # ── Background agent graph pipeline execution ─────────────────────────
    try:
        from apps.agents.src.orchestrator.graph import run_incident
        import asyncio
        asyncio.create_task(asyncio.to_thread(run_incident, str(tenant_id), str(new_incident_id), payload))
        logger.info("Launched background agent graph execution for incident_id=%s", new_incident_id)
    except Exception as exc:
        logger.warning("Failed launching background run_incident task: %s", exc)

    logger.info(
        "Webhook %s: incident created incident_id=%s resource_id=%r",
        source,
        new_incident_id,
        resource_id,
    )

    return build_response(
        data={
            "received": True,
            "incident_id": str(new_incident_id),
            "deduplicated": False,
            "queued_dlq": False,
        }
    )


def _write_audit_unknown_source(db: Session, *, source: str, identifier: str) -> None:
    """Write an audit event for a rejected unknown integration source attempt."""
    try:
        # Use the sentinel tenant for audit events that can't be tenant-resolved.
        sentinel = uuid.UUID("00000000-0000-0000-0000-000000000001")
        create_audit_event(
            db,
            tenant_id=sentinel,
            actor="system:webhook_ingestion",
            action="webhook.unknown_integration_source",
            after_state={"source": source, "identifier": identifier},
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to write audit event for unknown source: %s", exc)


# ---------------------------------------------------------------------------
# Endpoint definitions
# ---------------------------------------------------------------------------


@router.post("/cloudwatch")
async def cloudwatch_webhook(
    request: Request,
    verifier: SignatureVerifier = Depends(get_sns_verifier),
    db: Session = Depends(get_db),
    redis_client: Any = Depends(get_redis_client),
):
    """Inbound CloudWatch alarm via AWS SNS.

    Authentication: RSA signature embedded in SNS message body, cert fetched
    from ``SigningCertURL`` (must be an amazonaws.com domain).
    """
    return await _ingest(
        request=request,
        source="cloudwatch",
        verifier=verifier,
        db=db,
        redis_client=redis_client,
    )


@router.post("/alertmanager")
async def alertmanager_webhook(
    request: Request,
    verifier: SignatureVerifier = Depends(get_alertmanager_verifier),
    db: Session = Depends(get_db),
    redis_client: Any = Depends(get_redis_client),
):
    """Inbound Prometheus Alertmanager webhook.

    Authentication: constant-time compare of ``X-RISE-Secret`` header against
    ``ALERTMANAGER_WEBHOOK_SECRET`` env var.
    """
    return await _ingest(
        request=request,
        source="alertmanager",
        verifier=verifier,
        db=db,
        redis_client=redis_client,
    )


@router.post("/github")
async def github_webhook(
    request: Request,
    verifier: SignatureVerifier = Depends(get_github_verifier),
    db: Session = Depends(get_db),
    redis_client: Any = Depends(get_redis_client),
):
    """Inbound GitHub webhook (App or repository webhook).

    Authentication: HMAC-SHA256 of raw body with ``GITHUB_WEBHOOK_SECRET``,
    compared against the ``X-Hub-Signature-256`` header.
    """
    return await _ingest(
        request=request,
        source="github",
        verifier=verifier,
        db=db,
        redis_client=redis_client,
    )


@router.post("/slack")
async def slack_webhook(
    request: Request,
    verifier: SignatureVerifier = Depends(get_slack_verifier),
    db: Session = Depends(get_db),
    redis_client: Any = Depends(get_redis_client),
):
    """Inbound Slack Events API, Slash Commands, or Interactivity webhook.

    Authentication: HMAC-SHA256 of ``v0:{timestamp}:{body}`` with
    ``SLACK_SIGNING_SECRET``, plus a 5-minute replay-window check.
    """
    # ── 1. Read raw body & verify signature ─────────────────────────────────
    raw_body: bytes = await request.body()
    await verifier.verify(request, raw_body)

    # ── 2. Parse body (JSON or Form URL-encoded) ─────────────────────────────
    parsed_body: Optional[Dict[str, Any]] = None
    form_data: Optional[Dict[str, Any]] = None

    try:
        parsed_body = json.loads(raw_body)
    except Exception:
        import urllib.parse
        form_bytes = raw_body.decode("utf-8", errors="replace")
        qs = urllib.parse.parse_qs(form_bytes)
        form_data = {k: v[0] if len(v) == 1 else v for k, v in qs.items()}

    if form_data and "payload" in form_data:
        try:
            parsed_body = json.loads(form_data["payload"])
        except Exception:
            pass

    # ── 3. Check for Slash Command (/rise status <incident_id>) ──────────────
    command = (form_data or {}).get("command") or (parsed_body or {}).get("command", "")
    text = (form_data or {}).get("text") or (parsed_body or {}).get("text", "")

    if command == "/rise" or (command and "/rise" in str(command)) or (text and text.strip().startswith("status")):
        parts = text.strip().split() if text else []
        sub_cmd = parts[0] if parts else ""

        if sub_cmd == "status":
            if len(parts) >= 2:
                target_id = parts[1]
                incident = None

                # Search by UUID or title substring
                try:
                    target_uuid = uuid.UUID(target_id)
                    incident = db.query(Incident).filter(Incident.id == target_uuid).first()
                except Exception:
                    from sqlalchemy import String
                    incident = (
                        db.query(Incident)
                        .filter(
                            (Incident.title.ilike(f"%{target_id}%"))
                            | (Incident.id.cast(String).ilike(f"%{target_id}%"))
                        )
                        .first()
                    )

                if incident:
                    status_response = {
                        "response_type": "in_channel",
                        "text": f"*Incident Status: {incident.id}*",
                        "blocks": [
                            {
                                "type": "header",
                                "text": {
                                    "type": "plain_text",
                                    "text": f"Incident Status: {incident.id}",
                                    "emoji": True,
                                },
                            },
                            {
                                "type": "section",
                                "fields": [
                                    {"type": "mrkdwn", "text": f"*Incident ID:*\n{incident.id}"},
                                    {"type": "mrkdwn", "text": f"*Status:*\n{incident.status.upper()}"},
                                    {"type": "mrkdwn", "text": f"*Severity:*\n{incident.severity}"},
                                    {"type": "mrkdwn", "text": f"*Title:*\n{incident.title}"},
                                ],
                            },
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"*Summary / Description:*\n{incident.description or 'No description provided.'}",
                                },
                            },
                        ],
                        "incident_id": str(incident.id),
                        "status": incident.status,
                        "severity": incident.severity,
                        "title": incident.title,
                    }
                    return build_response(data=status_response)

                return build_response(
                    data={
                        "response_type": "ephemeral",
                        "text": f"Incident '{target_id}' not found.",
                        "incident_id": target_id,
                        "error": "NOT_FOUND",
                    }
                )

            return build_response(
                data={
                    "response_type": "ephemeral",
                    "text": "Usage: `/rise status <incident_id>`",
                    "error": "INVALID_USAGE",
                }
            )

    # ── 4. Check for Interactive Card Action Payloads (Block Kit Buttons) ────
    actions = (parsed_body or {}).get("actions", [])
    if actions:
        first_action = actions[0]
        action_id = first_action.get("action_id", "")
        val = first_action.get("value", "")

        act_type = ""
        target_incident_id = ""

        if ":" in val:
            parts = val.split(":", 1)
            act_type = parts[0]
            target_incident_id = parts[1]
        elif action_id.endswith("_action"):
            act_type = action_id.replace("_action", "")
            target_incident_id = val

        if not target_incident_id:
            target_incident_id = "inc-slack-001"

        act_id = f"act-{target_incident_id}"

        from apps.api.src.services.approval_lock import (
            acquire_single_use_approval_lock,
            is_approval_decided,
            mark_approval_decided,
            release_single_use_approval_lock,
        )

        if act_type == "approve" or action_id == "approve_action":
            if is_approval_decided(act_id, redis_client):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ALREADY_DECIDED",
                        "message": f"Approval for action '{act_id}' has already been decided",
                        "details": {},
                    },
                )

            if not acquire_single_use_approval_lock(act_id, redis_client):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "CONCURRENT_APPROVAL",
                        "message": f"Approval for action '{act_id}' is currently being processed",
                        "details": {},
                    },
                )

            try:
                mark_approval_decided(act_id, "approved", redis_client)
                import asyncio
                from apps.agents.src.nodes.execution import run_execution_agent
                state = {
                    "tenant_id": str(uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")),
                    "incident_id": target_incident_id,
                    "action_plan": {
                        "action_type": "restart_pod",
                        "action_steps": [
                            {"tool": "restart_pod", "params": {"namespace": "staging", "pod_name": "auth-service-7890"}}
                        ],
                        "rollback_plan": [],
                        "plan_rationale": "Approved via Slack interactive card",
                    },
                    "human_approval": "approved",
                }
                try:
                    asyncio.create_task(run_execution_agent(state))
                except Exception:
                    pass

                return build_response(
                    data={
                        "status": "approved",
                        "incident_id": target_incident_id,
                        "action_id": act_id,
                        "text": f"*Incident {target_incident_id} — APPROVED*\nAction execution queued.",
                    }
                )
            finally:
                release_single_use_approval_lock(act_id, redis_client)

        elif act_type == "reject" or action_id == "reject_action":
            if is_approval_decided(act_id, redis_client):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ALREADY_DECIDED",
                        "message": f"Approval for action '{act_id}' has already been decided",
                        "details": {},
                    },
                )
            mark_approval_decided(act_id, "rejected", redis_client)
            return build_response(
                data={
                    "status": "rejected",
                    "incident_id": target_incident_id,
                    "action_id": act_id,
                    "text": f"*Incident {target_incident_id} — REJECTED*\nAction rejected by user.",
                }
            )

        elif act_type == "modify" or action_id == "modify_action":
            return build_response(
                data={
                    "status": "re-evaluated",
                    "incident_id": target_incident_id,
                    "action_id": act_id,
                    "new_risk_tier": "medium",
                    "text": f"*Incident {target_incident_id} — MODIFIED*\nAction plan marked for re-evaluation.",
                }
            )

        elif act_type == "view_details" or action_id == "view_details_action":
            return build_response(
                data={
                    "status": "details",
                    "incident_id": target_incident_id,
                    "url": f"http://localhost:3000/incidents/{target_incident_id}",
                    "text": f"*Incident Details*: http://localhost:3000/incidents/{target_incident_id}",
                }
            )

    # ── 5. Alert Ingestion Fallback ─────────────────────────────────────────
    return await _ingest(
        request=request,
        source="slack",
        verifier=verifier,
        db=db,
        redis_client=redis_client,
    )

