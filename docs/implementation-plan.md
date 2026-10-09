# RISE Implementation Plan

**Status:** Proposed — approval required before implementation  
**Prepared:** 2026-10-06  
**Repository:** `/mnt/c/Project/RISE`  
**Implementation rule:** No application-code, infrastructure, dependency, migration, or configuration changes should be started from this plan until the project owner approves it.

## 1. Purpose

This document records the current implementation state of RISE and defines the ordered work required to complete the remaining product, safety, integration, testing, and deployment work.

The plan is intentionally based on the current checkout, including its existing uncommitted changes. It does not assume that the older `plan.md`, README diagrams, or historical launch checklist are current. Where documentation and code disagree, the code and the newer `docs/implementation-progress.md` record are treated as the working baseline until verified.

## 2. Approval Gate

Implementation must not begin until the owner confirms this plan. Approval should also confirm the release target:

- [ ] **Local/test-complete target** — finish the implementation and automated validation, but do not enable production autonomous execution.
- [ ] **Staging-complete target** — deploy to a real staging environment, exercise live dependencies, and complete shadow mode.
- [ ] **Production-ready target** — satisfy every safety, isolation, benchmark, operational, and stakeholder gate in this document before production autonomy is considered.

Suggested approval response: **“Approved — proceed with the implementation plan.”**

Until approval is received, work is limited to documenting and reviewing this plan.

## 3. Audit Basis and Current Verification State

The assessment used:

- `README.md`
- `RISE_ARCHITECTURE_AND_STATUS.md`
- `docs/implementation-progress.md`
- `docs/architecture-decisions.md`
- `docs/evaluation-methodology.md`
- `docs/launch-checklist-signoff.md`
- `plan.md`
- current Python, TypeScript, API, agent, database, evaluation, CI, Kubernetes, Helm, and Terraform files
- the current Git worktree and recent commit history

The current worktree contains extensive uncommitted changes. Those changes were not discarded, reset, or overwritten. They must be reviewed and committed separately before implementation phases are merged.

### Verification performed during this audit

| Check | Result | Meaning |
|---|---|---|
| Repository/status review | Completed | Current implementation and uncommitted work were inspected. |
| Documentation/code reconciliation | Completed | Major known gaps and stale status claims were identified. |
| `poetry run python scripts/run_unit_tests.py -q -o faulthandler_timeout=60` | Not runnable in this shell | `poetry` is not installed or available on `PATH`. The latest recorded repository result is 697 passed, 2 skipped, 17 deselected. |
| `pnpm --filter rise-dashboard test` | Dependency/install process was terminated by the shell timeout | A fresh dependency operation began and was killed after 180 seconds; this is not a test result. |
| OPA policy tests | Not runnable from this shell | No local OPA executable was available. The latest recorded result is 19/19 passed with OPA 0.63.0. |
| `git diff --check` | Existing worktree output is noisy | The current broad uncommitted diff contains line-ending/trailing-whitespace changes. This should be normalized or explicitly handled during baseline preparation. |

The recorded results in `docs/implementation-progress.md` are useful evidence, but they do not replace a clean rerun after the current worktree is stabilized.

## 4. Current Implementation Summary

### 4.1 Implemented foundations

| Area | Current state | Evidence / location |
|---|---|---|
| Python monorepo and shared kernel | Implemented | `pyproject.toml`, `packages/rise-core/`, editable `rise-core` dependency |
| FastAPI API | Implemented with many DB-backed routes | `apps/api/src/main.py`, `apps/api/src/routers/` |
| SQLAlchemy models and Alembic migrations | Implemented through revisions `0001`–`0007` | `packages/rise-core/db/models.py`, `db/migrations/versions/` |
| SQLite development fallback | Implemented | `packages/rise-core/db/session.py`, `db/runtime.py`, `conftest.py` |
| PostgreSQL tenant/RLS design | Implemented in code and migrations; live restricted-role validation remains required | `packages/rise-core/db/session.py`, `tests/integration/test_tenant_transactions.py` |
| Redis integration | Implemented for locks, deduplication, and event publication | `apps/api/src/deps/redis.py`, ingestion services, `packages/rise-core/mcp_client/lock.py` |
| Qdrant knowledge service | Implemented as an in-process service | `packages/rise-core/knowledge_service/` |
| LLM gateway | Implemented for Gemini, OpenAI, Ollama, and Groq | `packages/rise-core/llm_gateway/` |
| OPA policy evaluation | Implemented upstream in the Risk Engine | `apps/agents/src/engines/risk_engine.py`, `policies/` |
| Static tool allow-list | Implemented as gateway defense-in-depth | `packages/rise-core/mcp_client/gateway.py` |
| Hash-chained audit trail | Implemented with tenant serialization and fail-loud remediation behavior | `packages/rise-core/db/models.py`, `apps/api/src/middleware/audit.py`, `scripts/verify_chain.py` |

