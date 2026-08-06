"""Dead-Letter Queue (DLQ) helper for the RISE ingestion pipeline.

Malformed webhook payloads (failed JSON parse, failed Pydantic validation of
LLM output) are written here instead of crashing the service.  The stream is
consumed by an ops dashboard for human review and retry.

Stream: ``stream:events:dlq``  (configurable via ``DLQ_REDIS_STREAM`` env var)

DLQ entry fields
----------------
``source``        — webhook source (github, cloudwatch, …)
``raw_body_b64``  — base64-encoded raw request body (unredacted)
``reason``        — short machine-readable reason code
``error``         — full error detail string
``timestamp``     — ISO-8601 UTC write time

NOTE (security / access control): DLQ entries contain **unredacted raw webhook
payloads** because the ingestion pipeline failed before sanitization could run.
Any API endpoint or dashboard that reads DLQ contents MUST enforce ``admin``
role — treat DLQ data as untrusted and potentially attacker-crafted.
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DLQ_STREAM = os.environ.get("DLQ_REDIS_STREAM", "stream:events:dlq")
EVENTS_STREAM = os.environ.get("EVENTS_REDIS_STREAM", "stream:events")


def send_to_dlq(
    redis_client: Any,
    *,
    source: str,
    raw_body: bytes,
    reason: str,
    error_detail: str,
) -> None:
    """Write a failed ingestion event to the dead-letter queue.

    Parameters
    ----------
    redis_client:
        A connected ``redis.Redis`` client (or compatible mock in tests).
    source:
        The webhook source identifier (e.g. ``"github"``).
    raw_body:
        The raw request body bytes, base64-encoded before storing.
    reason:
        Short machine-readable reason code, e.g. ``"json_parse_error"``,
        ``"llm_schema_validation_failed"``, ``"unknown_integration_source"``.
    error_detail:
        Full error string for ops debugging.
    """
    entry = {
        "source": source,
        "raw_body_b64": base64.b64encode(raw_body).decode("ascii"),
        "reason": reason,
        "error": error_detail,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        redis_client.xadd(DLQ_STREAM, entry)
        logger.warning(
            "Ingestion event sent to DLQ source=%s reason=%s", source, reason
        )
    except Exception as exc:  # noqa: BLE001
        # DLQ write failure must not crash the service — log and continue.
        logger.error(
            "Failed to write to DLQ stream=%s source=%s: %s", DLQ_STREAM, source, exc
        )


def publish_event(
    redis_client: Any,
    *,
    incident_id: str,
    tenant_id: str,
    source: str,
    event_type: str,
    resource_id: str,
    severity_hint: str,
) -> None:
    """Publish a successfully ingested event to the main event bus.

    Downstream services (Context Builder Agent Celery worker) consume from
    this stream via consumer groups.
    """
    entry = {
        "incident_id": incident_id,
        "tenant_id": tenant_id,
        "source": source,
        "event_type": event_type,
        "resource_id": resource_id,
        "severity_hint": severity_hint,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        redis_client.xadd(EVENTS_STREAM, entry)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to publish event to stream=%s incident_id=%s: %s",
            EVENTS_STREAM,
            incident_id,
            exc,
        )
