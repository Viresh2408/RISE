"""Deterministic blast-radius calculator.

Computes the set of services transitively affected when a given service
degrades or fails, by performing a breadth-first search over the
``service_dependencies`` adjacency table stored in Postgres.

Design constraints (from agents-and-orchestration.md §2.6 and database-design.md §1):

* **No LLM involvement** — blast radius is a pure graph traversal, not an
  LLM guess.  There are zero imports from ``llm_gateway`` in this module.
  Grep check: ``grep -r "llm_gateway" topology/blast_radius.py`` must return
  nothing.

* **Deterministic** — given the same ``service_id`` and the same topology
  snapshot, this function always returns the same sorted list.

* **Missing-topology default** — if the topology table contains no rows for
  the queried tenant, the function cannot distinguish between "truly no
  dependents" and "topology not loaded yet."  Per the guardrail in
  agents-and-orchestration.md §2.6:

      "If topology data missing for a service, default to conservative
       'unknown — treat as high impact.'"

  The caller should check ``result.topology_missing`` and treat the incident
  as high-impact when this flag is set (the Impact Analyzer Agent escalates /
  marks max severity).

Edge semantics (from database-design.md §2 ERD)::

    SERVICE_DEPENDENCY.service_id          → the service that HAS the dependency
    SERVICE_DEPENDENCY.depends_on_service_id → the service it depends ON

So an edge ``(A, B)`` means "A depends on B".
Blast radius of B = all services that (directly or transitively) depend on B
= all A reachable from B by following edges *backwards* (dependents, not
dependencies).

The SQL query fetches all edges within the tenant; BFS then runs purely in
Python with no further DB round-trips.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# NOTE: Only standard-library and SQLAlchemy imports are present here.
# There are intentionally ZERO imports from llm_gateway.
# CI can verify: grep -r "llm_gateway" packages/rise-core/topology/blast_radius.py
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Public return type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlastRadiusResult:
    """Immutable result of a blast-radius traversal.

    Attributes:
        service_id: The originating service UUID (as a string).
        affected_services: Immutable tuple of service UUID strings that
            transitively depend on ``service_id``.  Does NOT include
            ``service_id`` itself.
        topology_missing: ``True`` when the topology table contained no edges
            for the tenant, OR when the queried ``service_id`` does not exist
            in the tenant's topology graph.  Callers MUST treat this as
            "high impact / unknown" per the documented guardrail
            (agents-and-orchestration.md §2.6).
        hop_count: Maximum BFS depth reached (0 when no dependents found).
    """

    service_id: str
    affected_services: tuple[str, ...] = field(default_factory=tuple)
    topology_missing: bool = False
    hop_count: int = 0


# ---------------------------------------------------------------------------
# Core function (DB-backed)
# ---------------------------------------------------------------------------


def blast_radius(
    service_id: str | uuid.UUID,
    *,
    session: "Session",
    tenant_id: str | uuid.UUID,
) -> BlastRadiusResult:
    """Return the set of services transitively affected by a failure in *service_id*.

    This is a **deterministic, pure graph traversal**.  No LLM is invoked.
    The same inputs always produce the same output for a given DB state.

    Args:
        service_id: UUID of the service that has failed / degraded.
        session: SQLAlchemy ``Session`` (read-only usage; no writes performed).
        tenant_id: Tenant scope — all traversal stays within the tenant.

    Returns:
        A :class:`BlastRadiusResult`.  When ``topology_missing`` is ``True``,
        the caller should treat the incident as high impact regardless of the
        empty ``affected_services`` list.

    Algorithm:
        1. Fetch ``service_dependencies`` rows for the specified tenant in one query.
        2. Build a reverse-adjacency map: ``{depended_on_id -> [dependent_ids]}``.
        3. Verify ``service_id`` is present in the topology graph. If not, set
           ``topology_missing=True`` per the documented guardrail.
        4. BFS from ``service_id`` over the reverse map to collect all
           transitive dependents.
        5. Return sorted tuple for determinism and immutability.
    """
    # Normalise to str for consistent dict keying and output.
    service_id_str = str(service_id)
    tenant_id_str = str(tenant_id)

    # ------------------------------------------------------------------
    # Step 1 — fetch topology (single query filtered at DB level by tenant_id).
    # ------------------------------------------------------------------
    from sqlalchemy import text as sa_text  # stdlib-compatible; no llm_gateway

    rows = session.execute(
        sa_text(
            "SELECT service_id, depends_on_service_id "
            "FROM service_dependencies "
            "WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id_str},
    ).fetchall()

    # ------------------------------------------------------------------
    # Step 2 — detect missing topology for tenant.
    # ------------------------------------------------------------------
    if not rows:
        return BlastRadiusResult(
            service_id=service_id_str,
            affected_services=(),
            topology_missing=True,
            hop_count=0,
        )

    # ------------------------------------------------------------------
    # Step 3 — build reverse-adjacency map and track known services.
    # Edge: (service_id) DEPENDS ON (depends_on_service_id)
    # Reverse edge: depends_on_service_id -> [service_id, ...]
    # ------------------------------------------------------------------
    reverse_adj: dict[str, list[str]] = {}
    known_services: set[str] = set()

    for row in rows:
        dependent_id = str(row[0])
        depended_on_id = str(row[1])
        known_services.add(dependent_id)
        known_services.add(depended_on_id)
        reverse_adj.setdefault(depended_on_id, []).append(dependent_id)

    # If service_id is not present in the topology graph at all, flag as missing topology
    if service_id_str not in known_services:
        return BlastRadiusResult(
            service_id=service_id_str,
            affected_services=(),
            topology_missing=True,
            hop_count=0,
        )

    # ------------------------------------------------------------------
    # Step 4 — BFS from service_id over reverse edges.
    # ------------------------------------------------------------------
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(service_id_str, 0)])
    max_hop = 0

    while queue:
        current, depth = queue.popleft()
        for dependent in reverse_adj.get(current, []):
            if dependent not in visited:
                visited.add(dependent)
                max_hop = max(max_hop, depth + 1)
                queue.append((dependent, depth + 1))

    affected = tuple(sorted(visited))

    return BlastRadiusResult(
        service_id=service_id_str,
        affected_services=affected,
        topology_missing=False,
        hop_count=max_hop,
    )


# ---------------------------------------------------------------------------
# In-memory variant (for unit tests and offline use)
# ---------------------------------------------------------------------------


def blast_radius_from_edges(
    service_id: str | uuid.UUID,
    edges: list[tuple[str, str]],
) -> BlastRadiusResult:
    """Deterministic blast-radius over a pre-supplied edge list.

    This variant does **not** require a database session, making it suitable
    for unit tests, local simulation, and offline tooling.  It shares the
    exact same BFS logic as :func:`blast_radius`.

    Args:
        service_id: UUID string of the origin service.
        edges: List of ``(service_id, depends_on_service_id)`` tuples — the
               same semantics as the ``service_dependencies`` table.
               An edge ``(A, B)`` means "A depends on B".

    Returns:
        A :class:`BlastRadiusResult`.  ``topology_missing=True`` is returned
        when ``edges`` is empty or when ``service_id`` is not in the topology graph.
    """
    service_id_str = str(service_id)

    if not edges:
        return BlastRadiusResult(
            service_id=service_id_str,
            affected_services=(),
            topology_missing=True,
            hop_count=0,
        )

    # Build reverse adjacency map and track known services.
    reverse_adj: dict[str, list[str]] = {}
    known_services: set[str] = set()

    for dependent_id, depended_on_id in edges:
        dep_str = str(dependent_id)
        dep_on_str = str(depended_on_id)
        known_services.add(dep_str)
        known_services.add(dep_on_str)
        reverse_adj.setdefault(dep_on_str, []).append(dep_str)

    if service_id_str not in known_services:
        return BlastRadiusResult(
            service_id=service_id_str,
            affected_services=(),
            topology_missing=True,
            hop_count=0,
        )

    # BFS.
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(service_id_str, 0)])
    max_hop = 0

    while queue:
        current, depth = queue.popleft()
        for dependent in reverse_adj.get(current, []):
            if dependent not in visited:
                visited.add(dependent)
                max_hop = max(max_hop, depth + 1)
                queue.append((dependent, depth + 1))

    return BlastRadiusResult(
        service_id=service_id_str,
        affected_services=tuple(sorted(visited)),
        topology_missing=False,
        hop_count=max_hop,
    )
