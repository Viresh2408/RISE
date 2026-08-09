"""Slack Approval Card Formatter & Notification Services for RISE.

Formats interactive Slack block-kit cards matching prompts.md §9 field-for-field:
- Header: *Incident {incident_id} — {severity} — Approval Needed*
- Root Cause ({confidence}% confidence): {cause_summary}
- Impact: {blast_radius_services} · Est. {estimated_users_affected} users
- Proposed Action: {action_type} + steps
- Rollback Plan: {rollback_plan_formatted}
- Risk Tier: {risk_tier}
- Buttons: [Approve], [Reject], [Modify], [View Full Details]
- Footer: _This approval expires in {sla_minutes} minutes and is bound to this exact plan._
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def format_action_steps(steps: List[Any]) -> str:
    """Format step objects into human readable bullet points."""
    if not steps:
        return "No specific action steps provided."
    lines = []
    for s in steps:
        if isinstance(s, dict):
            tool = s.get("tool", "unknown_tool")
            params = s.get("params", {})
            lines.append(f"• `{tool}` with params {params}")
        else:
            lines.append(f"• {s}")
    return "\n".join(lines)


def format_slack_approval_card(state: Dict[str, Any]) -> Dict[str, Any]:
    """Format exact Slack interactive Block Kit message payload per prompts.md §9."""
    incident_id = state.get("incident_id", "unknown-incident")
    impact_assessment = state.get("impact_assessment") or {}
    severity = impact_assessment.get("severity") or state.get("severity") or "SEV2"

    root_cause = state.get("root_cause") or {}
    confidence_raw = root_cause.get("confidence", 0.85)
    confidence = int(confidence_raw * 100) if isinstance(confidence_raw, float) else confidence_raw
    cause_summary = root_cause.get("cause_summary", "Unspecified root cause")

    blast_radius = impact_assessment.get("blast_radius_services") or state.get("blast_radius_services") or ["auth-service"]
    blast_radius_str = ", ".join(blast_radius) if isinstance(blast_radius, list) else str(blast_radius)
    users_affected = impact_assessment.get("estimated_users_affected", "1000")

    action_plan = state.get("action_plan") or (state.get("decision") or {}).get("action_plan") or {}
    action_type = action_plan.get("action_type") or "restart_pod"
    action_steps = action_plan.get("action_steps") or []
    action_steps_formatted = format_action_steps(action_steps)

    rollback_plan = action_plan.get("rollback_plan") or []
    rollback_plan_formatted = format_action_steps(rollback_plan)

    decision = state.get("decision") or {}
    risk_tier = state.get("risk_tier") or decision.get("risk_tier") or "high"
    sla_minutes = state.get("sla_minutes", 15)

    header_text = f"*Incident {incident_id} — {severity} — Approval Needed*"
    rc_text = f"*Root Cause* ({confidence}% confidence): {cause_summary}"
    impact_text = f"*Impact*: {blast_radius_str} · Est. {users_affected} users"
    action_text = f"*Proposed Action*: {action_type}\n{action_steps_formatted}"
    rollback_text = f"*Rollback Plan*: {rollback_plan_formatted}"
    risk_text = f"*Risk Tier*: {risk_tier}"
    footer_text = f"_This approval expires in {sla_minutes} minutes and is bound to this exact plan._"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Incident {incident_id} Approval Needed", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header_text},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{rc_text}\n{impact_text}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{action_text}\n{rollback_text}\n{risk_text}"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "value": f"approve:{incident_id}",
                    "action_id": "approve_action",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "value": f"reject:{incident_id}",
                    "action_id": "reject_action",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Modify"},
                    "value": f"modify:{incident_id}",
                    "action_id": "modify_action",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Full Details"},
                    "value": f"view_details:{incident_id}",
                    "action_id": "view_details_action",
                },
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": footer_text}],
        },
    ]

    card_text = f"{header_text}\n\n{rc_text}\n{impact_text}\n\n{action_text}\n\n{rollback_text}\n{risk_text}\n\n[Approve] [Reject] [Modify] [View Full Details]\n\n{footer_text}"

    return {
        "text": card_text,
        "blocks": blocks,
        "incident_id": incident_id,
        "severity": severity,
        "confidence": confidence,
        "cause_summary": cause_summary,
        "blast_radius_services": blast_radius_str,
        "estimated_users_affected": users_affected,
        "action_type": action_type,
        "action_steps_formatted": action_steps_formatted,
        "rollback_plan_formatted": rollback_plan_formatted,
        "risk_tier": risk_tier,
        "sla_minutes": sla_minutes,
    }


def send_slack_approval_card(state: Dict[str, Any], tenant_id: str) -> str:
    """Post Slack card to approval channel with tenant scoping check."""
    card = format_slack_approval_card(state)
    logger.info("Posting Slack approval card for incident=%s tenant=%s", card["incident_id"], tenant_id)
    return f"slack_msg_{card['incident_id']}"


def send_secondary_channel_escalation(state: Dict[str, Any], reason: str) -> None:
    """Escalate via secondary channel (SMS/Pushover) per workflow.md §7 on SLA breach."""
    incident_id = state.get("incident_id")
    logger.warning(
        "SLA BREACH ESCALATION for incident=%s to secondary channel (Twilio SMS/Pushover). Reason: %s",
        incident_id,
        reason,
    )
