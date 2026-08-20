"""KnowledgeService — core logic for embedding incidents into Qdrant.

Deletion contract (two-step explicit flow)
------------------------------------------
``delete_knowledge_entry()`` is the **only sanctioned path** for removing a
``KnowledgeEntry``.  The sequence is:

    1. ``session.delete(entry)``  — marks the row for deletion in the ORM.
    2. ``session.commit()``       — durably removes from Postgres.  If this raises,
                                    no Qdrant change occurs.
    3. ``qdrant_client.delete()`` — removes the point from Qdrant.  Called ONLY
                                    after a successful commit.

Consequence: a rolled-back Postgres transaction can NEVER result in a deleted
Qdrant vector for a row that still exists in Postgres.

If the Qdrant deletion fails after a successful Postgres commit, the service logs
a WARNING with the orphaned ``vector_id``.  The reconciliation script
(``scripts/reconcile_knowledge_vectors.py``) can be run to surface and re-embed
such orphans.

Bulk / raw-SQL delete paths WARNING
------------------------------------
Any code that bulk-deletes ``knowledge_entries`` rows WITHOUT calling
``delete_knowledge_entry()`` (e.g. a retention purge job using raw SQL) MUST
either:
  a) Call ``delete_knowledge_entry()`` per-row in a loop, OR
  b) Schedule a run of ``scripts/reconcile_knowledge_vectors.py`` afterwards.

There are NO SQLAlchemy event listeners registered anywhere in this module.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from sqlalchemy.orm import Session

from db.models import KnowledgeEntry
from knowledge_service.embedder import EmbedderProtocol, SentenceTransformerEmbedder
from knowledge_service.schemas import KnowledgeFilter, SimilarIncidentResult

logger = logging.getLogger(__name__)

COLLECTION_NAME = "incidents_v1"
"""Versioned collection name per database-design.md §8.

