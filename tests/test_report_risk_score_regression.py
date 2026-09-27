"""Regression test for the report-generator risk-score fallback (plan 3.3).

Bug: ``build_incident_report_data`` computed a fallback risk score on the
``risk_score <= 0`` path by calling ``compute_risk_score()`` with the wrong
keyword arguments (``blast_radius_count`` / ``affected_users`` / ``criticality``).
Because ``compute_risk_score`` is keyword-only with a fixed, different signature,
that call raised ``TypeError`` at runtime whenever an incident had no stored
(positive) risk score — i.e. exactly the common "no impact agent run yet" case.

These tests pin the contract:
  1. The old kwargs must still be rejected (documents the faulty signature).
  2. The report builder must traverse the ``risk_score <= 0`` fallback without
     raising and return a positive, deterministic integer score.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID


@compiles(JSONB, "sqlite")
def _visit_jsonb(element, compiler, **kw):  # pragma: no cover - dialect shim
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _visit_uuid(element, compiler, **kw):  # pragma: no cover - dialect shim
    return "TEXT"


from db.base import Base
from db.models import ImpactAssessment, Incident, Tenant
from schemas.agent_state import compute_risk_score
from apps.api.src.services.report_generator import build_incident_report_data


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_incident(db, *, severity: str = "SEV1") -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    inc_id = uuid.uuid4()
    db.add(Tenant(id=tenant_id, name="Regression Tenant"))
    db.flush()
    db.add(Incident(
        id=inc_id,
        tenant_id=tenant_id,
        title="Connection pool exhausted on auth-service",
        description="503s and pool_exhausted errors after deploy.",
        severity=severity,
        status="open",
    ))
    db.commit()
    return tenant_id, inc_id


def test_old_kwargs_still_raise_type_error():
    """The faulty call shape must remain a TypeError (guards against re-introduction)."""
    with pytest.raises(TypeError):
        compute_risk_score(  # type: ignore[call-arg]
            blast_radius_count=2,
            affected_users=1500,
            criticality="SEV1",
        )


def test_fallback_risk_score_computed_without_impact_row(db_session):
    """No ImpactAssessment → risk_score starts at 0 → fallback must compute cleanly."""
    tenant_id, inc_id = _seed_incident(db_session, severity="SEV1")

    data = build_incident_report_data(db_session, tenant_id, inc_id)

    assert data is not None
    assert isinstance(data["risk_score"], int)
    assert data["risk_score"] > 0


def test_fallback_risk_score_when_stored_score_is_zero(db_session):
    """A stored ImpactAssessment with risk_score=0 must still trigger the fallback."""
    tenant_id, inc_id = _seed_incident(db_session, severity="SEV2")
    db_session.add(ImpactAssessment(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        incident_id=inc_id,
        blast_radius_services=["auth-service", "gateway"],
        severity="SEV2",
        estimated_users_affected=800,
        business_impact_notes="",
        risk_score=0,
    ))
    db_session.commit()

    data = build_incident_report_data(db_session, tenant_id, inc_id)

    assert data is not None
    assert isinstance(data["risk_score"], int)
    assert data["risk_score"] > 0
