"""Single-use Approval locking and decision tracking service for RISE.

Enforces idempotency and prevents double execution of approval/rejection/modification requests
per database-design.md single-use approval semantics.
Handles concurrent double-clicks and race conditions between Slack webhooks and API dashboard calls.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Fallback sets for local testing / non-Redis environments
_DECIDED_APPROVALS: set[str] = set()
_ACTIVE_LOCKS: set[str] = set()


class AlreadyDecidedError(ValueError):
    """Raised when an action approval has already been decided."""

    def __init__(self, action_id: str):
        super().__init__(f"Approval for action {action_id} has already been decided.")
        self.code = "ALREADY_DECIDED"
        self.status_code = 409


class ConcurrentApprovalError(ValueError):
    """Raised when another request is currently processing this approval."""

    def __init__(self, action_id: str):
        super().__init__(f"Approval for action {action_id} is currently being processed.")
        self.code = "CONCURRENT_APPROVAL"
        self.status_code = 409


def acquire_single_use_approval_lock(
    action_id: str, redis_client: Optional[Any] = None
) -> bool:
    """Acquire single-use lock for approval processing."""
    lock_key = f"approval_lock:{action_id}"

    if redis_client is not None:
        try:
            # Atomic SETNX with 60s TTL
            acquired = redis_client.set(lock_key, "locked", nx=True, ex=60)
            return bool(acquired)
        except Exception as exc:
            logger.warning("Redis lock error: %s", exc)

    if lock_key in _ACTIVE_LOCKS:
        return False
    _ACTIVE_LOCKS.add(lock_key)
    return True


def release_single_use_approval_lock(
    action_id: str, redis_client: Optional[Any] = None
) -> None:
    """Release single-use lock."""
    lock_key = f"approval_lock:{action_id}"
    if redis_client is not None:
        try:
            redis_client.delete(lock_key)
        except Exception:
            pass
    _ACTIVE_LOCKS.discard(lock_key)


def is_approval_decided(action_id: str, redis_client: Optional[Any] = None) -> bool:
    """Check if approval has already been decided."""
    key = f"approval_decided:{action_id}"
    if redis_client is not None:
        try:
            val = redis_client.get(key)
            if val is not None:
                return True
        except Exception as exc:
            logger.warning("Redis read error: %s", exc)

    return action_id in _DECIDED_APPROVALS


def mark_approval_decided(
    action_id: str, decision: str, redis_client: Optional[Any] = None
) -> None:
    """Mark an approval as decided (single-use semantics)."""
    key = f"approval_decided:{action_id}"
    if redis_client is not None:
        try:
            redis_client.set(key, decision, ex=86400)
        except Exception as exc:
            logger.warning("Redis write error: %s", exc)

    _DECIDED_APPROVALS.add(action_id)


def reset_approval_locks_for_testing() -> None:
    """Clear memory sets for tests."""
    _DECIDED_APPROVALS.clear()
    _ACTIVE_LOCKS.clear()
