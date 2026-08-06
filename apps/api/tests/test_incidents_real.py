"""Real DB and Audit Log Integration Tests for Incident Endpoints.

Tests:
1. POST /incidents creates an incident and writes exactly 1 audit event (incident.created)
   with correct actor, before_state=None, after_state containing incident data.
2. Auto-created Service flag: POST /incidents with unknown service creates Service with is_auto_created=True.
3. PATCH /incidents/{id} updates incident and writes exactly 1 audit event (incident.updated)
   with before_state and after_state recorded.
4. POST /incidents/{id}/comment adds comment and writes exactly 1 audit event (incident.comment_added).
5. Hash chain tampering: Write 3 audit events in sequence, tamper with event #2 manually,
   and verify that verify_hash_chain() (and verify_chain.py logic) detects the tampering.
6. Audit row check: Confirm every mutating call produces exactly one audit row and no commit
   occurs without audit recording.
7. Concurrent audit chain (Postgres only): Fire two simultaneous POST /incidents for the same
   tenant and verify the resulting audit event chain is strictly linear (not forked) — i.e.,
   each event's prev_hash equals the previous event's hash.  This validates that the
   SELECT … FOR UPDATE locking in create_audit_event() prevents a race condition where two
   writers compute the same prev_hash and create a fork.
   Skipped automatically when the PG_TEST_URL environment variable is not set.
"""

from __future__ import annotations

import os
import time
import uuid
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.types import JSON, String

from sqlalchemy.pool import StaticPool

# Register SQLite compilers for PostgreSQL-specific types JSONB and UUID
@compiles(JSONB)
def visit_JSONB(element, compiler, **kw):
    return "JSON"

@compiles(PG_UUID)
def visit_UUID(element, compiler, **kw):
    return "TEXT"


TEST_JWT_SECRET = "test-supabase-secret-rise-unit-tests"
os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
os.environ["RISE_TEST_MODE"] = "0"

import sqlalchemy as _sa

from db.base import Base
from db.models import AuditEvent, Incident, Service, Comment, Tenant, User, verify_hash_chain
from apps.api.src.main import app
from apps.api.src.deps.db import get_db



def _patch_metadata_for_sqlite(metadata):
    """Strip Postgres-only server_defaults from the SQLAlchemy metadata for SQLite.

    gen_random_uuid() is a Postgres-only DDL expression; SQLite does not understand it
    and raises a syntax error during create_all().  Since every UUID column also declares
    a Python-side ``default=uuid.uuid4`` on the mapped_column(), stripping the
    server_default is safe: SQLAlchemy will use the Python default on INSERT, and the
    tests don't need the DB to generate the UUID independently.
    """
    for table in metadata.tables.values():
        for col in table.columns:
            if col.server_default is None:
                continue
            try:
                raw = str(col.server_default.arg)
            except Exception:
                raw = ""
            # Remove Postgres-only UUID generator — Python-side default=uuid.uuid4 handles it.
            if "gen_random_uuid" in raw:
                col.server_default = None


_patch_metadata_for_sqlite(Base.metadata)



# Create SQLite in-memory engine with StaticPool so all connections share the same database
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


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app, raise_server_exceptions=True)

TEST_TENANT_ID = "11111111-2222-3333-4444-555555555555"
TEST_USER_ID = "aaaa1111-bb22-cc33-dd44-eeee55555555"


def _make_token(role: str = "engineer", tenant_id: str = TEST_TENANT_ID, user_id: str = TEST_USER_ID) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "roles": [role],
            "tenant_id": tenant_id,
            "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0))),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _setup_tenant_and_user(db_session):
    t_uuid = uuid.UUID(TEST_TENANT_ID)
    u_uuid = uuid.UUID(TEST_USER_ID)
    
    existing_tenant = db_session.execute(select(Tenant).where(Tenant.id == t_uuid)).scalar_one_or_none()
    if not existing_tenant:
        tenant = Tenant(id=t_uuid, name="Test Tenant")
        db_session.add(tenant)
        db_session.flush()

    existing_user = db_session.execute(select(User).where(User.id == u_uuid)).scalar_one_or_none()
    if not existing_user:
        user = User(id=u_uuid, tenant_id=t_uuid, email="engineer@test.com", role="engineer")
        db_session.add(user)
        db_session.flush()
        
    db_session.commit()


