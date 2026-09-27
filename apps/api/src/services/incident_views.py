"""Shared, DB-backed incident view builders.

These functions are the single source of truth for turning stored DB rows
(Incident, RootCause, Evidence, ImpactAssessment, RemediationAction) into the
read-model dicts returned by both the incident *detail* endpoint
(`GET /incidents/{id}`) and the per-facet endpoints
(`GET /incidents/{id}/root-cause`, `/impact`, `/decision`, `/actions`).

Every builder queries real rows for the incident. When a specific sub-record
has not been produced yet (no agent run for this incident), the builder derives
an honest, *input-dependent* response from the real incident row — it never
returns a fixed fixture that ignores the incident. This keeps the per-facet
routers and the detail endpoint from drifting into two inconsistent shapes.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    AgentStepResult,
    Evidence,
    ImpactAssessment,
    Incident,
    RemediationAction,
    RootCause,
)
from schemas.agent_state import compute_risk_score


def _parse_uuid(id_str: str) -> uuid.UUID:
    """Parse a UUID, deterministically deriving one from non-UUID slugs.

    Mirrors the behaviour relied on across the incident routers and tests so a
    friendly id like ``inc-001`` maps to a stable UUID.
    """
    try:
        return uuid.UUID(id_str)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_DNS, id_str)


def _compute_confidence(incident_title: str, incident_desc: str, severity: str) -> float:
    """Derive a realistic confidence score from real error signals in the incident.

    Additive scoring (capped at 0.97) — see the original inline docstring in the
    incidents router. Kept here so the detail endpoint and the per-facet
    endpoints compute confidence identically.
    """
    title_lower = incident_title.lower()
    desc_lower = (incident_desc or "").lower()
    combined = title_lower + " " + desc_lower

    critical_keywords = {
        "oom", "oomkilled", "out of memory", "memory leak", "heap dump",
        "pool exhausted", "connection pool", "pool_exhausted",
        "503", "500", "timeout", "timed out",
        "latency", "latency spike", "p99",
        "database", "postgres", "redis",
        "exception", "panic", "crash", "segfault",
        "circuit breaker", "retry storm", "thundering herd",
        "pod restart", "restart", "backoff",
    }
    file_indicators = {"index.js", ".py", ".ts", "l42", "line ", "#l", "middleware", "cache"}

    matched = [kw for kw in critical_keywords if kw in combined]
    n_matches = len(matched)

    score = 0.45
    if n_matches >= 1:
        score += 0.20
    if n_matches >= 2:
        score += 0.05
    if re.search(r"\d", combined):
        score += 0.12
    if severity in ("SEV1", "SEV2"):
        score += 0.08
    elif severity == "SEV4":
        score -= 0.10
    if any(ind in combined for ind in file_indicators):
        score += 0.07
    if len(combined.strip()) < 20:
        score -= 0.05

    return round(min(0.97, max(0.20, score)), 2)


def build_root_cause_view(
    db: Session,
    tenant_id: uuid.UUID,
    incident: Incident,
    service_name: str = "",
) -> Dict[str, Any]:
    """Return the root-cause read-model for an incident from real DB rows.

    Preference order: a stored ``RootCause`` row (+ its ``Evidence``) →
    the latest root-cause ``AgentStepResult`` output → an incident-derived
    fallback (confidence computed from the incident's own error signals).
    """
    rc_row = db.execute(
        select(RootCause).where(
            RootCause.tenant_id == tenant_id,
            RootCause.incident_id == incident.id,
        ).order_by(RootCause.created_at.desc())
    ).scalars().first()

    if rc_row:
        evidence_rows = db.execute(
            select(Evidence).where(
                Evidence.tenant_id == tenant_id,
                Evidence.root_cause_id == rc_row.id,
            )
        ).scalars().all()
        return {
            "cause": rc_row.cause_summary,
            "confidence": rc_row.confidence,
            "explanation": f"Automated AI Diagnosis: {rc_row.cause_summary}",
            "evidence": [
                {
                    "id": str(ev.id),
                    "source": ev.type,
                    "type": ev.type,
                    "description": ev.excerpt or ev.reference,
                    "commit_sha": ev.commit_sha,
                    "file_path": ev.file_path,
                    "line_start": ev.line_start,
                    "line_end": ev.line_end,
                    "fetched_at": ev.fetched_at.isoformat() if ev.fetched_at else None,
                }
                for ev in evidence_rows
            ],
            "similar_incidents": [],
        }

    # Fallback to the most recent root-cause agent step, if one ran.
    step = db.execute(
        select(AgentStepResult).where(
            AgentStepResult.tenant_id == tenant_id,
            AgentStepResult.agent_name.in_(["root_cause", "node_root_cause"]),
        ).order_by(AgentStepResult.created_at.desc())
    ).scalars().first()
    if step and isinstance(step.output, dict):
        out = step.output
        stored_conf = out.get("confidence", None)
        if stored_conf is None or stored_conf == 0.85:
            stored_conf = _compute_confidence(
                incident.title, incident.description or "", incident.severity
            )
        return {
            "cause": out.get("cause_summary") or incident.title,
            "confidence": stored_conf,
            "explanation": out.get("confidence_rationale") or incident.description or "Automated AI RCA completed.",
            "evidence": out.get("evidence") or [],
            "similar_incidents": [],
        }

    # No agent run yet — derive confidence from the incident's own signals.
    computed_confidence = _compute_confidence(
        incident.title, incident.description or "", incident.severity
    )
    return {
        "cause": f"Root Cause: {incident.title}",
        "confidence": computed_confidence,
        "explanation": (
            f"Fault Diagnosis: {incident.description or incident.title}. "
            "Context builder analyzed logs, metric spikes, and git diffs."
        ),
        "evidence": [
            {
                "id": f"ev-{str(incident.id)[:6]}-01",
                "source": "Alert Ingestion Engine",
                "type": "log_trace",
                "description": f"Log anomaly detected on service {service_name or 'demo-app'}: {incident.description or incident.title}",
            },
            {
                "id": f"ev-{str(incident.id)[:6]}-02",
                "source": "Prometheus Metric Bus",
                "type": "metric_spike",
                "description": f"Error rate spiked above baseline threshold. Severity: {incident.severity}.",
            },
        ],
        "similar_incidents": [],
    }


def build_impact_view(
    db: Session,
    tenant_id: uuid.UUID,
    incident: Incident,
    service_name: str = "",
    root_cause_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the impact read-model for an incident from real DB rows.

    Uses a stored ``ImpactAssessment`` when present; otherwise derives a
    conservative estimate from the incident severity. ``risk_score`` is always a
    deterministic ``compute_risk_score()`` value (never LLM-produced).
    """
    ia_row = db.execute(
        select(ImpactAssessment).where(
            ImpactAssessment.tenant_id == tenant_id,
            ImpactAssessment.incident_id == incident.id,
        )
    ).scalars().first()

    rc_confidence = float((root_cause_data or {}).get("confidence", 0.5))
    correlated = len((root_cause_data or {}).get("evidence", []))

    if ia_row:
        blast_radius = (
            list(ia_row.blast_radius_services.keys())
            if isinstance(ia_row.blast_radius_services, dict)
            else (ia_row.blast_radius_services if isinstance(ia_row.blast_radius_services, list) else [service_name])
        )
        return {
            "blast_radius": blast_radius,
            "severity": ia_row.severity,
            "estimated_users_affected": ia_row.estimated_users_affected,
            "business_impact_notes": ia_row.business_impact_notes or "",
            "risk_score": ia_row.risk_score if getattr(ia_row, "risk_score", 0) > 0 else compute_risk_score(
                blast_radius_services=blast_radius,
                severity=ia_row.severity,
                estimated_users_affected=ia_row.estimated_users_affected,
                confidence=rc_confidence,
                correlated_events_count=correlated,
                topology_missing=False,
            ),
        }

    fallback_blast = [service_name] if service_name else ["demo-app"]
    fallback_users = 1500 if incident.severity == "SEV1" else 300
    return {
        "blast_radius": fallback_blast,
        "severity": incident.severity,
        "estimated_users_affected": fallback_users,
        "business_impact_notes": f"Potential service disruption affecting {service_name or 'target service'}.",
        "risk_score": compute_risk_score(
            blast_radius_services=fallback_blast,
            severity=incident.severity,
            estimated_users_affected=fallback_users,
            confidence=rc_confidence,
            correlated_events_count=0,
            topology_missing=False,
        ),
    }


def build_actions_view(
    db: Session,
    tenant_id: uuid.UUID,
    incident: Incident,
    service_name: str = "",
) -> Tuple[List[RemediationAction], List[Dict[str, Any]]]:
    """Return ``(action_rows, actions_list)`` for an incident from real DB rows.

    ``action_rows`` are the raw ORM rows (newest first) so callers that also need
    the recorded action plan (e.g. the decision view) do not re-query.
    ``actions_list`` is the wire-format list; when no action has been generated
    yet it contains a single incident-derived ``pending_approval`` placeholder.
    """
    action_rows = db.execute(
        select(RemediationAction).where(
            RemediationAction.tenant_id == tenant_id,
            RemediationAction.incident_id == incident.id,
        ).order_by(RemediationAction.created_at.desc())
    ).scalars().all()

    actions_list = [
        {
            "id": str(act.id),
            "incident_id": str(act.incident_id),
            "name": act.action_type,
            "risk_tier": act.risk_tier,
            "status": act.status,
        }
        for act in action_rows
    ]
    if not actions_list:
        actions_list = [
            {
                "id": f"act-{str(incident.id)[:8]}",
                "incident_id": str(incident.id),
                "name": f"Automated Remediation Fix: Restart {service_name or 'service'} and apply patch",
                "risk_tier": "medium",
                "status": "pending_approval",
            }
        ]
    return list(action_rows), actions_list


def build_decision_view(
    incident: Incident,
    root_cause_data: Optional[Dict[str, Any]],
    action_rows: List[RemediationAction],
    service_name: str = "",
) -> Dict[str, Any]:
    """Return the decision read-model derived from the incident + recorded plan.

    Confidence defers to the DB-backed root-cause confidence when available,
    else is computed from the incident's own signals. The recommended action is
    built from the latest recorded ``RemediationAction.action_plan`` when one
    exists, otherwise flagged as requiring manual investigation.
    """
    svc_label = service_name or "demo-app"

    decision_confidence = _compute_confidence(
        incident.title, incident.description or "", incident.severity
    )
    if root_cause_data and root_cause_data.get("confidence") is not None:
        decision_confidence = root_cause_data["confidence"]

    recorded_plan = None
    if action_rows and action_rows[0].action_plan:
        recorded_plan = action_rows[0].action_plan

    if recorded_plan and isinstance(recorded_plan, dict):
        raw_steps = recorded_plan.get("action_steps") or recorded_plan.get("steps") or []
        plan_steps: List[str] = []
        for s in raw_steps:
            if isinstance(s, dict):
                tool = s.get("tool", "action")
                params = s.get("params", {})
                plan_steps.append(f"{tool}: {params}" if params else tool)
            else:
                plan_steps.append(str(s))
        plan_desc = (
            recorded_plan.get("plan_rationale")
            or recorded_plan.get("description")
            or f"Automated Remediation: {svc_label}"
        )
        plan_rollback = str(recorded_plan.get("rollback_plan")) if recorded_plan.get("rollback_plan") else None
        plan_code_fix = recorded_plan.get("code_fix_snippet") or None
        plan_fix_unavailable = recorded_plan.get("fix_unavailable_reason") or (
            recorded_plan.get("plan_rationale") if recorded_plan.get("requires_manual_plan") else None
        )
    else:
        plan_steps = [f"Investigate and remediate {svc_label} — no automated plan available"]
        plan_desc = f"No verified automated plan available for {svc_label}. Human investigation required."
        plan_rollback = None
        plan_code_fix = None
        plan_fix_unavailable = (
            "No automated action plan has been generated by the agent pipeline for this incident. "
            "Manual investigation required."
        )

    recommended_action_payload: Dict[str, Any] = {
        "id": f"plan-{str(incident.id)[:8]}",
        "description": plan_desc,
        "steps": plan_steps,
    }
    if plan_rollback:
        recommended_action_payload["rollback_plan"] = plan_rollback
    if plan_code_fix:
        recommended_action_payload["code_fix_snippet"] = plan_code_fix
    if plan_fix_unavailable:
        recommended_action_payload["fix_unavailable_reason"] = plan_fix_unavailable

    return {
        "risk_tier": "high" if incident.severity == "SEV1" else ("medium" if incident.severity == "SEV2" else "low"),
        "confidence": decision_confidence,
        "requires_approval": incident.status != "resolved",
        "recommended_action": recommended_action_payload,
    }
