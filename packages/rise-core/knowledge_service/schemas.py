"""Pydantic schemas for the knowledge service public API."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator


class KnowledgeFilter(BaseModel):
    """Filters applied to ``search_similar_incidents``.

    ``tenant_id`` is **required** — searches are always scoped to a single tenant.
    Passing ``tenant_id=None`` or omitting the field raises ``ValueError`` both at
    construction time (Pydantic) and at the service layer (``KnowledgeService``),
    so there is no path to an accidental cross-tenant search.
    """

    tenant_id: str = Field(
        description=(
            "UUID of the tenant to scope the search to.  Required — cross-tenant "
            "searches are never permitted."
        )
    )
    service: Optional[str] = Field(
        default=None,
        description="Narrow results to incidents from this service name.",
    )
    severity: Optional[str] = Field(
        default=None,
        description="Narrow results to incidents of this severity (e.g. 'SEV1').",
    )

    @model_validator(mode="after")
    def _require_tenant_id(self) -> "KnowledgeFilter":
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError(
                "tenant_id is required on KnowledgeFilter — cross-tenant searches are "
                "not permitted."
            )
        return self


class SimilarIncidentResult(BaseModel):
    """One result returned by ``search_similar_incidents``."""

    knowledge_entry_id: str = Field(
        description="UUID of the matching KnowledgeEntry row in Postgres."
    )
    vector_id: str = Field(
        description="Qdrant point UUID (same as KnowledgeEntry.vector_id)."
    )
    title: str = Field(description="Title of the knowledge entry.")
    service: Optional[str] = Field(
        default=None, description="Service associated with the incident."
    )
    severity: Optional[str] = Field(
        default=None, description="Severity of the incident."
    )
    score: float = Field(
        description="Cosine similarity score in [0, 1].  Higher is more similar."
    )
    tags: Dict[str, Any] = Field(
        default_factory=dict,
        description="Tag payload stored alongside the embedding.",
    )
