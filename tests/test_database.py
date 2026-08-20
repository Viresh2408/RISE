import os
import sys
import uuid
import threading
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import ProgrammingError, DBAPIError

try:
    from psycopg2.errors import InsufficientPrivilege
except ImportError:
    InsufficientPrivilege = DBAPIError

sys.path.insert(0, os.path.abspath("packages/rise-core"))
sys.path.insert(0, os.path.abspath("."))

from db.models import (
    Base,
    Tenant,
    User,
    Service,
    ServiceDependency,
    Incident,
    IncidentEvent,
    AgentRun,
    AgentStepResult,
    RootCause,
    Evidence,
    ImpactAssessment,
    RiskPolicy,
    RemediationAction,
    Approval,
    ExecutionLog,
    VerificationResult,
    KnowledgeEntry,
    Comment,
    IntegrationConfig,
    AuditEvent,
    create_audit_event,
    verify_hash_chain,
    compute_tenant_genesis_hash,
)

SUPERUSER_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rise_dev")
APP_USER_URL = os.getenv("APP_DATABASE_URL", "postgresql://rise_app:rise_app_pass@localhost:5432/rise_dev")

pytestmark = pytest.mark.integration

engine_super = create_engine(SUPERUSER_URL, pool_pre_ping=True)
SessionSuper = sessionmaker(autocommit=False, autoflush=False, bind=engine_super)

engine_app = create_engine(APP_USER_URL, pool_pre_ping=True)
SessionApp = sessionmaker(autocommit=False, autoflush=False, bind=engine_app)


