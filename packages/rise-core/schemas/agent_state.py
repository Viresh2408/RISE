"""Domain and Agent State Schemas for RISE Agent Pipeline.

Each schema in this module corresponds to one agent's input or output as defined in:
  - agents-and-orchestration.md  (agent roster & field descriptions)
  - prompts.md                   (authoritative LLM output schemas)

Where the two source documents disagree, the mismatch is documented inline and the
resolution is stated explicitly. No mismatch was silently ignored.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Shared enumerations (Literals)
# ---------------------------------------------------------------------------

SeverityHint = Literal["SEV1", "SEV2", "SEV3", "SEV4", "unknown"]
"""Used by Ingestion Agent. 'unknown' is valid — severity may be unclear at ingestion time."""

Severity = Literal["SEV1", "SEV2", "SEV3", "SEV4"]
"""Used by Impact Analyzer. Always known at this pipeline stage; 'unknown' is not valid."""

IncidentSource = Literal[
    "cloudwatch", "alertmanager", "github", "kubernetes", "slack", "manual"
]

HypothesisSource = Literal["runbook", "inferred"]

EvidenceType = Literal["log", "metric", "deploy", "runbook", "past_incident"]

RiskTier = Literal["low", "medium", "high", "critical"]

ExecutionStatus = Literal["success", "partial", "failed"]

VerificationStatus = Literal["passed", "failed", "inconclusive"]

VerificationRecommendation = Literal["close", "rollback", "extend_monitoring"]


# ---------------------------------------------------------------------------
# 1. IncidentEvent  (Ingestion Agent output)
#
# SOURCE CROSS-CHECK:
#   agents-and-orchestration.md §2.2: lists resource_id, source, event_type,
#     severity_hint, summary, is_likely_duplicate, duplicate_of_incident_id
#     (7 fields, no sanitization_flags).
#   prompts.md §1: includes sanitization_flags: ["string"] as the 8th field.
#
# MISMATCH: `sanitization_flags` is absent from orchestration.md but present in
#   prompts.md.  RESOLUTION: Include it — it is a required security output of
#   the Ingestion Agent prompt and must not be dropped.
# ---------------------------------------------------------------------------


class IncidentEvent(BaseModel):
    """Output of the Ingestion Agent. Normalized, sanitized incident event."""

    resource_id: str = Field(
        description="Stable identifier for the affected resource (service, host, etc.)."
    )
    source: IncidentSource = Field(
        description="System that produced the raw event."
    )
    event_type: str = Field(
        description="Free-form event classifier (e.g. 'high_error_rate', 'pod_crashloop')."
    )
    severity_hint: SeverityHint = Field(
        description="Agent's best-effort severity estimate; 'unknown' if unclear."
    )
    summary: str = Field(
        max_length=200,
        description=(
            "Agent-written summary (max 200 chars). Must be in the agent's own words — "
            "verbatim copying of untrusted input is forbidden by the security preamble."
        ),
    )
    is_likely_duplicate: bool = Field(
        description="True when this event is probably already covered by an open incident."
    )
    duplicate_of_incident_id: Optional[str] = Field(
        default=None,
        description="Incident ID of the presumed duplicate, or null.",
    )
    sanitization_flags: list[str] = Field(
        default_factory=list,
        description=(
            "List of sanitization warnings raised during normalization "
            "(e.g. 'prompt_injection_attempt_detected', 'payload_truncated'). "
            "Present in prompts.md §1; absent from orchestration doc — included per prompts.md."
        ),
    )


# ---------------------------------------------------------------------------
# 2. IncidentContext  (Context Builder Agent output)
#
# SOURCE CROSS-CHECK:
#   agents-and-orchestration.md §2.3: describes the bundle as
#     "log excerpts, metric_snapshots, deploy_diff_refs, similarity_matches" (4 informal names).
#   prompts.md §2: defines 7 concrete fields:
#     timeline, log_excerpts, metric_snapshots, recent_deploys,
#     similar_past_incidents, context_completeness_pct, missing_sources.
#
# MISMATCHES:
#   - orchestration uses 'deploy_diff_refs' → prompts uses 'recent_deploys' (object list)
#   - orchestration uses 'similarity_matches' → prompts uses 'similar_past_incidents'
#   - orchestration omits: 'timeline', 'context_completeness_pct', 'missing_sources'
#
# RESOLUTION: prompts.md is the authoritative LLM output schema. Orchestration doc
#   names are informal descriptions. All 7 prompts.md fields are implemented.
# ---------------------------------------------------------------------------


class TimelineEntry(BaseModel):
    """One event in the reconstructed incident timeline."""

    timestamp: str = Field(description="ISO 8601 datetime string.")
    event: str
    source: str


class LogExcerpt(BaseModel):
    """A log snippet included in the context bundle."""

    source: str = Field(description="Log source identifier (e.g. 'loki/api-gateway').")
    excerpt: str = Field(
        max_length=500,
        description="Paraphrased or truncated log text. Max 500 chars per prompts.md §2.",
    )


class MetricSnapshot(BaseModel):
    """A point-in-time metric observation."""

    metric: str
    value: str = Field(description="String representation to accommodate units (e.g. '94.3%').")
    window: str = Field(description="Time window of the snapshot (e.g. '5m', '1h').")


class RecentDeploy(BaseModel):
    """A deployment event correlated with the incident timeline.

    Field name: 'recent_deploys' per prompts.md §2.
    orchestration.md informally calls this 'deploy_diff_refs' — resolved to prompts.md name.
    """

    repo: str
    commit: str
    deployed_at: str = Field(description="ISO 8601 datetime string.")
    author: str


class SimilarIncident(BaseModel):
    """A past incident retrieved by vector similarity search.

    Field name: 'similar_past_incidents' per prompts.md §2.
    orchestration.md informally calls this 'similarity_matches' — resolved to prompts.md name.
    """

    incident_id: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    resolution_summary: str


class IncidentContext(BaseModel):
    """Output of the Context Builder Agent. Structured evidence bundle."""

    timeline: list[TimelineEntry] = Field(
        default_factory=list,
        description=(
            "Reconstructed incident timeline. Present in prompts.md §2; "
            "absent from orchestration doc — included per prompts.md."
        ),
    )
    log_excerpts: list[LogExcerpt] = Field(default_factory=list)
    metric_snapshots: list[MetricSnapshot] = Field(default_factory=list)
    recent_deploys: list[RecentDeploy] = Field(
        default_factory=list,
        description="prompts.md field. orchestration.md called this 'deploy_diff_refs'.",
    )
    similar_past_incidents: list[SimilarIncident] = Field(
        default_factory=list,
        description="prompts.md field. orchestration.md called this 'similarity_matches'.",
    )
    context_completeness_pct: int = Field(
        default=100,
        ge=0,
        le=100,
        description=(
            "0–100 completeness score. Present in prompts.md §2; "
            "absent from orchestration doc — included per prompts.md."
        ),
    )
    missing_sources: list[str] = Field(
        default_factory=list,
        description=(
            "Data sources that were unavailable during context assembly. "
            "Present in prompts.md §2; absent from orchestration doc — included per prompts.md."
        ),
    )


# ---------------------------------------------------------------------------
# 3. Hypothesis  (Investigation Agent output element)
#
# SOURCE CROSS-CHECK:
#   agents-and-orchestration.md §2.4: guardrails mention 'evidence_refs: list[str]'
#     (1 field referenced, not a full schema).
#   prompts.md §3: full struct is {rank, hypothesis, plausibility_score, evidence_refs, source}
#     (5 fields).
#
# MISMATCH: orchestration doc only mentions evidence_refs, omitting rank, hypothesis,
#   plausibility_score, source.
# RESOLUTION: Use prompts.md's full 5-field struct. The orchestration mention is
#   a guardrail note, not the complete schema definition.
# ---------------------------------------------------------------------------


class Hypothesis(BaseModel):
    """One ranked hypothesis produced by the Investigation Agent."""

    rank: int = Field(ge=1, description="Rank 1 = most plausible.")
    hypothesis: str
    plausibility_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Agent's confidence in this hypothesis (0.0–1.0).",
    )
    evidence_refs: list[str] = Field(
        min_length=1,
        description=(
            "Non-empty list of evidence references. Enforced by guardrails: "
            "a hypothesis with zero evidence refs is schema-invalid and will be rejected."
        ),
    )
    source: HypothesisSource = Field(
        description="Whether this hypothesis is runbook-derived or freshly inferred."
    )

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("evidence_refs must be a non-empty list.")
        for ref in v:
            if not ref or not ref.strip():
                raise ValueError("evidence_refs cannot contain empty or whitespace-only strings.")
        return v


class InvestigationResult(BaseModel):
    """Output of the Investigation Agent. Contains ranked hypotheses."""

    hypotheses: list[Hypothesis] = Field(
        description="Ranked hypotheses generated by the Investigation Agent."
    )


# ---------------------------------------------------------------------------
# 4. RootCause  (Root Cause Agent output)
#
# SOURCE CROSS-CHECK:
#   agents-and-orchestration.md §2.5: {cause_summary, confidence: float[0,1], evidence[]}
#     (3 fields; evidence is an untyped list).
#   prompts.md §4: {cause_summary, confidence, confidence_rationale,
#     evidence[{type, reference, excerpt}], alternative_causes_considered,
#     insufficient_evidence}  (6 fields; evidence is a typed list).
#
# MISMATCHES:
#   - orchestration omits: confidence_rationale, alternative_causes_considered,
#     insufficient_evidence (3 missing fields)
#   - orchestration has untyped evidence[] vs prompts.md typed EvidenceItem list
#
# RESOLUTION: Use prompts.md's 6-field schema with typed EvidenceItem sub-model.
#   The three missing orchestration fields are required by the LLM prompt for
#   calibrated confidence and must not be dropped.
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    """A single piece of evidence cited in the Root Cause analysis."""

    type: EvidenceType
    reference: str = Field(description="Pointer to the evidence (e.g. log line ID, metric name).")
    excerpt: str = Field(description="Brief quoted or paraphrased excerpt.")


class RootCause(BaseModel):
    """Output of the Root Cause Agent. Single most probable root cause."""

    cause_summary: str
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Calibrated confidence score. >0.85 only when evidence is strong and consistent. "
            "orchestration.md says float[0,1]; prompts.md says 0.0-1.0. Validated [0.0, 1.0]."
        ),
    )
    confidence_rationale: str = Field(
        description=(
            "Explanation of why this score and not higher or lower. "
            "Present in prompts.md §4; absent from orchestration doc — included per prompts.md."
        )
    )
    evidence: list[EvidenceItem] = Field(
        description=(
            "Typed evidence list per prompts.md §4. "
            "orchestration.md describes evidence[] as an untyped list — resolved to typed form."
        )
    )
    alternative_causes_considered: list[str] = Field(
        default_factory=list,
        description=(
            "Other hypotheses considered and rejected. "
            "Present in prompts.md §4; absent from orchestration doc — included per prompts.md."
        ),
    )
    insufficient_evidence: bool = Field(
        default=False,
        description=(
            "True when no hypothesis is sufficiently supported. "
            "Present in prompts.md §4; absent from orchestration doc — included per prompts.md."
        ),
    )


# ---------------------------------------------------------------------------
# 5. ImpactAssessment  (Impact Analyzer Agent output)
#
# SOURCE CROSS-CHECK:
#   agents-and-orchestration.md §2.6:
#     {blast_radius_services[], severity, estimated_users_affected, business_impact_notes}
#   prompts.md §5: exact same 4 fields.
#
# NO MISMATCH. ✅
# ---------------------------------------------------------------------------


class ImpactAssessment(BaseModel):
    """Output of the Impact Analyzer Agent."""

    blast_radius_services: list[str] = Field(
        description=(
            "Deterministically-computed from topology graph — must be passed through "
            "unchanged from input per prompts.md §5. LLM must not recompute this list."
        )
    )
    severity: Severity = Field(
        description=(
            "SEV1–SEV4. Note: 'unknown' is NOT valid here (unlike SeverityHint at ingestion); "
            "Impact Analyzer always determines a definitive severity."
        )
    )
    estimated_users_affected: Optional[int] = Field(
        default=None,
        description="Estimated user count, or null if truly unknown.",
    )
    business_impact_notes: str = Field(
        description="Plain-language impact summary for a non-technical stakeholder."
    )


# ---------------------------------------------------------------------------
# 6. ActionPlan  (Decision & Plan Agent — Action Planner sub-component LLM output)
#    Decision    (full Decision & Plan Agent output, wrapping ActionPlan)
#
# SOURCE CROSS-CHECK:
#   agents-and-orchestration.md §2.7: Decision { risk_tier, requires_approval,
#     action_plan, rollback_plan }
#   prompts.md §6: ActionPlan { action_type, action_steps, rollback_plan,
#     plan_rationale, requires_manual_plan }
#     — NO 'Decision' wrapper. 'risk_tier' and 'requires_approval' are absent.
#
# MAJOR MISMATCH:
#   - prompts.md §6 is explicitly the "Action Planner sub-component" output schema
#     (see prompt text: "You do NOT decide whether human approval is required —
#     that is determined separately by the Risk Engine").
#   - 'risk_tier' and 'requires_approval' are Risk Engine outputs (non-LLM code).
#   - orchestration.md's 'action_plan' maps to prompts.md's 'ActionPlan' struct.
#   - orchestration.md's 'rollback_plan' is embedded inside ActionPlan in prompts.md.
#
# RESOLUTION: Two separate schemas:
#   1. ActionPlan  — exact prompts.md §6 LLM output (what the LLM produces).
#   2. Decision    — orchestration.md wrapper with risk_tier + requires_approval
#                    (set by Risk Engine), embedding an ActionPlan.
# ---------------------------------------------------------------------------


class ActionStep(BaseModel):
    """A single step in an action or rollback plan."""

    tool: str = Field(description="Tool name; must match the allow-list for this agent.")
    params: dict[str, Any] = Field(default_factory=dict)


class ActionPlan(BaseModel):
    """LLM output of the Action Planner sub-component within Decision & Plan Agent.

    This is what the model produces per prompts.md §6. The 'requires_manual_plan'
    flag replaces an attempt to produce a risky or non-reversible plan.
    """

    action_type: str = Field(
        description="Must match one of the available tool names injected at runtime."
    )
    action_steps: list[ActionStep] = Field(
        description="Ordered list of tool calls to execute."
    )
    rollback_plan: list[ActionStep] = Field(
        description=(
            "Required per guardrails: every plan must include a rollback plan. "
            "An empty rollback_plan triggers automatic escalation to human review."
        )
    )
    plan_rationale: str = Field(description="Explanation of why this plan was chosen.")
    requires_manual_plan: bool = Field(
        default=False,
        description=(
            "True when the agent cannot construct a safe, reversible plan with the "
            "available tools. Triggers human escalation."
        ),
    )

    @model_validator(mode="after")
    def rollback_plan_required_unless_manual(self) -> "ActionPlan":
        if not self.requires_manual_plan and len(self.rollback_plan) == 0:
            raise ValueError(
                "rollback_plan must be non-empty unless requires_manual_plan=True. "
                "Every automated action plan must include a rollback plan per guardrails."
            )
        return self



class Decision(BaseModel):
    """Full output of the Decision & Plan Agent, combining LLM ActionPlan with Risk Engine fields.

    orchestration.md §2.7 defines Decision { risk_tier, requires_approval, action_plan,
    rollback_plan }. prompts.md §6 defines ActionPlan (LLM sub-output). The 'risk_tier'
    and 'requires_approval' fields are set by the Risk Engine (OPA policy evaluation),
    not by the LLM. This schema wraps both.
    """

    risk_tier: RiskTier = Field(
        description=(
            "Determined by the Risk Engine (OPA policy), not the LLM. "
            "Critical tier is never auto-approved per §2.7 guardrails."
        )
    )
    requires_approval: bool = Field(
        description=(
            "True if human approval is required. Set by Decision Engine combining "
            "risk_tier, confidence, blast radius, and policy. NOT set by the LLM."
        )
    )
    action_plan: ActionPlan = Field(
        description="LLM-produced action plan (prompts.md §6 ActionPlan schema)."
    )

    @model_validator(mode="after")
    def critical_always_requires_approval(self) -> "Decision":
        if self.risk_tier == "critical" and not self.requires_approval:
            raise ValueError(
                "risk_tier='critical' must always have requires_approval=True. "
                "Critical-tier actions are never auto-approved (hardcoded guardrail, §2.7)."
            )
        return self


# ---------------------------------------------------------------------------
# 7. ExecutionLog  (Execution Agent output)
#
# SOURCE CROSS-CHECK:
#   agents-and-orchestration.md §2.8: {status, result} (2 fields, brief description).
#   prompts.md: No output schema — Execution Agent uses tool calls, not LLM structured output.
#
# MISMATCH: Only orchestration.md defines this. Additional fields inferred from
#   the failure-handling description: "partial-completion status", "aborts immediately",
#   "reports partial-completion status for Verification/human review".
# RESOLUTION: Define from orchestration doc + failure-handling prose. Added:
#   steps_completed, steps_total, error (for partial/failed states).
# ---------------------------------------------------------------------------


class ExecutionLog(BaseModel):
    """Output of the Execution Agent. Records the outcome of executing an ActionPlan."""

    status: ExecutionStatus = Field(
        description=(
            "'success' = all steps completed. 'partial' = aborted mid-plan on tool error "
            "(steps after the failure were NOT attempted). 'failed' = first step failed."
        )
    )
    steps_completed: int = Field(
        ge=0,
        description=(
            "Number of ActionPlan steps successfully completed before abort (or all steps). "
            "Inferred from orchestration.md §2.8 failure-handling description."
        ),
    )
    steps_total: int = Field(
        ge=0,
        description="Total number of steps in the approved ActionPlan.",
    )
    result: Optional[str] = Field(
        default=None,
        description=(
            "Human-readable outcome summary, or null on failure. "
            "For code-fix plans, includes the GitHub PR URL."
        ),
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message on partial or failed status; null on success.",
    )

    @model_validator(mode="after")
    def error_required_on_failure(self) -> "ExecutionLog":
        if self.status in ("partial", "failed") and not self.error:
            raise ValueError(
                "error must be set when status is 'partial' or 'failed'."
            )
        if self.steps_completed > self.steps_total:
            raise ValueError("steps_completed cannot exceed steps_total.")
        return self


# ---------------------------------------------------------------------------
# 8. VerificationResult  (Verification Agent output)
#
# SOURCE CROSS-CHECK:
#   agents-and-orchestration.md §2.9: {status, checks[]} (2 fields, untyped checks).
#   prompts.md §7: {status, checks[{name, result, value, threshold}], recommendation}
#     (3 fields, typed CheckResult list).
#
# MISMATCHES:
#   - orchestration omits 'recommendation'
#   - orchestration has untyped checks[] vs prompts.md typed CheckResult list
#
# RESOLUTION: Use prompts.md's full schema with typed CheckResult sub-model and
#   recommendation field. Orchestration description was a brief summary, not full spec.
# ---------------------------------------------------------------------------


class CheckResult(BaseModel):
    """A single health check performed during verification."""

    name: str
    result: Literal["pass", "fail"]
    value: str = Field(description="Observed metric/health value (string for unit flexibility).")
    threshold: str = Field(description="The threshold that determines pass/fail.")


class VerificationResult(BaseModel):
    """Output of the Verification Agent."""

    status: VerificationStatus = Field(
        description=(
            "Default to 'failed' or 'inconclusive' when evidence is ambiguous — "
            "never assume success without positive confirming evidence (prompts.md §7)."
        )
    )
    checks: list[CheckResult] = Field(
        description=(
            "Typed check results per prompts.md §7. "
            "orchestration.md had untyped checks[] — resolved to typed CheckResult list."
        )
    )
    recommendation: VerificationRecommendation = Field(
        description=(
            "Agent's recommended next action. Present in prompts.md §7; "
            "absent from orchestration doc — included per prompts.md."
        )
    )


# ---------------------------------------------------------------------------
# Orchestration infrastructure  (retained from original file, unchanged)
# ---------------------------------------------------------------------------


class GraphExecutionStep(BaseModel):
    """Records a single node execution within the LangGraph state machine."""

    step_id: str
    node: str
    started_at: str
    ended_at: Optional[str] = None
    state_delta: dict[str, Any] = Field(default_factory=dict)


class AgentState(BaseModel):
    """Top-level LangGraph state object persisted to Postgres after every node.

    The Orchestrator Agent owns and mutates this object throughout the pipeline.
    """

    incident_id: str
    tenant_id: str
    current_node: str
    context: dict[str, Any] = Field(default_factory=dict)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    execution_steps: list[GraphExecutionStep] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
