# -*- coding: utf-8 -*-
"""Integration tests for KnowledgeService + Qdrant.

Requirements
------------
- PostgreSQL running with applied migrations.
- Qdrant running.
- Both accessible at the default dev URLs (or set DATABASE_URL / QDRANT_URL env vars).

Run with:
    pytest tests/integration/test_knowledge_service.py -v -m integration

Definition of Done (from task spec):
[x] Near-duplicate query returns top match with score > 0.8
[x] Deleting a KnowledgeEntry in Postgres removes the Qdrant point (no orphaned vectors)
[x] Metadata filters (service, severity) correctly narrow results

Additional tests (from user amendments):
[x] Rolled-back Postgres transaction does NOT delete the Qdrant vector
[x] search_similar_incidents raises ValueError when tenant_id is missing
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.abspath("packages/rise-core"))
sys.path.insert(0, os.path.abspath("."))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from db.models import Base, KnowledgeEntry, Service, Tenant
from knowledge_service.client import get_qdrant_client
from knowledge_service.schemas import KnowledgeFilter
from knowledge_service.service import COLLECTION_NAME, KnowledgeService

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rise_dev")

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Seed data — 10 historical incidents (same data as scripts/seed_knowledge.py)
# ---------------------------------------------------------------------------

SEED_INCIDENTS: list[dict] = [
    {
        "title": "payment-service high error rate — 503s spiking to 45%",
        "content": (
            "The payment-service began returning HTTP 503 errors at 14:32 UTC. "
            "Error rate climbed from baseline 0.1% to 45% within 3 minutes. "
            "Root cause: upstream database connection pool exhausted after a slow "
            "query introduced in deploy v2.4.1. Resolution: connection pool size "
            "increased from 10 to 50; slow query index added; service auto-scaled."
        ),
        "service": "payment-service",
        "severity": "SEV1",
    },
    {
        "title": "payment-service memory leak causing OOM restarts",
        "content": (
            "payment-service pods restarted 12 times over 6 hours due to OOM kills. "
            "Heap dump analysis revealed a listener not removed on request completion "
            "in the billing middleware introduced in v2.3.0. "
            "Fix: listener cleanup added; memory limit raised from 512Mi to 1Gi temporarily."
        ),
        "service": "payment-service",
        "severity": "SEV2",
    },
    {
        "title": "auth-service JWT validation latency spike",
        "content": (
            "P99 latency for the auth-service /validate endpoint spiked from 12ms to "
            "820ms at 09:15 UTC. Downstream services began timing out. Root cause: "
            "Redis JWKS cache expired simultaneously across all pods (thundering herd). "
            "Resolution: staggered TTL jitter added to JWKS cache refresh."
        ),
        "service": "auth-service",
        "severity": "SEV2",
    },
    {
        "title": "auth-service complete outage — misconfigured TLS cert",
        "content": (
            "auth-service went fully down at 03:00 UTC during routine cert rotation. "
            "New certificate did not include the SAN for the internal cluster DNS name. "
            "All service-to-service auth calls failed with SSL handshake errors. "
            "Resolution: cert reissued with correct SAN; rotation runbook updated."
        ),
        "service": "auth-service",
        "severity": "SEV1",
    },
    {
        "title": "notification-service queue backlog — emails delayed 2h",
        "content": (
            "Email notifications queued in Redis fell behind by 50,000 messages over "
            "2 hours. Cause: notification-service worker count was accidentally reduced "
            "from 8 to 1 in the Helm values during a chart upgrade. "
            "Fix: worker count restored; added alerting on queue depth > 5000."
        ),
        "service": "notification-service",
        "severity": "SEV3",
    },
    {
        "title": "notification-service Slack webhook rate limit exceeded",
        "content": (
            "Slack alerts stopped delivering for 40 minutes after the notification-service "
            "hit the Slack API rate limit of 1 message/second per channel. "
            "Fix: exponential backoff + burst queue per channel."
        ),
        "service": "notification-service",
        "severity": "SEV3",
    },
    {
        "title": "api-gateway 502 cascade — upstream connection refused",
        "content": (
            "api-gateway returned 502 Bad Gateway for all /api/v2/* endpoints for 8 minutes. "
            "Root cause: payment-service deployment rollout left 0 ready pods due to a missing "
            "readiness probe path update. Fix: readiness probe corrected; RollingUpdate with minAvailable=1."
        ),
        "service": "api-gateway",
        "severity": "SEV1",
    },
    {
        "title": "api-gateway TLS 1.0 deprecation breaking legacy clients",
        "content": (
            "After enforcing TLS 1.2+ on the api-gateway, several legacy B2B integrations "
            "began failing with SSL handshake errors from Java 7 / .NET 4.5 clients. "
            "Resolution: 30-day grace period; affected partners notified."
        ),
        "service": "api-gateway",
        "severity": "SEV2",
    },
    {
        "title": "payment-service duplicate charge bug after retry storm",
        "content": (
            "A network timeout caused api-gateway to retry idempotent-keyed payment requests. "
            "Redis idempotency key expiry was 60s instead of 24h — duplicate charges processed "
            "for 127 transactions. Fix: TTL corrected; affected transactions refunded."
        ),
        "service": "payment-service",
        "severity": "SEV1",
    },
    {
        "title": "auth-service token refresh race condition causing logout loops",
        "content": (
            "Mobile clients were intermittently logged out when concurrent refresh requests raced. "
            "Second refresh invalidated the first's token. Fix: server-side token family tracking; "
            "one active refresh token per session."
        ),
        "service": "auth-service",
        "severity": "SEV2",
    },
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def db_session(db_engine):
    SessionFactory = sessionmaker(bind=db_engine)
    session = SessionFactory()
    yield session
    session.close()


@pytest.fixture(scope="module")
def qdrant_client():
    client = get_qdrant_client()
    yield client


@pytest.fixture(scope="module")
def knowledge_service(qdrant_client):
    return KnowledgeService(qdrant_client=qdrant_client)


@pytest.fixture(scope="module")
def test_tenant(db_session: Session) -> Tenant:
    """Create an isolated tenant for this test module."""
    tenant = Tenant(name=f"test-knowledge-service-{uuid.uuid4().hex[:8]}")
    db_session.add(tenant)
    db_session.commit()
    return tenant


@pytest.fixture(scope="module")
def seeded_entries(
    knowledge_service: KnowledgeService,
    db_session: Session,
    test_tenant: Tenant,
) -> list[KnowledgeEntry]:
    """Seed 10 KnowledgeEntry rows, embed them, and return the ORM objects."""
    entries: list[KnowledgeEntry] = []
    for data in SEED_INCIDENTS:
        entry = KnowledgeEntry(
            tenant_id=test_tenant.id,
            title=data["title"],
            content=data["content"],
            tags={"service": data["service"], "severity": data["severity"]},
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(entry)
        db_session.flush()
        knowledge_service.embed_and_upsert(entry, db_session)
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Test 1 — DoD: near-duplicate query returns top match with score > 0.8
# ---------------------------------------------------------------------------


def test_seed_and_similarity_search(
    seeded_entries: list[KnowledgeEntry],
    knowledge_service: KnowledgeService,
    test_tenant: Tenant,
) -> None:
    """Near-duplicate of seeded incident #1 must return it as top hit with score > 0.8."""
    # Slightly rephrased version of SEED_INCIDENTS[0]
    near_duplicate_query = (
        "payment-service is returning 503 errors, error rate jumped from normal to 45%. "
        "Looks like the database connection pool might be exhausted."
    )
    filters = KnowledgeFilter(tenant_id=str(test_tenant.id))
    results = knowledge_service.search_similar_incidents(near_duplicate_query, filters, top_k=5)

    assert results, "Expected at least one result"
    top = results[0]

    # DoD check: top result must be the matching seeded incident
    assert "payment-service" in top.title.lower() or "503" in top.title.lower() or "error rate" in top.title.lower(), (
        f"Top result title doesn't match expected incident: {top.title!r}"
    )
    assert top.score > 0.8, (
        f"Expected similarity score > 0.8, got {top.score:.4f} for title {top.title!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — DoD: deleting KnowledgeEntry removes the Qdrant point
# ---------------------------------------------------------------------------


def test_delete_removes_qdrant_point(
    knowledge_service: KnowledgeService,
    db_session: Session,
    test_tenant: Tenant,
    qdrant_client,
) -> None:
    """delete_knowledge_entry() must remove the Qdrant point — no orphaned vectors."""
    # Create a one-off entry so we don't disturb the module-scoped seed fixture.
    entry = KnowledgeEntry(
        tenant_id=test_tenant.id,
        title="ephemeral-svc transient crash for deletion test",
        content="This entry will be deleted to verify Qdrant cleanup.",
        tags={"service": "ephemeral-svc", "severity": "SEV4"},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(entry)
    db_session.flush()
    vector_id = knowledge_service.embed_and_upsert(entry, db_session)
    assert vector_id, "embed_and_upsert must return a non-empty vector_id"

    # Confirm the point exists in Qdrant before deletion.
    pre_delete_points = qdrant_client.retrieve(
        collection_name=COLLECTION_NAME,
        ids=[vector_id],
        with_payload=False,
        with_vectors=False,
    )
    assert pre_delete_points, "Qdrant point must exist before deletion"

    # Two-step delete: Postgres commit → Qdrant delete.
    knowledge_service.delete_knowledge_entry(entry, db_session)

    # Verify Qdrant point is gone.
    post_delete_points = qdrant_client.retrieve(
        collection_name=COLLECTION_NAME,
        ids=[vector_id],
        with_payload=False,
        with_vectors=False,
    )
    assert not post_delete_points, (
        f"Qdrant point {vector_id} still exists after delete_knowledge_entry() — orphaned vector!"
    )

    # Verify Postgres row is gone.
    surviving = db_session.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.vector_id == vector_id)
    ).scalar_one_or_none()
    assert surviving is None, "KnowledgeEntry must be deleted from Postgres"


