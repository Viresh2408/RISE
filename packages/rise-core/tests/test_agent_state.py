"""Unit tests for packages/rise-core/schemas/agent_state.py.

Tests each schema with:
  - A valid "happy path" instantiation (all required fields, legal values).
  - One or more invalid cases that must raise pydantic.ValidationError.

Run with:
    cd packages/rise-core
    python -m pytest tests/test_agent_state.py -v
"""

import pytest
from pydantic import ValidationError

from schemas.agent_state import (
    ActionPlan,
    ActionStep,
    AgentState,
    CheckResult,
    Decision,
    EvidenceItem,
    ExecutionLog,
    GraphExecutionStep,
    Hypothesis,
    ImpactAssessment,
    IncidentContext,
    IncidentEvent,
    LogExcerpt,
    MetricSnapshot,
    RecentDeploy,
    RootCause,
    SimilarIncident,
    TimelineEntry,
    VerificationResult,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

VALID_ACTION_STEP = {"tool": "k8s_restart_deployment", "params": {"deployment": "api", "namespace": "prod"}}
VALID_ROLLBACK_STEP = {"tool": "k8s_restart_deployment", "params": {"deployment": "api", "namespace": "prod", "rollback": True}}


def _valid_action_plan() -> dict:
    return {
        "action_type": "k8s_restart_deployment",
        "action_steps": [VALID_ACTION_STEP],
        "rollback_plan": [VALID_ROLLBACK_STEP],
        "plan_rationale": "Deployment is crashlooping; restart with last stable image.",
        "requires_manual_plan": False,
    }


def _valid_root_cause() -> dict:
    return {
        "cause_summary": "OOMKilled due to uncapped memory limit in api-gateway v2.3.1.",
        "confidence": 0.88,
        "confidence_rationale": "Three independent log sources and a metric spike all converge.",
        "evidence": [
            {"type": "log", "reference": "loki:api-gateway:2024-01-15T10:05Z", "excerpt": "OOMKilled"}
        ],
        "alternative_causes_considered": ["network saturation", "upstream dependency timeout"],
        "insufficient_evidence": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. IncidentEvent
# ─────────────────────────────────────────────────────────────────────────────


class TestIncidentEvent:
    def test_valid_full(self):
        e = IncidentEvent(
            resource_id="svc:api-gateway",
            source="alertmanager",
            event_type="high_error_rate",
            severity_hint="SEV2",
            summary="API gateway error rate exceeded 5% threshold for 3 consecutive minutes.",
            is_likely_duplicate=False,
            duplicate_of_incident_id=None,
            sanitization_flags=[],
        )
        assert e.source == "alertmanager"
        assert e.sanitization_flags == []

    def test_valid_with_duplicate_and_flags(self):
        e = IncidentEvent(
            resource_id="svc:api-gateway",
            source="cloudwatch",
            event_type="cpu_spike",
            severity_hint="SEV3",
            summary="CPU spike detected.",
            is_likely_duplicate=True,
            duplicate_of_incident_id="INC-0042",
            sanitization_flags=["payload_truncated"],
        )
        assert e.is_likely_duplicate is True
        assert e.duplicate_of_incident_id == "INC-0042"

    def test_invalid_source(self):
        with pytest.raises(ValidationError):
            IncidentEvent(
                resource_id="x",
                source="pagerduty",  # not in allowed Literal
                event_type="alert",
                severity_hint="SEV1",
                summary="test",
                is_likely_duplicate=False,
            )

    def test_invalid_severity_hint(self):
        with pytest.raises(ValidationError):
            IncidentEvent(
                resource_id="x",
                source="slack",
                event_type="alert",
                severity_hint="SEV5",  # not valid
                summary="test",
                is_likely_duplicate=False,
            )

    def test_summary_max_length_exceeded(self):
        with pytest.raises(ValidationError):
            IncidentEvent(
                resource_id="x",
                source="manual",
                event_type="alert",
                severity_hint="unknown",
                summary="A" * 201,  # exceeds max_length=200
                is_likely_duplicate=False,
            )

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            IncidentEvent(
                # resource_id missing
                source="github",
                event_type="push",
                severity_hint="SEV4",
                summary="test",
                is_likely_duplicate=False,
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. IncidentContext
# ─────────────────────────────────────────────────────────────────────────────


class TestIncidentContext:
    def test_valid_empty_lists(self):
        ctx = IncidentContext()
        assert ctx.context_completeness_pct == 100
        assert ctx.missing_sources == []

    def test_valid_with_all_fields(self):
        ctx = IncidentContext(
            timeline=[{"timestamp": "2024-01-15T10:00:00Z", "event": "Alert fired", "source": "alertmanager"}],
            log_excerpts=[{"source": "loki/api-gateway", "excerpt": "OOMKilled"}],
            metric_snapshots=[{"metric": "error_rate", "value": "6.2%", "window": "5m"}],
            recent_deploys=[{"repo": "api-gateway", "commit": "abc123", "deployed_at": "2024-01-15T09:00:00Z", "author": "alice"}],
            similar_past_incidents=[{"incident_id": "INC-0010", "similarity_score": 0.91, "resolution_summary": "Rolled back deploy."}],
            context_completeness_pct=85,
            missing_sources=["loki/db-sidecar"],
        )
        assert ctx.context_completeness_pct == 85
        assert ctx.recent_deploys[0].author == "alice"

    def test_invalid_completeness_pct_over_100(self):
        with pytest.raises(ValidationError):
            IncidentContext(context_completeness_pct=101)

    def test_invalid_completeness_pct_negative(self):
        with pytest.raises(ValidationError):
            IncidentContext(context_completeness_pct=-1)

    def test_log_excerpt_max_length(self):
        with pytest.raises(ValidationError):
            LogExcerpt(source="loki", excerpt="X" * 501)

    def test_similar_incident_score_out_of_range(self):
        with pytest.raises(ValidationError):
            SimilarIncident(incident_id="INC-1", similarity_score=1.5, resolution_summary="done")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Hypothesis
# ─────────────────────────────────────────────────────────────────────────────


class TestHypothesis:
    def test_valid(self):
        h = Hypothesis(
            rank=1,
            hypothesis="Memory leak in api-gateway v2.3.1 caused OOMKill.",
            plausibility_score=0.82,
            evidence_refs=["loki:api-gateway:10:05:22Z", "metric:memory_usage:spike"],
            source="inferred",
        )
        assert h.rank == 1

    def test_empty_evidence_refs_rejected(self):
        """Core guardrail: hypotheses with zero evidence_refs must be rejected."""
        with pytest.raises(ValidationError):
            Hypothesis(
                rank=1,
                hypothesis="Something went wrong.",
                plausibility_score=0.5,
                evidence_refs=[],  # violates min_length=1
                source="inferred",
            )

    def test_invalid_plausibility_score_gt_1(self):
        with pytest.raises(ValidationError):
            Hypothesis(
                rank=1,
                hypothesis="Test.",
                plausibility_score=1.1,
                evidence_refs=["ref1"],
                source="runbook",
            )

    def test_invalid_source(self):
        with pytest.raises(ValidationError):
            Hypothesis(
                rank=1,
                hypothesis="Test.",
                plausibility_score=0.5,
                evidence_refs=["ref1"],
                source="hallucinated",  # not in Literal
            )

    def test_rank_zero_rejected(self):
        with pytest.raises(ValidationError):
            Hypothesis(
                rank=0,  # ge=1 constraint
                hypothesis="Test.",
                plausibility_score=0.5,
                evidence_refs=["ref1"],
                source="inferred",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. RootCause
# ─────────────────────────────────────────────────────────────────────────────


class TestRootCause:
    def test_valid(self):
        rc = RootCause(**_valid_root_cause())
        assert rc.confidence == 0.88
        assert rc.insufficient_evidence is False

    def test_confidence_exceeds_1(self):
        data = _valid_root_cause()
        data["confidence"] = 1.01
        with pytest.raises(ValidationError):
            RootCause(**data)

    def test_confidence_negative(self):
        data = _valid_root_cause()
        data["confidence"] = -0.1
        with pytest.raises(ValidationError):
            RootCause(**data)

    def test_invalid_evidence_type(self):
        data = _valid_root_cause()
        data["evidence"] = [{"type": "tweet", "reference": "x", "excerpt": "y"}]
        with pytest.raises(ValidationError):
            RootCause(**data)

    def test_missing_cause_summary(self):
        data = _valid_root_cause()
        del data["cause_summary"]
        with pytest.raises(ValidationError):
            RootCause(**data)

    def test_insufficient_evidence_flag(self):
        data = _valid_root_cause()
        data["insufficient_evidence"] = True
        rc = RootCause(**data)
        assert rc.insufficient_evidence is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. ImpactAssessment
# ─────────────────────────────────────────────────────────────────────────────


class TestImpactAssessment:
    def test_valid(self):
        ia = ImpactAssessment(
            blast_radius_services=["api-gateway", "checkout-service"],
            severity="SEV1",
            estimated_users_affected=50000,
            business_impact_notes="Checkout is unavailable for all users.",
        )
        assert ia.severity == "SEV1"

    def test_null_estimated_users(self):
        ia = ImpactAssessment(
            blast_radius_services=["internal-tools"],
            severity="SEV4",
            estimated_users_affected=None,
            business_impact_notes="Impact limited to internal team tooling.",
        )
        assert ia.estimated_users_affected is None

    def test_invalid_severity_unknown_not_allowed(self):
        """Impact Analyzer uses Severity (no 'unknown'), not SeverityHint."""
        with pytest.raises(ValidationError):
            ImpactAssessment(
                blast_radius_services=["svc"],
                severity="unknown",  # not in Severity Literal
                estimated_users_affected=None,
                business_impact_notes="n/a",
            )

    def test_invalid_severity_value(self):
        with pytest.raises(ValidationError):
            ImpactAssessment(
                blast_radius_services=[],
                severity="SEV5",
                estimated_users_affected=0,
                business_impact_notes="n/a",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 6. ActionPlan
# ─────────────────────────────────────────────────────────────────────────────


class TestActionPlan:
    def test_valid(self):
        ap = ActionPlan(**_valid_action_plan())
        assert ap.action_type == "k8s_restart_deployment"
        assert len(ap.rollback_plan) == 1

    def test_empty_rollback_plan_without_manual_flag_rejected(self):
        """Core guardrail: empty rollback_plan must be rejected unless requires_manual_plan."""
        data = _valid_action_plan()
        data["rollback_plan"] = []
        data["requires_manual_plan"] = False
        with pytest.raises(ValidationError, match="rollback_plan must be non-empty"):
            ActionPlan(**data)

    def test_empty_rollback_plan_allowed_when_manual(self):
        data = _valid_action_plan()
        data["rollback_plan"] = []
        data["requires_manual_plan"] = True
        ap = ActionPlan(**data)
        assert ap.requires_manual_plan is True

    def test_missing_action_type(self):
        data = _valid_action_plan()
        del data["action_type"]
        with pytest.raises(ValidationError):
            ActionPlan(**data)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Decision
# ─────────────────────────────────────────────────────────────────────────────


class TestDecision:
    def test_valid_auto_approve(self):
        d = Decision(
            risk_tier="low",
            requires_approval=False,
            action_plan=ActionPlan(**_valid_action_plan()),
        )
        assert d.risk_tier == "low"
        assert d.requires_approval is False

    def test_valid_critical_with_approval(self):
        d = Decision(
            risk_tier="critical",
            requires_approval=True,
            action_plan=ActionPlan(**_valid_action_plan()),
        )
        assert d.requires_approval is True

    def test_critical_without_approval_rejected(self):
        """Core guardrail: critical tier must always require approval."""
        with pytest.raises(ValidationError, match="critical.*requires_approval"):
            Decision(
                risk_tier="critical",
                requires_approval=False,  # violates hardcoded guardrail
                action_plan=ActionPlan(**_valid_action_plan()),
            )

    def test_invalid_risk_tier(self):
        with pytest.raises(ValidationError):
            Decision(
                risk_tier="extreme",  # not in Literal
                requires_approval=True,
                action_plan=ActionPlan(**_valid_action_plan()),
            )


# ─────────────────────────────────────────────────────────────────────────────
# 8. ExecutionLog
# ─────────────────────────────────────────────────────────────────────────────


class TestExecutionLog:
    def test_valid_success(self):
        el = ExecutionLog(
            status="success",
            steps_completed=3,
            steps_total=3,
            result="Deployment restarted. PR: https://github.com/acme/api/pull/999",
            error=None,
        )
        assert el.status == "success"

    def test_valid_partial_with_error(self):
        el = ExecutionLog(
            status="partial",
            steps_completed=1,
            steps_total=3,
            result=None,
            error="k8s API returned 403 on step 2: insufficient RBAC permissions.",
        )
        assert el.steps_completed == 1

    def test_partial_without_error_rejected(self):
        with pytest.raises(ValidationError, match="error must be set"):
            ExecutionLog(status="partial", steps_completed=1, steps_total=3, error=None)

    def test_failed_without_error_rejected(self):
        with pytest.raises(ValidationError, match="error must be set"):
            ExecutionLog(status="failed", steps_completed=0, steps_total=2, error=None)

    def test_steps_completed_exceeds_total(self):
        with pytest.raises(ValidationError, match="steps_completed cannot exceed"):
            ExecutionLog(status="success", steps_completed=5, steps_total=3, error=None)

    def test_negative_steps_rejected(self):
        with pytest.raises(ValidationError):
            ExecutionLog(status="success", steps_completed=-1, steps_total=3)


# ─────────────────────────────────────────────────────────────────────────────
# 9. VerificationResult
# ─────────────────────────────────────────────────────────────────────────────


class TestVerificationResult:
    def test_valid_passed(self):
        vr = VerificationResult(
            status="passed",
            checks=[
                {"name": "error_rate", "result": "pass", "value": "0.2%", "threshold": "<1%"},
                {"name": "latency_p99", "result": "pass", "value": "145ms", "threshold": "<300ms"},
            ],
            recommendation="close",
        )
        assert vr.status == "passed"
        assert len(vr.checks) == 2

    def test_valid_failed_with_rollback(self):
        vr = VerificationResult(
            status="failed",
            checks=[{"name": "error_rate", "result": "fail", "value": "8.5%", "threshold": "<1%"}],
            recommendation="rollback",
        )
        assert vr.recommendation == "rollback"

    def test_valid_inconclusive(self):
        vr = VerificationResult(
            status="inconclusive",
            checks=[],
            recommendation="extend_monitoring",
        )
        assert vr.status == "inconclusive"

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            VerificationResult(
                status="success",  # not in Literal; must be passed|failed|inconclusive
                checks=[],
                recommendation="close",
            )

    def test_invalid_check_result(self):
        with pytest.raises(ValidationError):
            CheckResult(name="test", result="ok", value="0", threshold="<1")  # 'ok' not in pass|fail

    def test_invalid_recommendation(self):
        with pytest.raises(ValidationError):
            VerificationResult(
                status="passed",
                checks=[],
                recommendation="ignore",  # not in Literal
            )

    def test_missing_recommendation(self):
        with pytest.raises(ValidationError):
            VerificationResult(status="passed", checks=[])


# ─────────────────────────────────────────────────────────────────────────────
# 10. GraphExecutionStep and AgentState (orchestration infra)
# ─────────────────────────────────────────────────────────────────────────────


class TestOrchestrationState:
    def test_graph_execution_step_valid(self):
        step = GraphExecutionStep(
            step_id="step-001",
            node="investigate",
            started_at="2024-01-15T10:05:00Z",
        )
        assert step.ended_at is None

    def test_agent_state_valid(self):
        state = AgentState(
            incident_id="INC-0099",
            tenant_id="tenant-abc",
            current_node="verify",
        )
        assert state.context == {}
        assert state.errors == []

    def test_agent_state_missing_required(self):
        with pytest.raises(ValidationError):
            AgentState(incident_id="INC-0099")  # tenant_id and current_node missing
