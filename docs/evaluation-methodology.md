# RISE Evaluation Methodology & Release Gates

## Overview & Guiding Principles

This document defines the evaluation methodology, verification standards, and release criteria for **RISE (Reliability & Incident Self-Healing Engine)**.

A core tenet of RISE is that **reported evaluation results must be truthful, reproducible, and verifiable**. No test fixture, simulation stub, or benchmark harness may report success unless the expected terminal state is genuinely achieved. In particular:
- Synthetic mock execution is prohibited from masquerading as live production success.
- Background dispatch or exception-free execution is never conflated with verified remediation.
- Deterministic state machine validation must never be labeled or marketed as "AI diagnostic accuracy."

---

## The Four Evaluation Modes

To ensure clarity and prevent ambiguous claims, all testing and verification within RISE is classified into four strictly separated categories:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   RISE Evaluation Hierarchy                            │
├──────────────────────────┬─────────────────────────────────────────────┤
│ 1. Deterministic         │ State machine graph transitions,            │
│    Orchestration         │ approval gates, OPA guardrails, blast       │
│    Certification         │ radius, plan-hash checks, rollback loops.   │
├──────────────────────────┼─────────────────────────────────────────────┤
│ 2. Live RCA              │ AI diagnostic accuracy on frozen raw        │
│    Benchmarking          │ evidence against an isolated answer key     │
│                          │ and deterministic mechanism rubric.         │
├──────────────────────────┼─────────────────────────────────────────────┤
│ 3. Integration           │ Real containerized dependencies (Postgres,  │
│    Testing               │ Redis, Qdrant) and network interfaces.      │
├──────────────────────────┼─────────────────────────────────────────────┤
│ 4. Production            │ Canary verification, shadow-mode burn-in,   │
│    Validation            │ and audited human operator sign-off.        │
└──────────────────────────┴─────────────────────────────────────────────┘
```

---

### 1. Deterministic Orchestration Certification

- **Purpose**: Certify that the multi-agent state machine (LangGraph) executes legal node transitions, enforces human-in-the-loop (HITL) approval gates, halts on unapproved steps, detects tampered plans, respects per-resource locks, executes allow-listed tools, and triggers automated rollback on verification failure.
- **Execution Boundaries**:
  - LLM calls and external I/O boundaries are mocked with deterministic fixtures.
  - **Critical Rule**: The harness must execute real node logic. It **must never pre-populate** `root_cause`, `decision`, approval state, or verification results into the initial state in a way that bypasses real routing.
  - **Tool Contracts**: Tools must strictly conform to production schemas (`restart_pod`, `create_pr`, etc.) rather than ad-hoc names.
- **Success Criteria**:
  - Exact node trace matches legal transitions.
  - Reaches expected terminal state (`completed`, `manual_handoff`, or `escalated`).
  - Action execution cannot occur prior to authentic approval.
  - Verification failure cleanly triggers rollback and human escalation.
- **Reporting**:
  - Command: `python eval/run_eval.py --mode orchestration`
  - Output: `eval/artifacts/<run-id>/orchestration-report.json` and `.md`
  - Metric Label: `Orchestration Certification: X/Y passed` (strictly prohibited from being labeled as "RCA accuracy").

---

### 2. Live RCA Benchmarking

- **Purpose**: Measure the root-cause analysis and diagnostic capabilities of the LLM agents against genuine historical incidents.
- **Data-Separation Architecture**:
  - `raw_evidence.json`: The sole incident telemetry (logs, metrics, alerts) provided to the agent.
  - `answer_key.json`: Isolated ground truth containing the verified root cause and provenance metadata. Never exposed to agent prompts, runbooks, or context.
  - `mechanism_rubric.json`: Deterministic evaluation rules requiring correct component identification and causal mechanism.
- **Benchmarking Standards**:
  - Requires live LLM provider credentials via explicit invocation:
    `python eval/run_eval.py --mode rca --live --provider <provider> --model <model>`
  - Records execution metadata: provider, model, temperature (0.0/deterministic where supported), prompt hash, dataset hash, git SHA, latency, token count, and cost.
  - Never substitutes a mock or fallback response when a live provider fails; failures must fail loud.
  - Evaluates both:
    1. Isolated diagnosis (`investigation` $\to$ `root_cause` on frozen evidence).
    2. Full pipeline (`context` $\to$ `investigation` $\to$ `root_cause`).
- **Scoring & Metrics**:
  - Deterministic mechanism matching is primary.
  - LLM judge is secondary, returning structured citations without ungrounded reasoning.
  - Reports distinct metrics: strict mechanism match, evidence grounding score, hallucination rate, and 95% confidence intervals.
  - **Release Gate Requirement**: A benchmark must contain $\ge 50$ independently authored, stratified, and peer-reviewed cases before an RCA accuracy metric can be cited as a release gate. Pilot runs (< 50 cases) must be labeled `PILOT — NOT RELEASE ELIGIBLE`.

---

### 3. Integration Testing

- **Purpose**: Verify that RISE components interoperate with real external dependencies and datastores.
- **Scope**:
  - Live PostgreSQL database with Alembic migrations and tenant isolation.
  - Live Redis instance for distributed resource locks (`ResourceLockManager`) and webhook deduplication.
  - Live Qdrant vector database for runbook retrieval and similarity search.
  - Real cryptographic signature validation (GitHub HMAC, Slack replay protection, AWS cert chains).
- **Execution**:
  - Command: `pytest -m integration`
  - Requires local Docker services (`docker-compose up -d postgres redis qdrant`).

---

### 4. Production Validation

- **Purpose**: Validate operational safety, canary deployments, and human authorization workflows in staging and production.
- **Non-Negotiable Safety Invariants**:
  - **No Global Autopilot**: Remediation actions default to `requires_approval = True`. Only explicitly scoped `RiskPolicy` rows can permit auto-remediation for low/medium-risk actions in staging.
  - **Critical Actions Lockout**: Critical-tier actions and code modifications are hardcoded at the engine level to always require human approval.
  - **In-Process MCP Restriction**: Out-of-process isolation for MCP servers is required before production auto-execution is permitted. In-process MCP servers are restricted to local/test and human-supervised staging.
  - **Grounded Verification**: A code fix requires grounded file retrieval $\to$ patch validation against real bytes $\to$ execution $\to$ independent GitHub API confirmation. Inability to verify is treated as failure.

---

## Summary of Release Gates

| Milestone / Gate | Required Evidence | Status |
| :--- | :--- | :--- |
| **Unit Test Coverage** | `pytest -m "not integration"` passes 100% | Active |
| **Orchestration Certification** | `python eval/run_eval.py --mode orchestration` passes 100% of state-machine scenarios | Required for Milestone |
| **Integration Suite** | `pytest -m integration` passes against live Postgres, Redis, Qdrant | Active in Staging CI |
| **RCA Benchmark Release Gate** | $\ge 50$ independently reviewed cases, strict mechanism score $\ge 80\%$ | **Pending** (Currently Pilot: 10 cases, Not Release Eligible) |
| **Autonomous Production Gate** | Out-of-process MCP isolation + 2-week shadow-mode burn-in | **Blocked** (MCP remains in-process; production auto-remediation disabled) |
