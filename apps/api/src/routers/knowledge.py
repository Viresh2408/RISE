"""Knowledge Base Router — real DB-backed reads and writes."""

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import KnowledgeEntry
from schemas import KnowledgeCreateRequest, KnowledgeEntryDTO
from apps.api.src.deps import require_role, UserContext, get_db
from apps.api.src.middleware.audit import write_audit_event
from apps.api.src.middleware.envelope import build_response
from apps.api.src.services.incident_views import _parse_uuid

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


def _tags_list(raw: Any) -> List[str]:
    """Coerce the stored ``tags`` JSONB into a list[str] for the DTO."""
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, dict):
        return [str(k) for k in raw.keys()]
    return []


def _to_dto(entry: KnowledgeEntry) -> dict:
    return KnowledgeEntryDTO(
        id=str(entry.id),
        title=entry.title,
        content=entry.content,
        tags=_tags_list(entry.tags),
        # NB: KnowledgeEntry has no ``service`` column (see contradiction note in
        # the Phase 3 report); it cannot be recovered on read.
        service=None,
        created_at=entry.created_at.isoformat() if entry.created_at else "",
    ).model_dump()


@router.get("")
async def search_knowledge(
    q: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)

    entries = db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.tenant_id == tenant_id,
        ).order_by(KnowledgeEntry.created_at.desc())
    ).scalars().all()

    # Filter in Python so the same logic works on both Postgres (JSONB) and the
    # SQLite test engine, where JSONB containment operators are unavailable.
    if q:
        needle = q.lower()
        entries = [
            e for e in entries
            if needle in (e.title or "").lower() or needle in (e.content or "").lower()
        ]
    if tags:
        wanted = {t.strip().lower() for t in tags.split(",") if t.strip()}
        if wanted:
            entries = [
                e for e in entries
                if wanted & {t.lower() for t in _tags_list(e.tags)}
            ]

    data = [_to_dto(e) for e in entries]
    return build_response(data=data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    req: KnowledgeCreateRequest,
    user: UserContext = Depends(require_role("engineer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)

    entry = KnowledgeEntry(
        tenant_id=tenant_id,
        title=req.title,
        content=req.content,
        tags=list(req.tags or []),
    )
    db.add(entry)
    db.flush()

    write_audit_event(
        db=db,
        actor=f"user:{user.user_id}",
        tenant_id=tenant_id,
        action="knowledge.created",
        before_state=None,
        after_state={"id": str(entry.id), "title": entry.title},
    )
    db.commit()
    db.refresh(entry)

    dto = _to_dto(entry)
    # ``service`` is not persisted (no column); echo the caller's value on create
    # so the immediate response is faithful to the request.
    dto["service"] = req.service
    return build_response(data=dto, status_code=201)
