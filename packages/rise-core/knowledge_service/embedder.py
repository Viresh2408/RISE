"""Embedder implementations for the knowledge service.

Design
------
``EmbedderProtocol`` is a ``typing.Protocol`` so callers can type-hint against the
interface without importing any concrete implementation.  Two implementations are
provided:

``SentenceTransformerEmbedder`` (default)
    Uses ``sentence-transformers/all-MiniLM-L6-v2`` (384-dim, cosine).
    - Fully offline — no LLM API call, no network dependency in tests.
    - Deterministic output for the same input string, which makes test assertions
      on similarity scores reproducible.
    - Matches the ``incidents_v1`` Qdrant collection's declared vector dimension (384).

``LLMGatewayEmbedder`` (stub — production wiring)
    Placeholder for future wiring to the LLM Gateway when embedding quality becomes
    a measurable bottleneck (re-evaluate after the Similarity Engine ablation study).
    The collection would need to be versioned to ``incidents_v2`` with a new vector
    dimension if the model changes.

Both return ``list[float]`` of the model's native output dimension.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class EmbedderProtocol(Protocol):
    """Structural interface for text embedders used by KnowledgeService."""

    @property
    def vector_size(self) -> int:
        """Dimension of the produced embedding vectors."""
        ...

    def embed(self, text: str) -> list[float]:
        """Embed *text* and return a unit-normalised float vector."""
        ...


class SentenceTransformerEmbedder:
    """Offline embedder backed by ``sentence-transformers/all-MiniLM-L6-v2``.

    Produces 384-dimensional cosine-normalised vectors.  The model is downloaded
    once on first use and then cached by the ``sentence_transformers`` library.

    Parameters
    ----------
    model_name:
        Hugging Face model identifier.  Override only in tests that need a
        different dimension.
    """

    _MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer  # lazy import

        self._model = SentenceTransformer(model_name or self._MODEL_NAME)
        self._vector_size: int = self._model.get_sentence_embedding_dimension()

    @property
    def vector_size(self) -> int:
        return self._vector_size

    def embed(self, text: str) -> list[float]:
        """Return a normalised 384-dim embedding for *text*."""
        vector: np.ndarray = self._model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vector.tolist()


class LLMGatewayEmbedder:
    """Stub — future wiring to the RISE LLM Gateway for production embeddings.

    NOT YET IMPLEMENTED.  Raise ``NotImplementedError`` until the ablation study
    (Similarity Engine on/off) shows that ``all-MiniLM-L6-v2`` is a bottleneck.
    If a higher-quality model is adopted, create collection ``incidents_v2`` with
    the appropriate vector dimension and run the background re-embedding job before
    cutting over (see database-design.md §8).
    """

    @property
    def vector_size(self) -> int:
        raise NotImplementedError("LLMGatewayEmbedder is not yet wired.")

    def embed(self, text: str) -> list[float]:  # noqa: ARG002
        raise NotImplementedError("LLMGatewayEmbedder is not yet wired.")