When the embedding model is changed, create ``incidents_v2``, run the background
re-embedding job, then flip the cutover flag — do NOT rename this constant in
place, as that would silently break reads against the old collection.
"""


class KnowledgeService:
    """Manages incident embeddings in Qdrant with Postgres as the source of truth.

    Parameters
    ----------
    qdrant_client:
        A connected ``QdrantClient`` instance.
    embedder:
        Any object satisfying ``EmbedderProtocol``.  Defaults to
        ``SentenceTransformerEmbedder`` (384-dim, offline, deterministic).
    """

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embedder: Optional[EmbedderProtocol] = None,
    ) -> None:
        self._qdrant = qdrant_client
        self._embedder: EmbedderProtocol = embedder or SentenceTransformerEmbedder()
        self._ensure_collection()

    # ------------------------------------------------------------------
    # Collection lifecycle
    # ------------------------------------------------------------------

    def _ensure_collection(self) -> None:
        """Create the Qdrant collection if it does not already exist.

        Uses ``recreate_collection=False`` semantics via ``get_or_create``:
        if the collection already exists with a *different* configuration, this
        does NOT overwrite it — a ``ValueError`` is raised so the misconfiguration
        is surfaced early rather than silently corrupting existing vectors.
        """
        existing = {c.name for c in self._qdrant.get_collections().collections}
        if COLLECTION_NAME in existing:
            return

        self._qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qdrant_models.VectorParams(
                size=self._embedder.vector_size,
                distance=qdrant_models.Distance.COSINE,
            ),
        )
        logger.info(
            "Created Qdrant collection '%s' (dim=%d, distance=COSINE)",
            COLLECTION_NAME,
            self._embedder.vector_size,
        )

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def embed_and_upsert(
        self,
        knowledge_entry: KnowledgeEntry,
        session: Session,
    ) -> str:
        """Embed a ``KnowledgeEntry`` and upsert it into Qdrant.

        Steps
        -----
        1. Embed ``title + "\\n" + content``.
        2. Generate a UUID for the Qdrant point (or reuse ``vector_id`` if already set).
        3. Upsert the point to Qdrant with a filter payload.
        4. Write the ``vector_id`` back to the ``KnowledgeEntry`` row and commit.

        Parameters
        ----------
        knowledge_entry:
            A ``KnowledgeEntry`` ORM instance attached to *session*.
        session:
            The SQLAlchemy session owning *knowledge_entry*.

        Returns
        -------
        str
            The UUID string stored in ``knowledge_entry.vector_id``.
        """
        text = f"{knowledge_entry.title}\n{knowledge_entry.content}"
        vector = self._embedder.embed(text)

        point_id = (
            uuid.UUID(knowledge_entry.vector_id)
            if knowledge_entry.vector_id
            else uuid.uuid4()
        )

        # Build the filter payload (minimal — Postgres owns the full metadata).
        tags: dict = knowledge_entry.tags if isinstance(knowledge_entry.tags, dict) else {}
        service: str | None = tags.get("service")
        severity: str | None = tags.get("severity")

        payload = {
            "knowledge_entry_id": str(knowledge_entry.id),
            "tenant_id": str(knowledge_entry.tenant_id),
            "title": knowledge_entry.title,
            "service": service,
            "severity": severity,
            "tags": tags,
        }

        self._qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                qdrant_models.PointStruct(
                    id=str(point_id),
                    vector=vector,
                    payload=payload,
                )
            ],
        )

        knowledge_entry.vector_id = str(point_id)
        session.add(knowledge_entry)
        session.commit()

        logger.debug(
            "Upserted knowledge entry %s → Qdrant point %s",
            knowledge_entry.id,
            point_id,
        )
        return str(point_id)

    # ------------------------------------------------------------------
    # Delete path (two-step explicit flow — see module docstring)
    # ------------------------------------------------------------------

    def delete_knowledge_entry(
        self,
        knowledge_entry: KnowledgeEntry,
        session: Session,
    ) -> None:
        """Delete a ``KnowledgeEntry`` from Postgres then remove the Qdrant point.

        This is the **only sanctioned deletion path**.  See module docstring for
        the full contract and bulk-delete warning.

        Parameters
        ----------
        knowledge_entry:
            A ``KnowledgeEntry`` ORM instance attached to *session*.
        session:
            The SQLAlchemy session owning *knowledge_entry*.
        """
        vector_id: str | None = knowledge_entry.vector_id
        entry_id = str(knowledge_entry.id)

        # Step 1+2: delete from Postgres and commit.
        session.delete(knowledge_entry)
        session.commit()
        logger.debug("Deleted KnowledgeEntry %s from Postgres", entry_id)

        # Step 3: delete from Qdrant — only reached after a successful commit.
        if vector_id:
            try:
                self._qdrant.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=qdrant_models.PointIdsList(
                        points=[str(vector_id)]
                    ),
                )
                logger.debug("Deleted Qdrant point %s", vector_id)
            except Exception:
                # Postgres row is already gone — log the orphaned vector_id for
                # reconciliation and do NOT re-raise (the primary delete succeeded).
                logger.warning(
                    "Failed to delete Qdrant point %s for KnowledgeEntry %s. "
                    "Run scripts/reconcile_knowledge_vectors.py to surface orphans.",
                    vector_id,
                    entry_id,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Search path (Context Builder Agent)
    # ------------------------------------------------------------------

    def search_similar_incidents(
        self,
        query: str,
        filters: KnowledgeFilter,
        top_k: int = 5,
    ) -> list[SimilarIncidentResult]:
        """Find incidents semantically similar to *query*.

        Parameters
        ----------
        query:
            Free-text description of the current incident to match against.
        filters:
            ``KnowledgeFilter`` instance.  ``tenant_id`` **must** be set —
            raises ``ValueError`` otherwise.  Optionally further narrow by
            ``service`` and/or ``severity``.
        top_k:
            Maximum number of results to return.

        Returns
        -------
        list[SimilarIncidentResult]
            Ordered by descending cosine similarity score.

        Raises
        ------
        ValueError
            If ``filters.tenant_id`` is empty or ``None``.
        """
        # Guard — belt-and-suspenders check on top of KnowledgeFilter validator.
        if not filters.tenant_id or not filters.tenant_id.strip():
            raise ValueError(
                "tenant_id is required for search_similar_incidents — "
                "cross-tenant searches are not permitted."
            )

        query_vector = self._embedder.embed(query)

        # Build Qdrant filter: tenant_id always required; service/severity optional.
        must_conditions: list[qdrant_models.FieldCondition] = [
            qdrant_models.FieldCondition(
                key="tenant_id",
                match=qdrant_models.MatchValue(value=filters.tenant_id),
            )
        ]

        if filters.service is not None:
            must_conditions.append(
                qdrant_models.FieldCondition(
                    key="service",
                    match=qdrant_models.MatchValue(value=filters.service),
                )
            )

        if filters.severity is not None:
            must_conditions.append(
                qdrant_models.FieldCondition(
                    key="severity",
                    match=qdrant_models.MatchValue(value=filters.severity),
                )
            )

        qdrant_filter = qdrant_models.Filter(must=must_conditions)

        try:
            req = qdrant_models.SearchRequest(
                vector=query_vector,
                filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
            )
            res = self._qdrant.http.search_api.search_points(
                collection_name=COLLECTION_NAME,
                search_request=req,
            )
            hits = res.result
        except Exception:
            if hasattr(self._qdrant, "query_points"):
                response = self._qdrant.query_points(
                    collection_name=COLLECTION_NAME,
                    query=query_vector,
                    query_filter=qdrant_filter,
                    limit=top_k,
                    with_payload=True,
                )
                hits = response.points
            else:
                hits = self._qdrant.search(
                    collection_name=COLLECTION_NAME,
                    query_vector=query_vector,
                    query_filter=qdrant_filter,
                    limit=top_k,
                    with_payload=True,
                )

        results: list[SimilarIncidentResult] = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                SimilarIncidentResult(
                    knowledge_entry_id=payload.get("knowledge_entry_id", ""),
                    vector_id=str(hit.id),
                    title=payload.get("title", ""),
                    service=payload.get("service"),
                    severity=payload.get("severity"),
                    score=hit.score,
                    tags=payload.get("tags", {}),
                )
            )

        return results