### 4.2 Implemented security and governance controls

The following controls are present and should be preserved during all subsequent work:

- JWT authentication fails closed when configuration is missing or invalid.
- `RISE_TEST_MODE` is restricted to local/test-like environments.
- CORS is configured from an explicit environment list rather than a wildcard.
- The prior demo-token authentication backdoor is removed and regression-tested.
- Webhook signatures are verified for GitHub, Alertmanager/shared-secret sources, AWS SNS/CloudWatch, and Slack with replay protection.
- Tenant resolution and webhook deduplication are implemented.
- Critical-risk actions and plans without rollback strategies require human approval.
- There is no global autopilot switch.
- OPA unavailability fails closed in the Risk Engine.
- Action plan hashes are computed and checked in the execution path.
- Resource locks prevent conflicting remediation operations.
- Approval records persist the approver, decision, timestamp, and plan hash for DB-backed actions.
- Approval/rejection/modification lifecycle hardening includes idempotency, expiry, actor binding, stale-plan checks, and terminal-state protection.
- The direct GitHub path has explicit plan-hash, resource-lock, and fail-loud audit guardrails.
- The old Slack callback path that fabricated and dispatched an unanchored plan was removed.
- Cross-tenant incident reads are scoped by tenant.

### 4.3 Implemented agent and orchestration capabilities

The LangGraph pipeline and its major decision components exist:

```text
ingest
  -> build_context
  -> investigate
  -> root_cause
  -> impact_analysis
  -> decide
  -> await_human
  -> execute
  -> verify
  -> close / rollback / manual_handoff / escalate
```

Implemented capabilities include:

- checkpointed state graph with local memory and PostgreSQL checkpoint support paths;
- context construction, investigation, root-cause analysis, impact analysis, decision planning, execution, and verification nodes;
- confidence and risk engines;
- deterministic blast-radius calculation;
- prompt-injection-resistant prompt preambles and structured output validation;
- grounded file-fetch and patch-validation components on the agent-graph path;
- action plan hash generation;
- human interrupt/resume routing;
- rollback and escalation routing;
- per-node retry/timeout and agent step recording;
- fail-loud behavior when LLM providers fail or structured output cannot be validated.

### 4.4 Implemented API, dashboard, and integration surfaces

- Incident, timeline, action, approval, rollback, policy, knowledge, report, verification, audit, health, and webhook route families exist.
- Dashboard routes exist for incidents, incident detail, reports, policies, knowledge, integrations, login, and design-system primitives.
- The frontend no longer manufactures demo incident data or fake commit success on API outage.
- Approval UI primitives, risk/confidence displays, incident lifecycle states, evidence links, and execution-status components exist.
- Direct GitHub branch/commit/PR creation and independent PR re-fetch verification exist when credentials are configured.
- Kubernetes, AWS, Slack, and GitHub tool modules exist in-process; the GitHub module is explicitly a simulation fixture and fails closed in staging/production.
- Celery beat logic exists for approval SLA timeout checks.
- API and dashboard Dockerfiles, Kustomize manifests, Helm files, Terraform environments/modules, and CI/security workflows exist in the current worktree, although several are not yet proven against live infrastructure.

### 4.5 Implemented evaluation and test foundations

- Unit tests span the API, agents, shared kernel, security invariants, policy behavior, audit behavior, tenant boundaries, action plans, GitHub behavior, ingestion, and dashboard primitives.
- Integration test modules exist for PostgreSQL tenant transactions, Redis lock ownership, knowledge service behavior, and execution boundaries.
- Chaos and load simulation tests exist.
- Orchestration certification and adversarial evaluation modes exist.
- `eval/rca_judge.py` and a 10-case pilot dataset now exist, with explicit pilot/non-release semantics.
- CI now includes Python tests, OPA tests, PostgreSQL/Redis validation jobs, frontend tests, lint, and build commands.

## 5. Remaining Work Inventory

The remaining work is grouped below by whether it blocks a safe, complete system.

### 5.1 P0 — Required before autonomous staging or production behavior

1. **Stabilize and verify the current baseline.**
   - Install/use the supported Poetry and pnpm environments.
   - Review the large uncommitted change set, preserve intended changes, and establish a clean baseline.
   - Re-run unit, frontend, OPA, type, lint, build, migration, and integration gates.
   - Resolve any failures rather than treating historical recorded results as current proof.

2. **Make the persisted plan the only executable plan.**
   - The approval and execution path must use the exact plan stored and shown to the approver.
   - Manual modifications must not fall back to the generic templated plan.
   - Dashboard and Slack approvals must carry or resolve the canonical persisted plan hash.
   - Staging/production execution must fail closed when the approval anchor is absent.

