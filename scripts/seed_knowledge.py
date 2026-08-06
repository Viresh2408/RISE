#!/usr/bin/env python3
"""Seed the knowledge service with 10 historical incidents for local testing.

Usage
-----
    # From the RISE repo root:
    python scripts/seed_knowledge.py

    # Optionally override the DB or Qdrant URLs:
    DATABASE_URL=postgresql://... QDRANT_URL=http://... python scripts/seed_knowledge.py

Prerequisites
-------------
- PostgreSQL running with applied migrations (``alembic upgrade head``).
- Qdrant running (``docker-compose up -d qdrant``).
- A tenant row must exist, or this script creates one.

After seeding you can verify the Qdrant state at:
    http://localhost:6333/dashboard#/collections/incidents_v1
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

# Allow running from repo root without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "rise-core"))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from db.models import KnowledgeEntry, Service, Tenant
from knowledge_service.client import get_qdrant_client
from knowledge_service.service import KnowledgeService

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rise_dev")

# ---------------------------------------------------------------------------
# 10 realistic historical incidents
# (service × severity chosen to exercise all filter combinations in tests)
# ---------------------------------------------------------------------------

HISTORICAL_INCIDENTS: list[dict] = [
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
            "Resolution: cert reissued with correct SAN; rotation runbook updated to "
            "include SAN validation step."
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
            "Impact: transactional emails delayed but not lost. "
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
            "An incident storm (15 simultaneous alerts) was the trigger. "
            "Fix: exponential backoff + burst queue per channel; rate limit documented in runbook."
        ),
        "service": "notification-service",
        "severity": "SEV3",
    },
    {
        "title": "api-gateway 502 cascade — upstream connection refused",
        "content": (
            "api-gateway returned 502 Bad Gateway for all /api/v2/* endpoints for 8 minutes. "
            "Root cause: payment-service deployment rollout left 0 ready pods for 8 minutes "
            "due to a missing readiness probe path update. "
            "Resolution: readiness probe corrected; deployment strategy changed to "
            "RollingUpdate with minAvailable=1."
        ),
        "service": "api-gateway",
        "severity": "SEV1",
    },
    {
        "title": "api-gateway TLS 1.0 deprecation breaking legacy clients",
        "content": (
            "After enforcing TLS 1.2+ on the api-gateway, several legacy B2B integrations "
            "began failing with SSL handshake errors. "
            "Affected clients were using Java 7 / .NET 4.5 which default to TLS 1.0. "
            "Resolution: 30-day grace period extension; affected partners notified; "
            "migration guide published."
        ),
        "service": "api-gateway",
        "severity": "SEV2",
    },
    {
        "title": "payment-service duplicate charge bug after retry storm",
        "content": (
            "A network timeout between api-gateway and payment-service caused the gateway "
            "to retry idempotent-keyed payment requests. A bug in idempotency key storage "
            "(Redis key expiry too short — 60s instead of 24h) meant duplicate charges "
            "were processed for 127 transactions. "
            "Resolution: key TTL corrected; affected transactions refunded; idempotency "
            "test coverage added."
        ),
        "service": "payment-service",
        "severity": "SEV1",
    },
    {
        "title": "auth-service token refresh race condition causing logout loops",
        "content": (
            "Mobile clients were intermittently logged out when background token refresh "
            "requests raced. Two concurrent refresh calls both succeeded but the second "
            "invalidated the first's refresh token, causing the client holding the first "
            "to be rejected on next call. "
            "Fix: server-side token family tracking; only one active refresh token per "
            "session allowed; all others invalidated on use."
        ),
        "service": "auth-service",
        "severity": "SEV2",
    },
]


def main() -> None:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    qdrant_client = get_qdrant_client()
    svc = KnowledgeService(qdrant_client=qdrant_client)

    # Ensure a default tenant exists.
    tenant = session.execute(select(Tenant).limit(1)).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name="RISE Default Tenant")
        session.add(tenant)
        session.commit()
        print(f"Created tenant: {tenant.id}")
    else:
        print(f"Using existing tenant: {tenant.id}")

    # Ensure one service row per unique service name in the seed data.
    service_names = {inc["service"] for inc in HISTORICAL_INCIDENTS}
    service_map: dict[str, uuid.UUID] = {}
    for name in service_names:
        row = session.execute(
            select(Service).where(
                Service.tenant_id == tenant.id,
                Service.name == name,
            )
        ).scalar_one_or_none()
        if row is None:
            row = Service(tenant_id=tenant.id, name=name, environment="production")
            session.add(row)
            session.commit()
        service_map[name] = row.id

    print(f"\nSeeding {len(HISTORICAL_INCIDENTS)} knowledge entries...\n")
    print(f"{'#':<4} {'title':<55} {'vector_id':<38} score")
    print("-" * 100)

    for i, data in enumerate(HISTORICAL_INCIDENTS, start=1):
        # Check if a knowledge entry with this title already exists (idempotent re-run).
        existing = session.execute(
            select(KnowledgeEntry).where(
                KnowledgeEntry.tenant_id == tenant.id,
                KnowledgeEntry.title == data["title"],
            )
        ).scalar_one_or_none()

        if existing is not None:
            print(f"{i:<4} {'(already seeded) ' + data['title'][:38]:<55} {existing.vector_id or 'N/A':<38}")
            continue

        entry = KnowledgeEntry(
            tenant_id=tenant.id,
            title=data["title"],
            content=data["content"],
            tags={
                "service": data["service"],
                "severity": data["severity"],
            },
            created_at=datetime.now(timezone.utc),
        )
        session.add(entry)
        session.flush()  # get the id before upsert

        vector_id = svc.embed_and_upsert(entry, session)
        print(f"{i:<4} {data['title'][:54]:<55} {vector_id:<38}")

    session.close()
    print("\n✅ Seed complete.  Qdrant collection: incidents_v1")
    print(f"   Verify at: http://localhost:6333/dashboard#/collections/incidents_v1")


if __name__ == "__main__":
    main()
