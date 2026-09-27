# RISE — Remediation Plan
Source: ground-truth audit (verified against code + tests, 559/16/1/13 pytest run).
Work phases in order. Each item lists exact file(s) — do not explore broadly, go directly
to the cited location. Report back with a diff summary + test output per phase, not prose.

---

## PHASE 0 — SECURITY (block everything else until done)

### 0.1 Remove auth backdoor
File: `apps/api/src/deps/auth.py`
- Delete the `demo-token-hardcoded` / `demo-` prefix admin bypass entirely. No env-gate,
  no flag — remove the code path completely, same treatment as the earlier
  `RISE_TEST_MODE` fix.
- Grep repo-wide for `demo-token-hardcoded` and `demo-` token references, remove all.
- If a demo/dev login is genuinely needed, replace with a seeded real user row + real
  Supabase auth flow, documented in README setup steps — not a magic string.

### 0.2 Fix CORS
File: `apps/api/src/main.py`
- Replace `allow_origins=["*"]` with an explicit origin list from env
  (`CORS_ALLOWED_ORIGINS`, comma-separated), defaulting to `http://localhost:3000` for
  local dev.

### 0.3 Fail closed on missing JWT secret
File: `apps/api/src/deps/auth.py`
- If `SUPABASE_JWT_SECRET` is unset, refuse to start the app in any environment (raise at
  import/startup, same pattern as the existing `_validate_github_configuration` guard) —
  never "warn only and fall through."

### 0.4 Remove frontend fabrication
File: `apps/dashboard/lib/api-client.ts` (or wherever `approveAction` lives)
- Delete the hardcoded `commit_sha: '101a1992ff'` fake-success fallback. On backend
  failure, surface a real error state to the UI — never fabricate a success response.
File: dashboard incident list/demo data source (locate the 9+ hardcoded incidents)
- Delete hardcoded incident fixtures. If backend is unreachable, show a real "cannot
  connect to API" empty/error state, not fake data.

### 0.5 Test: prove 0.1–0.4
- Add/run a test confirming a request with `Authorization: Bearer demo-token-hardcoded`
  (or any `demo-` prefixed token) is rejected as any other invalid token would be.
- Add/run a test confirming app startup raises if `SUPABASE_JWT_SECRET` is unset.
- Add/run a frontend test confirming a simulated backend-down state renders an error UI,
  not fabricated data.

**Phase 0 gate: do not proceed to Phase 1 until 0.1–0.5 pass.**

---

## PHASE 1 — Cheap, high-value test fixes (unlocks real coverage)

### 1.1 Fix pytest-asyncio marker mismatch
File: `tests/test_safety_invariants_regression.py`
- Repo standard is `@pytest.mark.anyio` (per audit) — either change this file's markers
  from `@pytest.mark.asyncio` to `@pytest.mark.anyio`, OR add `pytest-asyncio` as a
  dependency and configure `asyncio_mode` — pick whichever matches the rest of the repo's
  existing convention. Re-run: all 11 previously-silent safety invariant tests must
  actually execute and pass (GitHub-error-never-fabricates-success, local-files-never-
  modified-as-fallback, nonexistent-PR-fails-verification).

### 1.2 Reconcile 4 tests to the new fail-closed contract
These are **not bugs to revert** — the hardening is correct; the old tests are stale.
- `tests/test_mock_smoke.py:215` and `apps/api/tests/test_api_endpoints.py:146`: update
  expected value from `'approved'` to `'requires_human'` (no GitHub token in test env →
  correct refusal, not a regression).
- `tests/test_security_actions.py:187`: update expected value from `'executed'` to
  `'verified_success'`.
- `apps/agents/tests/test_execution_agent_mcp.py:300`: update test to expect the MCP
  GitHub server's rejection message when mock transport is disabled in staging/prod, or
  explicitly mark this test as local/dev-only if it depends on the mock path.

### 1.3 Fix doc/test drift
File: `docs/launch-checklist-signoff.md` and `tests/test_prod_shadow_mode.py:164`
- The doc honestly shows 9/12 checked (3 flipped to "superseded"). Update the test's
  assertion from `>= 12` to match reality, or restore doc parity if 3 items were wrongly
  marked superseded — confirm which is correct before changing either.

**Phase 1 gate:** run full suite, report new pass/fail/skip counts. Expect ~570 passing.

---

## PHASE 2 — Close the gateway enforcement gap

### 2.1 Reconcile "OPA" naming
File: `packages/rise-core/mcp_client/gateway.py` (function `evaluate_opa_allowlist`)
- This is a hardcoded Python allow-list, not OPA. Either (a) rename it to stop implying
  OPA (`evaluate_python_allowlist` or similar) and document clearly that only the Risk
  Engine makes a real OPA HTTP call, or (b) wire this function to actually call the stored
  `opa_client` against the real `tool_allowlist.rego` policy. Given the risk engine
  already does real OPA evaluation upstream of this point, (a) — honest renaming — is the
  lower-effort, acceptable fix; note the decision in `docs/architecture-decisions.md`.