3. **Bridge grounded, validated diffs into the real GitHub write path.**
   - The current canonical real-PR service still derives a templated patch with `apply_patch_to_text`.
   - The agent-graph grounded/validated diff currently does not feed the canonical real write path.
   - The real path must receive the validated diff, source revision, target file, patch hash, and validation result.
   - The templated fallback must be removed from executable production remediation.

4. **Wire alert ingestion to durable graph execution.**
   - Webhooks currently persist and publish to `stream:events`, but a production consumer is not wired.
   - A consumer must claim events, preserve tenant context, start/resume the graph, retry safely, and move poison events to the DLQ.
   - Duplicate delivery must not start duplicate remediation plans.

5. **Replace synthetic verification inputs with live, action-specific evidence.**
   - The current approval path can feed hardcoded post-action metrics such as `200 OK` and `error_rate: 0.0`.
   - Verification must independently query the relevant health checks, metrics, logs, deployment/PR state, and action postconditions.
   - A missing or inconclusive observation must produce an unverified/failure outcome, not success.

6. **Complete durable worker/checkpoint execution.**
   - The `apps/agents` container currently compiles the graph and serves liveness; it does not accept incident work.
   - Production graph execution must run in a durable worker process with PostgreSQL-backed checkpoints and restart/resume behavior.
   - The Celery SLA task must use tenant-scoped DB access and not be the accidental substitute for graph workers.

7. **Complete live dependency and release validation.**
   - Run migrations, RLS, audit concurrency, Redis ownership, Qdrant, cryptographic webhooks, and full-stack flows against real disposable services.
   - Replace skipped/placeholder E2E coverage with a real API + browser + backing-service harness.

8. **Satisfy the release gates.**
   - Build an independently authored, stratified, peer-reviewed RCA dataset of at least 50 cases.
   - Run live RCA with explicit provider/model metadata and no mock fallback.
   - Complete staging shadow mode and obtain current stakeholder sign-off.
   - Keep production autonomous execution blocked until MCP isolation and all safety gates pass.

### 5.2 P1 — Required for a complete operational product

1. Implement the observability tool surface or provide a formally supported live observability adapter for logs, metrics, health checks, and deployment state.
2. Implement the knowledge tool surface or formally expose the existing Qdrant knowledge service through the approved tool boundary.
3. Replace simulated security actions with authorized provider integrations and explicit dry-run behavior.
4. Bind deployed Slack approval callbacks to a real tenant, action, plan hash, actor, and persisted approval record.
5. Make API report, verification, root-cause/impact, knowledge, policy, agent-run, and action views fully DB-backed and truthful for all supported states.
6. Finish persistent integrations and connection health reporting for GitHub, Slack, Kubernetes, AWS, Redis, PostgreSQL, Qdrant, OPA, and LLM providers.
7. Make the deployment workflow actually deploy the currently available Helm/Kustomize artifacts rather than relying on placeholder steps.
8. Add worker deployment, autoscaling, queue/stream lag monitoring, dead-letter handling, and operational runbooks.
9. Reconcile all status documentation with the code and current infrastructure files.

### 5.3 P2 — Extensions and post-release improvements

1. Automate shadow-mode statistics and promotion/demotion decisions.
2. Add reviewed human-feedback capture and offline recalibration of confidence/risk models.
3. Export and version n8n ingestion, notification, and escalation workflows if n8n remains a supported deployment path.
4. Add additional LLM provider adapters such as Anthropic or Bedrock only if they are required by the deployment target.
5. Add multi-tenant operational exercises beyond unit-level RLS checks.
6. Expand load testing from simulated timing to live provider and queue benchmarks.

## 6. Target End-to-End Behavior

The completed system should follow this contract:

1. A signed alert is accepted only from a configured integration and is assigned to the correct tenant.
2. The event is normalized, deduplicated, persisted, published to a durable stream, and acknowledged safely.
3. A worker claims the event exactly once for execution purposes and starts a tenant-scoped, PostgreSQL-checkpointed graph run.
4. The graph gathers current evidence from approved integrations and records evidence references and timestamps.
5. Investigation, RCA, impact, confidence, risk, and policy decisions are persisted as auditable step results.
6. The action planner creates one canonical persisted plan with a rollback strategy, exact targets, source revisions, and a plan hash.
7. Critical/high-risk or otherwise policy-blocked plans pause for human approval.
8. The approver sees the same plan hash and exact action content that execution will use.
9. Approval writes a durable actor-bound anchor before any external write. Replays are idempotent.
10. Code-fix execution uses only a real current file snapshot, a generated diff, and a successful patch/syntax/security validation result.
11. The canonical GitHub service writes the exact approved diff, re-fetches the PR, and records the verified external result.
12. Other tools execute through an isolated, authenticated tool boundary with policy, allow-list, hash, lock, timeout, and audit enforcement.
13. Verification independently queries live postconditions and classifies the result as verified, failed, or inconclusive.
14. Failed verification attempts only an explicitly approved rollback; otherwise the incident is escalated/manual-handoff.
15. Reports, dashboard state, audit history, and knowledge write-back reflect persisted facts rather than placeholders or inferred success.

