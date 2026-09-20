"""Unit tests for deterministic risk_score computation in ImpactAssessment."""

from schemas.agent_state import compute_risk_score, ImpactAssessment


def test_compute_risk_score_boundaries():
    # SEV1, max blast, max users, high confidence & correlated events -> 100
    score_max = compute_risk_score(
        blast_radius_services=["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11"],
        severity="SEV1",
        estimated_users_affected=15000,
        confidence=1.0,
        correlated_events_count=5,
        topology_missing=False,
    )
    assert score_max == 100

    # SEV4, 0 services, 0 users, 0 confidence -> severity floor (0.25 * 40 = 10)
    score_min = compute_risk_score(
        blast_radius_services=[],
        severity="SEV4",
        estimated_users_affected=0,
        confidence=0.0,
        correlated_events_count=0,
        topology_missing=False,
    )
    assert score_min == 10


def test_compute_risk_score_topology_missing_guardrail():
    # When topology is missing, the score must be at least 70 regardless of other inputs
    score_missing = compute_risk_score(
        blast_radius_services=["s1"],
        severity="SEV4",
        estimated_users_affected=10,
        confidence=0.1,
        correlated_events_count=0,
        topology_missing=True,
    )
    assert score_missing >= 70


def test_compute_risk_score_severity_scaling():
    # Isolated severity variations
    scores = {}
    for sev in ["SEV1", "SEV2", "SEV3", "SEV4"]:
        scores[sev] = compute_risk_score(
            blast_radius_services=["auth"],
            severity=sev,
            estimated_users_affected=500,
            confidence=0.8,
            correlated_events_count=2,
            topology_missing=False,
        )
    assert scores["SEV1"] > scores["SEV2"] > scores["SEV3"] > scores["SEV4"]


def test_impact_assessment_model_risk_score():
    ia = ImpactAssessment(
        blast_radius_services=["auth-service", "api-gateway"],
        severity="SEV2",
        estimated_users_affected=1200,
        business_impact_notes="Latency degradation for login API",
        risk_score=55,
    )
    assert ia.risk_score == 55
    data = ia.model_dump()
    assert data["risk_score"] == 55
