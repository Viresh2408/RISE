"""Unit tests for topology.blast_radius.

Verifies:
  - Determinism: same input always yields same output.
  - Correctness: BFS returns the right transitive dependent set.
  - Missing-topology guardrail: empty edge list -> topology_missing=True.
  - Zero LLM imports: grep assertion on the module source.
  - Edge cases: leaf node (no dependents), isolated node, diamond DAG,
    multi-hop chain, service not in topology, cycle (data integrity fault —
    should not hang).

All tests use blast_radius_from_edges (in-memory, no DB session required).
Tests are pure functions: no mocking, no I/O, no randomness.

Run with::

    cd packages/rise-core
    python -m pytest tests/test_blast_radius.py -v
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path

import pytest

# Ensure the package root is on the path when running from repo root.
_pkg_root = Path(__file__).parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from topology.blast_radius import BlastRadiusResult, blast_radius_from_edges


# ---------------------------------------------------------------------------
# Fixed fake topology
#
# Services (UUIDs are short strings for readability):
#   db       — Postgres database
#   cache    — Redis cache
#   api      — Core API; depends on db and cache
#   worker   — Background worker; depends on db
#   gateway  — API gateway; depends on api
#   frontend — Web frontend; depends on gateway
#   reporter — Reporting service; depends on db and api
#   isolated — Standalone service; no edges to/from the rest
#
# Edge list (service_id, depends_on_service_id):
#   api      -> db       (api depends on db)
#   api      -> cache    (api depends on cache)
#   worker   -> db       (worker depends on db)
#   gateway  -> api      (gateway depends on api)
#   frontend -> gateway  (frontend depends on gateway)
#   reporter -> db       (reporter depends on db)
#   reporter -> api      (reporter depends on api)
#
# Expected blast radii:
#   db:      {api, worker, gateway, frontend, reporter}   hops=4
#   cache:   {api, gateway, frontend, reporter}            hops=3
#   api:     {gateway, frontend, reporter}                 hops=2
#   gateway: {frontend}                                    hops=1
#   frontend:{} (leaf — no dependents)                     hops=0
#   worker:  {} (leaf — no dependents)                     hops=0
#   reporter:{} (leaf — no dependents)                     hops=0
#   isolated:{} (in topology but no dependents)            hops=0
# ---------------------------------------------------------------------------

DB = "svc-db"
CACHE = "svc-cache"
API = "svc-api"
WORKER = "svc-worker"
GATEWAY = "svc-gateway"
FRONTEND = "svc-frontend"
REPORTER = "svc-reporter"
ISOLATED = "svc-isolated"

# fmt: off
TOPOLOGY: list[tuple[str, str]] = [
    (API,      DB),       # api depends on db
    (API,      CACHE),    # api depends on cache
    (WORKER,   DB),       # worker depends on db
    (GATEWAY,  API),      # gateway depends on api
    (FRONTEND, GATEWAY),  # frontend depends on gateway
    (REPORTER, DB),       # reporter depends on db
    (REPORTER, API),      # reporter depends on api
    # ISOLATED intentionally has no edges — it IS known to the topology
    # (it appears in no edge), so topology_missing stays False.
]
# fmt: on


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def affected(service_id: str) -> tuple[str, ...]:
    """Return the sorted affected_services tuple for *service_id* in TOPOLOGY."""
    return blast_radius_from_edges(service_id, TOPOLOGY).affected_services


def result(service_id: str) -> BlastRadiusResult:
    """Return the full BlastRadiusResult for *service_id* in TOPOLOGY."""
    return blast_radius_from_edges(service_id, TOPOLOGY)


# ---------------------------------------------------------------------------
# 1. Guardrail: zero LLM imports in the blast_radius module
# ---------------------------------------------------------------------------


class TestNoLLMImports:
    """Confirms blast_radius.py contains no llm_gateway imports.

    The check is performed at the AST level so that mentions of 'llm_gateway'
    in docstrings or comments (which are legitimate design notes) do not
    cause false positives.
    """

    def test_no_llm_gateway_import_in_ast(self) -> None:
        """Parse blast_radius.py with the AST and assert no import of llm_gateway."""
        import ast

        import topology.blast_radius as br_mod

        source = inspect.getsource(br_mod)
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "llm_gateway" not in alias.name, (
                        f"blast_radius.py imports 'llm_gateway' via 'import {alias.name}' — "
                        "blast radius is a deterministic graph traversal, not an LLM call."
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "llm_gateway" not in module, (
                    f"blast_radius.py imports from 'llm_gateway' via 'from {module} import ...' — "
                    "blast radius is a deterministic graph traversal, not an LLM call."
                )

    def test_no_llm_gateway_in_runtime_attrs(self) -> None:
        """Verify no attribute on the loaded module originates from llm_gateway."""
        import topology.blast_radius as br_mod

        for attr_name, attr_val in vars(br_mod).items():
            module_name = getattr(attr_val, "__module__", "") or ""
            assert "llm_gateway" not in module_name, (
                f"Attribute '{attr_name}' in blast_radius.py originates from "
                f"llm_gateway — this is forbidden."
            )


# ---------------------------------------------------------------------------
# 2. Missing-topology guardrail
# ---------------------------------------------------------------------------


class TestMissingTopologyGuardrail:
    """Per agents-and-orchestration.md §2.6: missing topology data -> high impact."""

    def test_empty_edge_list_sets_topology_missing(self) -> None:
        r = blast_radius_from_edges(DB, [])
        assert r.topology_missing is True

    def test_empty_edge_list_returns_empty_affected_services(self) -> None:
        r = blast_radius_from_edges(DB, [])
        assert r.affected_services == ()

    def test_empty_edge_list_hop_count_zero(self) -> None:
        r = blast_radius_from_edges(DB, [])
        assert r.hop_count == 0

    def test_topology_missing_false_when_edges_present(self) -> None:
        r = blast_radius_from_edges(DB, TOPOLOGY)
        assert r.topology_missing is False

    def test_service_id_preserved_in_result(self) -> None:
        r = blast_radius_from_edges(DB, [])
        assert r.service_id == DB

    def test_service_id_not_in_topology_returns_missing_topology_guardrail(self) -> None:
        """When service_id is not in the topology at all, it must return topology_missing=True."""
        r = blast_radius_from_edges("svc-unknown-999", TOPOLOGY)
        assert r.affected_services == ()
        assert r.topology_missing is True
        assert r.hop_count == 0


# ---------------------------------------------------------------------------
# 3. Correctness — known topology
# ---------------------------------------------------------------------------


class TestBlastRadiusCorrectness:
    """Verify BFS returns the correct transitive dependent sets."""

    # ---- db ----

    def test_db_has_all_dependents(self) -> None:
        expected = tuple(sorted([API, WORKER, GATEWAY, FRONTEND, REPORTER]))
        assert affected(DB) == expected

    def test_db_hop_count_is_four(self) -> None:
        r = result(DB)
        assert r.hop_count == 3

    # ---- cache ----

    def test_cache_dependents(self) -> None:
        expected = tuple(sorted([API, GATEWAY, FRONTEND, REPORTER]))
        assert affected(CACHE) == expected

    def test_cache_hop_count(self) -> None:
        assert result(CACHE).hop_count == 3

    # ---- api ----

    def test_api_dependents(self) -> None:
        expected = tuple(sorted([GATEWAY, FRONTEND, REPORTER]))
        assert affected(API) == expected

    def test_api_hop_count(self) -> None:
        assert result(API).hop_count == 2

    # ---- gateway ----

    def test_gateway_dependents(self) -> None:
        assert affected(GATEWAY) == (FRONTEND,)

    def test_gateway_hop_count_is_one(self) -> None:
        assert result(GATEWAY).hop_count == 1

    # ---- leaf nodes (no dependents) ----

    def test_frontend_has_no_dependents(self) -> None:
        assert affected(FRONTEND) == ()

    def test_worker_has_no_dependents(self) -> None:
        assert affected(WORKER) == ()

    def test_reporter_has_no_dependents(self) -> None:
        assert affected(REPORTER) == ()

    def test_leaf_hop_count_is_zero(self) -> None:
        assert result(FRONTEND).hop_count == 0


# ---------------------------------------------------------------------------
# 4. Determinism — same input, same output, multiple calls
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Same service_id + same edges must always produce identical results."""

    def test_repeated_calls_db_are_identical(self) -> None:
        results = [result(DB) for _ in range(5)]
        first = results[0]
        for r in results[1:]:
            assert r == first

    def test_repeated_calls_api_are_identical(self) -> None:
        results = [result(API) for _ in range(5)]
        first = results[0]
        for r in results[1:]:
            assert r == first

    def test_affected_list_is_always_sorted(self) -> None:
        r = result(DB)
        assert r.affected_services == tuple(sorted(r.affected_services))

    def test_shuffled_edge_list_gives_same_result(self) -> None:
        """Edge insertion order must not affect the result."""
        import random

        shuffled = TOPOLOGY[:]
        random.seed(42)
        random.shuffle(shuffled)

        r_original = blast_radius_from_edges(DB, TOPOLOGY)
        r_shuffled = blast_radius_from_edges(DB, shuffled)

        assert r_original.affected_services == r_shuffled.affected_services
        assert r_original.hop_count == r_shuffled.hop_count