## 7. Ordered Implementation Phases

### Phase 0 — Baseline, decisions, and worktree stabilization

**Objective:** Establish a trustworthy starting point without losing the current uncommitted work.

**Actions:**

1. Inventory the current diff by feature area and identify generated files, intentional changes, stale files, and accidental line-ending churn.
2. Preserve all user work; do not reset or delete unreviewed files.
3. Decide and document the target release level: local/test, staging, or production-ready.
4. Install the supported toolchain from `pyproject.toml`, `poetry.lock`, `package.json`, and `pnpm-lock.yaml`.
5. Run the current baseline checks and record exact output.
6. Reconcile package metadata and documentation, including the current Next.js/React versions and infrastructure files.
7. Create or update a release-gate tracking record so each later phase has an owner, evidence, and status.

**Likely files:**

- `docs/implementation-progress.md`
- `docs/implementation-plan.md`
- `README.md`
- `RISE_ARCHITECTURE_AND_STATUS.md`
- `infra/README.md`
- `.github/workflows/`
- `pyproject.toml`, `poetry.lock`, `package.json`, `pnpm-lock.yaml`

**Acceptance criteria:**

- A clean baseline branch or commit exists for implementation.
- Unit, dashboard, OPA, lint, type, build, migration, and applicable integration results are recorded.
- No phase is marked complete based only on a historical result.

### Phase 1 — Durable event-to-graph workers

**Objective:** Turn ingestion from a producer-only path into a reliable incident-triggered workflow.

**Actions:**

1. Define the Redis Stream event envelope: event ID, tenant ID, incident ID, source, payload reference, correlation key, schema version, created time, and retry metadata.
2. Add a consumer group with explicit acknowledgment and pending-entry recovery.
3. Start the graph through a worker entrypoint rather than through an API request or an in-process liveness container.
4. Use PostgreSQL-backed LangGraph checkpoints in staging/production and retain `MemorySaver` only for local/test use.
5. Propagate tenant-scoped DB sessions and correlation IDs through every graph node.
6. Add bounded retries, exponential backoff, poison-event detection, and DLQ records.
7. Make event-to-graph start idempotent using the persisted incident/event identity.
8. Expose worker health, stream lag, retry count, DLQ count, and checkpoint age metrics.
9. Keep `AUTO_RUN_AGENT_GRAPH` disabled in tests and preserve explicit invocation support for evaluation.

**Likely files:**

- `apps/api/src/services/ingestion/`
- `apps/api/src/deps/redis.py`
- `apps/agents/src/__main__.py`
- `apps/agents/src/orchestrator/graph.py`
- `packages/rise-core/db/session.py`
- `packages/rise-core/db/runtime.py`
- `packages/rise-core/db/models.py`
- new worker/checkpoint modules under `apps/agents/src/`
- `apps/agents/Dockerfile`, `apps/api/Dockerfile.worker`
- `infra/k8s/base/`, `infra/k8s/overlays/`, `infra/k8s/helm/`

**Tests and acceptance:**

- A signed webhook creates one incident and one graph run.
- Redelivery does not create a duplicate run or duplicate action.
- A worker restart resumes from a PostgreSQL checkpoint.
- A permanently invalid event reaches the DLQ with a reason and audit record.
- Stream lag and worker health are observable.
- No action can execute without the existing policy and approval controls.

### Phase 2 — Exact persisted plans and grounded real-PR remediation

**Objective:** Make the real remediation path use the same grounded, validated, approved plan that the user reviewed.

**Actions:**

1. Define a canonical persisted remediation-plan representation containing:
   - incident/action identity;
   - action type and exact tool arguments;
   - target repository, branch, file, and source revision;
   - original file hash and current file hash;
   - generated diff/patch content or immutable artifact reference;
   - patch hash and full action-plan hash;
   - validation results and validator version;
   - rollback strategy;
   - evidence references and timestamps.
2. Ensure the context/grounding node fetches current GitHub bytes before requesting a code-fix diff.
3. Generate the diff from the grounded file bytes using the configured LLM gateway.
4. Run patch application, syntax, target-file, size, path, secret, and policy validation before persistence.
5. Persist the exact validated plan and expose its hash to the API and dashboard.
6. Change `commit_remediation_to_github` to accept only the persisted validated patch and source revision.
7. Remove the executable `apply_patch_to_text` fallback from the production path. It may remain only as an explicitly labeled local fixture if needed for tests.
8. Re-check the source revision and file bytes immediately before the write to detect drift.
9. Preserve ADR-004: `github_service.py` remains the canonical real writer and `mcp-github` remains a simulation fixture.
10. Keep the direct path's hash check, `{repo}:{target_file}` lock, fail-loud audit, independent PR re-fetch, and verification behavior.
11. Make modified/manual plans require a reviewed persisted diff and a new approval; they must not become a generic executable fix.