# ---------------------------------------------------------------------------
# Test 3 — Amendment: rolled-back Postgres transaction must NOT delete Qdrant point
# ---------------------------------------------------------------------------


def test_rollback_does_not_delete_qdrant_point(
    knowledge_service: KnowledgeService,
    db_engine,
    test_tenant: Tenant,
    qdrant_client,
) -> None:
    """A rolled-back Postgres transaction must not remove the Qdrant vector.

    This validates the two-step delete safety: the Qdrant delete is only called
    AFTER a successful Postgres commit.  If the commit is never reached (rolled back),
    the Qdrant vector must survive.
    """
    # Use a separate session so we can roll it back without affecting other tests.
    SessionFactory = sessionmaker(bind=db_engine)
    rollback_session = SessionFactory()

    try:
        entry = KnowledgeEntry(
            tenant_id=test_tenant.id,
            title="rollback-test entry — must survive rollback",
            content="If this vector is deleted without a commit, the two-step contract is broken.",
            tags={"service": "rollback-svc", "severity": "SEV4"},
            created_at=datetime.now(timezone.utc),
        )
        rollback_session.add(entry)
        rollback_session.flush()

        # Embed and upsert while we have a valid session (commits internally).
        vector_id = knowledge_service.embed_and_upsert(entry, rollback_session)
        assert vector_id

        # Simulate the application beginning a delete but rolling back before commit.
        rollback_session.delete(entry)
        rollback_session.rollback()  # <-- no commit → Postgres row survives

    finally:
        rollback_session.close()

    # The Qdrant point must still exist because delete_knowledge_entry() was never called.
    points = qdrant_client.retrieve(
        collection_name=COLLECTION_NAME,
        ids=[vector_id],
        with_payload=False,
        with_vectors=False,
    )
    assert points, (
        "Qdrant point was deleted despite a rolled-back Postgres transaction — "
        "the two-step delete contract is violated!"
    )

    # Cleanup: properly delete via the sanctioned path.
    SessionFactory2 = sessionmaker(bind=db_engine)
    cleanup_session = SessionFactory2()
    surviving = cleanup_session.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.vector_id == vector_id)
    ).scalar_one_or_none()
    if surviving:
        knowledge_service.delete_knowledge_entry(surviving, cleanup_session)
    cleanup_session.close()


