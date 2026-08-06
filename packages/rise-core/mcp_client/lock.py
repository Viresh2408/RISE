"""Per-resource locking module using Redis (with in-memory fallback)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ResourceLockedException(Exception):
    """Raised when a resource is already locked by another remediation action."""

    def __init__(self, resource_id: str, message: Optional[str] = None):
        self.resource_id = resource_id
        self.code = "RESOURCE_LOCKED"
        self.status_code = 409
        super().__init__(message or f"Concurrent remediation lock held for resource '{resource_id}'")


# In-memory lock fallback registry for environments without real Redis
_IN_MEMORY_LOCKS: Dict[str, Dict[str, Any]] = {}


class ResourceLockManager:
    """Manages per-resource lock acquisition and release."""

    @staticmethod
    def acquire_lock(
        resource_id: str,
        ttl_seconds: int = 300,
        redis_client: Optional[Any] = None,
        owner_id: Optional[str] = None,
    ) -> str:
        """Acquire lock on resource_id. Raises ResourceLockedException if lock is held."""
        lock_token = owner_id or str(uuid.uuid4())
        lock_key = f"lock:resource:{resource_id}"

        # 1. Try real Redis if client provided
        if redis_client is not None:
            try:
                # SET key token NX EX ttl_seconds
                acquired = redis_client.set(lock_key, lock_token, nx=True, ex=ttl_seconds)
                if not acquired:
                    raise ResourceLockedException(resource_id)
                logger.info("Acquired Redis lock for resource '%s' (token: %s)", resource_id, lock_token)
                return lock_token
            except ResourceLockedException:
                raise
            except Exception as exc:
                logger.warning("Redis lock attempt failed (%s), using in-memory fallback", exc)

        # 2. In-memory lock fallback
        now = time.time()
        existing = _IN_MEMORY_LOCKS.get(resource_id)

        if existing:
            # Check if expired
            if existing["expires_at"] > now:
                if existing["token"] != lock_token:
                    raise ResourceLockedException(resource_id)
            else:
                # Lock expired, cleanup
                del _IN_MEMORY_LOCKS[resource_id]

        _IN_MEMORY_LOCKS[resource_id] = {
            "token": lock_token,
            "expires_at": now + ttl_seconds,
        }
        logger.info("Acquired in-memory lock for resource '%s' (token: %s)", resource_id, lock_token)
        return lock_token

    @staticmethod
    def release_lock(
        resource_id: str,
        lock_token: str,
        redis_client: Optional[Any] = None,
    ) -> None:
        """Release lock on resource_id if token matches."""
        lock_key = f"lock:resource:{resource_id}"

        if redis_client is not None:
            try:
                val = redis_client.get(lock_key)
                if val and (val == lock_token or (isinstance(val, bytes) and val.decode() == lock_token)):
                    redis_client.delete(lock_key)
                    logger.info("Released Redis lock for resource '%s'", resource_id)
            except Exception as exc:
                logger.warning("Failed to release Redis lock (%s)", exc)

        existing = _IN_MEMORY_LOCKS.get(resource_id)
        if existing and existing["token"] == lock_token:
            del _IN_MEMORY_LOCKS[resource_id]
            logger.info("Released in-memory lock for resource '%s'", resource_id)


def clear_all_in_memory_locks() -> None:
    """Clear all in-memory locks (helper for tests)."""
    _IN_MEMORY_LOCKS.clear()
