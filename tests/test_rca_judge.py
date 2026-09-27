"""tests/test_rca_judge.py -- Tests for Live RCA Benchmark Judge (Phase 5).

Verifies:
  - 10 frozen golden scenarios schema & ground-truth isolation
  - Benchmark constants (pilot labeling, release gate N >= 50)
  - Deterministic mechanism rubric scoring & hallucination detection
  - Non-live skip behavior (no credentials required, clean report generation)
  - Live mode validation & missing-credentials enforcement (no silent mocks)
"""

from __future__ import annotations

import json
import os
import tempfile
import pytest

from eval.rca_judge import (
    BENCHMARK_LABEL,
    BENCHMARK_N,
    RELEASE_GATE_N,
    GOLDEN_SCENARIOS,
    _dataset_hash,
    _score_mechanism,
    _build_live_gateway,
    run_benchmark,
)


def test_golden_scenarios_schema_and_isolation():
    """Verify all 10 golden scenarios have proper schema and answer_key isolation."""
    assert len(GOLDEN_SCENARIOS) == BENCHMARK_N == 10

    for scenario in GOLDEN_SCENARIOS:
        # Required top-level fields
        assert "id" in scenario
        assert "title" in scenario
        assert "service" in scenario
        assert "raw_evidence" in scenario
        assert "answer_key" in scenario
        assert "mechanism_rubric" in scenario

        raw = scenario["raw_evidence"]
        assert "timeline" in raw
        assert "log_excerpts" in raw
        assert "metric_snapshots" in raw

        ans = scenario["answer_key"]
        assert "ground_truth_root_cause" in ans
        assert "provenance" in ans
        assert "verified_by" in ans

        # Ground truth isolation: answer_key must not be in raw_evidence keys or values
        gt = ans["ground_truth_root_cause"].lower()
        raw_json = json.dumps(raw).lower()
        # Ensure exact ground truth text is not in raw logs/timeline verbatim
        assert gt not in raw_json, f"Scenario {scenario['id']} leaks exact ground truth into raw_evidence!"

        rubric = scenario["mechanism_rubric"]
        assert "primary_components" in rubric and len(rubric["primary_components"]) > 0
        assert "causal_mechanisms" in rubric and len(rubric["causal_mechanisms"]) > 0
        assert "hallucination_check" in rubric and len(rubric["hallucination_check"]) > 0


def test_benchmark_constants_and_labeling():
    """Verify pilot labeling and release gate thresholds."""
    assert BENCHMARK_LABEL == "PILOT -- NOT RELEASE ELIGIBLE"
    assert BENCHMARK_N == 10
    assert RELEASE_GATE_N == 50
    assert BENCHMARK_N < RELEASE_GATE_N


def test_dataset_hash_is_deterministic():
    """Dataset hash must be a deterministic 16-char hex string."""
    hash1 = _dataset_hash(GOLDEN_SCENARIOS)
    hash2 = _dataset_hash(GOLDEN_SCENARIOS)
    assert hash1 == hash2
    assert len(hash1) == 16


def test_score_mechanism_pass():
    """Scoring passes when primary component and causal mechanism are both identified."""
    rubric = {
        "primary_components": ["connection pool", "database"],
        "causal_mechanisms": ["exhausted", "depleted"],
        "causal_trigger": ["slow query"],
        "hallucination_check": ["network partition", "OOM"],
    }
    cause_summary = "The database connection pool was exhausted due to high concurrency."
    rationale = "Connections reached maximum capacity of 20."
    passed, comp_hit, mech_hit, trig_hit, hallucinated, detail = _score_mechanism(
        cause_summary, rationale, rubric
    )

    assert passed is True
    assert "connection pool" in comp_hit
    assert "exhausted" in mech_hit
    assert hallucinated is False


def test_score_mechanism_missing_component_fails():
    """Scoring fails if component is missing even if mechanism is stated."""
    rubric = {
        "primary_components": ["connection pool", "database"],
        "causal_mechanisms": ["exhausted", "depleted"],
        "causal_trigger": ["slow query"],
        "hallucination_check": ["network partition"],
    }
    cause_summary = "Resources were exhausted due to unbounded traffic."
    rationale = "Everything was depleted."
    passed, comp_hit, mech_hit, trig_hit, hallucinated, detail = _score_mechanism(
        cause_summary, rationale, rubric
    )

    assert passed is False
    assert len(comp_hit) == 0
    assert len(mech_hit) > 0


def test_score_mechanism_missing_mechanism_fails():
    """Scoring fails if component is named without causal mechanism (e.g. repeating title)."""
    rubric = {
        "primary_components": ["connection pool", "database"],
        "causal_mechanisms": ["exhausted", "depleted"],
        "causal_trigger": ["slow query"],
        "hallucination_check": ["network partition"],
    }
    cause_summary = "An issue occurred on the database connection pool."
    rationale = "The database was accessed by payment-service."
    passed, comp_hit, mech_hit, trig_hit, hallucinated, detail = _score_mechanism(
        cause_summary, rationale, rubric
    )

    assert passed is False
    assert len(comp_hit) > 0
    assert len(mech_hit) == 0


def test_score_mechanism_hallucination_fails():
    """Scoring fails if a hallucinated root cause is stated in the lead sentence."""
    rubric = {
        "primary_components": ["connection pool", "database"],
        "causal_mechanisms": ["exhausted", "depleted"],
        "causal_trigger": ["slow query"],
        "hallucination_check": ["network partition", "OOM"],
    }
    # Lead sentence attributes failure to network partition
    cause_summary = "A network partition caused database connection pool exhausted state."
    rationale = "All connections timed out."
    passed, comp_hit, mech_hit, trig_hit, hallucinated, detail = _score_mechanism(
        cause_summary, rationale, rubric
    )

    assert passed is False
    assert hallucinated is True
    assert "network partition" in detail


import asyncio

def test_run_benchmark_non_live_mode():
    """Non-live benchmark execution creates skip report without failing or requiring credentials."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = asyncio.run(
            run_benchmark(
                run_id="test-run-123",
                live=False,
                provider=None,
                model=None,
                artifacts_dir=tmp_dir,
            )
        )
        assert res is True
        report_file = os.path.join(tmp_dir, "rca-benchmark-report.json")
        assert os.path.exists(report_file)

        with open(report_file) as f:
            data = json.load(f)
        assert data["live"] is False
        assert data["status"] == "SKIPPED"
        assert data["label"] == BENCHMARK_LABEL


def test_build_live_gateway_enforces_credentials():
    """Missing or placeholder API keys must raise RuntimeError and never silently mock."""
    with pytest.raises(RuntimeError, match="Unknown provider"):
        _build_live_gateway("invalid_provider", "some-model")

    # When key is not in environ, or is placeholder
    orig_key = os.environ.get("GEMINI_API_KEY")
    try:
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key"
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set or is a placeholder"):
            _build_live_gateway("gemini", "gemini-1.5-pro")
    finally:
        if orig_key is not None:
            os.environ["GEMINI_API_KEY"] = orig_key
        else:
            os.environ.pop("GEMINI_API_KEY", None)
