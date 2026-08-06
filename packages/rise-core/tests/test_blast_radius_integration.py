"""Integration tests for topology.blast_radius.

Tests:
  1. Multi-tenant isolation with colliding/overlapping service IDs across two distinct tenants:
     - Verifies zero cross-tenant data leakage in blast_radius() output.
     - Confirms SQL query filtering happens at the DB level (WHERE tenant_id = :tid).
  2. Missing service_id guardrail:
     - Calling blast_radius() for a service_id not present in the tenant's topology graph
       returns topology_missing=True (high-impact guardrail).
  3. Immutability of affected_services:
     - Asserts affected_services is a tuple and rejects in-place mutation attempts.

Uses Testcontainers (PostgresContainer) when Docker daemon is running, with an
in-memory SQLite session fixture fallback for non-containerized execution.

Run with::

    cd packages/rise-core
    python -m pytest tests/test_blast_radius_integration.py -v
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import Column, Engine, String, Table, Text, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

# Ensure package root is on path.
_pkg_root = Path(__file__).parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from topology.blast_radius import BlastRadiusResult, blast_radius


# ---------------------------------------------------------------------------
# Database Fixture (Testcontainers with SQLite fallback)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_engine() -> Generator[Engine, None, None]:
    """Provide a SQLAlchemy Engine using Testcontainers Postgres if available, else SQLite."""
    use_container = False
    container = None

    # Check if Testcontainers can connect to Docker
    try:
        from testcontainers.postgres import PostgresContainer
        container = PostgresContainer("postgres:16-alpine")
        container.start()
        use_container = True
        connection_url = container.get_connection_url()
        engine = create_engine(connection_url, pool_pre_ping=True)
    except Exception:
        # Fallback to in-memory SQLite for test execution when Docker engine is offline
        engine = create_engine("sqlite:///:memory:", echo=False)

    # Initialize schema
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS service_dependencies (
                    id VARCHAR(36) PRIMARY KEY,
                    tenant_id VARCHAR(36) NOT NULL,
                    service_id VARCHAR(36) NOT NULL,
                    depends_on_service_id VARCHAR(36) NOT NULL
                );
                """
            )
        )

    yield engine

    if use_container and container is not None:
        try:
            container.stop()
        except Exception:
            pass
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    """Provide a clean DB session rolled back after each test."""
    SessionMaker = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = SessionMaker()
    
    # Clear table before test
    session.execute(text("DELETE FROM service_dependencies;"))
    session.commit()

    yield session

    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# Integration Test Cases
# ---------------------------------------------------------------------------