def test_1_create_one_row_every_table_and_fk_resolution():
    """Confirms 1 row created in all 20 tables and FKs resolve successfully."""
    session: Session = SessionSuper()
    try:
        # 1. Tenant
        tenant = Tenant(name="Acme Corp")
        session.add(tenant)
        session.flush()

        # 2. User
        user = User(tenant_id=tenant.id, email="alice@acme.com", role="admin")
        session.add(user)
        session.flush()

        # 3. Service
        svc_a = Service(tenant_id=tenant.id, name="api-gateway", environment="production")
        svc_b = Service(tenant_id=tenant.id, name="auth-service", environment="production")
        session.add_all([svc_a, svc_b])
        session.flush()

        # 4. ServiceDependency
        svc_dep = ServiceDependency(tenant_id=tenant.id, service_id=svc_a.id, depends_on_service_id=svc_b.id)
        session.add(svc_dep)
        session.flush()

        # 5. Incident
        incident = Incident(
            tenant_id=tenant.id,
            title="High Latency on API Gateway",
            description="504 Gateway Timeout spike",
            status="investigating",
            severity="SEV-1",
            affected_service_id=svc_a.id,
        )
        session.add(incident)
        session.flush()

        # 6. IncidentEvent
        inc_evt = IncidentEvent(
            tenant_id=tenant.id,
            incident_id=incident.id,
            source="datadog",
            raw_payload={"metric": "latency", "value": 1500},
        )
        session.add(inc_evt)
        session.flush()

        # 7. AgentRun
        agent_run = AgentRun(
            tenant_id=tenant.id,
            incident_id=incident.id,
            trigger_type="auto_triage",
            status="running",
        )
        session.add(agent_run)
        session.flush()

        # 8. AgentStepResult
        step_res = AgentStepResult(
            tenant_id=tenant.id,
            agent_run_id=agent_run.id,
            agent_name="LogAnalyzerAgent",
            input={"query": "error log"},
            output={"found": "database pool exhaustion"},
            confidence=0.92,
            duration_ms=350,
        )
        session.add(step_res)
        session.flush()

        # 9. RootCause
        root_cause = RootCause(
            tenant_id=tenant.id,
            incident_id=incident.id,
            cause_summary="Connection pool exhausted in auth-service",
            confidence=0.95,
        )
        session.add(root_cause)
        session.flush()

        # 10. Evidence
        evidence = Evidence(
            tenant_id=tenant.id,
            root_cause_id=root_cause.id,
            type="log_excerpt",
            reference="auth-service log #4892",
            excerpt="FATAL: remaining connection slots are reserved for non-replication superuser connections",
        )
        session.add(evidence)
        session.flush()

        # 11. ImpactAssessment
        impact = ImpactAssessment(
            tenant_id=tenant.id,
            incident_id=incident.id,
            blast_radius_services={"services": ["api-gateway", "auth-service"]},
            severity="SEV-1",
            estimated_users_affected=5000,
            business_impact_notes="Intermittent login failures",
        )
        session.add(impact)
        session.flush()

        # 12. RiskPolicy
        risk_policy = RiskPolicy(
            tenant_id=tenant.id,
            action_pattern="restart_service",
            environment="production",
            risk_tier="LOW",
            requires_approval=False,
            version=1,
            active=True,
        )
        session.add(risk_policy)
        session.flush()

        # 13. RemediationAction
        rem_action = RemediationAction(
            tenant_id=tenant.id,
            incident_id=incident.id,
            action_type="restart_service",
            action_plan={"target": "auth-service"},
            risk_tier="LOW",
            risk_policy_id=risk_policy.id,
            status="pending_approval",
        )
        session.add(rem_action)
        session.flush()

        # 14. Approval
        approval = Approval(
            tenant_id=tenant.id,
            action_id=rem_action.id,
            user_id=user.id,
            decision="approved",
            note="Restart approved by SRE lead",
            plan_hash="sha256_mock_hash",
        )
        session.add(approval)
        session.flush()

        # 15. ExecutionLog
        exec_log = ExecutionLog(
            tenant_id=tenant.id,
            action_id=rem_action.id,
            status="success",
            result={"restarted": True, "pod": "auth-service-78f9d"},
        )
        session.add(exec_log)
        session.flush()

        # 16. VerificationResult
        ver_result = VerificationResult(
            tenant_id=tenant.id,
            incident_id=incident.id,
            status="passed",
            checks={"latency_p99_ms": 45, "error_rate": 0.0},
        )
        session.add(ver_result)
        session.flush()

        # 17. KnowledgeEntry
        kn_entry = KnowledgeEntry(
            tenant_id=tenant.id,
            derived_incident_id=incident.id,
            title="Auth Service Pool Exhaustion Resolution",
            content="Increase max_connections and restart auth pods during traffic spikes",
            vector_id="vec_12345",
            tags=["auth", "postgres", "pool"],
        )
        session.add(kn_entry)
        session.flush()

        # 18. Comment
        comment = Comment(
            tenant_id=tenant.id,
            incident_id=incident.id,
            user_id=user.id,
            text="Service restored to normal operation",
        )
        session.add(comment)
        session.flush()

        # 19. IntegrationConfig
        integ_config = IntegrationConfig(
            tenant_id=tenant.id,
            type="pagerduty",
            status="active",
            credential_ref="arn:aws:secretsmanager:us-east-1:123456789:secret:pd_key",
            scopes={"read": True, "write": True},
        )
        session.add(integ_config)
        session.flush()

        # 20. AuditEvent
        audit_evt = create_audit_event(
            session=session,
            tenant_id=tenant.id,
            actor="alice@acme.com",
            action="resolve_incident",
            before_state={"status": "investigating"},
            after_state={"status": "resolved"},
            incident_id=incident.id,
        )
        session.flush()

        session.commit()

        # Verify all 20 tables exist and have count >= 1
        tables = [
            Tenant, User, Service, ServiceDependency, Incident, IncidentEvent,
            AgentRun, AgentStepResult, RootCause, Evidence, ImpactAssessment,
            RiskPolicy, RemediationAction, Approval, ExecutionLog, VerificationResult,
            KnowledgeEntry, Comment, IntegrationConfig, AuditEvent
        ]
        for model in tables:
            cnt = session.query(model).count()
            assert cnt >= 1, f"Table {model.__tablename__} is empty!"

    finally:
        session.close()


def test_2_rls_tenant_isolation():
    """Confirms cross-tenant query returns zero rows under RLS policies when connected as app user role."""
    session_super: Session = SessionSuper()
    try:
        tenant_a = Tenant(name="Tenant A")
        tenant_b = Tenant(name="Tenant B")
        session_super.add_all([tenant_a, tenant_b])
        session_super.commit()

        inc_a = Incident(
            tenant_id=tenant_a.id,
            title="Tenant A Incident",
            status="open",
            severity="SEV-2",
        )
        session_super.add(inc_a)
        session_super.commit()

        tenant_a_id_str = str(tenant_a.id)
        tenant_b_id_str = str(tenant_b.id)
    finally:
        session_super.close()

    # Connect as rise_app role subject to RLS enforcement
    session_app: Session = SessionApp()
    try:
        # Set session context to Tenant B
        session_app.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, false)"),
            {"tid": tenant_b_id_str},
        )

        # Query incidents when scoped to Tenant B -> should return 0 rows
        incidents_b = session_app.query(Incident).all()
        assert len(incidents_b) == 0, f"Tenant B should see 0 incidents, but saw {len(incidents_b)}"

        # Set session context to Tenant A
        session_app.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, false)"),
            {"tid": tenant_a_id_str},
        )
        incidents_a = session_app.query(Incident).all()
        assert len(incidents_a) >= 1, "Tenant A should see its incident"

    finally:
        session_app.close()


