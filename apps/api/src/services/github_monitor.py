"""GitHub Repository Monitor Agent.

Continuously scans a configurable list of files in the GitHub repo for
known code anti-patterns and manages Incident rows accordingly:

  - Pattern DETECTED in real file content  → create a new Incident (idempotent)
  - Pattern NO LONGER DETECTED (fixed)     → auto-resolve any open Incident for it

All incident creation and resolution is driven entirely by real GitHub file
content fetched at runtime.  No hardcoded incident data exists here.

Design guarantees
-----------------
- Idempotency:  A ``source_signature`` (SHA-256 of ``file_path:pattern_id``) is
  stored in the Incident description JSON header so duplicate incidents are
  never created for the same pattern on the same file.
- No false positives: each pattern rule defines both a ``detect`` callable
  (returns True when the bug is present) and an ``is_fixed`` callable (returns
  True when the fix is confirmed in the current file).  An incident is only
  created when ``detect()`` is True **and** ``is_fixed()`` is False.
- Audit trail: every auto-created and auto-resolved incident writes an
  ``audit_events`` row via ``write_audit_event()``.
- Graceful failure: network or GitHub API errors do not crash the monitor;
  they are logged and the next cycle retries from scratch.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_MONITOR_ACTOR = "system:github_monitor"
_SOURCE_SIG_PREFIX = "[rise-monitor-sig:"  # embedded in description to find managed incidents


# ── Pattern definitions ───────────────────────────────────────────────────────


@dataclass
class FilePattern:
    """A single code anti-pattern to watch for in a specific file.

    Attributes
    ----------
    pattern_id:
        Stable string identifier for this pattern.  Used in idempotency hash.
    file_path:
        Path within the GitHub repo (e.g. ``"apps/api/src/deps/redis.py"``).
    title:
        Human-readable incident title created when the pattern is detected.
    description:
        Human-readable description of the problem.
    severity:
        Incident severity (``"SEV1"`` .. ``"SEV4"``).
    affected_service:
        Service name to associate with the created incident.
    detect:
        Callable ``(file_content: str) -> bool`` — returns True when the
        anti-pattern is present in the file content.
    is_fixed:
        Callable ``(file_content: str) -> bool`` — returns True when the fix
        is confirmed in the current file content.  If ``is_fixed()`` is True,
        the pattern is NOT raised regardless of what ``detect()`` returns.
    repo:
        Optional GitHub repo in ``"owner/name"`` format.  When empty/None the
        monitor falls back to the ``GITHUB_REPO`` env var (the primary repo).
        Set this to watch files in a *different* repository from the primary one.
    ref:
        Optional branch or commit SHA to monitor.  When empty/None the monitor
        falls back to ``GITHUB_MONITOR_REF`` (default ``"main"``).
    """

    pattern_id: str
    file_path: str
    title: str
    description: str
    severity: str
    affected_service: str
    detect: Callable[[str], bool]
    is_fixed: Callable[[str], bool]
    # Per-pattern repo + ref overrides (optional)
    repo: str = field(default="")   # empty → use GITHUB_REPO env var
    ref: str = field(default="")    # empty → use GITHUB_MONITOR_REF env var


def _make_patterns() -> List[FilePattern]:
    """Return the list of file patterns to monitor.

    Patterns are grouped by repository:

    Primary repo (GITHUB_REPO env var, default Viresh2408/RISE)
    ─────────────────────────────────────────────────────────────
    All patterns whose ``repo`` field is empty.

    Secondary / external repos
    ──────────────────────────
    Set ``GITHUB_MONITOR_REPO_2=owner/repo`` in .env and add your patterns
    inside the ``if repo2:`` block below.  Each pattern receives
    ``repo=repo2`` so the monitor fetches from the correct repository.
    Set ``GITHUB_MONITOR_REF_2=your-branch`` to watch a branch other than main.
    """

    # ── Secondary repo config (from env) ─────────────────────────────────────
    repo2 = os.getenv("GITHUB_MONITOR_REPO_2", "").strip()   # e.g. "acme-org/backend-api"
    ref2  = os.getenv("GITHUB_MONITOR_REF_2", "main").strip()

    # ── Primary-repo patterns ─────────────────────────────────────────────────
    patterns: List[FilePattern] = [
        FilePattern(
            pattern_id="redis_no_pool",
            file_path="apps/api/src/deps/redis.py",
            title="Redis Client Connection Storm & TCP Socket Churn in api-gateway",
            description=(
                "Unpooled redis.from_url() instantiated a new TCP handshake on every incoming "
                "API request. Under high load Redis client connection churn exhausts local "
                "ephemeral TCP ports, triggering 500 internal server errors."
            ),
            severity="SEV1",
            affected_service="api-gateway",
            detect=lambda c: "redis.from_url(" in c and "_REDIS_POOL" not in c,
            is_fixed=lambda c: "_REDIS_POOL" in c and "ConnectionPool" in c,
        ),
        FilePattern(
            pattern_id="db_small_pool",
            file_path="packages/rise-core/db/session.py",
            title="PostgreSQL Connection Pool Saturation in auth-service",
            description=(
                "Database connection pool configured with pool_size <= 10. "
                "Under sustained OAuth token load this exhausts all connections, "
                "causing cascading 503 errors from connection leak in error handlers."
            ),
            severity="SEV1",
            affected_service="auth-service",
            detect=lambda c: bool(
                re.search(r"pool_size\s*=\s*([1-9]|10)\b", c)
                and "create_engine" in c
            ),
            is_fixed=lambda c: bool(
                re.search(r"pool_size\s*=\s*(1[1-9]|[2-9]\d)", c)
            ),
        ),
        FilePattern(
            pattern_id="webhook_no_dedup",
            file_path="apps/api/src/routers/webhooks.py",
            title="Payment Webhook Missing Distributed Nonce Deduplication",
            description=(
                "Webhook router processes events without a distributed nonce "
                "idempotency check. Rapid retries with identical event IDs can "
                "pass signature verification and trigger duplicate ledger operations."
            ),
            severity="SEV2",
            affected_service="payment-service",
            detect=lambda c: "register_dedup" not in c and "async def _ingest" in c,
            is_fixed=lambda c: "register_dedup" in c,
        ),
        FilePattern(
            pattern_id="fixed_ttl_stampede",
            file_path="apps/api/src/routers/auth.py",
            title="Redis Session Cache Stampede on Token Refresh",
            description=(
                "Session TTL is a fixed 3600 seconds with no jitter. "
                "When bulk user sessions expire simultaneously a cache miss storm "
                "hits the primary database causing latency spikes."
            ),
            severity="SEV2",
            affected_service="auth-service",
            detect=lambda c: "ttl = 3600" in c and "jitter" not in c and "randint" not in c,
            is_fixed=lambda c: "jitter" in c or "randint" in c,
        ),
    ]

    # ── Secondary-repo patterns ───────────────────────────────────────────────
    # Activated when GITHUB_MONITOR_REPO_2 is set in .env.
    # Add as many FilePattern entries as you need for the external repo.
    # The `repo` and `ref` fields tell the monitor which GitHub repo to fetch from.
    if repo2:
        logger.info(
            "[GitHubMonitor] Secondary repo configured: %s @ %s — loading patterns.",
            repo2, ref2,
        )
        patterns += [
            # ----------------------------------------------------------------
            # EXAMPLE: detect an unprotected debug endpoint in the external repo
            # Replace file_path / detect / is_fixed lambdas with your own logic.
            # ----------------------------------------------------------------
            FilePattern(
                pattern_id="ext_debug_route_exposed",
                file_path="src/routes/debug.py",        # ← path inside repo2
                title=f"Debug Route Exposed Without Auth Guard in {repo2}",
                description=(
                    f"A debug or admin route in {repo2} is reachable without "
                    "authentication middleware.  This exposes internal diagnostics "
                    "to unauthenticated callers and is a SEV2 security risk."
                ),
                severity="SEV2",
                affected_service="external-api",         # ← your service name
                # Detect: route defined but no auth decorator present
                detect=lambda c: (
                    "@router.get(\"/debug\")" in c or "@app.route(\"/debug\")" in c
                ) and "require_auth" not in c and "verify_token" not in c,
                is_fixed=lambda c: "require_auth" in c or "verify_token" in c,
                repo=repo2,
                ref=ref2,
            ),
            # ----------------------------------------------------------------
            # Add more FilePattern entries here for repo2 …
            # ----------------------------------------------------------------
        ]
    else:
        logger.debug(
            "[GitHubMonitor] GITHUB_MONITOR_REPO_2 not set — secondary repo monitoring disabled."
        )

    return patterns


# ── Source signature helpers ───────────────────────────────────────────────────

_META_SIG_PREFIX = "[rise-monitor-meta:"  # JSON envelope with sig + context


def _make_source_sig(file_path: str, pattern_id: str) -> str:
    """Produce a stable 12-char hex signature for a (file, pattern) pair."""
    raw = f"{file_path}:{pattern_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _extract_buggy_context(content: str, pattern: "FilePattern") -> str:
    """Extract up to 15 lines of context around the detected bug pattern.

    We find the first line that indicates the anti-pattern and return
    a window of ±7 lines around it to give reviewers enough context.
    """
    lines = content.splitlines()
    # Try to locate a representative trigger line from the detect lambda
    trigger_terms: list = []
    if pattern.pattern_id == "redis_no_pool":
        trigger_terms = ["redis.from_url("]
    elif pattern.pattern_id == "db_small_pool":
        trigger_terms = ["pool_size"]
    elif pattern.pattern_id == "webhook_no_dedup":
        trigger_terms = ["async def _ingest"]
    elif pattern.pattern_id == "fixed_ttl_stampede":
        trigger_terms = ["ttl = 3600"]

    center_idx = None
    for i, line in enumerate(lines):
        if any(term in line for term in trigger_terms):
            center_idx = i
            break

    if center_idx is None:
        # Fall back: first 20 lines
        snippet_lines = lines[:20]
    else:
        start = max(0, center_idx - 7)
        end = min(len(lines), center_idx + 8)
        snippet_lines = lines[start:end]

    # Prefix each line with its 1-based line number in the file
    start_offset = max(0, (center_idx or 0) - 7)
    numbered = []
    for rel, line in enumerate(snippet_lines):
        abs_lineno = start_offset + rel + 1
        numbered.append(f"{abs_lineno:>4}: {line}")
    return "\n".join(numbered)


def _embed_sig_in_description(
    description: str,
    sig: str,
    pattern: Optional["FilePattern"] = None,
    buggy_context: str = "",
) -> str:
    """Embed a JSON metadata block into the incident description.

    Format::

        [rise-monitor-meta:{"sig": "...", "pattern_id": "...", "file_path": "...", "buggy_context": "..."}]
        <human-readable description>

    The JSON block is machine-parseable by the incidents router so it can
    display the actual buggy code and proposed fix diff to the operator
    BEFORE they approve any remediation.
    """
    meta: dict = {"sig": sig}
    if pattern is not None:
        meta["pattern_id"] = pattern.pattern_id
        meta["file_path"] = pattern.file_path
        meta["title"] = pattern.title
        meta["severity"] = pattern.severity
        meta["affected_service"] = pattern.affected_service
    if buggy_context:
        meta["buggy_context"] = buggy_context
    meta_json = json.dumps(meta, ensure_ascii=False)
    return f"{_META_SIG_PREFIX}{meta_json}]\n{description}"


def _extract_sig_from_description(description: str) -> Optional[str]:
    """Extract the source signature from a managed incident description.

    Handles both the new JSON envelope format and the legacy plain format.
    """
    if not description:
        return None

    # New JSON envelope format
    if _META_SIG_PREFIX in description:
        try:
            start = description.index(_META_SIG_PREFIX) + len(_META_SIG_PREFIX)
            end = description.index("]", start)
            meta = json.loads(description[start:end])
            return meta.get("sig")
        except (ValueError, IndexError, json.JSONDecodeError):
            pass

    # Legacy plain format  (backward compat)
    if _SOURCE_SIG_PREFIX in description:
        try:
            start = description.index(_SOURCE_SIG_PREFIX) + len(_SOURCE_SIG_PREFIX)
            end = description.index("]", start)
            return description[start:end]
        except (ValueError, IndexError):
            pass

    return None


def extract_monitor_meta(description: str) -> Optional[dict]:
    """Extract the full monitor metadata dict from an incident description.

    Returns None if the incident was not created by the GitHub monitor.
    """
    if not description or _META_SIG_PREFIX not in description:
        return None
    try:
        start = description.index(_META_SIG_PREFIX) + len(_META_SIG_PREFIX)
        end = description.index("]", start)
        return json.loads(description[start:end])
    except (ValueError, IndexError, json.JSONDecodeError):
        return None


# ── DB helpers ─────────────────────────────────────────────────────────────────


def _get_or_create_monitor_tenant(db: Session) -> uuid.UUID:
    """Return the default tenant ID, creating a minimal tenant row if none exists."""
    from db.models import Tenant

    row = db.execute(select(Tenant).limit(1)).scalar_one_or_none()
    if row is None:
        tenant = Tenant(name="default")
        db.add(tenant)
        db.flush()
        db.commit()
        db.refresh(tenant)
        logger.info("[GitHubMonitor] Created default tenant %s", tenant.id)
        return tenant.id
    return row.id


def _get_or_create_service(db: Session, tenant_id: uuid.UUID, service_name: str) -> uuid.UUID:
    """Return service ID for service_name, auto-creating if absent."""
    from db.models import Service

    row = db.execute(
        select(Service)
        .where(Service.tenant_id == tenant_id, Service.name == service_name)
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        svc = Service(
            tenant_id=tenant_id,
            name=service_name,
            environment="local",
            is_auto_created=True,
        )
        db.add(svc)
        db.flush()
        return svc.id
    return row.id


def _find_open_incident_for_sig(db: Session, tenant_id: uuid.UUID, sig: str):
    """Find an open incident whose description embeds the given source signature."""
    from db.models import Incident

    rows = db.execute(
        select(Incident).where(
            Incident.tenant_id == tenant_id,
            Incident.status.in_(["open", "investigating", "awaiting_approval"]),
        )
    ).scalars().all()

    for row in rows:
        if row.description and _extract_sig_from_description(row.description) == sig:
            return row
    return None


def _create_incident(
    db: Session,
    tenant_id: uuid.UUID,
    pattern: FilePattern,
    sig: str,
    file_content_sha: str,
    file_content: str = "",
) -> None:
    """Create a new Incident row for a detected pattern and write an audit event.

    The ``file_content`` is used to extract a code snippet around the bug
    so that the incident detail page can show operators exactly what is wrong
    in the GitHub file BEFORE they approve any fix.
    """
    from db.models import Incident
    from apps.api.src.middleware.audit import write_audit_event

    service_id = _get_or_create_service(db, tenant_id, pattern.affected_service)

    # Extract the buggy code context from the real file content
    buggy_context = _extract_buggy_context(file_content, pattern) if file_content else ""

    full_desc = _embed_sig_in_description(
        pattern.description,
        sig,
        pattern=pattern,
        buggy_context=buggy_context,
    )

    incident = Incident(
        tenant_id=tenant_id,
        title=pattern.title,
        description=full_desc,
        status="open",
        severity=pattern.severity,
        affected_service_id=service_id,
    )
    db.add(incident)
    db.flush()

    write_audit_event(
        db=db,
        actor=_MONITOR_ACTOR,
        tenant_id=tenant_id,
        action="incident.created_by_monitor",
        before_state=None,
        after_state={
            "id": str(incident.id),
            "title": incident.title,
            "pattern_id": pattern.pattern_id,
            "file_path": pattern.file_path,
            "source_sig": sig,
            "file_sha": file_content_sha,
            "has_buggy_context": bool(buggy_context),
        },
        incident_id=incident.id,
    )

    db.commit()
    logger.info(
        "[GitHubMonitor] Created incident %s for pattern '%s' in %s (context_lines=%d)",
        incident.id,
        pattern.pattern_id,
        pattern.file_path,
        buggy_context.count('\n') + 1 if buggy_context else 0,
    )


def _resolve_incident(
    db: Session,
    tenant_id: uuid.UUID,
    incident,
    pattern: FilePattern,
    sig: str,
) -> None:
    """Auto-resolve an open incident because the fix is confirmed in GitHub."""
    from apps.api.src.middleware.audit import write_audit_event

    before = {
        "id": str(incident.id),
        "status": incident.status,
        "title": incident.title,
    }

    incident.status = "resolved"
    incident.resolved_at = datetime.now(timezone.utc)
    db.flush()

    write_audit_event(
        db=db,
        actor=_MONITOR_ACTOR,
        tenant_id=tenant_id,
        action="incident.auto_resolved_by_monitor",
        before_state=before,
        after_state={
            "id": str(incident.id),
            "status": "resolved",
            "pattern_id": pattern.pattern_id,
            "file_path": pattern.file_path,
            "source_sig": sig,
            "reason": "Fix confirmed in real GitHub file content",
        },
        incident_id=incident.id,
    )

    db.commit()
    logger.info(
        "[GitHubMonitor] Auto-resolved incident %s — pattern '%s' fix confirmed in %s",
        incident.id,
        pattern.pattern_id,
        pattern.file_path,
    )


# ── Core monitor loop ──────────────────────────────────────────────────────────


async def _run_monitor_cycle(patterns: List[FilePattern]) -> None:
    """Execute one full monitoring cycle across all patterns."""
    from db.session import SessionLocal
    from apps.agents.src.nodes.github_file_fetcher import fetch_github_file_content

    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_READ_TOKEN")
    github_repo = os.getenv("GITHUB_REPO", "Viresh2408/RISE")
    ref = os.getenv("GITHUB_MONITOR_REF", "main")

    if not github_token:
        logger.warning(
            "[GitHubMonitor] GITHUB_TOKEN not set — monitor will not fetch files. "
            "Set GITHUB_TOKEN in .env to enable real-time incident monitoring."
        )
        return

    db: Session = SessionLocal()
    try:
        tenant_id = _get_or_create_monitor_tenant(db)

        for pattern in patterns:
            sig = _make_source_sig(pattern.file_path, pattern.pattern_id)

            # Fetch the real current file content from GitHub
            # Use the per-pattern repo/ref if set; fall back to the global env var.
            pattern_repo = pattern.repo or github_repo
            pattern_ref  = pattern.ref  or ref
            file_result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda p=pattern, pr=pattern_repo, pref=pattern_ref: fetch_github_file_content(
                    p.file_path,
                    repo=pr,
                    ref=pref,
                    github_token=github_token,
                    timeout_s=10.0,
                ),
            )

            if file_result is None:
                logger.debug(
                    "[GitHubMonitor] Could not fetch %s — skipping pattern '%s'",
                    pattern.file_path,
                    pattern.pattern_id,
                )
                continue

            content = file_result.content
            file_sha = file_result.sha

            bug_present = pattern.detect(content)
            fix_confirmed = pattern.is_fixed(content)

            logger.debug(
                "[GitHubMonitor] %s | pattern='%s' | bug_present=%s | fix_confirmed=%s",
                pattern.file_path,
                pattern.pattern_id,
                bug_present,
                fix_confirmed,
            )

            # Look for an existing open incident for this pattern
            existing = _find_open_incident_for_sig(db, tenant_id, sig)

            if fix_confirmed:
                # Fix is already in the file — auto-resolve any open incident
                if existing is not None:
                    _resolve_incident(db, tenant_id, existing, pattern, sig)
                else:
                    logger.debug(
                        "[GitHubMonitor] Pattern '%s' is fixed in %s — no open incident to resolve.",
                        pattern.pattern_id,
                        pattern.file_path,
                    )
            elif bug_present:
                # Anti-pattern is present and not fixed
                if existing is None:
                    _create_incident(db, tenant_id, pattern, sig, file_sha, file_content=content)
                else:
                    logger.debug(
                        "[GitHubMonitor] Pattern '%s' already has open incident %s — skipping creation.",
                        pattern.pattern_id,
                        existing.id,
                    )
            else:
                # Neither clearly broken nor clearly fixed — leave as-is
                logger.debug(
                    "[GitHubMonitor] Pattern '%s' in %s — inconclusive, no action taken.",
                    pattern.pattern_id,
                    pattern.file_path,
                )

    except Exception as exc:
        logger.exception("[GitHubMonitor] Unhandled error in monitor cycle: %s", exc)
    finally:
        db.close()


async def run_github_monitor(interval_seconds: int = 60) -> None:
    """Long-running background coroutine.  Runs a monitor cycle every ``interval_seconds``.

    Designed to be launched as an ``asyncio`` task in the FastAPI lifespan.
    Cancellation (on app shutdown) stops the loop cleanly.

    Args:
        interval_seconds: How often to poll GitHub for file changes.
    """
    patterns = _make_patterns()
    logger.info(
        "[GitHubMonitor] Starting — watching %d file patterns, interval=%ds, repo=%s",
        len(patterns),
        interval_seconds,
        os.getenv("GITHUB_REPO", "Viresh2408/RISE"),
    )

    # Run an immediate first cycle on startup
    await _run_monitor_cycle(patterns)

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await _run_monitor_cycle(patterns)
        except asyncio.CancelledError:
            logger.info("[GitHubMonitor] Shutting down cleanly.")
            break
        except Exception as exc:
            logger.exception("[GitHubMonitor] Unexpected error, will retry next cycle: %s", exc)