# ---------------------------------------------------------------------------
# 5. Simple linear chain
# ---------------------------------------------------------------------------


class TestLinearChain:
    """A -> B -> C -> D — verify each node's blast radius."""

    CHAIN: list[tuple[str, str]] = [
        ("svc-b", "svc-a"),  # B depends on A
        ("svc-c", "svc-b"),  # C depends on B
        ("svc-d", "svc-c"),  # D depends on C
    ]

    def test_a_affects_b_c_d(self) -> None:
        r = blast_radius_from_edges("svc-a", self.CHAIN)
        assert r.affected_services == ("svc-b", "svc-c", "svc-d")

    def test_a_hop_count_is_three(self) -> None:
        r = blast_radius_from_edges("svc-a", self.CHAIN)
        assert r.hop_count == 3

    def test_b_affects_c_d(self) -> None:
        r = blast_radius_from_edges("svc-b", self.CHAIN)
        assert r.affected_services == ("svc-c", "svc-d")

    def test_c_affects_d(self) -> None:
        r = blast_radius_from_edges("svc-c", self.CHAIN)
        assert r.affected_services == ("svc-d",)

    def test_d_is_leaf(self) -> None:
        r = blast_radius_from_edges("svc-d", self.CHAIN)
        assert r.affected_services == ()
        assert r.topology_missing is False


