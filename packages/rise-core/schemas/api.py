"""API DTO Schemas for RISE API Service."""

from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class Meta(BaseModel):
    request_id: str = Field(..., description="Unique request tracing ID")
    timestamp: str = Field(..., description="ISO8601 timestamp")
    next_cursor: Optional[str] = Field(None, description="Cursor for pagination if applicable")


class ErrorDetail(BaseModel):
    code: str = Field(..., description="Machine readable error code")
    message: str = Field(..., description="Human readable error message")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional context or validation details")


class ApiResponse(BaseModel, Generic[T]):
    data: Optional[T] = None
    meta: Meta
    error: Optional[ErrorDetail] = None


class SessionResponse(BaseModel):
    user_id: str
    roles: list[str]
    tenant_id: str


class IncidentDTO(BaseModel):
    id: str
    title: str
    description: str
    severity: str
    status: str
    # affected_service is a resolved service name; Optional because auto-created
    # incidents may not yet have a named service.
    affected_service: Optional[str] = None
    created_at: str
    # updated_at: Optional because rows created before migration 0002 won't have
    # this column populated until the migration runs. Intentional contract change
    # from the original Step 1.2 spec where it was required — see openapi.yaml.
    updated_at: Optional[str] = None
    resolution_note: Optional[str] = None


class EvidenceDTO(BaseModel):
    id: str
    type: str
    description: str
    source: str


class IncidentRefDTO(BaseModel):
    id: str
    title: str
    similarity: float


class ActionPlanDTO(BaseModel):
    id: str
    description: str
    steps: list[str]


class IncidentDetailDTO(IncidentDTO):
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    root_cause: Optional[dict[str, Any]] = None
    impact: Optional[dict[str, Any]] = None
    actions: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)


class IncidentCreateRequest(BaseModel):
    title: str = Field(..., max_length=200)
    description: str
    severity: str = Field(..., description="SEV1, SEV2, SEV3, or SEV4")
    affected_service: str


class IncidentUpdateRequest(BaseModel):
    status: str
    resolution_note: str


class CommentCreateRequest(BaseModel):
    text: str


class CommentDTO(BaseModel):
    id: str
    incident_id: str
    text: str
    created_at: str
    author: str


class ReinvestigateResponse(BaseModel):
    agent_run_id: str
    status: str


class AgentRunDTO(BaseModel):
    id: str
    incident_id: str
    status: str
    created_at: str


class AgentStepResultDTO(BaseModel):
    id: str
    agent_run_id: str
    node_name: str
    input: dict[str, Any]
    output: dict[str, Any]
    confidence: float
    duration_ms: float
    llm_trace_link: Optional[str] = None


class RootCauseDTO(BaseModel):
    cause: str
    confidence: float
    evidence: list[EvidenceDTO] = Field(default_factory=list)
    similar_incidents: list[IncidentRefDTO] = Field(default_factory=list)


class ImpactDTO(BaseModel):
    blast_radius: list[str]
    severity: str
    estimated_users_affected: int
    business_impact_notes: str


class DecisionDTO(BaseModel):
    risk_tier: str
    confidence: float
    recommended_action: ActionPlanDTO
    requires_approval: bool


class ActionApproveRequest(BaseModel):
    note: Optional[str] = None
    plan_hash: Optional[str] = None


class ActionApproveResponse(BaseModel):
    status: str
    execution_status: str


class ActionExecuteRequest(BaseModel):
    plan_hash: Optional[str] = None
    action_plan: Optional[dict] = None


class ActionExecuteResponse(BaseModel):
    status: str
    execution_log: dict



class ActionRejectRequest(BaseModel):
    reason: str


class ActionRejectResponse(BaseModel):
    status: str


class ActionModifyRequest(BaseModel):
    modified_plan: ActionPlanDTO


class ActionModifyResponse(BaseModel):
    status: str
    new_risk_tier: str


class RemediationActionDTO(BaseModel):
    id: str
    incident_id: str
    name: str
    risk_tier: str
    status: str


class CheckItemDTO(BaseModel):
    name: str
    result: str
    value: str


class VerificationDTO(BaseModel):
    status: str
    checks: list[CheckItemDTO]


class KnowledgeEntryDTO(BaseModel):
    id: str
    title: str
    content: str
    tags: list[str]
    service: Optional[str] = None
    created_at: str


class KnowledgeCreateRequest(BaseModel):
    title: str
    content: str
    tags: list[str]
    service: Optional[str] = None


class RiskPolicyDTO(BaseModel):
    id: str
    action_pattern: str
    environment: str
    risk_tier: str
    requires_approval: bool
    max_blast_radius: int
    version: int = 1


class PolicyCreateRequest(BaseModel):
    action_pattern: str
    environment: str
    risk_tier: str
    requires_approval: bool
    max_blast_radius: int


class PolicyUpdateRequest(BaseModel):
    action_pattern: Optional[str] = None
    environment: Optional[str] = None
    risk_tier: Optional[str] = None
    requires_approval: Optional[bool] = None
    max_blast_radius: Optional[int] = None


class IntegrationDTO(BaseModel):
    type: str
    status: str
    scopes: list[str] = Field(default_factory=list)


class IntegrationConnectResponse(BaseModel):
    redirect_url: str


class MttrReportDTO(BaseModel):
    avg_mttr_minutes: float
    trend: list[dict[str, Any]] = Field(default_factory=list)


class AutonomyReportDTO(BaseModel):
    auto_resolved_pct: float
    human_approved_pct: float
    rejected_pct: float


class WebhookIngestResponse(BaseModel):
    received: bool
    incident_id: Optional[str] = None
    deduplicated: bool = False
    queued_dlq: bool = False


# Kept for backward compat with existing test_api_endpoints.py assertions.
WebhookResponse = WebhookIngestResponse


class AuditEventDTO(BaseModel):
    id: str
    incident_id: Optional[str] = None
    actor: str
    action: str
    timestamp: str
    # before_state / after_state expose the full audit payload stored in DB.
    # before_state is None for creation events; after_state is None for deletions.
    before_state: Optional[dict[str, Any]] = None
    after_state: Optional[dict[str, Any]] = None
    details: dict[str, Any] = Field(default_factory=dict)
