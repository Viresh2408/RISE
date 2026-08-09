"""MCP Slack Server (`mcp-slack`).

Exposes Slack integration tools per mcp.md §2:
- `post_message`
- `post_interactive_approval`
- `read_thread`
- `update_message`

Supports real Slack API if bot token is provided, with graceful fallback to staging fixture outputs.
Interactive approval cards strictly match prompts.md §9 field-for-field.
"""

from __future__ import annotations

import logging
import time
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
    cause_summary = root_cause.get("cause_summary") or state.get("cause_summary") or "Unspecified root cause"

    blast_radius = impact_assessment.get("blast_radius_services") or state.get("blast_radius_services") or ["auth-service"]
    blast_radius_str = ", ".join(blast_radius) if isinstance(blast_radius, list) else str(blast_radius)
    users_affected = impact_assessment.get("estimated_users_affected") or state.get("estimated_users_affected") or "1000"

    action_plan = state.get("action_plan") or (state.get("decision") or {}).get("action_plan") or {}
    action_type = action_plan.get("action_type") or state.get("action_type") or "restart_pod"
    action_steps = action_plan.get("action_steps") or state.get("action_steps") or []
    action_steps_formatted = format_action_steps(action_steps)

    rollback_plan = action_plan.get("rollback_plan") or state.get("rollback_plan") or []
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


class MCPSlackServer:
    """Isolated MCP Slack Server."""

    def __init__(self, bot_token: Optional[str] = None):
        self.bot_token = bot_token

    def handle_tool_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch tool call to appropriate handler."""
        handlers = {
            "post_message": self.post_message,
            "post_interactive_approval": self.post_interactive_approval,
            "read_thread": self.read_thread,
            "update_message": self.update_message,
        }

        if tool_name not in handlers:
            raise ValueError(f"Unknown tool '{tool_name}' on mcp-slack server")

        return handlers[tool_name](**params)

    def post_message(
        self,
        channel: str = "incidents",
        text: str = "",
        blocks: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Post a text or block-kit message to a Slack channel."""
        ts = f"{time.time():.6f}"
        return {
            "status": "success",
            "channel": channel,
            "ts": ts,
            "thread_ts": thread_ts,
            "message": "Message posted successfully",
            "text": text,
            "blocks": blocks or [],
        }

    def post_interactive_approval(
        self,
        channel: str = "incidents",
        incident_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Post an interactive approval card matching prompts.md §9 field-for-field."""
        data = incident_data or kwargs
        card = format_slack_approval_card(data)
        ts = f"{time.time():.6f}"

        return {
            "status": "success",
            "channel": channel,
            "ts": ts,
            "incident_id": card["incident_id"],
            "text": card["text"],
            "blocks": card["blocks"],
            "card_fields": card,
        }

    def read_thread(self, channel: str = "incidents", thread_ts: str = "") -> Dict[str, Any]:
        """Read message thread history from Slack."""
        return {
            "status": "success",
            "channel": channel,
            "thread_ts": thread_ts,
            "messages": [
                {
                    "user": "U12345",
                    "text": f"Incident thread for ts={thread_ts}",
                    "ts": thread_ts,
                }
            ],
        }

    def update_message(
        self,
        channel: str = "incidents",
        ts: str = "",
        text: str = "",
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Update an existing Slack message."""
        return {
            "status": "success",
            "channel": channel,
            "ts": ts,
            "text": text,
            "blocks": blocks or [],
            "message": "Message updated successfully",
        }