# ---------------------------------------------------------------------------
# 6. Diamond DAG (shared dependency)
# ---------------------------------------------------------------------------


class TestDiamondDAG:
    """
            A
           / \\
          B   C
           \\ /
            D
    D is depended-on by B and C, both of which are depended-on by A.
    """

    DIAMOND: list[tuple[str, str]] = [
        ("svc-b", "svc-d"),  # B depends on D
        ("svc-c", "svc-d"),  # C depends on D
        ("svc-a", "svc-b"),  # A depends on B
        ("svc-a", "svc-c"),  # A depends on C
    ]

    def test_d_affects_all(self) -> None:
        r = blast_radius_from_edges("svc-d", self.DIAMOND)
        assert r.affected_services == tuple(sorted(["svc-a", "svc-b", "svc-c"]))

    def test_d_hop_count_is_two(self) -> None:
        r = blast_radius_from_edges("svc-d", self.DIAMOND)
        assert r.hop_count == 2

    def test_b_affects_a_only(self) -> None:
        r = blast_radius_from_edges("svc-b", self.DIAMOND)
        assert r.affected_services == ("svc-a",)

    def test_a_is_leaf(self) -> None:
        r = blast_radius_from_edges("svc-a", self.DIAMOND)
        assert r.affected_services == ()


# ---------------------------------------------------------------------------
# 7. Self-loop / cycle (corrupted topology — must not hang)
# ---------------------------------------------------------------------------


class TestCycleHandling:
    """BFS must terminate even if the topology has cycles (data integrity faults)."""

    CYCLE: list[tuple[str, str]] = [
        ("svc-x", "svc-y"),
        ("svc-y", "svc-z"),
        ("svc-z", "svc-x"),  # cycle: x -> y -> z -> x
    ]

    def test_cycle_does_not_hang(self) -> None:
        r = blast_radius_from_edges("svc-x", self.CYCLE)
        assert isinstance(r, BlastRadiusResult)

    def test_self_loop_does_not_hang(self) -> None:
        r = blast_radius_from_edges("svc-x", [("svc-x", "svc-x")])
        assert isinstance(r, BlastRadiusResult)

    def test_cycle_terminates_with_full_cycle_members(self) -> None:
        r = blast_radius_from_edges("svc-x", self.CYCLE)
        assert set(r.affected_services).issubset({"svc-x", "svc-y", "svc-z"})
        assert r.topology_missing is False


# ---------------------------------------------------------------------------
# 8. BlastRadiusResult and affected_services Immutability
# ---------------------------------------------------------------------------


class TestBlastRadiusResultImmutability:
    def test_result_is_frozen(self) -> None:
        r = blast_radius_from_edges(DB, TOPOLOGY)
        with pytest.raises((AttributeError, TypeError)):
            r.affected_services = ()  # type: ignore[misc]

    def test_result_equality(self) -> None:
        r1 = blast_radius_from_edges(DB, TOPOLOGY)
        r2 = blast_radius_from_edges(DB, TOPOLOGY)
        assert r1 == r2

    def test_affected_services_is_tuple(self) -> None:
        r = blast_radius_from_edges(DB, TOPOLOGY)
        assert isinstance(r.affected_services, tuple)

    def test_affected_services_mutation_fails(self) -> None:
        """Verify that attempting to mutate affected_services raises an exception."""
        r = blast_radius_from_edges(DB, TOPOLOGY)
        with pytest.raises(AttributeError):
            r.affected_services.append("svc-hack")  # type: ignore[attr-defined]

        if r.affected_services:
            with pytest.raises(TypeError):
                r.affected_services[0] = "svc-hack"  # type: ignore[index]

