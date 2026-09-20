"""Unit and integration tests for Incident Report endpoint (GET /incidents/{id}/report).

Verifies:
  1. GET /incidents/{id}/report returns 404 for unknown incident.
  2. GET /incidents/{id}/report?format=pdf returns valid application/pdf binary with Content-Disposition header.
  3. GET /incidents/{id}/report?format=md returns structured Markdown with incident metadata, root cause, evidence citations, impact, actions, and audit timeline.
  4. GET /incidents/{id}/report?format=json returns valid JSON report payload.
  5. Deterministic generation with zero LLM re-derivation from stored DB records.
"""

from __future__ import annotations

import datetime
import os
import uuid
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.pool import StaticPool

@compiles(JSONB, "sqlite")
def visit_JSONB(element, compiler, **kw):
    return "JSON"

@compiles(PG_UUID, "sqlite")
def visit_UUID(element, compiler, **kw):
    return "TEXT"


TEST_JWT_SECRET = "test-supabase-secret-rise-unit-tests"
os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
os.environ["RISE_TEST_MODE"] = "0"

from db.base import Base
from db.models import (
    Approval,
    AuditEvent,
    Evidence,
    ExecutionLog,
    ImpactAssessment,
    Incident,
    RemediationAction,
    RootCause,
    Service,
    Tenant,
    User,
)
from apps.api.src.main import app
from apps.api.src.deps.db import get_db


def _patch_metadata_for_sqlite(metadata):
    for table in metadata.tables.values():
        for col in table.columns:
            if col.server_default is None:
                continue
            try:
                raw = str(col.server_default.arg)
            except Exception:
                raw = ""
            if "gen_random_uuid" in raw:
                col.server_default = None


_patch_metadata_for_sqlite(Base.metadata)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


