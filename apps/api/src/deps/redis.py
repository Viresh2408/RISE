"""Redis client dependency for FastAPI.

Provides a ``get_redis_client()`` dependency that can be overridden in tests
via ``app.dependency_overrides``.

Environment variable: ``REDIS_URL`` (default: ``redis://localhost:6379/0``).
"""

from __future__ import annotations

import os
from typing import Any, Generator

try:
    import redis
except ImportError:
    redis = None  # type: ignore


def get_redis_client() -> Generator[Any, None, None]:
    """FastAPI dependency: yield a redis.Redis client, close on teardown."""
    if redis is None:
        yield None
        return
    client = redis.from_url(_REDIS_URL, decode_responses=False)
    try:
        yield client
    finally:
        client.close()
