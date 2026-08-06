"""Incidents Router — real DB implementation.

Every state-changing endpoint (POST, PATCH, POST /comment) writes exactly
one audit_event row within the **same transaction** as the data mutation.
The pattern is:

  1. Start: session provided by Depends(get_db).
  2. Capture before_state if updating.
  3. Mutate ORM objects via db.add() / attribute assignment.
  4. db.flush() to assign server-generated IDs without committing.
  5. Call write_audit_event() — adds audit row to the open transaction.
  6. db.commit() — single commit covers data + audit atomically.
  7. db.refresh() to load server-side defaults (updated_at, etc.).

This guarantees: no code path mutates an incident without an audit row.
Grep test: every db.commit() call in this file is preceded by
write_audit_event() with no intervening exception handling that would
allow a commit to sneak through without an audit write.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Comment, Incident, Service
from schemas import (
    CommentCreateRequest,
    CommentDTO,
    IncidentCreateRequest,
    IncidentDetailDTO,
    IncidentDTO,
    IncidentUpdateRequest,
    ReinvestigateResponse,
)
from apps.api.src.deps import get_db, require_role, UserContext
from apps.api.src.middleware.audit import write_audit_event
from apps.api.src.middleware.envelope import build_meta, build_response

router = APIRouter(prefix="/incidents", tags=["Incidents"])

# ── Serialisation helpers ──────────────────────────────────────────────────────


def _incident_to_dict(incident: Incident) -> Dict[str, Any]:
    """Convert an Incident ORM row to an audit-safe dict (no lazy loads)."""
    return {
        "id": str(incident.id),
        "title": incident.title,
        "description": incident.description,
        "status": incident.status,
        "severity": incident.severity,
        "affected_service_id": str(incident.affected_service_id) if incident.affected_service_id else None,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
    }


def _incident_to_dto(incident: Incident, service_name: Optional[str] = None) -> Dict[str, Any]:
    """Serialise an Incident ORM row to the IncidentDTO wire format."""
    return IncidentDTO(
        id=str(incident.id),
        title=incident.title,
        description=incident.description or "",
        severity=incident.severity,
        status=incident.status,
        affected_service=service_name or "",
        created_at=incident.created_at.isoformat(),
        updated_at=incident.updated_at.isoformat() if incident.updated_at else incident.created_at.isoformat(),
        resolution_note=None,
    ).model_dump()


def _resolve_service(
    db: Session,
    tenant_id: uuid.UUID,
    service_name: str,
) -> Service:
    """Look up a Service by name; auto-create with is_auto_created=True if absent.

    The caller must flush/commit after this call to persist new rows.
    """
    stmt = (
        select(Service)
        .where(Service.tenant_id == tenant_id)
        .where(Service.name == service_name)
        .limit(1)
    )
    svc = db.execute(stmt).scalar_one_or_none()
    if svc is None:
        svc = Service(
            tenant_id=tenant_id,
            name=service_name,
            environment="unknown",  # admin can correct via service management API
            is_auto_created=True,
        )
        db.add(svc)
        db.flush()  # assigns svc.id without committing
    return svc


# ── Cursor helpers (opaque base64-encoded ISO timestamp) ──────────────────────

def _encode_cursor(dt: datetime) -> str:
    return base64.urlsafe_b64encode(dt.isoformat().encode()).decode()


def _decode_cursor(cursor: str) -> datetime:
    try:
        return datetime.fromisoformat(base64.urlsafe_b64decode(cursor).decode())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": f"Invalid cursor: {exc}", "details": {}},
        ) from exc


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
async def list_incidents(
    status_param: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    stmt = (
        select(Incident)
        .where(Incident.tenant_id == tenant_id)
        .order_by(Incident.created_at.desc())
    )

    if status_param:
        stmt = stmt.where(Incident.status == status_param)
    if severity:
        stmt = stmt.where(Incident.severity == severity)
    if from_date:
        stmt = stmt.where(Incident.created_at >= from_date)
    if to_date:
        stmt = stmt.where(Incident.created_at <= to_date)
    if cursor:
        cursor_dt = _decode_cursor(cursor)
        stmt = stmt.where(Incident.created_at < cursor_dt)

    # Service name filter: join via affected_service_id
    if service:
        svc_stmt = select(Service.id).where(
            Service.tenant_id == tenant_id,
            Service.name == service,
        )
        svc_row = db.execute(svc_stmt).scalar_one_or_none()
        if svc_row:
            stmt = stmt.where(Incident.affected_service_id == svc_row)
        else:
            # Unknown service name → return empty list
            meta = build_meta(next_cursor=None)
            return build_response(data=[], meta=meta)

    stmt = stmt.limit(limit + 1)
    rows = db.execute(stmt).scalars().all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    # Bulk-resolve service names
    svc_ids = {r.affected_service_id for r in rows if r.affected_service_id}
    svc_map: Dict[uuid.UUID, str] = {}
    if svc_ids:
        svc_rows = db.execute(
            select(Service).where(Service.id.in_(svc_ids))
        ).scalars().all()
        svc_map = {s.id: s.name for s in svc_rows}

    data = [_incident_to_dto(inc, svc_map.get(inc.affected_service_id)) for inc in rows]
    next_cursor = _encode_cursor(rows[-1].created_at) if has_more and rows else None
    meta = build_meta(next_cursor=next_cursor)
    return build_response(data=data, meta=meta)


def _parse_uuid(id_str: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_DNS, id_str)


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    inc_uuid = _parse_uuid(incident_id)

    incident = db.execute(
        select(Incident).where(
            Incident.tenant_id == tenant_id,
            Incident.id == inc_uuid,
        )
    ).scalar_one_or_none()

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Incident {incident_id} not found", "details": {}},
        )

    # Resolve service name
    service_name = ""
    if incident.affected_service_id:
        svc = db.execute(
            select(Service).where(Service.id == incident.affected_service_id)
        ).scalar_one_or_none()
        service_name = svc.name if svc else ""

    # Build timeline from comments
    comments = db.execute(
        select(Comment)
        .where(Comment.incident_id == incident.id)
        .order_by(Comment.created_at.asc())
    ).scalars().all()

    timeline = [
        {
            "timestamp": c.created_at.isoformat(),
            "event": "comment",
            "text": c.text,
            "author": str(c.user_id) if c.user_id else "system",
        }
        for c in comments
    ]

    detail = IncidentDetailDTO(
        id=str(incident.id),
        title=incident.title,
        description=incident.description or "",
        severity=incident.severity,
        status=incident.status,
        affected_service=service_name,
        created_at=incident.created_at.isoformat(),
        updated_at=incident.updated_at.isoformat() if incident.updated_at else incident.created_at.isoformat(),
        timeline=timeline,
        root_cause=None,
        impact=None,
        actions=[],
        approvals=[],
    ).model_dump()
    return build_response(data=detail)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_incident(
    req: IncidentCreateRequest,
    user: UserContext = Depends(require_role("engineer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    actor = f"user:{user.user_id}"

    # Resolve or auto-create the service (is_auto_created=True if new)
    svc = _resolve_service(db, tenant_id, req.affected_service)

    incident = Incident(
        tenant_id=tenant_id,
        title=req.title,
        description=req.description,
        status="open",
        severity=req.severity,
        affected_service_id=svc.id,
    )
    db.add(incident)
    db.flush()  # populates incident.id, incident.created_at, incident.updated_at

    after_state = _incident_to_dict(incident)

    # Audit write — same transaction, locks tenant row FOR UPDATE
    write_audit_event(
        db=db,
        actor=actor,
        tenant_id=tenant_id,
        action="incident.created",
        before_state=None,
        after_state=after_state,
        incident_id=incident.id,
    )

    db.commit()          # ← single commit: service row + incident + audit event
    db.refresh(incident)

    return build_response(
        data=_incident_to_dto(incident, svc.name),
        status_code=201,
    )


@router.post("/{incident_id}/reinvestigate", status_code=status.HTTP_202_ACCEPTED)
async def reinvestigate_incident(
    incident_id: str,
    user: UserContext = Depends(require_role("engineer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    inc_uuid = _parse_uuid(incident_id)

    incident = db.execute(
        select(Incident).where(
            Incident.tenant_id == tenant_id,
            Incident.id == inc_uuid,
        )
    ).scalar_one_or_none()

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Incident {incident_id} not found", "details": {}},
        )

    # Stub: full Celery dispatch is a follow-up task.
    # No state mutation → no audit event required.
    placeholder_run_id = str(uuid.uuid4())
    res = ReinvestigateResponse(
        agent_run_id=placeholder_run_id,
        status="queued",
    ).model_dump()
    return build_response(data=res, status_code=202)


@router.post("/{incident_id}/comment", status_code=status.HTTP_201_CREATED)
async def add_comment(
    incident_id: str,
    req: CommentCreateRequest,
    user: UserContext = Depends(require_role("engineer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    actor = f"user:{user.user_id}"
    inc_uuid = _parse_uuid(incident_id)

    incident = db.execute(
        select(Incident).where(
            Incident.tenant_id == tenant_id,
            Incident.id == inc_uuid,
        )
    ).scalar_one_or_none()

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Incident {incident_id} not found", "details": {}},
        )

    user_uuid = _parse_uuid(user.user_id)

    comment = Comment(
        tenant_id=tenant_id,
        incident_id=incident.id,
        user_id=user_uuid,
        text=req.text,
    )
    db.add(comment)
    db.flush()  # populates comment.id and comment.created_at

    write_audit_event(
        db=db,
        actor=actor,
        tenant_id=tenant_id,
        action="incident.comment_added",
        before_state=None,
        after_state={
            "comment_id": str(comment.id),
            "incident_id": str(incident.id),
            "text": comment.text,
        },
        incident_id=incident.id,
    )

    db.commit()
    db.refresh(comment)

    comment_dto = CommentDTO(
        id=str(comment.id),
        incident_id=str(comment.incident_id),
        text=comment.text,
        created_at=comment.created_at.isoformat(),
        author=user.user_id,
    ).model_dump()
    return build_response(data=comment_dto, status_code=201)


@router.patch("/{incident_id}")
async def patch_incident(
    incident_id: str,
    req: IncidentUpdateRequest,
    user: UserContext = Depends(require_role("approver")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    actor = f"user:{user.user_id}"
    inc_uuid = _parse_uuid(incident_id)

    incident = db.execute(
        select(Incident).where(
            Incident.tenant_id == tenant_id,
            Incident.id == inc_uuid,
        )
    ).scalar_one_or_none()

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Incident {incident_id} not found", "details": {}},
        )

    before_state = _incident_to_dict(incident)

    # Apply permitted mutations
    if req.status:
        incident.status = req.status
        if req.status == "resolved":
            incident.resolved_at = datetime.now(timezone.utc)

    db.flush()  # trigger updated_at refresh via DB trigger; not yet committed

    after_state = _incident_to_dict(incident)

    write_audit_event(
        db=db,
        actor=actor,
        tenant_id=tenant_id,
        action="incident.updated",
        before_state=before_state,
        after_state=after_state,
        incident_id=incident.id,
    )

    db.commit()
    db.refresh(incident)

    # Resolve service name for DTO
    service_name = ""
    if incident.affected_service_id:
        svc = db.execute(
            select(Service).where(Service.id == incident.affected_service_id)
        ).scalar_one_or_none()
        service_name = svc.name if svc else ""

    updated = _incident_to_dto(incident, service_name)
    # Attach resolution_note from request body (not stored on Incident model)
    updated["resolution_note"] = req.resolution_note
    return build_response(data=updated)
