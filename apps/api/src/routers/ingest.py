"""Ingest Router — security log batch upload endpoint.

Endpoint summary
----------------
POST /ingest/security-log
    Accept a batch of security log lines (JSON array, NDJSON, CSV, or plain
    syslog text) as a multipart file upload or pasted text body.  Each record
    is normalised and fed through the same Ingestion Agent pipeline used by
    all four webhook endpoints.

Auth
----
Bearer JWT with ``require_role("engineer")`` — the same minimum role as
``POST /incidents``.  This is an authenticated upload endpoint, not a
machine-driven webhook, so HMAC signature verification is not applied.

Batch semantics
---------------
- Each log line / record is processed independently through the pipeline.
- Failures on individual records are collected and returned in the response
  rather than aborting the entire batch.
- The endpoint always returns HTTP 200 (even for partial failures) so that
  CI pipelines get a deterministic success response for the upload action
  itself.  Per-line errors are surfaced via the ``results`` array.

``dry_run`` mode
----------------
When ``dry_run=true``, the normalizer runs and the LLM call is made, but no
``Incident`` or ``IncidentEvent`` rows are written to the database and no
events are published to the Redis stream.  Dedup is also skipped.  Useful for
validating a dataset before committing it.

Input formats (auto-detected from ``Content-Type`` / filename / content)
------------------------------------------------------------------------
Multipart file upload
    ``multipart/form-data`` with a ``file`` field (UploadFile).
    Format is detected from the file extension (.json, .csv, .log) and then
    by content heuristic if the extension is absent or unrecognised.

JSON body
    ``application/json`` body: ``{ "lines": ["...", ...], "dry_run": false }``.
    Each element of ``lines`` is treated as one raw text record.

Form text field
    ``multipart/form-data`` with a ``text`` field containing raw pasted lines.
    Processed the same as a plain-text file.

Limits
------
- Maximum 500 records per request (configurable via ``INGEST_MAX_BATCH_SIZE`` env var).
- Maximum file size: 5 MB (enforced by reading the upload into memory).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.deps import get_db, get_redis_client, require_role, UserContext
from apps.api.src.middleware.envelope import build_response
from apps.api.src.services.ingestion.agent import IngestionAgentError, run_ingestion_agent
from apps.api.src.services.ingestion.dedup import check_dedup, register_dedup
from apps.api.src.services.ingestion.dlq import publish_event, send_to_dlq
from apps.api.src.services.ingestion.normalizer import SecurityLogNormalizer
from db.models import Incident, IncidentEvent, create_audit_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["Ingest"])

_NORMALIZER = SecurityLogNormalizer()

_MAX_BATCH = int(os.environ.get("INGEST_MAX_BATCH_SIZE", "500"))
_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

SOURCE = "security_log"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SecurityLogJsonBody(BaseModel):
    """JSON body alternative to multipart upload."""

    lines: List[str] = Field(..., description="Raw log line strings (one per element).")
    dry_run: bool = Field(False, description="Parse + normalise but skip DB writes.")


class LineResult(BaseModel):
    line_index: int
    status: str  # "created" | "deduplicated" | "dry_run" | "dlq_error" | "parse_error"
    incident_id: Optional[str] = None
    summary: Optional[str] = None
    error: Optional[str] = None


class IngestBatchResponse(BaseModel):
    processed: int
    incidents_created: int
    deduplicated: int
    queued_dlq: int
    dry_run_skipped: int
    errors: int
    results: List[LineResult]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_upload_to_records(
    text: str,
    filename: Optional[str],
) -> List[Dict[str, Any]]:
    """Run the normalizer on a text blob and return enriched records."""
    records = _NORMALIZER.parse_auto(text, filename=filename)
    _NORMALIZER.enrich_with_metadata(records, upload_filename=filename)
    return records


async def _process_record(
    record: Dict[str, Any],
    *,
    dry_run: bool,
    tenant_id: uuid.UUID,
    db: Session,
    redis_client: Any,
) -> LineResult:
    """Run one record through the full ingestion pipeline.

    Returns a ``LineResult`` — never raises.
    """
    line_index: int = record.get("_line_index", 0)

    # ── Ingestion Agent (LLM normalisation call) ─────────────────────────────
    try:
        incident_event_schema = await run_ingestion_agent(
            source=SOURCE,
            raw_payload=record,
            db=db,
        )
    except IngestionAgentError as exc:
        logger.warning(
            "Ingest security-log: Ingestion Agent failed line=%d reason=%s",
            line_index,
            exc.reason,
        )
        send_to_dlq(
            redis_client,
            source=SOURCE,
            raw_body=json.dumps(record, default=str).encode(),
            reason=exc.reason,
            error_detail=exc.detail,
        )
        return LineResult(
            line_index=line_index,
            status="dlq_error",
            error=f"{exc.reason}: {exc.detail[:200]}",
        )

    resource_id: str = incident_event_schema.resource_id
    summary: str = incident_event_schema.summary

    if dry_run:
        return LineResult(
            line_index=line_index,
            status="dry_run",
            summary=summary,
        )

    # ── Dedup check ─────────────────────────────────────────────────────────
    existing_id = check_dedup(redis_client, resource_id)
    if existing_id is not None:
        logger.info(
            "Ingest security-log: dedup hit line=%d resource_id=%r existing=%s",
            line_index,
            resource_id,
            existing_id,
        )
        return LineResult(
            line_index=line_index,
            status="deduplicated",
            incident_id=existing_id,
            summary=summary,
        )

    # ── Create DB records ────────────────────────────────────────────────────
    new_incident_id = uuid.uuid4()
    severity = incident_event_schema.severity_hint
    if severity == "unknown":
        severity = "SEV3"  # conservative default for security events

    incident = Incident(
        id=new_incident_id,
        tenant_id=tenant_id,
        title=summary[:255],
        description=summary,
        status="open",
        severity=severity,
    )
    db.add(incident)

    event_row = IncidentEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        incident_id=new_incident_id,
        source=SOURCE,
        raw_payload=record,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event_row)
    db.flush()

    create_audit_event(
        db,
        tenant_id=tenant_id,
        actor="system:security_log_ingest",
        action="incident.created",
        after_state={
            "incident_id": str(new_incident_id),
            "source": SOURCE,
            "resource_id": resource_id,
            "severity": severity,
            "line_index": line_index,
        },
        incident_id=new_incident_id,
    )
    db.commit()

    # ── Register dedup key & publish event ──────────────────────────────────
    register_dedup(redis_client, resource_id, str(new_incident_id))

    publish_event(
        redis_client,
        incident_id=str(new_incident_id),
        tenant_id=str(tenant_id),
        source=SOURCE,
        event_type=incident_event_schema.event_type,
        resource_id=resource_id,
        severity_hint=incident_event_schema.severity_hint,
    )

    logger.info(
        "Ingest security-log: incident created line=%d incident_id=%s resource_id=%r",
        line_index,
        new_incident_id,
        resource_id,
    )

    return LineResult(
        line_index=line_index,
        status="created",
        incident_id=str(new_incident_id),
        summary=summary,
    )


def _build_summary(results: List[LineResult], dry_run: bool) -> IngestBatchResponse:
    """Aggregate per-line results into a summary response."""
    return IngestBatchResponse(
        processed=len(results),
        incidents_created=sum(1 for r in results if r.status == "created"),
        deduplicated=sum(1 for r in results if r.status == "deduplicated"),
        queued_dlq=sum(1 for r in results if r.status == "dlq_error"),
        dry_run_skipped=sum(1 for r in results if r.status == "dry_run"),
        errors=sum(1 for r in results if r.status == "parse_error"),
        results=results,
    )


def _parse_tenant_id(tenant_id_str: str) -> uuid.UUID:
    try:
        return uuid.UUID(tenant_id_str)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_DNS, tenant_id_str)


# ---------------------------------------------------------------------------
# Endpoint — multipart file upload + optional text field
# ---------------------------------------------------------------------------


@router.post(
    "/security-log",
    summary="Batch-ingest security log lines",
    description=(
        "Upload a batch of security log lines (JSON, CSV, or plain syslog text) "
        "as a multipart file or pasted text.  Each record is normalised by the "
        "Ingestion Agent and produces an Incident + IncidentEvent row if it passes "
        "dedup checks.  Set ``dry_run=true`` to validate without writing to the DB."
    ),
    response_description="Per-line results and aggregate counts.",
)
async def ingest_security_log_upload(
    file: Optional[UploadFile] = File(None, description="Security log file (.json, .csv, .log)"),
    text: Optional[str] = Form(None, description="Raw pasted log lines (alternative to file upload)"),
    dry_run: bool = Form(False, description="Normalise but skip DB writes."),
    user: UserContext = Depends(require_role("engineer")),
    db: Session = Depends(get_db),
    redis_client: Any = Depends(get_redis_client),
):
    """Multipart-form variant: accepts ``file`` (UploadFile) and/or ``text`` (Form)."""
    return await _handle_ingest(
        file=file,
        raw_text=text,
        dry_run=dry_run,
        user=user,
        db=db,
        redis_client=redis_client,
    )


# ---------------------------------------------------------------------------
# Endpoint — JSON body variant
# ---------------------------------------------------------------------------


@router.post(
    "/security-log/json",
    summary="Batch-ingest security log lines (JSON body)",
    description=(
        "JSON-body alternative to the multipart upload.  "
        "Pass ``lines`` as a list of raw log line strings."
    ),
)
async def ingest_security_log_json(
    body: SecurityLogJsonBody,
    user: UserContext = Depends(require_role("engineer")),
    db: Session = Depends(get_db),
    redis_client: Any = Depends(get_redis_client),
):
    """JSON body variant: ``{ \"lines\": [\"<log line>\", ...], \"dry_run\": false }``."""
    joined = "\n".join(body.lines)
    return await _handle_ingest(
        file=None,
        raw_text=joined,
        dry_run=body.dry_run,
        user=user,
        db=db,
        redis_client=redis_client,
    )


# ---------------------------------------------------------------------------
# Shared ingestion logic
# ---------------------------------------------------------------------------


async def _handle_ingest(
    *,
    file: Optional[UploadFile],
    raw_text: Optional[str],
    dry_run: bool,
    user: UserContext,
    db: Session,
    redis_client: Any,
) -> Any:
    """Core handler shared by both endpoint variants."""
    tenant_id = _parse_tenant_id(user.tenant_id)

    # ── 1. Read raw content ──────────────────────────────────────────────────
    filename: Optional[str] = None
    content_text: Optional[str] = None

    if file is not None:
        filename = file.filename
        raw_bytes = await file.read()
        if len(raw_bytes) > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "code": "FILE_TOO_LARGE",
                    "message": f"Upload exceeds {_MAX_FILE_BYTES // (1024*1024)} MB limit.",
                    "details": {"max_bytes": _MAX_FILE_BYTES, "received_bytes": len(raw_bytes)},
                },
            )
        try:
            content_text = raw_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "VALIDATION_ERROR",
                    "message": f"Could not decode uploaded file as UTF-8: {exc}",
                    "details": {},
                },
            ) from exc
    elif raw_text:
        content_text = raw_text

    if not content_text or not content_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "No content provided. Supply a ``file`` upload or ``text`` field.",
                "details": {},
            },
        )

    # ── 2. Normalise ─────────────────────────────────────────────────────────
    try:
        records = _parse_upload_to_records(content_text, filename)
    except Exception as exc:
        logger.exception("SecurityLogNormalizer raised unexpectedly: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PARSE_ERROR",
                "message": f"Could not parse log content: {exc}",
                "details": {},
            },
        ) from exc

    if not records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "No log records could be extracted from the provided content.",
                "details": {},
            },
        )

    if len(records) > _MAX_BATCH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "BATCH_TOO_LARGE",
                "message": (
                    f"Batch contains {len(records)} records; maximum is {_MAX_BATCH}. "
                    "Split the upload into smaller files."
                ),
                "details": {"received": len(records), "max": _MAX_BATCH},
            },
        )

    logger.info(
        "Ingest security-log: tenant=%s file=%r records=%d dry_run=%s",
        tenant_id,
        filename,
        len(records),
        dry_run,
    )

    # ── 3. Process each record through the pipeline ─────────────────────────
    results: List[LineResult] = []
    for record in records:
        result = await _process_record(
            record,
            dry_run=dry_run,
            tenant_id=tenant_id,
            db=db,
            redis_client=redis_client,
        )
        results.append(result)

    summary = _build_summary(results, dry_run=dry_run)
    return build_response(data=summary.model_dump())
