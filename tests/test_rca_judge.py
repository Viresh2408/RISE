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
    LLMJudgeVerdict,
    _dataset_hash,
    _flatten_raw_evidence,
    _run_llm_judge,
    _score_grounding,
    _score_mechanism,
    _tokenize,
    _wilson_ci,
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


def test_infra_failure_recorded_as_errored_not_failed(monkeypatch):
    """A0: an LLM/infra outage during a live run is recorded as `errored`,
    never as a diagnostic FAIL, and the run returns False (not silently green).

    Guards the fail-loud contract: agents raise AgentLLMError under
    ``raise_on_llm_failure=True`` so the judge never scores an infra failure as
    a low-confidence diagnostic answer (which would corrupt accuracy).
    """

    class _RaisingGateway:
        async def call_structured(self, prompt, schema, db=None):
            raise RuntimeError("all providers failed: simulated outage")

    monkeypatch.setattr(
        "eval.rca_judge._build_live_gateway",
        lambda provider, model: _RaisingGateway(),
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        res = asyncio.run(
            run_benchmark(
                run_id="test-infra-fail",
                live=True,
                provider="gemini",
                model="gemini-1.5-pro",
                artifacts_dir=tmp_dir,
            )
        )
        # An infra failure must fail the run, not pass silently.
        assert res is False

        with open(os.path.join(tmp_dir, "rca-benchmark-report.json")) as f:
            data = json.load(f)

        assert data["total"] == BENCHMARK_N
        assert data["errored"] == BENCHMARK_N
        assert data["failed"] == 0
        assert data["passed"] == 0
        # Every score carries the infra error; none scored as a diagnostic result.
        assert all(s["error"] for s in data["scores"])


# ---------------------------------------------------------------------------
# A2: scoring-rigor metrics (Wilson CI, evidence grounding, secondary judge)
# ---------------------------------------------------------------------------


def test_wilson_ci_bounds():
    """Wilson interval stays within [0,100] and brackets the point estimate."""
    # Perfect score: upper bound is exactly 100%, lower bound below 100%.
    low, high = _wilson_ci(10, 10)
    assert high == pytest.approx(100.0)
    assert 0.0 < low < 100.0

    # Zero score: lower bound is exactly 0%, upper bound above 0%.
    low0, high0 = _wilson_ci(0, 10)
    assert low0 == pytest.approx(0.0)
    assert 0.0 < high0 < 100.0

    # 50%: interval straddles 50 and is contained in (0,100).
    low5, high5 = _wilson_ci(5, 10)
    assert low5 < 50.0 < high5
    assert 0.0 < low5 and high5 < 100.0

    # n == 0 is defined as (0,0), never a division error.
    assert _wilson_ci(0, 0) == (0.0, 0.0)


def test_score_grounding_rewards_present_excerpts():
    """A cited excerpt whose tokens appear in raw_evidence scores high; a
    fabricated excerpt scores 0."""
    raw = {
        "log_excerpts": ["log-1: connection pool exhausted: max reached on payment-service"],
        "metric_snapshots": [],
        "timeline": [],
    }
    # Every token of both the excerpt AND the reference id ("log-1") is present
    # in the corpus, so grounding is a perfect 1.0.  (_score_grounding tokenizes
    # excerpt + reference together, so a reference pointing at a real evidence id
    # must itself appear in raw_evidence to be fully grounded.)
    grounded = [{"type": "log", "reference": "log-1", "excerpt": "connection pool exhausted payment-service"}]
    score, detail = _score_grounding(grounded, raw)
    assert score == pytest.approx(1.0)
    assert "0 weakly grounded" in detail

    fabricated = [{"type": "log", "reference": "x", "excerpt": "etcd raft leader election flapping"}]
    score_f, detail_f = _score_grounding(fabricated, raw)
    assert score_f == pytest.approx(0.0)
    assert "1 weakly grounded" in detail_f


def test_score_grounding_no_evidence_is_zero():
    """A RootCause that cites no evidence cannot demonstrate grounding."""
    score, detail = _score_grounding([], {"log_excerpts": ["anything"]})
    assert score == 0.0
    assert detail == "no evidence cited"


def test_run_llm_judge_returns_verdict():
    """The secondary judge returns the gateway's structured verdict verbatim."""

    class _JudgeGateway:
        async def call_structured(self, prompt, schema, db=None):
            assert schema is LLMJudgeVerdict
            return LLMJudgeVerdict(
                verdict="correct", confidence=0.9, citations=["evidence"], reasoning="ok"
            )

    verdict = asyncio.run(
        _run_llm_judge(_JudgeGateway(), GOLDEN_SCENARIOS[0], "some cause summary")
    )
    assert verdict is not None
    assert verdict.verdict == "correct"


def test_run_llm_judge_swallows_failure_non_gating():
    """The judge is advisory: an outage returns None, never propagates."""

    class _RaisingJudge:
        async def call_structured(self, prompt, schema, db=None):
            raise RuntimeError("judge provider down")

    verdict = asyncio.run(
        _run_llm_judge(_RaisingJudge(), GOLDEN_SCENARIOS[0], "some cause summary")
    )
    assert verdict is None


# ---------------------------------------------------------------------------
# A2: run_benchmark happy-path aggregation (CI, grounding, tokens, judge)
# ---------------------------------------------------------------------------


def _passing_state_for(scenario):
    """A synthetic agent result that satisfies the scenario's own rubric and
    cites a grounded excerpt drawn from its raw_evidence."""
    rubric = scenario["mechanism_rubric"]
    comp = rubric["primary_components"][0]
    mech = rubric["causal_mechanisms"][0]
    logs = scenario["raw_evidence"].get("log_excerpts") or []
    excerpt = logs[0] if logs else f"{comp} {mech}"
    return {
        "root_cause": {
            "cause_summary": f"The {comp} was {mech} under sustained load.",
            "confidence": 0.8,
            "confidence_rationale": f"{comp} {mech}",
            "evidence": [{"type": "log", "reference": "log-1", "excerpt": excerpt}],
        }
    }


class _FakeGateway:
    """Stand-in for the live gateway: carries a usage_events list the harness
    reads to attribute tokens/cost per scenario."""

    def __init__(self):
        self.usage_events = []


def _install_happy_path(monkeypatch, *, tokens_in=100, tokens_out=50, cost=0.001):
    gw = _FakeGateway()

    async def _fake_run_agents(scenario, gateway):
        gateway.usage_events.append({
            "provider": "gemini", "model": "fake-model",
            "input_tokens": tokens_in, "output_tokens": tokens_out,
            "cost_usd": cost, "prompt_hash": f"hash{scenario['id']:02d}",
            "success": True, "is_repair_attempt": False, "latency_ms": 5,
        })
        return _passing_state_for(scenario)

    monkeypatch.setattr("eval.rca_judge._build_live_gateway", lambda p, m: gw)
    monkeypatch.setattr("eval.rca_judge._run_agents_on_scenario", _fake_run_agents)
    return gw
# <<APPEND_HAPPY_PATH_TESTS>>


def test_run_benchmark_live_happy_path_populates_scoring_metrics(monkeypatch):
    """A successful live run fills every A2 metric: Wilson CI, grounding,
    hallucination rate, token/cost totals, temperature, and (with --llm-judge)
    a grounded secondary verdict on every score."""
    _install_happy_path(monkeypatch)

    async def _fake_judge(gateway, scenario, cause_summary):
        # "timeline" is a key present in every scenario's raw_evidence, so the
        # citation is verbatim-grounded in the flattened corpus.
        return LLMJudgeVerdict(
            verdict="correct", confidence=0.9, citations=["timeline"], reasoning="ok"
        )

    monkeypatch.setattr("eval.rca_judge._run_llm_judge", _fake_judge)

    with tempfile.TemporaryDirectory() as tmp_dir:
        res = asyncio.run(run_benchmark(
            run_id="hp", live=True, provider="gemini", model="fake-model",
            artifacts_dir=tmp_dir, llm_judge=True,
        ))
        assert res is True
        with open(os.path.join(tmp_dir, "rca-benchmark-report.json")) as f:
            data = json.load(f)

    assert data["total"] == BENCHMARK_N
    assert data["passed"] == BENCHMARK_N
    assert data["failed"] == 0 and data["errored"] == 0
    assert data["mechanism_accuracy_pct"] == pytest.approx(100.0)
    assert data["mechanism_accuracy_ci_high"] == pytest.approx(100.0)
    assert 0.0 < data["mechanism_accuracy_ci_low"] < 100.0
    assert data["temperature"] == 0.0
    assert data["llm_judge_enabled"] is True
    assert data["hallucination_rate_pct"] == 0.0
    assert data["mean_evidence_grounding"] > 0.5
    assert data["total_input_tokens"] == 100 * BENCHMARK_N
    assert data["total_output_tokens"] == 50 * BENCHMARK_N
    assert data["total_cost_usd"] == pytest.approx(0.001 * BENCHMARK_N)
    assert data["release_eligible"] is False
    for s in data["scores"]:
        assert s["llm_calls"] == 1
        assert len(s["prompt_hashes"]) == 1
        assert s["llm_judge_verdict"] == "correct"
        assert s["llm_judge_citations_grounded"] is True


def test_run_benchmark_live_omits_judge_by_default(monkeypatch):
    """Without --llm-judge the secondary judge never runs: verdict fields stay
    None and llm_judge_enabled is False, but deterministic scoring still fills."""
    _install_happy_path(monkeypatch)

    with tempfile.TemporaryDirectory() as tmp_dir:
        res = asyncio.run(run_benchmark(
            run_id="nojudge", live=True, provider="gemini", model="fake-model",
            artifacts_dir=tmp_dir,
        ))
        assert res is True
        with open(os.path.join(tmp_dir, "rca-benchmark-report.json")) as f:
            data = json.load(f)

    assert data["llm_judge_enabled"] is False
    assert data["passed"] == BENCHMARK_N
    for s in data["scores"]:
        assert s["llm_judge_verdict"] is None
        assert s["llm_judge_citations_grounded"] is None
