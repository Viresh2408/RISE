# Approved implementation progress

## 2026-10-04 — Phase 1: in progress

This record follows the approved 11-phase implementation roadmap. Backend unit
checks are green; Phase 1 is not complete until the dependency/build and live
infrastructure gates below are resolved. No production-readiness claim follows
from the offline tests.

### Changes in this continuation

- **Approval lifecycle** — `apps/api/src/routers/actions.py`: durable, operation-
  and actor-bound idempotency for approve/reject/modify; conditional pending-action
  claims comparing the unchanged plan; expiry checks; rollback on audit failure;
  terminal actions cannot be edited/resurrected. Intent is committed before external
  writes, and completion/result/audit commit together. Deployed actors must be
  provisioned for the action's tenant. Manual plans cannot execute as a generic fix.
- **API boundaries** — `apps/api/src/middleware/envelope.py`, `main.py`,
  `routers/webhooks.py`: structured Redis-lock 503 responses; deployed Slack
  approve/reject/modify callbacks are refused until real actor/action/plan binding
  exists. Fixture-named action IDs no longer manufacture conflict results.
- **Tenant transactions** — `packages/rise-core/db/session.py`:
  transaction-local RLS scope survives commits/rollbacks; borrowed sessions clear
  their scope and cannot switch tenants; local in-memory SQLite uses StaticPool.
  `apps/agents/src/orchestrator/graph.py` and `nodes/investigation.py` now use the
  scoped session itself rather than opening a separate unscoped one.
- **Audit integrity** — `packages/rise-core/db/models.py`,
  `apps/api/src/middleware/audit.py`: the tenant row remains the serialization lock;
  the immutable tail is read under READ COMMITTED without requiring revoked UPDATE
  privileges on audit rows. See ADR-006 and the restricted-role concurrency test.
- **Execution boundary** — `packages/rise-core/mcp_client/gateway.py`, `lock.py`:
  production/unknown-deployment writes are denied at dispatch regardless of plan
  parameters; deployed writes must persist audit intent before dispatch. Resource
  leases have unique nonces distinct from stable ownership, with atomic release.
- **Evidence/policy** — `apps/agents/src/engines/decision_engine.py`,
  `risk_engine.py`, `policies/approval_rules.rego`: missing RCA confidence is zero,
  not an invented 95%; inactive or wrongly scoped policies cannot authorize auto
  execution; production autonomy remains blocked by the in-process transport.
- **Frontend API contract** — `apps/dashboard/lib/api-client.ts`: reject/modify
  send the now-required idempotency header.
- **Test isolation/CI** — `conftest.py`, `scripts/run_unit_tests.py`,
  `.github/workflows/ci.yml`: offline routing fixtures and isolated credentials;
  CI now runs frontend tests, checksum-pinned OPA tests, and disposable PostgreSQL
  migration/RLS/audit-concurrency plus Redis ownership checks.
- **Migrations** — `db/migrations/env.py` honors `MIGRATION_DATABASE_URL` or
  `DATABASE_URL`, preserving URL-encoded passwords. Revisions `0006_policy_limits`
  and `0007_approval_intent` compile successfully to PostgreSQL SQL.

### Verification

| Command/check | Actual result |
| --- | --- |
| `poetry.exe run python scripts/run_unit_tests.py -q -o faulthandler_timeout=60` | **697 passed, 2 skipped, 17 deselected**, 5 warnings, 56.30s |
| `pnpm --filter rise-dashboard test` | **22 passed**, 2 test files |
| `/tmp/omnirush/opa test policies/ -v` (OPA 0.63.0) | **19/19 passed** |
| Ruff on the touched approval/webhook/audit, database, gateway/locks, engine and new regression/integration sources | Passed |
| `poetry.exe run mypy apps/api/src/routers/actions.py packages/rise-core/db/runtime.py packages/rise-core/mcp_client/lock.py --follow-imports=skip --ignore-missing-imports` | Passed; targeted check, not a whole-repository type certification |
| `poetry.exe run alembic upgrade head --sql` | Passed; offline SQL generation, not a live migration |
| `pnpm --filter rise-dashboard exec tsc --noEmit --incremental false` | Passed |
| `pnpm lint` | Earlier run passed with existing hook warnings; final 180s rerun timed out |
| `pnpm build` | Compilation succeeded on one run; validation worker stalled and the 600s run timed out |
| Scoped `git diff --check` with `cr-at-eol` | Passed, preserving the working tree's existing Windows line endings |

New coverage: `apps/api/tests/test_phase1_execution_boundaries.py`,
`tests/integration/test_tenant_transactions.py`,
`tests/integration/test_redis_execution_locks.py`. Existing API/RBAC, routing,
approval-anchor, GitHub, Slack and smoke fixtures were reconciled to persisted
targets and fail-closed outcomes.

### Open gates and required inputs

1. **Live PostgreSQL/Redis validation**: Docker Desktop's Linux engine is stopped.
   Restricted-role RLS after transaction boundaries, concurrent audit-chain writes,
   migration upgrade/downgrade, and Redis ownership tests are wired into CI but
   have not been executed locally against live services. Explicit test connection
   variables are `RISE_INTEGRATION_DATABASE_URL`,
   `RISE_INTEGRATION_APP_PASSWORD`, and `RISE_INTEGRATION_REDIS_URL`.
2. **Framework upgrade decision**: `pnpm audit --prod` reports **38 vulnerabilities**
   (3 critical, 14 high, 17 moderate, 4 low). The two critical Next.js RCE advisories
   GHSA-p293-qw3h-jr36 and GHSA-2xp9-vwfh-vxw4 require **Next.js >=15.5.24**.
   This needs a compatible Next.js/React-stack migration from the current Next.js
   14 / React 18 dashboard, plus a fresh dependency audit and build.
3. **Build gate**: standalone TypeScript checking passes, but the Next.js build
   worker does not finish in this WSL environment. No lint/type-check bypass was
   added to the application or CI. Recheck the migrated stack using the CI Node
   runtime or an isolated build container once the Docker engine is available.

### Subsequent approved phases

2. Durable workers and PostgreSQL checkpoints.
3. Exact persisted-plan execution and reviewed patch/hash binding.
4. Evidence-based live verification and recovery criteria.
5. Persistent integrations and authorized ChatOps.
6. Truthful API/reporting and knowledge workflows.
7. Tool completion and execution isolation.
8. Automated E2E/integration/evaluation release gates.
9. Deployment and operational readiness.
10. Live staging/shadow-mode validation and sign-off.
11. Provider, n8n and reviewed-feedback extensions.