**Likely files:**

- `apps/agents/src/nodes/github_file_fetcher.py`
- `apps/agents/src/engines/patch_validator.py`
- `apps/agents/src/engines/action_planner.py`
- `apps/agents/src/nodes/decision_plan.py`
- `apps/agents/src/nodes/execution.py`
- `apps/api/src/services/github_service.py`
- `apps/api/src/routers/actions.py`
- `packages/rise-core/db/models.py`
- `packages/rise-core/schemas/agent_state.py`
- `packages/rise-core/schemas/api.py`
- `db/migrations/versions/`
- `apps/dashboard/components/action-modals.tsx`
- `apps/dashboard/app/incidents/[id]/page.tsx`

**Tests and acceptance:**

- No LLM code-fix call occurs if the current source file cannot be fetched.
- A patch against stale bytes is rejected before any GitHub write.
- Invalid, syntactically broken, out-of-scope, or secret-containing diffs are rejected.
- A successful PR contains exactly the reviewed diff and source revision.
- A plan modification requires a new hash and a new approval.
- Approval replay, stale approval, concurrent file lock, audit failure, and GitHub failure remain fail-closed.
- A real GitHub success is never routed through the failing simulation fixture.

### Phase 3 — Live evidence and verification/recovery

**Objective:** Replace synthetic post-action success with independent, action-specific, live verification.

**Actions:**

1. Define an observability adapter contract for metrics, logs, health probes, deployment state, and relevant security signals.
2. Implement adapters for the supported deployment targets, with explicit credentials, timeouts, query limits, and tenant/resource scoping.
3. Add pre-action baseline capture where needed so verification can compare before/after behavior.
4. Define verification criteria per action type: pod restart, deployment rollback, scaling, configuration change, code-fix PR, security response, and AWS action.
5. Persist every observation with source, query, timestamp, result, and confidence.
6. Treat unavailable telemetry, stale telemetry, and ambiguous results as `unverified` or failure; never convert them to success.
7. Define rollback eligibility and rollback plans per action type.
8. Ensure rollback is itself policy-checked, approval-aware, locked, audited, and independently verified.
9. Remove hardcoded `post_action_metrics` from canonical approval flows.

**Likely files:**

- `apps/agents/src/nodes/verification.py`
- `apps/agents/src/nodes/impact_analyzer.py`
- `packages/rise-core/knowledge_service/`
- `packages/mcp-servers/mcp-observability/`
- `packages/mcp-servers/mcp-kubernetes/`
- `packages/mcp-servers/mcp-aws/`
- `apps/api/src/routers/verification.py`
- `packages/rise-core/db/models.py`
- `db/migrations/versions/`

**Tests and acceptance:**

- Verification independently re-fetches the external system of record.
- A successful API call with an unhealthy postcondition fails verification.
- Missing telemetry cannot close an incident.
- A failed verification follows the configured rollback/manual-handoff route.
- Rollback failure escalates and remains fully auditable.

### Phase 4 — Persistent integrations and authorized ChatOps

**Objective:** Complete real human approval and integration behavior in deployed environments.

**Actions:**

1. Store integration credentials/configuration references securely and scope them by tenant.
2. Complete GitHub installation/app permission validation and repository/resource mapping.
3. Bind Slack interactive callbacks to a persisted action, tenant, displayed plan hash, and real provisioned actor.
4. Resolve the Slack actor to a RISE user through a configured mapping; reject unknown actors.
5. Persist approval intent before execution and make callback retries idempotent.
6. Add signed callback expiry, replay prevention, and message/action correlation.
7. Send approval cards with RCA evidence, impact, risk, exact action, rollback, plan hash, and simulation labels.
8. Wire dashboard approve/reject/modify actions to the same server-side persisted contract and display the canonical hash.
9. Ensure secondary-channel SLA escalation is durable and records its result.
10. Expose integration health and last successful verification in the integrations console.

**Likely files:**

- `apps/api/src/routers/webhooks.py`
- `apps/api/src/routers/actions.py`
- `apps/api/src/services/approval_lock.py`
- `apps/api/src/services/incident_views.py`
- `apps/agents/src/services/slack_card.py`
- `packages/mcp-servers/mcp-slack/slack_server.py`
- `apps/dashboard/components/action-modals.tsx`
- `apps/dashboard/lib/api-client.ts`
- `apps/dashboard/lib/auth-context.tsx`
- `packages/rise-core/db/models.py`

