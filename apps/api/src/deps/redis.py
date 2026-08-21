# [RISE Autonomous Patch - 2026-08-21 01:25:30Z] Remediation for: Redis Connection Churn & Missing ConnectionPool in api-gateway
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


_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_REDIS_POOL = None if redis is None else redis.ConnectionPool.from_url(_REDIS_URL, max_connections=50)


def get_redis_client() -> Generator[Any, None, None]:
    """FastAPI dependency: yield a redis.Redis client, close on teardown."""
    if redis is None:
        yield None
        return
    client = redis.Redis(connection_pool=_REDIS_POOL, decode_responses=False)
    try:
        yield client
    finally:
        client.close()
