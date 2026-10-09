"""Per-resource locking module using Redis (with in-memory fallback)."""

from __future__ import annotations

import logging
import json
import time
import uuid
from threading import RLock
from typing import Any, Dict, Optional
from db.runtime import allows_local_fallbacks

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
_MEMORY_MUTEX = RLock()


class ResourceLockUnavailableError(RuntimeError):
    code = "REDIS_UNAVAILABLE"
    status_code = 503


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
        # The owner identifies the plan caller; a distinct nonce identifies this
        # particular lease. A stale release must not delete a successor lease
        # merely because the same incident reacquired the resource after expiry.
        lock_token = str(uuid.uuid4())
        owner = owner_id or lock_token
        lease = json.dumps({"owner": owner, "token": lock_token}, sort_keys=True)
        lock_key = f"lock:resource:{resource_id}"
        if redis_client is None and not allows_local_fallbacks():
            raise ResourceLockUnavailableError("Distributed Redis locking is required in deployed environments")

        # 1. Try real Redis if client provided
        if redis_client is not None:
            try:
                # SET key token NX EX ttl_seconds
                acquired = redis_client.set(lock_key, lease, nx=True, ex=ttl_seconds)
                if not acquired:
                    raise ResourceLockedException(resource_id)
                logger.info("Acquired Redis lock for resource '%s' (token: %s)", resource_id, lock_token)
                return lock_token
            except ResourceLockedException:
                raise
            except Exception as exc:
                if not allows_local_fallbacks():
                    raise ResourceLockUnavailableError("Redis resource lock failed") from exc
                logger.warning("Redis lock attempt failed (%s), using in-memory fallback", exc)

        # 2. In-memory lock fallback
        with _MEMORY_MUTEX:
            now = time.time()
            existing = _IN_MEMORY_LOCKS.get(resource_id)
            if existing and existing["expires_at"] > now:
                raise ResourceLockedException(resource_id)
            _IN_MEMORY_LOCKS[resource_id] = {
                "token": lock_token,
                "owner": owner,
                "expires_at": now + ttl_seconds,
            }
        logger.info("Acquired in-memory lock for resource '%s' (token: %s)", resource_id, lock_token)
        return lock_token

    @staticmethod
    def get_lock_owner(
        resource_id: str,
        redis_client: Optional[Any] = None,
    ) -> Optional[str]:
        """Return the current lock owner/token for resource_id, or None if unlocked.

        Non-destructive read used for defense-in-depth conflict checks (e.g. in the MCP
        gateway) — it never acquires, releases, or mutates the lock.
        """
        lock_key = f"lock:resource:{resource_id}"
        if redis_client is None and not allows_local_fallbacks():
            raise ResourceLockUnavailableError("Redis lock ownership cannot be verified")

        if redis_client is not None:
            try:
                val = redis_client.get(lock_key)
                if val is None:
                    return None
                value = val.decode() if isinstance(val, bytes) else str(val)
                try:
                    lease = json.loads(value)
                except (TypeError, ValueError):
                    return value  # A lease issued by the previous plain-token implementation.
                if isinstance(lease, dict) and isinstance(lease.get("owner"), str):
                    return lease["owner"]
                return value
            except Exception as exc:
                if not allows_local_fallbacks():
                    raise ResourceLockUnavailableError("Redis lock ownership check failed") from exc
                logger.warning("Failed to read Redis lock owner (%s), using in-memory fallback", exc)

        with _MEMORY_MUTEX:
            existing = _IN_MEMORY_LOCKS.get(resource_id)
            if existing and existing["expires_at"] > time.time():
                return existing.get("owner", existing["token"])
        return None

    @staticmethod
    def release_lock(
        resource_id: str,
        lock_token: str,
        redis_client: Optional[Any] = None,
    ) -> None:
        """Release lock on resource_id if token matches."""
        lock_key = f"lock:resource:{resource_id}"
        if redis_client is None and not allows_local_fallbacks():
            raise ResourceLockUnavailableError("Distributed Redis lock release is required in deployed environments")

        if redis_client is not None:
            try:
                redis_client.eval(
                    "local value = redis.call('GET', KEYS[1]); if not value then return 0 end; "
                    "local ok, lease = pcall(cjson.decode, value); "
                    "if ok and type(lease) == 'table' then "
                    "if lease.token == ARGV[1] then return redis.call('DEL', KEYS[1]) end "
                    "elseif value == ARGV[1] then return redis.call('DEL', KEYS[1]) end; return 0",
                    1, lock_key, lock_token,
                )
            except Exception as exc:
                if not allows_local_fallbacks():
                    raise ResourceLockUnavailableError("Redis resource lock release failed") from exc
                logger.warning("Failed to release Redis lock (%s)", exc)

        with _MEMORY_MUTEX:
            existing = _IN_MEMORY_LOCKS.get(resource_id)
            if existing and existing["token"] == lock_token:
                del _IN_MEMORY_LOCKS[resource_id]
                logger.info("Released in-memory lock for resource '%s'", resource_id)


def clear_all_in_memory_locks() -> None:
    """Clear all in-memory locks (helper for tests)."""
    with _MEMORY_MUTEX:
        _IN_MEMORY_LOCKS.clear()
