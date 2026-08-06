"""RISE Knowledge Service — Qdrant-backed semantic search over resolved incidents.

Design constraints (see database-design.md §3 and agents-and-orchestration.md §2.3):

- Postgres is the source of truth; Qdrant holds embeddings + minimal filter payload only.
- ``KnowledgeEntry.vector_id`` is the linkage key between the two stores.
- Deletion is a two-step explicit flow:
    1. ``session.delete(entry)`` + ``session.commit()``  — removes from Postgres.
    2. ``qdrant_client.delete(vector_id)``               — removes from Qdrant.
  A rolled-back Postgres transaction will NEVER cause a deleted Qdrant point for a row
  that still exists.

WARNING — bulk / raw-SQL delete paths (e.g. a retention purge job) MUST either:
  a) Route through ``KnowledgeService.delete_knowledge_entry()``, OR
  b) Be followed by a run of ``scripts/reconcile_knowledge_vectors.py`` to detect
     any KnowledgeEntry rows whose vector_id no longer resolves in Qdrant.
"""

from knowledge_service.client import get_qdrant_client
from knowledge_service.embedder import EmbedderProtocol, SentenceTransformerEmbedder
from knowledge_service.schemas import KnowledgeFilter, SimilarIncidentResult
from knowledge_service.service import KnowledgeService

__all__ = [
    "get_qdrant_client",
    "EmbedderProtocol",
    "SentenceTransformerEmbedder",
    "KnowledgeFilter",
    "SimilarIncidentResult",
    "KnowledgeService",
]