**Tests and acceptance:**

- A valid Slack action can approve only its bound action and plan.
- An unknown, expired, replayed, cross-tenant, or modified callback is rejected.
- Dashboard and Slack approvals produce the same persisted approval semantics.
- Approval retries return the original committed result without repeating the external write.
- SLA escalation is tested against persisted pending actions.

### Phase 5 — Complete API, reporting, knowledge, and UI truthfulness

**Objective:** Ensure every user-visible response is sourced from current tenant-scoped persisted state.

**Actions:**

1. Audit every route against the actual schema and API contract.
2. Ensure action lists, decisions, agent runs, verification, RCA/impact, knowledge, policies, reports, and evidence-chain routes query real rows and represent empty/loading/failed states honestly.
3. Fix any remaining signature drift such as report risk-score calls.
4. Remove stale fixed DTOs, fixture-shaped responses, and inferred status values.
5. Add pagination, filters, tenant scoping, authorization checks, and stable ordering to high-volume routes.
6. Ensure report metrics distinguish simulated, human-approved, auto-approved, failed, verified, and unverified outcomes.
7. Make knowledge ingestion and retrieval preserve source, tenant, version, and provenance.
8. Update dashboard types to match backend enums and lifecycle states.
9. Ensure the UI never turns a missing backend field into a success claim.

**Likely files:**

- `apps/api/src/routers/actions.py`
- `apps/api/src/routers/agent_runs.py`
- `apps/api/src/routers/verification.py`
- `apps/api/src/routers/root_cause_impact.py`
- `apps/api/src/routers/knowledge.py`
- `apps/api/src/routers/policies.py`
- `apps/api/src/routers/reports.py`
- `apps/api/src/routers/incidents.py`
- `apps/api/src/services/report_generator.py`
- `apps/api/src/services/incident_views.py`
- `apps/dashboard/lib/api-client.ts`
- `apps/dashboard/lib/types.ts`
- `apps/dashboard/app/`

**Tests and acceptance:**

- Every route has tenant-isolation and authorization coverage.
- Report totals reconcile with persisted incidents/actions/verification rows.
- Empty, unavailable, simulated, and failed states are distinct in API and UI.
- Evidence-chain output contains stored evidence rather than display-time LLM reconstruction.

### Phase 6 — Finish tools and enforce execution isolation

**Objective:** Move from in-process/demo-compatible tools to production-grade, independently constrained execution.

**Actions:**

1. Decide and document the production tool boundary: JSON-RPC over stdio, HTTP/SSE, or another explicitly supported protocol.
2. Package Kubernetes, AWS, Slack, observability, and knowledge tools as separate processes or services.
3. Give each server only the credentials and network access required for its tool set.
4. Add authenticated gateway-to-server communication, request IDs, timeouts, cancellation, and bounded response sizes.
5. Preserve the gateway static Python allow-list as defense-in-depth and the upstream Risk Engine OPA decision; do not mislabel the allow-list as OPA.
6. Keep resource lock acquisition plan-level and retain gateway non-destructive conflict checks.
7. Implement observability MCP tools or an equivalent approved adapter.
8. Implement knowledge MCP tools over the existing Qdrant-backed knowledge service, including tenant filters and provenance.
9. Replace security-action no-ops with real provider calls where supported; otherwise mark them as non-executable and route to manual handoff.
10. Ensure the GitHub real-write path remains the direct canonical service unless a new ADR explicitly changes that decision.
11. Restrict in-process tools to local/test and supervised staging; fail closed in production when isolation is unavailable.

**Likely files:**

- `packages/rise-core/mcp_client/gateway.py`
- `packages/rise-core/mcp_client/lock.py`
- `packages/mcp-servers/`
- `packages/rise-core/knowledge_service/`
- `apps/agents/src/nodes/execution.py`
- `apps/api/src/services/github_service.py`
- `infra/k8s/`
- `infra/terraform/`
- new MCP service Dockerfiles and transport clients
- `docs/architecture-decisions.md`

**Tests and acceptance:**

- A tool server crash cannot crash or corrupt the graph worker.
- Tool credentials cannot be used across server boundaries or tenants.
- Unauthorized tool, unsafe argument, wrong environment, stale hash, lock conflict, timeout, and transport failure all fail closed.
- Production configuration rejects in-process autonomous execution.
- Observability and knowledge tool calls either work against live dependencies or return a structured, auditable unsupported result.

### Phase 7 — Evaluation, integration, E2E, and resilience gates

**Objective:** Prove the completed system without conflating mock orchestration with live RCA or production success.

**Actions:**

