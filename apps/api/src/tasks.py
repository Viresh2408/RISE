"""Celery Beat tasks for RISE API.

Includes periodic SLA timeout check task: `check_approval_sla_timeout_task`.
Scans pending approvals past SLA expiration and fires secondary channel escalation per workflow.md §7.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from apps.agents.src.services.slack_card import send_secondary_channel_escalation

logger = logging.getLogger(__name__)

# Basic Celery app definition with fallback if celery package unavailable
try:
    from celery import Celery
    celery_app = Celery("rise_tasks", broker="redis://localhost:6379/0")
    celery_app.conf.beat_schedule = {
        "check-approval-sla-timeout-every-60s": {
            "task": "apps.api.src.tasks.check_approval_sla_timeout_task",
            "schedule": 60.0,
        },
    }
except Exception:
    celery_app = None


def evaluate_sla_timeouts(pending_approvals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Scan pending approvals and return those that breached SLA timeout."""
    escalated = []
    now = datetime.now(timezone.utc)

    for approval in pending_approvals:
        created_at = approval.get("requested_at") or approval.get("created_at")
        sla_minutes = approval.get("sla_minutes", 15)

        if isinstance(created_at, str):
            try:
                created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_dt = now
        elif isinstance(created_at, datetime):
            created_dt = created_at
        else:
            created_dt = now

        elapsed_mins = (now - created_dt).total_seconds() / 60.0
        if elapsed_mins >= sla_minutes and not approval.get("escalated"):
            approval["escalated"] = True
            approval["escalated_at"] = now.isoformat()
            send_secondary_channel_escalation(
                approval, reason=f"Approval SLA of {sla_minutes}m breached (elapsed: {elapsed_mins:.1f}m)"
            )
            escalated.append(approval)

    return escalated


def check_approval_sla_timeout_task_impl(db_session: Optional[Any] = None) -> int:
    """Core logic for checking approval SLA timeouts."""
    logger.info("Running periodic Celery task: check_approval_sla_timeout_task")
    pending: List[Dict[str, Any]] = []

    if db_session is not None:
        try:
            from db.models import Incident, RemediationAction
            rows = (
                db_session.query(RemediationAction)
                .filter(RemediationAction.status == "pending_approval")
                .all()
            )
            for r in rows:
                pending.append({
                    "incident_id": str(r.incident_id),
                    "action_id": str(r.id),
                    "requested_at": r.created_at,
                    "sla_minutes": 15,
                })
        except Exception as exc:
            logger.warning("Failed querying pending approvals from DB: %s", exc)

    escalated = evaluate_sla_timeouts(pending)
    return len(escalated)


if celery_app:
    @celery_app.task(name="apps.api.src.tasks.check_approval_sla_timeout_task")
    def check_approval_sla_timeout_task() -> int:
        return check_approval_sla_timeout_task_impl()
else:
    def check_approval_sla_timeout_task() -> int:
        return check_approval_sla_timeout_task_impl()
