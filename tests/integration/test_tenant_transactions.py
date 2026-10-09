"""Real PostgreSQL RLS/append-only audit contracts under the restricted app role.

Requires a migrated, isolated test database and RISE_INTEGRATION_DATABASE_URL
(admin DSN). RISE_INTEGRATION_APP_PASSWORD defaults to the local migration's
rise_app_pass. No SQLite fallback is accepted for these tests.
"""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import uuid

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from db.models import AuditEvent, Tenant, create_audit_event, verify_hash_chain
from db.session import tenant_session

pytestmark = pytest.mark.integration


@pytest.fixture
def postgres_store():
    dsn = os.getenv("RISE_INTEGRATION_DATABASE_URL")
    if not dsn:
        pytest.skip("Set RISE_INTEGRATION_DATABASE_URL to an isolated migrated PostgreSQL test database")
    url = make_url(dsn)
    assert url.get_backend_name() == "postgresql", "RLS tests require PostgreSQL"
    admin = create_engine(url)
    app_engine = create_engine(
        url.set(username="rise_app", password=os.getenv("RISE_INTEGRATION_APP_PASSWORD", "rise_app_pass")),
        pool_size=2, max_overflow=0, isolation_level="READ COMMITTED",
    )
    owner, foreign = uuid.uuid4(), uuid.uuid4()
    with admin.begin() as connection:
        connection.execute(Tenant.__table__.insert(), [
            {"id": owner, "name": "phase1-rls-owner"},
            {"id": foreign, "name": "phase1-rls-foreign"},
        ])
    try:
        with app_engine.connect() as connection:
            role = connection.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
            assert role == (False, False), "A superuser/BYPASSRLS role cannot certify tenant isolation"
        yield sessionmaker(bind=app_engine), owner, foreign
    finally:
        app_engine.dispose()
        # Teardown only this fixture's generated data in the explicit test DB.
        with admin.begin() as connection:
            connection.execute(delete(AuditEvent).where(AuditEvent.tenant_id.in_([owner, foreign])))
            connection.execute(delete(Tenant).where(Tenant.id.in_([owner, foreign])))
        admin.dispose()


def test_rls_is_reapplied_after_commit_and_rollback_and_cleared_on_exit(postgres_store):
    sessions, owner, foreign = postgres_store
    with sessions() as db:
        with tenant_session(str(owner), db):
            assert db.execute(select(Tenant.id)).scalars().all() == [owner]
            db.commit()
            assert db.execute(select(Tenant.id)).scalars().all() == [owner]
            db.rollback()
            assert db.execute(select(Tenant.id)).scalars().all() == [owner]
        # Borrowed sessions cannot retain a tenant for subsequent unscoped work.
        assert db.execute(select(Tenant.id)).scalars().all() == []
    with sessions() as db:
        with tenant_session(str(foreign), db):
            assert db.execute(select(Tenant.id)).scalars().all() == [foreign]
            db.commit()
            assert db.execute(select(Tenant.id)).scalars().all() == [foreign]


def test_shared_session_cannot_switch_tenants(postgres_store):
    sessions, owner, foreign = postgres_store
    with sessions() as db, tenant_session(str(owner), db):
        assert db.execute(select(Tenant.id)).scalars().all() == [owner]
        with pytest.raises(ValueError, match="already scoped"):
            with tenant_session(str(foreign), db):
                pytest.fail("A scoped session must never yield to a foreign tenant")
        assert db.execute(select(Tenant.id)).scalars().all() == [owner]


def test_concurrent_restricted_role_audit_writers_produce_one_valid_chain(postgres_store):
    sessions, owner, _ = postgres_store
    ready = Barrier(2)

    def write(index: int) -> None:
        with sessions() as db, tenant_session(str(owner), db):
            ready.wait(timeout=10)
            create_audit_event(db, owner, f"system:writer-{index}", "phase1.concurrent_audit")
            db.flush()
            # Hold the tenant lock long enough for the other writer to contend.
            db.execute(text("SELECT pg_sleep(0.05)"))
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(write, index) for index in range(2)]
        for result in results:
            result.result(timeout=20)
    with sessions() as db, tenant_session(str(owner), db):
        events = db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars().all()
        assert len(events) == 2
        assert events[1].prev_hash == events[0].hash
        assert verify_hash_chain(db, owner)[0] is True