### 2.2 Move (or duplicate) resource lock + plan-hash check into the gateway
Files: `packages/rise-core/mcp_client/gateway.py`, `apps/agents/src/nodes/execution.py`
- Currently the Redis lock and plan-hash verification happen only in the execution node,
  not at the actual tool-dispatch point (the gateway). Confirm whether every tool call
  genuinely routes through the execution node first (if so, this may be an acceptable
  single-choke-point design — document it as such) or whether any other code path can
  reach the gateway directly, bypassing those checks (if so, this is a real gap — move the
  lock acquisition and hash check into the gateway itself so it's enforced regardless of
  caller).

### 2.3 Fix silent audit-write failure
File: `packages/rise-core/mcp_client/gateway.py` (best-effort audit write)
- Currently throws "badly formed hexadecimal UUID string" on non-UUID incident IDs and
  silently swallows the error — audit logging quietly fails. Fix: validate/coerce the
  incident ID before the audit write, and if it still fails, raise/log loudly — audit
  writes must never fail silently given the immutability guarantee they exist to provide.

---

## PHASE 3 — Finish the hardcoded/facade API routers

Audit found these are hardcoded DTOs, not real DB-backed logic:
`decision.py`, `reject.py`/`modify.py` (or wherever these live in `actions.py`),
`GET /actions`, `agent_runs.py`, `knowledge.py`, `policies.py`, `verification.py`,
`root_cause_impact.py`.

### 3.1 Audit each router against its actual approved spec
Cross-reference each against `api-specification.md` (if present) — each should query real
DB rows (Incident, RootCause, ImpactAssessment, RemediationAction, RiskPolicy,
KnowledgeEntry tables), not return a fixed/templated response regardless of input.

### 3.2 Fix in priority order (highest-traffic / most load-bearing first)
1. `GET /actions`, `decision.py` — these back the incident detail page's core approval UI
2. `agent_runs.py` — backs the timeline view
3. `verification.py`, `root_cause_impact.py` — backs RCA/impact display
4. `knowledge.py`, `policies.py` — lower traffic, fix last

### 3.3 Fix known latent bug
File: `report_generator.py` vs wherever `incidents.py` calls it
- `compute_risk_score` is called with two different signatures → `TypeError` on the
  `risk_score <= 0` path. Standardize the signature, add a regression test for the zero/
  negative risk score case specifically.

---

## PHASE 4 — Reconcile GitHub integration paths

### 4.1 Clarify which GitHub path is real
The audit found `github_service.py` performs real GitHub writes (confirmed by prior real
PRs on the live repo), while `packages/mcp-servers/mcp-github` is a mock facade
(`is_test_fixture: True`, now blocked in staging/prod).
- Determine: does the actual remediation flow (Execution Agent → PR creation) call
  `github_service.py` directly, or does it go through the MCP gateway → mcp-github facade?