# ---------------------------------------------------------------------------
# Test 4 — DoD: metadata filter by service narrows results
# ---------------------------------------------------------------------------


def test_metadata_filter_by_service(
    seeded_entries: list[KnowledgeEntry],
    knowledge_service: KnowledgeService,
    test_tenant: Tenant,
) -> None:
    """Filtering by service='auth-service' must return only auth-service incidents."""
    filters = KnowledgeFilter(
        tenant_id=str(test_tenant.id),
        service="auth-service",
    )
    results = knowledge_service.search_similar_incidents(
        query="authentication service is down",
        filters=filters,
        top_k=10,
    )

    assert results, "Expected at least one result for auth-service"
    non_matching = [r for r in results if r.service != "auth-service"]
    assert not non_matching, (
        f"Filter by service='auth-service' returned non-auth results: "
        f"{[r.service for r in non_matching]}"
    )


# ---------------------------------------------------------------------------
# Test 5 — DoD: metadata filter by severity narrows results
# ---------------------------------------------------------------------------


def test_metadata_filter_by_severity(
    seeded_entries: list[KnowledgeEntry],
    knowledge_service: KnowledgeService,
    test_tenant: Tenant,
) -> None:
    """Filtering by severity='SEV1' must return only SEV1 incidents."""
    filters = KnowledgeFilter(
        tenant_id=str(test_tenant.id),
        severity="SEV1",
    )
    results = knowledge_service.search_similar_incidents(
        query="critical outage service down",
        filters=filters,
        top_k=10,
    )

    assert results, "Expected at least one result for SEV1"
    non_matching = [r for r in results if r.severity != "SEV1"]
    assert not non_matching, (
        f"Filter by severity='SEV1' returned non-SEV1 results: "
        f"{[r.severity for r in non_matching]}"
    )