1. Keep orchestration certification deterministic and report it only as `Orchestration Certification: X/Y`.
2. Expand the RCA corpus to at least 50 independently authored, stratified, peer-reviewed cases.
3. Keep raw evidence separate from answer keys and mechanism rubrics.
4. Run live RCA with explicit provider/model/prompt/dataset/git metadata, deterministic temperature where supported, latency, token, and cost data.
5. Fail loud when live providers fail; never substitute a mock response.
6. Measure strict mechanism match, evidence grounding, hallucination rate, and confidence intervals.
7. Implement a full-stack E2E harness using the API, dashboard browser, PostgreSQL, Redis, Qdrant, and deterministic external-service doubles where live third-party writes are inappropriate.
8. Exercise the full flow: signed alert → persistence → worker → graph → approval → exact execution → live verification → report.
9. Run integration tests against disposable PostgreSQL, Redis, and Qdrant services.
10. Run chaos scenarios for worker restart, provider outage, Redis loss, DB outage, tool crash, stale checkpoint, duplicate event, and verification failure.
11. Run load tests against live worker/stream behavior and record capacity assumptions.
12. Add policy tests for every supported action/environment/risk tier combination.

**Likely files:**

- `eval/run_eval.py`
- `eval/rca_judge.py`
- `eval/golden_dataset/`
- `eval/adversarial_dataset/`
- `tests/e2e/`
- `tests/integration/`
- `tests/chaos/`
- `tests/load/`
- `policies/tests/`
- `.github/workflows/ci.yml`

**Acceptance criteria:**

- Unit suite is green with expected skips only.
- OPA policy suite is green from a checksum-pinned binary.
- PostgreSQL migrations upgrade and downgrade cleanly.
- RLS and concurrent audit-chain tests pass with restricted application privileges.
- Redis lock ownership and nonce/release tests pass.
- Full-stack E2E completes without fabricated success.
- RCA pilot is clearly labeled until it reaches 50 cases and meets the release threshold.
- Zero false auto-approvals across adversarial scenarios.

### Phase 8 — Deployment and operations readiness

**Objective:** Make deployment artifacts executable, observable, and recoverable.

**Actions:**

1. Validate Dockerfiles for API, worker, agents, dashboard, and isolated tool services.
2. Finalize Kustomize base/overlays and Helm chart parity.
3. Ensure staging Terraform is complete and plan-able against the intended AWS account.
4. Validate production Terraform IAM policies, trust conditions, secrets access, network boundaries, and resource names.
5. Add PostgreSQL, Redis, Qdrant, OPA, API, worker, dashboard, and MCP service configuration through secret references rather than committed values.
6. Add worker and stream consumer deployments, HPAs, PodDisruptionBudgets, resource limits, and security contexts.
7. Add metrics, logs, traces, alerts, dashboards, and runbook links for every critical queue and remediation path.
8. Replace staging workflow no-op deployment with an authenticated, environment-protected rollout.
9. Make production canary health checks query real metrics and block promotion on failure; do not print a success message from a Python placeholder.
10. Add tested rollback for application, migration, worker, tool-service, and configuration changes.
11. Decide whether n8n is a supported runtime. If yes, export and version the workflows; if no, remove it from the supported architecture and documentation.

**Likely files:**

- `apps/*/Dockerfile*`
- `infra/k8s/base/`
- `infra/k8s/overlays/`
- `infra/k8s/helm/`
- `infra/terraform/envs/`
- `infra/terraform/modules/`
- `.github/workflows/deploy-staging.yml`
- `.github/workflows/deploy-prod.yml`
- `infra/n8n-workflows/`
- `docs/runbooks/`

**Acceptance criteria:**

- `helm lint` and `kubectl kustomize` succeed for each supported environment.
- Terraform formatting, validation, and plan succeed without embedded secrets.
- A staging deployment reaches readiness and exposes worker/tool health.
- A canary is promoted only using real health data.
- Rollback is rehearsed and documented.

### Phase 9 — Shadow mode, release review, and controlled promotion

**Objective:** Prove operational behavior before enabling any autonomous production action.

**Actions:**

1. Run a new, current staging shadow-mode period with immutable event and decision records.
2. Measure recommendation precision, false-positive rate, confidence calibration, latency, queue lag, failure rate, rollback rate, and human override rate.
3. Review every proposed autonomous action with an identified operator.
4. Validate that only the explicitly approved low-risk policy scope can auto-execute.
5. Confirm critical actions, code changes, missing rollback plans, missing evidence, unavailable OPA, unavailable telemetry, and isolated-tool failures remain human-gated.
6. Produce an updated burn-in report; do not reuse the historical 2026-07/08 report as current evidence.
7. Obtain independent security, platform, and stakeholder sign-off.
8. Promote in stages: observation only → supervised staging execution → restricted canary → broader operation, with rollback triggers at each stage.

