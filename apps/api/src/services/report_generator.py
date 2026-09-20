"""Deterministic Incident Report Generator for RISE.

Generates PDF and Markdown incident reports entirely from stored DB records
(Incident, RootCause, Evidence, ImpactAssessment, RemediationAction, AgentStepResult, AuditEvent).
Follows the zero-LLM-rederivation principle to ensure 100% audit accuracy and provenance.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    AgentStepResult,
    Approval,
    AuditEvent,
    Evidence,
    ExecutionLog,
    ImpactAssessment,
    Incident,
    RemediationAction,
    RootCause,
    Service,
    VerificationResult,
)
from schemas.agent_state import compute_risk_score


def build_incident_report_data(
    db: Session,
    tenant_id: uuid.UUID,
    incident_uuid: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """Query DB for all incident artifacts and compile deterministic report payload."""
    incident = db.execute(
        select(Incident).where(
            Incident.tenant_id == tenant_id,
            Incident.id == incident_uuid,
        )
    ).scalar_one_or_none()

    if not incident:
        return None

    # Service info
    service_name = "N/A"
    if incident.affected_service_id:
        svc = db.execute(
            select(Service).where(
                Service.tenant_id == tenant_id,
                Service.id == incident.affected_service_id,
            )
        ).scalar_one_or_none()
        if svc:
            service_name = svc.name

    # Root Cause & Evidence
    rc_row = db.execute(
        select(RootCause).where(
            RootCause.tenant_id == tenant_id,
            RootCause.incident_id == incident.id,
        ).order_by(RootCause.created_at.desc())
    ).scalars().first()

    evidence_items = []
    if rc_row:
        ev_rows = db.execute(
            select(Evidence).where(
                Evidence.tenant_id == tenant_id,
                Evidence.root_cause_id == rc_row.id,
            )
        ).scalars().all()
        for ev in ev_rows:
            evidence_items.append({
                "id": str(ev.id),
                "type": ev.type,
                "reference": ev.reference,
                "excerpt": ev.excerpt,
                "commit_sha": ev.commit_sha,
                "file_path": ev.file_path,
                "line_start": ev.line_start,
                "line_end": ev.line_end,
                "fetched_at": ev.fetched_at.isoformat() if ev.fetched_at else None,
            })

    # Impact Assessment
    ia_row = db.execute(
        select(ImpactAssessment).where(
            ImpactAssessment.tenant_id == tenant_id,
            ImpactAssessment.incident_id == incident.id,
        )
    ).scalars().first()

    blast_radius_services = []
    estimated_users = 0
    business_notes = ""
    risk_score = 0
    if ia_row:
        br = ia_row.blast_radius_services
        if isinstance(br, list):
            blast_radius_services = br
        elif isinstance(br, dict):
            blast_radius_services = br.get("services") or list(br.keys())
        estimated_users = ia_row.estimated_users_affected or 0
        business_notes = ia_row.business_impact_notes or ""
        risk_score = ia_row.risk_score or 0

    if risk_score <= 0:
        risk_score = compute_risk_score(
            severity=incident.severity,
            blast_radius_count=len(blast_radius_services),
            affected_users=estimated_users,
            criticality="high" if incident.severity == "SEV1" else "normal",
            confidence=rc_row.confidence if rc_row else 0.85,
        )

    # Remediation Action(s), Approvals & Execution Logs
    actions_data = []
    action_rows = db.execute(
        select(RemediationAction).where(
            RemediationAction.tenant_id == tenant_id,
            RemediationAction.incident_id == incident.id,
        ).order_by(RemediationAction.created_at.asc())
    ).scalars().all()

    for act in action_rows:
        approval = db.execute(
            select(Approval).where(
                Approval.tenant_id == tenant_id,
                Approval.action_id == act.id,
            ).order_by(Approval.decided_at.desc())
        ).scalars().first()

        exec_log = db.execute(
            select(ExecutionLog).where(
                ExecutionLog.tenant_id == tenant_id,
                ExecutionLog.action_id == act.id,
            ).order_by(ExecutionLog.executed_at.desc())
        ).scalars().first()

        plan = act.action_plan or {}
        is_sim = plan.get("is_simulated", False) or act.action_type in {
            "block_ip_address", "isolate_host", "revoke_session_token",
            "quarantine_file", "flag_for_soc_review", "unblock_ip_address",
            "reconnect_host", "restore_file", "restore_session_token",
        }

        actions_data.append({
            "id": str(act.id),
            "action_type": act.action_type,
            "risk_tier": act.risk_tier,
            "status": act.status,
            "is_simulated": is_sim,
            "plan_rationale": plan.get("plan_rationale", ""),
            "action_steps": plan.get("action_steps", []),
            "rollback_plan": plan.get("rollback_plan", []),
            "created_at": act.created_at.isoformat() if act.created_at else None,
            "approval": {
                "decision": approval.decision,
                "note": approval.note,
                "plan_hash": approval.plan_hash,
                "decided_at": approval.decided_at.isoformat(),
            } if approval else None,
            "execution": {
                "status": exec_log.status,
                "result": exec_log.result,
                "executed_at": exec_log.executed_at.isoformat(),
            } if exec_log else None,
        })

    # Verification Result
    verif = db.execute(
        select(VerificationResult).where(
            VerificationResult.tenant_id == tenant_id,
            VerificationResult.incident_id == incident.id,
        ).order_by(VerificationResult.checked_at.desc())
    ).scalars().first()

    verification_data = None
    if verif:
        verification_data = {
            "status": verif.status,
            "checks": verif.checks,
            "checked_at": verif.checked_at.isoformat() if verif.checked_at else None,
        }

    # Timeline & Audit Events
    audit_rows = db.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.incident_id == incident.id,
        ).order_by(AuditEvent.seq.asc())
    ).scalars().all()

    timeline = []
    for evt in audit_rows:
        timeline.append({
            "seq": evt.seq,
            "actor": evt.actor,
            "action": evt.action,
            "timestamp": evt.created_at.isoformat() if evt.created_at else None,
            "hash": evt.hash[:16] + "..." if evt.hash else None,
        })

    # Agent Step Results (Provenance details)
    agent_steps = db.execute(
        select(AgentStepResult).where(
            AgentStepResult.tenant_id == tenant_id,
        ).order_by(AgentStepResult.created_at.asc())
    ).scalars().all()

    agent_run_summary = []
    for step in agent_steps:
        agent_run_summary.append({
            "agent_name": step.agent_name,
            "confidence": step.confidence,
            "duration_ms": step.duration_ms,
            "created_at": step.created_at.isoformat() if step.created_at else None,
        })

    return {
        "incident": {
            "id": str(incident.id),
            "title": incident.title,
            "description": incident.description or "No description provided.",
            "severity": incident.severity,
            "status": incident.status,
            "affected_service": service_name,
            "created_at": incident.created_at.isoformat() if incident.created_at else None,
            "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        },
        "risk_score": risk_score,
        "root_cause": {
            "summary": rc_row.cause_summary if rc_row else "Root cause analysis not completed.",
            "confidence": rc_row.confidence if rc_row else 0.0,
        },
        "evidence": evidence_items,
        "impact": {
            "severity": ia_row.severity if ia_row else incident.severity,
            "blast_radius_services": blast_radius_services,
            "estimated_users_affected": estimated_users,
            "business_impact_notes": business_notes,
        },
        "actions": actions_data,
        "verification": verification_data,
        "timeline": timeline,
        "agent_runs": agent_run_summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_markdown_report(data: Dict[str, Any]) -> str:
    """Generate a clean, structured GitHub-Flavored Markdown report."""
    inc = data["incident"]
    rc = data["root_cause"]
    evidence = data.get("evidence", [])
    impact = data.get("impact", {})
    actions = data.get("actions", [])
    timeline = data.get("timeline", [])
    verif = data.get("verification")
    risk_score = data.get("risk_score", 0)

    lines: List[str] = []
    lines.append(f"# Incident Report: {inc['title']}")
    lines.append("")
    lines.append(f"**Generated:** {data.get('generated_at', '')} (UTC) • **Provenance:** Deterministic DB Record (Zero LLM Re-derivation)")
    lines.append("")

    # Executive Summary Table
    lines.append("## 1. Incident Overview")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| **Incident ID** | `{inc['id']}` |")
    lines.append(f"| **Severity** | `{inc['severity']}` |")
    lines.append(f"| **Status** | `{inc['status'].upper()}` |")
    lines.append(f"| **Affected Service** | `{inc['affected_service']}` |")
    lines.append(f"| **Deterministic Risk Score** | **{risk_score}/100** |")
    lines.append(f"| **Triggered At** | {inc['created_at']} |")
    lines.append(f"| **Last Updated** | {inc['updated_at']} |")
    if inc.get("resolved_at"):
        lines.append(f"| **Resolved At** | {inc['resolved_at']} |")
    lines.append("")
    lines.append(f"**Description:** {inc['description']}")
    lines.append("")

    # Root Cause & Cited Evidence
    lines.append("## 2. Root Cause Analysis & Evidence Provenance")
    lines.append("")
    lines.append(f"**Identified Cause:** {rc['summary']}")
    lines.append(f"**Confidence:** `{int(rc['confidence'] * 100)}%`")
    lines.append("")

    if evidence:
        lines.append("### Cited Grounded Evidence")
        lines.append("")
        for idx, ev in enumerate(evidence, start=1):
            lines.append(f"#### Evidence #{idx} — Type: `{ev['type']}`")
            if ev.get("file_path"):
                lines.append(f"- **File:** `{ev['file_path']}` (Lines: `{ev.get('line_start')}-{ev.get('line_end')}`)")
            if ev.get("commit_sha"):
                lines.append(f"- **Commit SHA:** `{ev['commit_sha']}`")
            if ev.get("reference"):
                lines.append(f"- **Reference:** {ev['reference']}")
            if ev.get("excerpt"):
                lines.append("```")
                lines.append(ev["excerpt"])
                lines.append("```")
            lines.append("")
    else:
        lines.append("*No specific code-level or log evidence items were recorded for this incident.*")
        lines.append("")

    # Impact Assessment
    lines.append("## 3. Impact & Blast Radius Assessment")
    lines.append("")
    lines.append(f"- **Evaluated Severity:** `{impact.get('severity', inc['severity'])}`")
    lines.append(f"- **Estimated Users Affected:** `{impact.get('estimated_users_affected', 0):,}`")
    lines.append(f"- **Blast Radius Services:** {', '.join(f'`{s}`' for s in impact.get('blast_radius_services', [])) or 'None'}")
    if impact.get("business_impact_notes"):
        lines.append(f"- **Business Impact Notes:** {impact['business_impact_notes']}")
    lines.append("")

    # Response & Remediation Actions
    lines.append("## 4. Remediation Plan & Execution Audit")
    lines.append("")
    if actions:
        for idx, act in enumerate(actions, start=1):
            sim_badge = " *(SIMULATED AUDITED NO-OP)*" if act.get("is_simulated") else ""
            lines.append(f"### Action #{idx}: `{act['action_type']}`{sim_badge}")
            lines.append(f"- **Risk Tier:** `{act['risk_tier'].upper()}`")
            lines.append(f"- **Status:** `{act['status'].upper()}`")
            if act.get("plan_rationale"):
                lines.append(f"- **Rationale:** {act['plan_rationale']}")

            if act.get("action_steps"):
                lines.append("- **Action Steps:**")
                for s_idx, step in enumerate(act["action_steps"], start=1):
                    lines.append(f"  {s_idx}. Tool: `{step.get('tool', 'unknown')}` — Params: `{step.get('params', {})}`")

            if act.get("rollback_plan"):
                lines.append("- **Rollback Plan:**")
                for r_idx, rb in enumerate(act["rollback_plan"], start=1):
                    lines.append(f"  {r_idx}. Tool: `{rb.get('tool', 'unknown')}` — Params: `{rb.get('params', {})}`")

            if act.get("approval"):
                appr = act["approval"]
                lines.append(f"- **Human Approval Decision:** `{appr['decision'].upper()}` at {appr['decided_at']}")
                if appr.get("note"):
                    lines.append(f"  - Note: {appr['note']}")
                lines.append(f"  - Plan SHA256 Hash: `{appr['plan_hash']}`")

            if act.get("execution"):
                ex = act["execution"]
                lines.append(f"- **Execution Result:** `{ex['status'].upper()}` at {ex['executed_at']}")
                if ex.get("result"):
                    lines.append(f"  - Output Summary: `{ex['result']}`")
            lines.append("")
    else:
        lines.append("*No remediation action plans were executed.*")
        lines.append("")

    # Verification
    if verif:
        lines.append("## 5. Automated Verification Status")
        lines.append("")
        lines.append(f"- **Verification Status:** `{verif['status'].upper()}` (Checked at: {verif.get('checked_at', 'N/A')})")
        if verif.get("checks"):
            lines.append(f"- **Checks Summary:** `{verif['checks']}`")
        lines.append("")

    # Audit Trail Timeline
    lines.append("## 6. Cryptographic Audit Trail Timeline")
    lines.append("")
    if timeline:
        lines.append("| Seq | Timestamp | Actor | Action | Integrity Hash |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for evt in timeline:
            lines.append(f"| {evt['seq']} | {evt['timestamp']} | `{evt['actor']}` | `{evt['action']}` | `{evt['hash']}` |")
        lines.append("")
    else:
        lines.append("*No timeline events recorded.*")
        lines.append("")

    lines.append("---")
    lines.append("*Report compiled deterministically by RISE Autonomous Incident Remediation System.*")
    return "\n".join(lines)


def generate_pdf_report(data: Dict[str, Any]) -> bytes:
    """Generate a clean, professional multi-page PDF report using ReportLab."""
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("PDF generation requires 'reportlab'. Please install reportlab to generate PDF incident reports.")
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    primary_color = colors.HexColor("#151121")
    accent_color = colors.HexColor("#8B5CF6")
    text_dark = colors.HexColor("#1E293B")
    text_muted = colors.HexColor("#64748B")
    bg_light = colors.HexColor("#F8FAFC")
    border_color = colors.HexColor("#E2E8F0")

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        textColor=primary_color,
        fontName="Helvetica-Bold",
        spaceAfter=4,
    )

    h2_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=12,
        leading=16,
        textColor=accent_color,
        fontName="Helvetica-Bold",
        spaceBefore=12,
        spaceAfter=6,
    )

    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=text_dark,
        fontName="Helvetica",
    )

    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=text_muted,
        fontName="Helvetica-Bold",
    )

    meta_val_style = ParagraphStyle(
        "MetaValue",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=text_dark,
        fontName="Helvetica",
    )

    code_style = ParagraphStyle(
        "ReportCode",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#0F172A"),
        fontName="Courier",
        spaceBefore=2,
        spaceAfter=2,
    )

    story = []

    inc = data["incident"]
    rc = data["root_cause"]
    evidence = data.get("evidence", [])
    impact = data.get("impact", {})
    actions = data.get("actions", [])
    timeline = data.get("timeline", [])
    risk_score = data.get("risk_score", 0)

    # ── Header ──
    story.append(Paragraph(f"RISE Incident Report: {inc['title']}", title_style))
    meta_sub = f"<b>Incident ID:</b> {inc['id']} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Generated:</b> {data.get('generated_at', '')[:19]} UTC &nbsp;&nbsp;|&nbsp;&nbsp; <b>Provenance:</b> Stored DB Record"
    story.append(Paragraph(meta_sub, body_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.5, color=accent_color, spaceAfter=8))

    # ── Overview Grid Table ──
    overview_data = [
        [
            Paragraph("Severity", meta_label_style),
            Paragraph(f"<b>{inc['severity']}</b>", meta_val_style),
            Paragraph("Status", meta_label_style),
            Paragraph(f"<b>{inc['status'].upper()}</b>", meta_val_style),
        ],
        [
            Paragraph("Affected Service", meta_label_style),
            Paragraph(inc["affected_service"] or "N/A", meta_val_style),
            Paragraph("Risk Score", meta_label_style),
            Paragraph(f"<b>{risk_score}/100</b>", meta_val_style),
        ],
        [
            Paragraph("Triggered At", meta_label_style),
            Paragraph(inc["created_at"] or "N/A", meta_val_style),
            Paragraph("Resolved At", meta_label_style),
            Paragraph(inc.get("resolved_at") or "In Progress", meta_val_style),
        ],
    ]
    t_overview = Table(overview_data, colWidths=[1.3 * inch, 2.2 * inch, 1.3 * inch, 2.2 * inch])
    t_overview.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg_light),
            ("BOX", (0, 0), (-1, -1), 1, border_color),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(t_overview)
    story.append(Spacer(1, 8))

    # ── Summary Description ──
    if inc.get("description"):
        story.append(Paragraph(f"<b>Incident Description:</b> {inc['description']}", body_style))
        story.append(Spacer(1, 6))

    # ── Root Cause & Confidence ──
    story.append(Paragraph("1. Root Cause Analysis", h2_style))
    rc_text = f"<b>Identified Cause:</b> {rc['summary']} (<b>Confidence:</b> {int(rc['confidence'] * 100)}%)"
    story.append(Paragraph(rc_text, body_style))
    story.append(Spacer(1, 6))

    # ── Cited Evidence ──
    if evidence:
        story.append(Paragraph("2. Cited Evidence Chain", h2_style))
        for idx, ev in enumerate(evidence, start=1):
            ev_desc = f"<b>#{idx} [{ev['type'].upper()}]:</b> "
            if ev.get("file_path"):
                ev_desc += f"<code>{ev['file_path']}</code> (Lines: {ev.get('line_start')}-{ev.get('line_end')}) "
            if ev.get("commit_sha"):
                ev_desc += f"• Commit: <code>{ev['commit_sha'][:8]}</code> "
            if ev.get("reference") and not ev.get("file_path"):
                ev_desc += f"{ev['reference']} "

            story.append(Paragraph(ev_desc, body_style))
            if ev.get("excerpt"):
                # Render snippet in a box
                exc_p = Paragraph(f"<font face='Courier' size='7'>{ev['excerpt'][:500]}</font>", code_style)
                t_box = Table([[exc_p]], colWidths=[7.0 * inch])
                t_box.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), bg_light),
                    ("BOX", (0, 0), (-1, -1), 0.5, border_color),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(t_box)
            story.append(Spacer(1, 4))

    # ── Impact Assessment ──
    story.append(Paragraph("3. Impact & Blast Radius Assessment", h2_style))
    impact_items = [
        f"<b>Severity Tier:</b> {impact.get('severity', inc['severity'])}",
        f"<b>Estimated Affected Users:</b> {impact.get('estimated_users_affected', 0):,}",
        f"<b>Blast Radius Services:</b> {', '.join(impact.get('blast_radius_services', [])) or 'None'}",
    ]
    if impact.get("business_impact_notes"):
        impact_items.append(f"<b>Business Notes:</b> {impact['business_impact_notes']}")
    story.append(Paragraph(" &nbsp;&bull;&nbsp; ".join(impact_items), body_style))
    story.append(Spacer(1, 6))

    # ── Response Actions ──
    story.append(Paragraph("4. Response Actions & Audit Verification", h2_style))
    if actions:
        for idx, act in enumerate(actions, start=1):
            sim_str = " <i>(Simulated Audited Action)</i>" if act.get("is_simulated") else ""
            act_header = f"<b>Action #{idx}:</b> <code>{act['action_type']}</code>{sim_str} &nbsp;|&nbsp; <b>Risk:</b> {act['risk_tier'].upper()} &nbsp;|&nbsp; <b>Status:</b> {act['status'].upper()}"
            story.append(Paragraph(act_header, body_style))

            if act.get("plan_rationale"):
                story.append(Paragraph(f"<b>Rationale:</b> {act['plan_rationale']}", body_style))

            if act.get("approval"):
                appr = act["approval"]
                story.append(Paragraph(
                    f"<b>Human Approval:</b> {appr['decision'].upper()} at {appr['decided_at'][:19]} UTC • Hash: <code>{appr['plan_hash'][:16]}...</code>",
                    body_style
                ))

            if act.get("execution"):
                ex = act["execution"]
                story.append(Paragraph(
                    f"<b>Execution Result:</b> {ex['status'].upper()} at {ex['executed_at'][:19]} UTC",
                    body_style
                ))
            story.append(Spacer(1, 4))
    else:
        story.append(Paragraph("<i>No automated remediation actions executed.</i>", body_style))

    story.append(Spacer(1, 6))

    # ── Audit Timeline ──
    if timeline:
        story.append(Paragraph("5. Audit Log Timeline", h2_style))
        table_rows = [
            [
                Paragraph("<b>Seq</b>", meta_label_style),
                Paragraph("<b>Timestamp</b>", meta_label_style),
                Paragraph("<b>Actor</b>", meta_label_style),
                Paragraph("<b>Action</b>", meta_label_style),
                Paragraph("<b>Audit Hash</b>", meta_label_style),
            ]
        ]
        for evt in timeline[:12]:  # Top 12 events to keep layout concise
            table_rows.append([
                Paragraph(str(evt["seq"]), meta_val_style),
                Paragraph((evt["timestamp"] or "")[:19], meta_val_style),
                Paragraph(evt["actor"], meta_val_style),
                Paragraph(evt["action"], meta_val_style),
                Paragraph(f"<code>{evt['hash']}</code>", meta_val_style),
            ])
        t_tl = Table(table_rows, colWidths=[0.5 * inch, 1.6 * inch, 1.3 * inch, 1.8 * inch, 1.8 * inch])
        t_tl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), bg_light),
            ("BOX", (0, 0), (-1, -1), 0.5, border_color),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t_tl)

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5, color=border_color, spaceAfter=6))
    story.append(Paragraph(
        "<font size='7' color='#64748B'>RISE Autonomous Incident Remediation • Deterministically Generated from Stored Cryptographic Audit Trail • Zero Runtime LLM Re-derivation</font>",
        body_style
    ))

    doc.build(story)
    return buffer.getvalue()
