"""Qdrant client singleton for the knowledge service.

Reads connection settings from environment variables so no config object needs
to be threaded through callers:

    QDRANT_URL      — full URL, e.g. ``http://localhost:6333``  (default)
    QDRANT_API_KEY  — optional; omit for unauthenticated local dev
"""

from __future__ import annotations

import os
from functools import lru_cache

from qdrant_client import QdrantClient


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """Return a cached Qdrant client configured from environment variables.

    The cache is process-scoped.  In tests that need a fresh client (e.g. after
    monkey-patching env vars) call ``get_qdrant_client.cache_clear()`` first.
    """
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    api_key = os.getenv("QDRANT_API_KEY") or None  # empty string → None
    timeout = float(os.getenv("QDRANT_TIMEOUT", "1.0"))

    return QdrantClient(url=url, api_key=api_key, timeout=timeout)

