"""Redis-backed deduplication for the RISE ingestion pipeline.

When two alerts about the same resource arrive within the dedup window (default
30 minutes) only the first creates a new ``Incident`` row.  The second is
acknowledged (200) but returns the existing ``incident_id`` and
``deduplicated=true``.

This implements the "Ingest & Correlate" step from workflow.md §1.2:
    "deduplicates against Alertmanager's existing grouping, and checks Redis
    for an already-open incident on the same resource."

Redis key layout
----------------
``dedup:incident:{resource_id}``  →  incident_id (UUID string)
TTL: ``DEDUP_WINDOW_SECONDS`` (default 1800 = 30 min).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEDUP_KEY_PREFIX = "dedup:incident:"
DEDUP_WINDOW_SECONDS: int = int(os.environ.get("DEDUP_WINDOW_SECONDS", "1800"))


def _key(resource_id: str) -> str:
    return f"{_DEDUP_KEY_PREFIX}{resource_id}"


def check_dedup(redis_client: Any, resource_id: str) -> Optional[str]:
    """Return the existing incident_id if a dedup key is active, else None.

    Parameters
    ----------
    redis_client:
        A connected ``redis.Redis`` client (or compatible mock in tests).
    resource_id:
        The normalized resource identifier from the ``IncidentEvent``.

    Returns
    -------
    str | None
        The existing incident UUID string if within the dedup window, else None.
    """
    try:
        val = redis_client.get(_key(resource_id))
        if val is None:
            return None
        return val.decode("utf-8") if isinstance(val, bytes) else str(val)
    except Exception as exc:  # noqa: BLE001
        # Redis unavailable — fail open (create a new incident rather than block).
        logger.error("Dedup Redis GET failed for resource_id=%r: %s", resource_id, exc)
        return None


def register_dedup(
    redis_client: Any,
    resource_id: str,
    incident_id: str,
    ttl: int = DEDUP_WINDOW_SECONDS,
) -> None:
    """Register a new incident in the dedup window.

    Parameters
    ----------
    redis_client:
        A connected ``redis.Redis`` client (or compatible mock in tests).
    resource_id:
        The normalized resource identifier.
    incident_id:
        The UUID string of the newly created Incident row.
    ttl:
        Window duration in seconds (default: ``DEDUP_WINDOW_SECONDS``).
    """
    try:
        redis_client.setex(_key(resource_id), ttl, incident_id)
    except Exception as exc:  # noqa: BLE001
        # Redis unavailable — log and continue; the worst case is a duplicate
        # incident created within the window, which is recoverable.
        logger.error(
            "Dedup Redis SETEX failed for resource_id=%r incident_id=%s: %s",
            resource_id,
            incident_id,
            exc,
        )
