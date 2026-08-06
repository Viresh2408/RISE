"""Audit Logs Router — real DB implementation."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AuditEvent
from schemas import AuditEventDTO
from apps.api.src.deps import get_db, require_role, UserContext
from apps.api.src.middleware.envelope import build_meta, build_response

router = APIRouter(prefix="/audit", tags=["Audit"])


def _encode_cursor(seq: int) -> str:
    return base64.urlsafe_b64encode(str(seq).encode()).decode()


def _decode_cursor(cursor: str) -> int:
    try:
        return int(base64.urlsafe_b64decode(cursor).decode())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": f"Invalid cursor: {exc}", "details": {}},
        ) from exc


@router.get("")
async def list_audit_events(
    incident_id: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    user: UserContext = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    tenant_id = uuid.UUID(user.tenant_id)

    stmt = (
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.seq.desc())
    )

    if incident_id:
        try:
            stmt = stmt.where(AuditEvent.incident_id == uuid.UUID(incident_id))
        except ValueError:
            return build_response(data=[], meta=build_meta(next_cursor=None))

    if actor:
        stmt = stmt.where(AuditEvent.actor == actor)

    if from_date:
        stmt = stmt.where(AuditEvent.created_at >= from_date)

    if to_date:
        stmt = stmt.where(AuditEvent.created_at <= to_date)

    if cursor:
        cursor_seq = _decode_cursor(cursor)
        stmt = stmt.where(AuditEvent.seq < cursor_seq)

    stmt = stmt.limit(limit + 1)
    rows = db.execute(stmt).scalars().all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    data = [
        AuditEventDTO(
            id=str(e.id),
            incident_id=str(e.incident_id) if e.incident_id else None,
            actor=e.actor,
            action=e.action,
            timestamp=e.created_at.isoformat(),
            before_state=e.before_state,
            after_state=e.after_state,
            details={},
        ).model_dump()
        for e in rows
    ]

    next_cursor = _encode_cursor(rows[-1].seq) if has_more and rows else None
    meta = build_meta(next_cursor=next_cursor)
    return build_response(data=data, meta=meta)
