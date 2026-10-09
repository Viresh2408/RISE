# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What RISE Is

RISE (Resilient Incident & Remediation System Engine) is an autonomous multi-agent AIOps platform: it ingests alerts, reconstructs incident context, does root-cause analysis, computes blast radius, decides auto-vs-human remediation under policy, executes via tool servers, and independently verifies the result. The governing principle throughout the code is: **the system must never be more confident than the evidence supports.** Most of the non-obvious complexity exists to enforce that — respect it (see Safety Invariants below) rather than simplifying it away.

## Monorepo Layout & Tooling

Two workspaces overlaid on one tree:
- **Python** (Poetry, `pyproject.toml`) — `apps/api` (FastAPI), `apps/agents` (LangGraph), `packages/rise-core` (shared kernel), `packages/mcp-servers` (tool servers).
- **Frontend** (pnpm, `pnpm-workspace.yaml`) — `apps/dashboard` (Next.js 14 App Router).

`packages/rise-core` is installed as an editable dependency and is on `sys.path` (also injected manually in several entrypoints via `sys.path.insert`). Imports like `from db.models import ...` and `from schemas.agent_state import ...` resolve to `packages/rise-core/`, **not** a top-level package.

## Commands

Environment: `.env` is auto-loaded (dotenv) by the API and eval entrypoints. Copy `.env.example` first. Platform is Windows/PowerShell primary; the `poetry`/`pnpm` commands are shell-agnostic.

```bash
# --- Python ---
poetry install
poetry run alembic upgrade head                       # migrations (db/migrations)
poetry run python scripts/seed_knowledge.py           # seed Qdrant vector index
poetry run uvicorn apps.api.src.main:app --port 8000 --reload

# Tests: integration tests are DESELECTED BY DEFAULT via addopts (-m 'not integration')
poetry run pytest                                     # unit suite only
poetry run pytest -m integration                      # requires live Postgres + Redis + Qdrant
poetry run pytest tests/test_risk_score.py            # a single file
poetry run pytest apps/agents/tests/test_verification.py::test_name   # a single test
poetry run pytest -k "pattern"

# Lint / format / type-check (dev deps)
poetry run ruff check .
poetry run black .
poetry run mypy .

# --- Frontend (from repo root; pnpm scripts filter to rise-dashboard) ---
pnpm install
pnpm dev              # next dev on :3000
pnpm build            # next build  (CI gate)
pnpm lint             # next lint   (CI gate)
pnpm --filter rise-dashboard test    # vitest

# --- Backing services ---
docker-compose up -d  # postgres:16, redis:7, qdrant:1.9

# --- Eval & integrity ---
poetry run python eval/run_eval.py                    # orchestration certification (default mode)
poetry run python scripts/verify_chain.py --tenant-id <uuid>   # audit hash-chain check
```

CI (`.github/workflows/ci.yml`) gates PRs on `poetry run pytest -q` + `pnpm lint` + `pnpm build`.

`pytest` config lives in `pyproject.toml`: `testpaths` = `tests`, `apps/agents/tests`, `apps/api/tests`, `packages/rise-core/tests`; `pythonpath` = `.` + `packages/rise-core`.

## Database Duality (critical for tests)

`packages/rise-core/db/session.py` **auto-falls back to SQLite (`rise_dev.db`)** when `DATABASE_URL` points at Postgres but Postgres is unreachable. This is why the unit suite runs with no containers.

Consequences to keep in mind:
- `conftest.py` compiles Postgres types down for SQLite: `JSONB → JSON`, `UUID → TEXT`, and strips `gen_random_uuid()` server defaults. New models using PG-specific types/defaults must survive this patching or they'll break unit tests.
- **Row-Level Security is Postgres-only.** `tenant_session()` issues `set_config('app.current_tenant_id', ...)` solely when the bind is `postgresql`. Under SQLite there is no RLS — do not rely on tenant isolation being enforced by the DB in unit tests.

## Agent Pipeline (LangGraph)

The orchestrator is a compiled `StateGraph` in `apps/agents/src/orchestrator/graph.py`, keyed on a single `AgentState` TypedDict. Node order:

`ingest → build_context → investigate → root_cause → impact_analysis → decide → (await_human) → execute → verify → close | rollback | manual_handoff | escalate`

- Every node runs through `run_node_with_retry_and_timeout` (120s cap) and records an `AgentStepResult` row.
- Read-only nodes (context/investigation/root-cause/impact/verification) call the **LLM gateway** (`llm_gateway.gateway.call_structured`). Only `execute` calls the **MCP gateway**. Do not add MCP tool dispatch to read-only nodes.
- Human-in-the-loop uses LangGraph `interrupt` + `interrupt_after=["await_human"]`; the graph is durable/resumable via a checkpointer (`MemorySaver` locally, `PostgresSaver` in prod). Approval anchoring fields (`approved_plan_hash`, `require_approved_hash`) are channels so they survive the interrupt into `execute`.