**Acceptance criteria:**

- Current burn-in evidence meets the approved thresholds.
- No unresolved critical/high security findings remain.
- RCA benchmark has reached the required release-gate size and quality.
- MCP isolation and real verification gates are proven.
- Stakeholders sign off on the exact action classes and environments enabled.
- Emergency stop procedure has been rehearsed.

### Phase 10 — Post-release extensions

**Objective:** Complete remaining roadmap items that are not required for the first safe release.

**Actions:**

- Add provider adapters only when required by a supported deployment contract.
- Add offline reviewed-feedback analysis and risk/confidence recalibration.
- Automate shadow-mode promotion criteria and statistical reporting.
- Expand tenant-scale, multi-region, and capacity exercises.
- Add additional integrations and workflow exports only with owners and live validation.

## 8. Cross-Phase Safety Invariants

The following must remain true throughout implementation:

1. There is no global autopilot flag.
2. Critical-risk actions and plans without rollback remain human-approved regardless of policy.
3. OPA policy failure fails closed.
4. The gateway Python allow-list is not described as OPA.
5. The Execution Agent retains plan-level lock ownership across all plan steps.
6. Gateway checks remain caller-independent defense-in-depth.
7. Human approval is persisted as actor + plan hash + decision + timestamp before external writes.
8. A stale or missing approval anchor cannot execute.
9. Real code fixes require current source bytes, grounded generation, validation, exact persisted content, and independent external verification.
10. GitHub real writes have one canonical path.
11. Audit failures on remediation paths fail loudly.
12. Tenant boundaries are enforced in application queries and PostgreSQL RLS where available.
13. Simulations are labeled and cannot be reported as live success.
14. Verification is independent of the action result claim.
15. Unknown, incomplete, or ambiguous evidence never increases confidence.

## 9. Suggested Delivery Order and Dependencies

```text
Phase 0 baseline
    ├── Phase 1 durable workers/checkpoints
    ├── Phase 2 exact plan + grounded PR path
    ├── Phase 3 live verification/recovery
    ├── Phase 4 authorized integrations/ChatOps
    └── Phase 5 truthful API/dashboard/reporting

Phase 1 + Phase 2 + Phase 3
    └── Phase 6 isolated tool execution

Phases 1–6
    └── Phase 7 integration/E2E/evaluation gates

Phases 1–7
    └── Phase 8 deployment/operations readiness

Phases 1–8
    └── Phase 9 shadow mode and controlled release

Phase 10 extensions follow the approved release scope.
```

The following dependencies are external inputs, not code tasks:

- PostgreSQL, Redis, and Qdrant environments;
- OPA binary/version and policy review;
- GitHub App/token with least-privilege write access;
- Slack app, signing secret, actor mapping, and public callback endpoint;
- Kubernetes/AWS test targets and scoped credentials;
- supported metrics/logging/health systems;
- live LLM provider credentials for RCA benchmarking;
- staging AWS account, cluster, DNS, secret manager, and observability;
- independent dataset reviewers and release stakeholders.

## 10. Definition of Done

RISE is complete for the production-ready target only when all of the following are true:

- The alert-to-graph workflow is durable, idempotent, tenant-scoped, and restart-safe.
- Every executable action is derived from an exact persisted plan and approval anchor.
- Real code-fix PRs contain grounded, validated, reviewed diffs rather than templated fallback edits.
- Verification uses independent live evidence and supports safe rollback or escalation.
- Human approvals work through dashboard and authorized Slack callbacks.
- Supported tool services are isolated, authenticated, least-privileged, and observable.
- All supported API and dashboard data is DB-backed and truthful.
- Unit, policy, integration, E2E, chaos, load, security, and migration gates pass.
- The RCA benchmark contains at least 50 independently reviewed cases and satisfies the approved release threshold.
- A current shadow-mode burn-in is complete and signed off.
- Deployment workflows perform real, protected, observable staging/canary rollouts.
- Runbooks, rollback procedures, incident response, and emergency stop procedures are tested.
- Documentation, ADRs, release gates, and status tables match the code and deployed topology.

## 11. First Implementation Batch After Approval

After approval, implementation should begin with only this bounded batch:

1. Stabilize the worktree and establish a clean baseline.
2. Install the supported toolchains and rerun the recorded checks.
3. Reconcile the status documents with the current code and infrastructure files.
4. Produce a confirmed failure list for the next phase.
5. Implement Phase 1 durable worker/checkpoint foundations only after the baseline is green or every blocker is explicitly recorded.

Each subsequent batch must report:

- exact files changed;
- database/schema impact;
- safety invariants affected;
- tests and commands run;
- full pass/fail/skip output;
- unresolved environment-dependent checks;
- any contradiction discovered in this plan.

No later phase should be silently implemented ahead of its dependencies.