@pytest.fixture(autouse=True)
def prepare_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    _setup_tenant_and_user(db)
    db.close()


def test_create_incident_writes_single_audit_event_and_flags_auto_created_service():
    headers = {"Authorization": f"Bearer {_make_token('engineer')}"}
    payload = {
        "title": "Database High Memory Usage",
        "description": "RAM usage hit 95% on postgres-primary",
        "severity": "SEV1",
        "affected_service": "db-primary-svc",
    }

    db = TestingSessionLocal()
    initial_audit_count = len(db.execute(select(AuditEvent).where(AuditEvent.tenant_id == uuid.UUID(TEST_TENANT_ID))).scalars().all())
    db.close()

    response = client.post("/api/v1/incidents", headers=headers, json=payload)
    assert response.status_code == 201, f"Status: {response.status_code}, Body: {response.text}"
    res_data = response.json()["data"]
    incident_id = res_data["id"]
    assert res_data["title"] == payload["title"]
    assert res_data["affected_service"] == payload["affected_service"]

    db = TestingSessionLocal()
    # Confirm exactly 1 new audit row appears
    audit_events = db.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == uuid.UUID(TEST_TENANT_ID))
        .order_by(AuditEvent.seq.asc())
    ).scalars().all()

    assert len(audit_events) == initial_audit_count + 1
    new_event = audit_events[-1]
    assert new_event.action == "incident.created"
    assert new_event.actor == f"user:{TEST_USER_ID}"
    assert new_event.before_state is None
    assert new_event.after_state is not None
    assert new_event.after_state["id"] == incident_id
    assert new_event.after_state["title"] == payload["title"]

    # Confirm auto-created Service flag
    svc = db.execute(
        select(Service).where(
            Service.tenant_id == uuid.UUID(TEST_TENANT_ID),
            Service.name == payload["affected_service"],
        )
    ).scalar_one_or_none()
    assert svc is not None
    assert svc.is_auto_created is True
    db.close()


def test_patch_incident_writes_single_audit_event_with_before_and_after_state():
    headers_eng = {"Authorization": f"Bearer {_make_token('engineer')}"}
    headers_app = {"Authorization": f"Bearer {_make_token('approver')}"}

    create_res = client.post(
        "/api/v1/incidents",
        headers=headers_eng,
        json={
            "title": "API Gateway 502 Errors",
            "description": "Spike in 502 Bad Gateway responses",
            "severity": "SEV2",
            "affected_service": "api-gateway",
        },
    )
    incident_id = create_res.json()["data"]["id"]

    db = TestingSessionLocal()
    audit_count_before = len(db.execute(select(AuditEvent).where(AuditEvent.tenant_id == uuid.UUID(TEST_TENANT_ID))).scalars().all())
    db.close()

    patch_res = client.patch(
        f"/api/v1/incidents/{incident_id}",
        headers=headers_app,
        json={"status": "resolved", "resolution_note": "Restarted upstream pods"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["data"]["status"] == "resolved"

    db = TestingSessionLocal()
    audit_events = db.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == uuid.UUID(TEST_TENANT_ID))
        .order_by(AuditEvent.seq.asc())
    ).scalars().all()

    assert len(audit_events) == audit_count_before + 1
    patch_event = audit_events[-1]
    assert patch_event.action == "incident.updated"
    assert patch_event.actor == f"user:{TEST_USER_ID}"
    assert patch_event.before_state["status"] == "open"
    assert patch_event.after_state["status"] == "resolved"
    db.close()


def test_add_comment_writes_single_audit_event():
    headers = {"Authorization": f"Bearer {_make_token('engineer')}"}

    create_res = client.post(
        "/api/v1/incidents",
        headers=headers,
        json={
            "title": "Redis Connection Spike",
            "description": "High connection count on Redis cluster",
            "severity": "SEV3",
            "affected_service": "redis-svc",
        },
    )
    incident_id = create_res.json()["data"]["id"]

    db = TestingSessionLocal()
    audit_count_before = len(db.execute(select(AuditEvent).where(AuditEvent.tenant_id == uuid.UUID(TEST_TENANT_ID))).scalars().all())
    db.close()

    comment_res = client.post(
        f"/api/v1/incidents/{incident_id}/comment",
        headers=headers,
        json={"text": "Investigating connection pool leak in worker nodes"},
    )
    assert comment_res.status_code == 201

    db = TestingSessionLocal()
    audit_events = db.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == uuid.UUID(TEST_TENANT_ID))
        .order_by(AuditEvent.seq.asc())
    ).scalars().all()

    assert len(audit_events) == audit_count_before + 1
    comment_event = audit_events[-1]
    assert comment_event.action == "incident.comment_added"
    assert comment_event.after_state["text"] == "Investigating connection pool leak in worker nodes"
    db.close()


