"""Knowledge Base Router."""

from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from schemas import KnowledgeCreateRequest, KnowledgeEntryDTO
from apps.api.src.deps import require_role, UserContext
from apps.api.src.middleware.envelope import build_response

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


@router.get("")
async def search_knowledge(
    q: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    user: UserContext = Depends(require_role("viewer")),
):
    entries = [
        KnowledgeEntryDTO(
            id="kb-001",
            title="Kubernetes OOMKilled Runbook",
            content="# Handling OOMKilled pods\n1. Increase memory limit...",
            tags=["k8s", "oom"],
            service="k8s",
            created_at="2026-08-01T08:00:00Z",
        ).model_dump()
    ]
    return build_response(data=entries)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    req: KnowledgeCreateRequest,
    user: UserContext = Depends(require_role("engineer")),
):
    entry = KnowledgeEntryDTO(
        id="kb-002",
        title=req.title,
        content=req.content,
        tags=req.tags,
        service=req.service,
        created_at="2026-08-01T10:30:00Z",
    ).model_dump()
    return build_response(data=entry, status_code=201)