def test_3_audit_events_immutability_for_app_role():
    """Confirms rise_app role has NO UPDATE or DELETE grants on audit_events."""
    session_super = SessionSuper()
    try:
        tenant = Tenant(name="Immutability Test Tenant")
        session_super.add(tenant)
        session_super.commit()

        audit = create_audit_event(
            session=session_super,
            tenant_id=tenant.id,
            actor="test_user",
            action="test_action",
        )
        session_super.commit()
        audit_id_str = str(audit.id)
        tenant_id_str = str(tenant.id)
    finally:
        session_super.close()

    session_app: Session = SessionApp()
    try:
        # Set session tenant_id so RLS doesn't hide the row
        session_app.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, false)"),
            {"tid": tenant_id_str},
        )

        # Attempt UPDATE as rise_app -> expecting permission denied
        with pytest.raises((ProgrammingError, DBAPIError, InsufficientPrivilege)):
            session_app.execute(
                text("UPDATE audit_events SET action = 'tampered' WHERE id = :id"),
                {"id": audit_id_str},
            )
            session_app.commit()

        session_app.rollback()

        # Attempt DELETE as rise_app -> expecting permission denied
        with pytest.raises((ProgrammingError, DBAPIError, InsufficientPrivilege)):
            session_app.execute(
                text("DELETE FROM audit_events WHERE id = :id"),
                {"id": audit_id_str},
            )
            session_app.commit()

    finally:
        session_app.close()


def test_4_superuser_tamper_detection_via_hash_chain():
    """Directly UPDATE an audit_events row as superuser and verify verify_hash_chain detects tamper."""
    session: Session = SessionSuper()
    try:
        tenant = Tenant(name="Hash Chain Tamper Tenant")
        session.add(tenant)
        session.commit()

        # Create 3 audit events
        e1 = create_audit_event(session, tenant.id, actor="user1", action="action1")
        session.commit()
        e2 = create_audit_event(session, tenant.id, actor="user2", action="action2")
        session.commit()
        e3 = create_audit_event(session, tenant.id, actor="user3", action="action3")
        session.commit()

        # Verify chain is valid initially
        valid, bad_event, msg = verify_hash_chain(session, tenant.id)
        assert valid is True, f"Initial chain should be valid: {msg}"

        # Superuser tampers with middle event e2 action field directly via SQL
        session.execute(
            text("UPDATE audit_events SET action = 'MALICIOUS_TAMPER' WHERE id = :id"),
            {"id": str(e2.id)},
        )
        session.commit()

        # Run hash chain verification -> must detect tampered row
        valid_after, bad_event_after, msg_after = verify_hash_chain(session, tenant.id)
        assert valid_after is False, "Hash chain verification MUST flag tampered row!"
        assert bad_event_after is not None
        assert bad_event_after.id == e2.id
        assert "Hash mismatch" in msg_after

    finally:
        session.close()


def test_5_concurrent_audit_event_writes_chain_linearity():
    """Confirms concurrent audit writes for the same tenant produce a linear hash chain (no fork)."""
    tenant_id = None
    session_init = SessionSuper()
    try:
        tenant = Tenant(name="Concurrent Audit Tenant")
        session_init.add(tenant)
        session_init.commit()
        tenant_id = tenant.id
    finally:
        session_init.close()

    errors = []

    def worker(worker_id: int):
        sess = SessionSuper()
        try:
            for i in range(5):
                create_audit_event(
                    session=sess,
                    tenant_id=tenant_id,
                    actor=f"worker_{worker_id}",
                    action=f"action_{i}",
                )
                sess.commit()
        except Exception as ex:
            errors.append(ex)
        finally:
            sess.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent workers encountered errors: {errors}"

    session_verify = SessionSuper()
    try:
        valid, bad_event, msg = verify_hash_chain(session_verify, tenant_id)
        assert valid is True, f"Concurrent hash chain failed verification: {msg}"
        cnt = session_verify.query(AuditEvent).filter(AuditEvent.tenant_id == tenant_id).count()
        assert cnt == 15, f"Expected 15 audit events, found {cnt}"
    finally:
        session_verify.close()