def test_hash_chain_verification_and_tamper_detection():
    headers = {"Authorization": f"Bearer {_make_token('engineer')}"}

    # Step 1: Write 3 mutating calls in sequence
    client.post(
        "/api/v1/incidents",
        headers=headers,
        json={
            "title": "Chain Event 1",
            "description": "First incident",
            "severity": "SEV3",
            "affected_service": "svc-1",
        },
    )
    res2 = client.post(
        "/api/v1/incidents",
        headers=headers,
        json={
            "title": "Chain Event 2",
            "description": "Second incident",
            "severity": "SEV2",
            "affected_service": "svc-2",
        },
    )
    inc2_id = res2.json()["data"]["id"]

    client.post(
        f"/api/v1/incidents/{inc2_id}/comment",
        headers=headers,
        json={"text": "Chain Event 3 - comment"},
    )

    db = TestingSessionLocal()
    tenant_uuid = uuid.UUID(TEST_TENANT_ID)

    # Step 2: Confirm initial hash chain is valid
    valid, bad_evt, msg = verify_hash_chain(db, tenant_uuid)
    assert valid is True, f"Hash chain should be valid initially: {msg}"

    events = db.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_uuid)
        .order_by(AuditEvent.seq.asc())
    ).scalars().all()

    assert len(events) >= 3
    e1, e2, e3 = events[-3], events[-2], events[-1]
    # Check that prev_hash of e2 equals hash of e1, and prev_hash of e3 equals hash of e2
    assert e2.prev_hash == e1.hash
    assert e3.prev_hash == e2.hash

    # Step 3: Tamper with event #2 manually (mutate action field directly)
    e2.action = "TAMPERED_ACTION_MALICIOUS"
    db.add(e2)
    db.commit()

    # Step 4: Verify hash chain fails detection
    valid_after, bad_evt_after, msg_after = verify_hash_chain(db, tenant_uuid)
    assert valid_after is False
    assert bad_evt_after is not None
    assert bad_evt_after.id == e2.id
    assert "Hash mismatch" in msg_after
    db.close()


# ── Concurrent audit chain test (Postgres only) ───────────────────────────────
#
# Requires a real Postgres instance because:
#   - SELECT ... FOR UPDATE is a no-op in SQLite.
#   - True concurrency between two threads sharing a real connection pool is
#     needed to exercise the lock path.
#
# Set PG_TEST_URL to a valid Postgres DSN to enable this test, e.g.:
#   export PG_TEST_URL="postgresql://postgres:postgres@localhost:5432/rise_test"
#
# The test is automatically *skipped* (not failed) when PG_TEST_URL is absent.

import threading

PG_TEST_URL = os.environ.get("PG_TEST_URL", "")
SKIP_PG = not PG_TEST_URL
SKIP_REASON = "PG_TEST_URL not set — requires a live Postgres instance to test SELECT FOR UPDATE"