class TestMultiTenantIsolation:
    """Confirms tenant isolation at the database query level and zero cross-tenant leakage."""

    def test_multi_tenant_isolation_and_sql_where_clause(
        self, db_session: Session, db_engine: Engine
    ) -> None:
        """Seed 2 tenants with colliding service_id 'svc-shared-db'.

        Tenant 1 Topology:
            svc-api-t1 depends on svc-shared-db
            (Edge in tenant 1: service_id=svc-api-t1, depends_on_service_id=svc-shared-db)

        Tenant 2 Topology:
            svc-worker-t2 depends on svc-shared-db
            svc-analytics-t2 depends on svc-shared-db
            (Edges in tenant 2: service_id=svc-worker-t2, depends_on=svc-shared-db;
                              service_id=svc-analytics-t2, depends_on=svc-shared-db)

        Call blast_radius('svc-shared-db', tenant_id=t1):
          Must return ONLY ('svc-api-t1',).
          Must NOT include 'svc-worker-t2' or 'svc-analytics-t2'.
        """
        tenant_1 = str(uuid.uuid4())
        tenant_2 = str(uuid.uuid4())

        shared_service_id = "svc-shared-db"
        t1_api = "svc-api-t1"
        t2_worker = "svc-worker-t2"
        t2_analytics = "svc-analytics-t2"

        # Seed Tenant 1 dependency
        db_session.execute(
            text(
                "INSERT INTO service_dependencies (id, tenant_id, service_id, depends_on_service_id) "
                "VALUES (:id, :tid, :sid, :dep_id)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_1,
                "sid": t1_api,
                "dep_id": shared_service_id,
            },
        )

        # Seed Tenant 2 dependencies (colliding service_id = svc-shared-db)
        db_session.execute(
            text(
                "INSERT INTO service_dependencies (id, tenant_id, service_id, depends_on_service_id) "
                "VALUES (:id, :tid, :sid, :dep_id)"
            ),
            [
                {
                    "id": str(uuid.uuid4()),
                    "tid": tenant_2,
                    "sid": t2_worker,
                    "dep_id": shared_service_id,
                },
                {
                    "id": str(uuid.uuid4()),
                    "tid": tenant_2,
                    "sid": t2_analytics,
                    "dep_id": shared_service_id,
                },
            ],
        )
        db_session.commit()

        # Track executed SQL statements to confirm DB-level WHERE clause filtering
        executed_sqls: list[str] = []

        def capture_sql(conn, cursor, statement, parameters, context, executemany):
            executed_sqls.append(statement)

        event.listen(db_engine, "before_cursor_execute", capture_sql)

        try:
            # Act: query blast radius for tenant 1
            res_t1 = blast_radius(
                shared_service_id, session=db_session, tenant_id=tenant_1
            )

            # Act: query blast radius for tenant 2
            res_t2 = blast_radius(
                shared_service_id, session=db_session, tenant_id=tenant_2
            )
        finally:
            event.remove(db_engine, "before_cursor_execute", capture_sql)

        # Assert zero cross-tenant leakage
        assert res_t1.affected_services == (t1_api,), (
            f"Tenant 1 blast radius leaked tenant 2 data: {res_t1.affected_services}"
        )
        assert res_t1.topology_missing is False
        assert t2_worker not in res_t1.affected_services
        assert t2_analytics not in res_t1.affected_services

        assert res_t2.affected_services == tuple(sorted([t2_analytics, t2_worker]))
        assert res_t2.topology_missing is False
        assert t1_api not in res_t2.affected_services

        # Assert SQL query filtering by tenant_id at the DB level
        assert len(executed_sqls) >= 2
        for sql in executed_sqls:
            assert "WHERE tenant_id =" in sql, (
                "SQL query must filter by tenant_id at the database level in the WHERE clause, "
                f"got query: {sql}"
            )


class TestMissingServiceGuardrail:
    """Verifies that a service_id not present in the topology triggers high-impact guardrail."""

    def test_service_not_in_topology_returns_missing_topology_guardrail(
        self, db_session: Session
    ) -> None:
        tenant_id = str(uuid.uuid4())
        existing_service = "svc-existing-1"
        dependent_service = "svc-dependent-1"

        # Seed topology for tenant_id
        db_session.execute(
            text(
                "INSERT INTO service_dependencies (id, tenant_id, service_id, depends_on_service_id) "
                "VALUES (:id, :tid, :sid, :dep_id)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "sid": dependent_service,
                "dep_id": existing_service,
            },
        )
        db_session.commit()

        # Query a service_id that is NOT present in the topology graph at all
        unmapped_service_id = "svc-ghost-not-in-graph"

        res = blast_radius(unmapped_service_id, session=db_session, tenant_id=tenant_id)

        assert res.topology_missing is True, (
            "Service ID not in topology must set topology_missing=True so caller "
            "defaults to high-impact guardrail."
        )
        assert res.affected_services == ()
        assert res.hop_count == 0


class TestAffectedServicesImmutability:
    """Verifies affected_services is immutable at runtime."""

    def test_affected_services_is_tuple_and_rejects_mutation(
        self, db_session: Session
    ) -> None:
        tenant_id = str(uuid.uuid4())
        svc_a = "svc-a"
        svc_b = "svc-b"

        db_session.execute(
            text(
                "INSERT INTO service_dependencies (id, tenant_id, service_id, depends_on_service_id) "
                "VALUES (:id, :tid, :sid, :dep_id)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "sid": svc_a,
                "dep_id": svc_b,
            },
        )
        db_session.commit()

        res = blast_radius(svc_b, session=db_session, tenant_id=tenant_id)

        assert isinstance(res.affected_services, tuple)
        assert res.affected_services == (svc_a,)

        # Mutation attempts must raise errors
        with pytest.raises(AttributeError):
            res.affected_services.append("svc-malicious")  # type: ignore[attr-defined]

        with pytest.raises(TypeError):
            res.affected_services[0] = "svc-malicious"  # type: ignore[index]
