"""Agent Runs Router."""

from fastapi import APIRouter, Depends
from schemas import AgentRunDTO, AgentStepResultDTO
from apps.api.src.deps import require_role, UserContext
from apps.api.src.middleware.envelope import build_response

router = APIRouter(tags=["Agent Runs"])


@router.get("/incidents/{incident_id}/agent-runs")
async def list_incident_agent_runs(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
):
    runs = [
        AgentRunDTO(
            id="run-001",
            incident_id=incident_id,
            status="completed",
            created_at="2026-08-01T10:01:00Z",
        ).model_dump()
    ]
    return build_response(data=runs)


@router.get("/agent-runs/{agent_run_id}/steps")
async def get_agent_run_steps(
    agent_run_id: str,
    user: UserContext = Depends(require_role("viewer")),
):
    steps = [
        AgentStepResultDTO(
            id="step-001",
            agent_run_id=agent_run_id,
            node_name="root_cause_analysis",
            input={"logs": "OOMKilled event detected"},
            output={"cause": "Memory leak", "confidence": 0.89},
            confidence=0.89,
            duration_ms=1250.0,
            llm_trace_link="https://langfuse.internal/trace/tr-123",
        ).model_dump()
    ]
    return build_response(data=steps)