- If the real path bypasses MCP entirely: document this explicitly (the MCP-github "tool
  server" concept is currently unused for real execution) and either (a) wire it to
  actually call `github_service.py` so the MCP abstraction is real, or (b) remove/mark the
  facade as deprecated and simplify — don't leave two parallel, inconsistent GitHub
  integration paths undocumented.

---

## PHASE 5 — RCA accuracy: build the real benchmark

(See prior conversation — the existing 100% figure is orchestration-plumbing validation
only; `rca_judge.py` referenced in `docs/evaluation-methodology.md` doesn't exist.)

### 5.1 Build `eval/rca_judge.py`
- Run the REAL Root Cause Agent (real LLM call, real fetched context) against 10 golden
  scenarios (not the mock-populated state).
- Score `cause_summary` against `ground_truth_root_cause` requiring the correct technical
  mechanism, not substring/keyword overlap (see prior conversation for the scoring
  critique).
- Report this as a separate, clearly-labeled number: "Live RCA benchmark (pilot, n=10):
  X% — NOT RELEASE ELIGIBLE, target n≥50" per the existing doc's own stated bar.

### 5.2 Update all references
Any doc/README claiming "100% RCA accuracy" must be updated to distinguish orchestration-
certification (mock-based, 20/20) from the real RCA benchmark (live, pilot-scale, separate
number) per the split already agreed in this project's history.

---

## PHASE 6 — Lower priority, explicitly scope in or out

Confirm with project owner before spending tokens on these — likely acceptable to
document as "intentionally out of scope for this project's current stage" rather than fix:

- MCP AWS (no boto3), MCP Slack (bot_token unused, no real sends), Slack/SMS log-only
  senders — real integrations, meaningful effort, low portfolio value unless demoing
  live notifications specifically.
- MCP observability / MCP knowledge — currently crash with `ValueError` if called (tools
  allow-listed but undispatched). Minimum fix: catch and return a clear "not implemented"
  error instead of an unhandled crash — do this regardless of whether full implementation
  happens.
- K8s overlays (missing `base/`), Helm (values-only, no chart), n8n workflow READMEs,
  Terraform staging/prod gaps — these were never going to be deployed for real; either
  finish them or explicitly label the `infra/` directory's incomplete parts as reference
  scaffolding, not working IaC.
- CI stub workflows (`ci.yml`, `deploy-staging.yml`, `security-scan.yml` are checkout-only)
  — at minimum wire `ci.yml` to actually run `pytest` and `pnpm build` on every PR, so the
  559 passing tests actually gate something.
- `tests/e2e/` empty, `policies/tests/policy_test.rego` is 2 empty lines — low priority
  unless demoing E2E/policy-test coverage specifically.

---

## Housekeeping
- Delete the transient `_test_run.log` at repo root (confirmed safe, read-only audit made
  no code changes).
- After Phase 0–2 complete, re-run the full suite once and update
  `docs/launch-checklist-signoff.md` to reflect genuinely new state — don't let it drift
  stale again.

## Reporting format for every phase
For each phase, report: (1) exact diff or new/changed file list, (2) exact test command
run + full pass/fail output, (3) anything found during the work that contradicts this
plan's assumptions — don't silently work around a contradiction, flag it.

---

## ADDENDUM — 2026-09-27 reconciliation + security fixes applied

Re-verified this plan's security items against current code before acting.
**Contradiction flagged (per the reporting rule above):** most of Phase 0 is already
implemented in the tree — do not redo it:

- **0.1 auth backdoor** — no `demo-token-hardcoded` / `demo-` bypass exists in
  [auth.py](apps/api/src/deps/auth.py). `_verify_token` (auth.py:215) fails closed;
  a regression test already guards it ([test_auth_rbac.py:354](apps/api/tests/test_auth_rbac.py#L354)). DONE.
- **0.2 CORS** — [main.py:304-315](apps/api/src/main.py#L304-L315) reads
  `CORS_ALLOWED_ORIGINS` (default `http://localhost:3000`); no `["*"]`. DONE.
- **0.3 fail-closed JWT** — `_validate_auth_configuration` runs at import
  ([main.py:251](apps/api/src/main.py#L251)); `_verify_token` rejects when no secret. DONE.
- **0.4 api-client fabrication** — `commit_sha:'101a1992ff'` is gone; dashboard tests
  assert the outage path throws ([dashboard.test.tsx:108-134](apps/dashboard/tests/dashboard.test.tsx#L108-L134)). DONE.

### Newly-confirmed-open gaps FIXED this session (verified against code, tests green)

1. **Cross-tenant incident read (IDOR).** [incidents.py:391](apps/api/src/routers/incidents.py#L391)
   `get_incident` filtered on `Incident.id` only — a user in tenant A could read any
   incident by id. Added `Incident.tenant_id == tenant_id` to the WHERE (every sibling
   endpoint already scoped by tenant; this one was the outlier). New regression:
   `TestCrossTenantIncidentIsolation` in [test_auth_rbac.py](apps/api/tests/test_auth_rbac.py).
2. **Slack button → un-anchored autonomous action.** [webhooks.py:534](apps/api/src/routers/webhooks.py#L534)
   The interactive `approve` handler fabricated a hardcoded `restart_pod` plan
   (auth-service-7890/staging) and fire-and-forgot `run_execution_agent()` with no
   `approved_plan_hash`, no `require_approved_hash`, no db_session, swallowing every
   exception. Removed the fabricated execution; the button now only records the durable
   decision. Real execution flows through the anchored API approve path (ADR-005), which
   binds the persisted `Approval` hash before any tool runs.
3. **Frontend privilege fabrication.** [auth-context.tsx:49](apps/dashboard/lib/auth-context.tsx#L49)
   On backend session-exchange failure, `fetchBackendSession` invented
   `roles:['approver','engineer','viewer']` + a user_id + tenant. Now fails closed
   (clears session, propagates error) so the UI shows an outage state, not fake privileges.

### Still open (security) — next

- **Execution hash anchor is opt-in.** [execution.py:84](apps/agents/src/nodes/execution.py#L84)
  enforces only when `require_approved_hash` is set. The external un-anchored trigger
  (Slack) is now closed, but the LangGraph `node_execute` path still runs un-anchored
  ([graph.py](apps/agents/src/orchestrator/graph.py)). Decide: make the anchor mandatory
  in staging/prod (fail-closed by environment) vs. keep opt-in — needs the integration
  suite run to confirm no legitimate path breaks. Tracked as the next security task.