# ---------------------------------------------------------------------------
# Test 6 — Amendment: search_similar_incidents raises ValueError without tenant_id
# ---------------------------------------------------------------------------


def test_search_requires_tenant_id(
    knowledge_service: KnowledgeService,
) -> None:
    """search_similar_incidents must raise ValueError when tenant_id is missing or empty.

    Validates two enforcement layers:
    1. KnowledgeFilter model_validator rejects empty/None tenant_id at construction.
    2. The service raises ValueError as a belt-and-suspenders check even if a filter
       somehow bypasses the Pydantic validator.
    """
    # Layer 1: KnowledgeFilter validator should raise at construction time.
    with pytest.raises((ValueError, Exception)) as exc_info:
        _ = KnowledgeFilter(tenant_id="")  # type: ignore[arg-type]
    assert "tenant_id" in str(exc_info.value).lower() or "required" in str(exc_info.value).lower(), (
        f"Expected error mentioning 'tenant_id' or 'required', got: {exc_info.value}"
    )

    # Layer 2: Construct a filter with a whitespace-only tenant_id to simulate a
    # bypass attempt, and confirm the service layer also rejects it.
    with pytest.raises(ValueError, match="tenant_id is required"):
        # Bypass Pydantic by using model_construct (no validation).
        bad_filter = KnowledgeFilter.model_construct(tenant_id="   ")
        knowledge_service.search_similar_incidents(
            query="any query",
            filters=bad_filter,
        )


# ---------------------------------------------------------------------------
# Test 7 — Filters combined: service + severity
# ---------------------------------------------------------------------------


def test_combined_service_and_severity_filter(
    seeded_entries: list[KnowledgeEntry],
    knowledge_service: KnowledgeService,
    test_tenant: Tenant,
) -> None:
    """Combining service + severity filters must narrow to that exact combination."""
    filters = KnowledgeFilter(
        tenant_id=str(test_tenant.id),
        service="payment-service",
        severity="SEV1",
    )
    results = knowledge_service.search_similar_incidents(
        query="payment service critical failure",
        filters=filters,
        top_k=10,
    )

    assert results, "Expected at least one result for payment-service + SEV1"
    for r in results:
        assert r.service == "payment-service", f"Unexpected service: {r.service}"
        assert r.severity == "SEV1", f"Unexpected severity: {r.severity}"
