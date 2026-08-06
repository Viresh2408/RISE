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
    """Inbound Slack Events API or Interactivity webhook.

    Authentication: HMAC-SHA256 of ``v0:{timestamp}:{body}`` with
    ``SLACK_SIGNING_SECRET``, plus a 5-minute replay-window check.
    """
    return await _ingest(
        request=request,
        source="slack",
        verifier=verifier,
        db=db,
        redis_client=redis_client,
    )