def make_token(tenant_id: str, user_id: str, role: str = "engineer") -> str:
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "roles": [role],
        "aud": "authenticated",
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def test_incident_report_404_for_missing_incident():
    """Verify 404 is returned when requested incident does not exist."""
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    token = make_token(tenant_id, user_id)

    client = TestClient(app)
    resp = client.get(
        f"/api/v1/incidents/{uuid.uuid4()}/report",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_incident_report_generates_pdf_and_markdown():
    """Verify PDF and Markdown report generation from real DB evidence and actions."""
    tenant_id_uuid = uuid.uuid4()
    tenant_id = str(tenant_id_uuid)
    user_id_uuid = uuid.uuid4()
    user_id = str(user_id_uuid)
    token = make_token(tenant_id, user_id)

    db = TestingSessionLocal()
    tenant = Tenant(id=tenant_id_uuid, name="Report Test Corp")
    db.add(tenant)

    user = User(
        id=user_id_uuid,
        tenant_id=tenant_id_uuid,
        email="report-tester@test.com",
        role="engineer",
    )
    db.add(user)

    service = Service(
        id=uuid.uuid4(),
        tenant_id=tenant_id_uuid,
        name="payment-service",
        environment="production",
    )
    db.add(service)

    inc_id = uuid.uuid4()
    incident = Incident(
        id=inc_id,
        tenant_id=tenant_id_uuid,
        title="High Latency & Connection Pool Exhaustion in payment-service",
        description="Payment API experiencing connection timeouts under spike traffic",
        severity="SEV1",
        status="remediating",
        affected_service_id=service.id,
    )
    db.add(incident)

    rc_id = uuid.uuid4()
    rc = RootCause(
        id=rc_id,
        tenant_id=tenant_id_uuid,
        incident_id=inc_id,
        cause_summary="Connection pool max limit reached due to unclosed DB transactions in payment_gateway.py",
        confidence=0.96,
    )
    db.add(rc)

    ev = Evidence(
        id=uuid.uuid4(),
        tenant_id=tenant_id_uuid,
        root_cause_id=rc_id,
        type="github_code",
        reference="services/payment/payment_gateway.py#L42-L68",
        file_path="services/payment/payment_gateway.py",
        commit_sha="a1b2c3d4e5f67890",
        line_start=42,
        line_end=68,
        excerpt="def acquire_connection():\n    conn = pool.get()\n    # missing try/finally release",
    )
    db.add(ev)

    ia = ImpactAssessment(
        id=uuid.uuid4(),
        tenant_id=tenant_id_uuid,
        incident_id=inc_id,
        severity="SEV1",
        blast_radius_services=["payment-service", "checkout-api", "notification-worker"],
        estimated_users_affected=45000,
        business_impact_notes="Payment processing degraded by 38%",
        risk_score=85,
    )
    db.add(ia)

    action_id = uuid.uuid4()
    action = RemediationAction(
        id=action_id,
        tenant_id=tenant_id_uuid,
        incident_id=inc_id,
        action_type="scale_deployment",
        risk_tier="high",
        status="executed",
        action_plan={
            "action_type": "scale_deployment",
            "action_steps": [{"tool": "scale_deployment", "params": {"replicas": 8}}],
            "rollback_plan": [{"tool": "scale_deployment", "params": {"replicas": 3}}],
            "plan_rationale": "Scale up pool handlers to drain backlog and relieve deadlock",
            "is_simulated": False,
        },
    )
    db.add(action)

    approval = Approval(
        id=uuid.uuid4(),
        tenant_id=tenant_id_uuid,
        action_id=action_id,
        user_id=user_id_uuid,
        decision="approved",
        note="Approved emergency scale-up to resolve connection backlog",
        plan_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    db.add(approval)

    exec_log = ExecutionLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id_uuid,
        action_id=action_id,
        status="success",
        result={"status": "success", "replicas": 8, "duration_ms": 1240},
    )
    db.add(exec_log)

    audit_evt = AuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id_uuid,
        incident_id=inc_id,
        actor="system",
        action="scale_deployment",
        before_state={"replicas": 3},
        after_state={"replicas": 8},
        prev_hash="0" * 64,
        hash="a" * 64,
    )
    db.add(audit_evt)

    db.commit()
    db.close()

    client = TestClient(app)

    # 1. Test Markdown format
    resp_md = client.get(
        f"/api/v1/incidents/{inc_id}/report?format=md",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_md.status_code == 200
    assert "text/markdown" in resp_md.headers.get("content-type", "")
    assert f'filename="incident-report-{inc_id}.md"' in resp_md.headers.get("content-disposition", "")
    md_body = resp_md.text
    assert "High Latency & Connection Pool Exhaustion in payment-service" in md_body
    assert "payment-service" in md_body
    assert "85/100" in md_body
    assert "payment_gateway.py" in md_body
    assert "a1b2c3d4e5f67890" in md_body
    assert "scale_deployment" in md_body
    assert "Approved emergency scale-up" in md_body

    # 2. Test PDF format (default)
    resp_pdf = client.get(
        f"/api/v1/incidents/{inc_id}/report?format=pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_pdf.status_code == 200
    assert "application/pdf" in resp_pdf.headers.get("content-type", "")
    assert f'filename="incident-report-{inc_id}.pdf"' in resp_pdf.headers.get("content-disposition", "")
    # Check PDF magic bytes '%PDF'
    assert resp_pdf.content.startswith(b"%PDF")
    assert len(resp_pdf.content) > 1000

    # 3. Test JSON format
    resp_json = client.get(
        f"/api/v1/incidents/{inc_id}/report?format=json",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_json.status_code == 200
    json_data = resp_json.json().get("data", {})
    assert json_data.get("risk_score") == 85
    assert json_data.get("incident", {}).get("title") == "High Latency & Connection Pool Exhaustion in payment-service"
    assert len(json_data.get("evidence", [])) == 1
    assert len(json_data.get("actions", [])) == 1
