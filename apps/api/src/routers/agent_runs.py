"""Agent Runs Router — real DB-backed reads."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AgentRun, AgentStepResult
from schemas import AgentRunDTO, AgentStepResultDTO
from apps.api.src.deps import require_role, UserContext, get_db
from apps.api.src.middleware.envelope import build_response
from apps.api.src.services.incident_views import _parse_uuid

router = APIRouter(tags=["Agent Runs"])


@router.get("/incidents/{incident_id}/agent-runs")
async def list_incident_agent_runs(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    inc_uuid = _parse_uuid(incident_id)

    runs = db.execute(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.incident_id == inc_uuid,
        ).order_by(AgentRun.started_at.desc())
    ).scalars().all()

    data = [
        AgentRunDTO(
            id=str(run.id),
            incident_id=str(run.incident_id),
            status=run.status,
            created_at=run.started_at.isoformat() if run.started_at else "",
        ).model_dump()
        for run in runs
    ]
    return build_response(data=data)


@router.get("/agent-runs/{agent_run_id}/steps")
async def get_agent_run_steps(
    agent_run_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)

    # A non-UUID run id (e.g. the demo ``run-001``) can never match a real row,
    # so report an empty timeline rather than 404 — the run simply has no
    # recorded steps yet.
    try:
        run_uuid = uuid.UUID(agent_run_id)
    except ValueError:
        return build_response(data=[])

    steps = db.execute(
        select(AgentStepResult).where(
            AgentStepResult.tenant_id == tenant_id,
            AgentStepResult.agent_run_id == run_uuid,
        ).order_by(AgentStepResult.created_at.asc())
    ).scalars().all()

    data = [
        AgentStepResultDTO(
            id=str(step.id),
            agent_run_id=str(step.agent_run_id),
            node_name=step.agent_name,
            input=step.input if isinstance(step.input, dict) else {},
            output=step.output if isinstance(step.output, dict) else {},
            confidence=step.confidence,
            duration_ms=float(step.duration_ms),
            llm_trace_link=step.llm_trace_id,
        ).model_dump()
        for step in steps
    ]
    return build_response(data=data)