Node engines live in `apps/agents/src/engines/` (action_planner, risk_engine, decision_engine, confidence_engine, patch_validator, similarity_engine).

## Safety Invariants — Do Not Break These

These are the load-bearing guarantees. They are documented in `docs/architecture-decisions.md` (ADRs); read the relevant ADR before touching any of these paths.

- **No autopilot flag.** There is no `AUTOPILOT_ENABLED` anywhere. Auto-execution requires an admin-created `RiskPolicy` row scoped to `action_pattern` + `environment` + `risk_tier` with `requires_approval=false`. Critical-risk actions and any plan lacking a rollback strategy are hardcoded to always require human approval. If OPA is unreachable, the system **fails closed** (everything needs approval).
- **Two distinct policy layers (ADR-002).** Real OPA evaluation against `policies/*.rego` happens **upstream in the Risk Engine** (`apps/agents/src/engines/risk_engine.py`). `MCPGateway.evaluate_python_allowlist` is a **static Python allow-list** (defense-in-depth), *not* an OPA call — do not rename or describe it as OPA.
- **One canonical GitHub write path (ADR-004).** Real branch/commit/PR writes go through `apps/api/src/services/github_service.py` (`commit_remediation_to_github`), called directly from `approve_action` in `apps/api/src/routers/actions.py`. `packages/mcp-servers/mcp-github` is a **simulation fixture only** and fail-closes in staging/prod. Never route real PR creation back through the MCP gateway — doing so previously reported verified remediations as failures. The direct path re-implements the gateway's guardrails itself: plan-hash check (409 `ACTION_PLAN_CHANGED`), a `{repo}:{target_file}` resource lock (409 `RESOURCE_LOCKED`), and fail-loud audit.
- **Execution is the single choke-point (ADR-003).** The Execution Agent holds the plan-level resource lock (spanning all steps) and verifies the plan hash before dispatch. The gateway adds caller-independent defense-in-depth: plan-hash re-verify and a *non-destructive* lock-owner peek. Lock **acquisition** stays plan-level; do not move it into the per-call gateway.
- **Persisted approval anchor (ADR-005).** `approve_action` writes an `Approval` row binding `user_id` + `plan_hash` + `decided_at`, in the same fail-loud commit as the audit event. Later executions compare against the *persisted* hash, not an in-flight one.
- **Grounded remediation.** A code fix is generated only after the LLM has seen the real, current file bytes fetched from GitHub; if that fetch fails, `requires_manual_plan=true` and no LLM is called. Every diff is validated against the real file before a PR opens. Verification independently re-fetches the PR from GitHub before an incident may close.
- **Hash-chained audit log.** `audit_events` rows are append-only: `hash[n] = SHA256(hash[n-1] || event_data)`, scoped per tenant. Audit-write failure on a remediation path raises (`AUDIT_WRITE_FAILED`) rather than being swallowed.
- **`RISE_TEST_MODE=1` disables JWT signature verification** and is hard-blocked outside `local`/`test`/`dev`/`ci` by a startup guard in `apps/api/src/main.py`. This is intentional; a startup error there is the guard working.

## Evaluation Semantics (actively evolving)

`eval/run_eval.py` has three modes with deliberately distinct meanings — **do not conflate them**:
- `--mode orchestration` (default): deterministic certification of the state-machine routing with LLM/IO mocked. Report as "Orchestration Certification: X/Y", **never** as "RCA accuracy".
- `--mode rca`: live RCA benchmarking via `eval/rca_judge.py` against frozen `eval/golden_dataset/rca_scenarios.json`. Without `--live` it runs a fake-provider fixture labeled `PILOT — NOT RELEASE ELIGIBLE`.

A prior circular eval (mock responses echoing embedded ground-truth) was removed. When working on scoring, never let a mock/fallback be labeled as a live result, and don't reintroduce a static "RCA accuracy >= 80%" claim. See `docs/evaluation-methodology.md` for release-gate definitions.

## Conventions

- Keep code strictly typed (Pydantic v2 on the backend, TypeScript + MyPy) per `CONTRIBUTING.md`.
- All changes go through a PR targeting `main`.
- Shared Pydantic schemas live in `packages/rise-core/schemas/`; SQLAlchemy models in `packages/rise-core/db/models.py`. Agent prompts are versioned per-agent under `prompts/`.