@pytest.mark.skipif(SKIP_PG, reason=SKIP_REASON)
def test_concurrent_post_incidents_produces_linear_audit_chain():
    """Two concurrent POST /incidents for the same tenant must produce a strictly
    linear audit chain — i.e., every audit event has a unique prev_hash value
    that equals the hash of the immediately preceding event in seq order.

    If SELECT … FOR UPDATE is broken or absent, both threads would read the
    same latest event as their chain tail, compute the *same* prev_hash, and
    insert two events with identical prev_hash values — a detectable fork.
    """
    from sqlalchemy import create_engine as pg_create_engine
    from sqlalchemy.orm import sessionmaker as pg_sessionmaker
    from sqlalchemy.pool import NullPool

    # Use NullPool so each thread gets a fully independent connection,
    # maximising the chance of a race on the audit table.
    pg_engine = pg_create_engine(PG_TEST_URL, poolclass=NullPool)
    PgSession = pg_sessionmaker(bind=pg_engine)

    # Bootstrap a dedicated tenant so this test is isolated from the SQLite suite.
    PG_TENANT_ID = str(uuid.uuid4())
    PG_USER_ID = str(uuid.uuid4())

    setup_db = PgSession()
    try:
        tenant = Tenant(id=uuid.UUID(PG_TENANT_ID), name="PG Concurrent Test Tenant")
        setup_db.add(tenant)
        user = User(
            id=uuid.UUID(PG_USER_ID),
            tenant_id=uuid.UUID(PG_TENANT_ID),
            email="pgtest@example.com",
            role="engineer",
        )
        setup_db.add(user)
        setup_db.commit()
    finally:
        setup_db.close()

    # Build a separate FastAPI TestClient that uses the real Postgres DB.
    from fastapi.testclient import TestClient as PgTestClient
    from apps.api.src.main import app as pg_app

    def pg_get_db():
        db = PgSession()
        try:
            yield db
        finally:
            db.close()

    # Temporarily override get_db for this test only.
    original_override = pg_app.dependency_overrides.get(get_db)
    pg_app.dependency_overrides[get_db] = pg_get_db
    pg_client = PgTestClient(pg_app, raise_server_exceptions=True)

    token = jwt.encode(
        {
            "sub": PG_USER_ID,
            "roles": ["engineer"],
            "tenant_id": PG_TENANT_ID,
            "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0))),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}

    results: list = []
    errors: list = []

    def fire_create(idx: int) -> None:
        try:
            r = pg_client.post(
                "/api/v1/incidents",
                headers=headers,
                json={
                    "title": f"Concurrent Incident {idx}",
                    "description": f"Thread {idx} incident",
                    "severity": "SEV3",
                    "affected_service": f"pg-svc-{idx}",
                },
            )
            results.append(r.status_code)
        except Exception as exc:
            errors.append(str(exc))

    # Fire both threads simultaneously using a Barrier so they start at the same time.
    barrier = threading.Barrier(2, timeout=10)

    def guarded_fire(idx: int) -> None:
        barrier.wait()          # both threads release together
        fire_create(idx)

    t1 = threading.Thread(target=guarded_fire, args=(1,), daemon=True)
    t2 = threading.Thread(target=guarded_fire, args=(2,), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    # Restore the original DB override (important for test isolation).
    if original_override is None:
        pg_app.dependency_overrides.pop(get_db, None)
    else:
        pg_app.dependency_overrides[get_db] = original_override

    assert not errors, f"Thread errors: {errors}"
    assert all(s == 201 for s in results), f"Unexpected statuses: {results}"

    # Now verify the audit chain for the PG tenant is strictly linear.
    verify_db = PgSession()
    try:
        tenant_uuid = uuid.UUID(PG_TENANT_ID)
        events = verify_db.execute(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_uuid)
            .order_by(AuditEvent.seq.asc())
        ).scalars().all()

        # We should have exactly 2 audit events — one per incident.
        assert len(events) == 2, (
            f"Expected 2 audit events, got {len(events)}. "
            "Possible audit chain fork or missing write."
        )

        # The critical assertion: no two events share the same prev_hash.
        # A fork manifests as events[0].prev_hash == events[1].prev_hash.
        prev_hashes = [e.prev_hash for e in events]
        assert len(set(prev_hashes)) == len(prev_hashes), (
            f"FORK DETECTED: two audit events share the same prev_hash: {prev_hashes}. "
            "SELECT FOR UPDATE locking did not serialise concurrent writers!"
        )

        # Additionally verify the full chain integrity (hash chain is valid).
        valid, bad_evt, msg = verify_hash_chain(verify_db, tenant_uuid)
        assert valid, f"Hash chain invalid after concurrent writes: {msg} (event: {bad_evt})"
    finally:
        verify_db.close()
        # Clean up the test tenant to leave the DB tidy.
        cleanup_db = PgSession()
        try:
            cleanup_db.execute(
                Tenant.__table__.delete().where(Tenant.id == uuid.UUID(PG_TENANT_ID))
            )
            cleanup_db.commit()
        finally:
            cleanup_db.close()
        pg_engine.dispose()
