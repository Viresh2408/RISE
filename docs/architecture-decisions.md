# Architecture Decision Records (ADRs)

## ADR-001: MCP Server In-Process Execution vs. Out-of-Process Isolation

- **Status**: Accepted
- **Date**: 2026-09-20
- **Context**: RISE Model Context Protocol (MCP) Integration

### Context & Problem Statement
Model Context Protocol (MCP) servers (Kubernetes, AWS, GitHub, Slack) provide tool execution capabilities for RISE remediation actions. In an idealized enterprise deployment, MCP servers run in separate processes or containers communicating over JSON-RPC (stdio / SSE / gRPC) to ensure sandboxed fault isolation and security boundaries. 

In `packages/rise-core/mcp_client/gateway.py`, the MCP server modules are imported directly in-process via `sys.path.insert`:
```python
_ROOT_DIR = Path(__file__).resolve().parents[3]
for _server_dir in ["mcp-kubernetes", "mcp-aws", "mcp-github", "mcp-slack"]:
    _p = str(_ROOT_DIR / "packages" / "mcp-servers" / _server_dir)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kubernetes_server import MCPKubernetesServer
from aws_server import MCPAWSServer
from github_server import MCPGitHubServer
from slack_server import MCPSlackServer
```

### Decision
For the current operational scope of RISE (local orchestration, CI/CD evaluation, single-tenant / containerized worker nodes):
1. **In-process execution is accepted**: MCP servers are instantiated directly as Python classes (`MCPKubernetesServer`, `MCPAWSServer`, etc.) within `MCPGateway`.
2. **Security & Guardrails Enforced via Middleware**:
   - All tool calls pass through `evaluate_python_allowlist()`, a static in-process
     structural allow-list (defense-in-depth). The authoritative OPA evaluation happens
     upstream in the Risk Engine — see ADR-002.
   - Action plan step parameters and names are verified before dispatch.
   - Resource locking (`ResourceLockManager`) and execution timeouts (`default_timeout_seconds=30.0`) prevent runaway tool executions.
   - Immutable audit logs are recorded for every invocation (`audit_events`).

### Trade-offs & Consequences
- **Pros**:
  - Eliminates inter-process RPC latency and serialization overhead.
  - Simplifies local deployment and development (no need to manage separate long-running daemon processes for each MCP server).
  - Clean async Python debugging and stack traces across agent nodes and tools.
- **Cons**:
  - Memory or unhandled exceptions in third-party tool libraries (e.g. boto3, kubernetes client) run within the worker's address space.
  - Subprocess boundary crash isolation is absent.

### Future Migration Path
When scaling to multi-tenant or untrusted tool execution environments:
- Wrap each MCP server in a separate container/subprocess adhering to the Anthropic Model Context Protocol specification over stdio or SSE/HTTP.
- Update `MCPGateway` to instantiate MCP stdio/SSE client connections rather than direct class instances.

---

## ADR-002: The Gateway Allow-list is a Static Python List, Not OPA

- **Status**: Accepted
- **Date**: 2026-09-24
- **Context**: RISE MCP Gateway guardrail naming honesty

### Context & Problem Statement
`MCPGateway` previously exposed a method named `evaluate_opa_allowlist()`. The name implied
the gateway made a live Open Policy Agent (OPA) call, but the implementation is a hardcoded
Python allow-list keyed on `(agent_identity, tool_name, environment)`. The only component
that performs a real OPA HTTP evaluation against the `.rego` policies is the **Risk Engine**
(`apps/agents/src/engines/risk_engine.py`), which runs upstream of tool dispatch.

### Decision
The method is renamed to `evaluate_python_allowlist()` to describe what it actually does.
The class docstring and error messages no longer claim "OPA". The distinction is:

| Layer | Mechanism | Location |
|-------|-----------|----------|
| Risk / approval gate | **Real OPA** evaluation against `policies/*.rego` | Risk Engine (upstream) |
| Tool-dispatch allow-list | **Static Python** structural allow-list (defense-in-depth) | `MCPGateway.evaluate_python_allowlist` |

Option (a) — honest renaming — was chosen over wiring a second OPA call into the gateway,
because the authoritative policy decision already happens in the Risk Engine and duplicating
the OPA round-trip per tool call adds latency without adding a real control.

### Consequences
- `ToolBlockedError` from the allow-list now carries `reason="allowlist_denied"` (was
  `opa_allowlist_denied`), and its message reads "blocked by allow-list policy".
- Historical audit records in `eval/audit_trail.json` retain their original "OPA" wording
  and are intentionally left unmodified (immutable audit artifacts).

---

## ADR-003: Gateway Enforcement — Single Choke-Point + Defense-in-Depth

- **Status**: Accepted
- **Date**: 2026-09-24
- **Context**: Where the resource lock and plan-hash checks are enforced

### Context & Problem Statement
The per-resource Redis lock and the approved-plan hash verification originally lived only
in the Execution Agent node (`apps/agents/src/nodes/execution.py`), not at the tool-dispatch
point (`MCPGateway.dispatch_tool_call`). The concern: could any code path reach the gateway
directly and bypass those checks?

**Finding (verified):** In the current codebase the **only** production caller of
`MCPGateway.dispatch_tool_call` is the Execution Agent node. The read-only agents
(context-builder, investigation, root-cause, impact-analyzer, verification) do **not** call
the MCP gateway at all — they call the *LLM* gateway (`llm_gateway.gateway.call_structured`).
So today the Execution Agent is a single choke-point for all write-tool dispatch, and it
acquires the plan-level resource lock (held for the whole plan) and verifies the plan hash
before dispatch.

### Decision
Keep the Execution Agent as the authoritative choke-point, **and** add caller-independent
defense-in-depth inside the gateway so a future/direct caller cannot silently bypass the
controls:

1. **Plan-hash re-verification (moved into the gateway):** when `approved_plan` and
   `approved_plan_hash` are passed, `dispatch_tool_call` recomputes the hash and blocks on
   mismatch (`reason="action_plan_changed"`). The Execution Agent now passes both, so the
   check runs at both layers.
2. **Resource-lock conflict check (added to the gateway):** for write tools, the gateway
   performs a **non-destructive** lock-owner peek (`ResourceLockManager.get_lock_owner`).
   If the resource is locked by a *different* owner than the current `incident_id`, the
   write is blocked (`reason="resource_locked"`).

**Deliberate deviation from "move lock *acquisition* into the gateway":** the gateway is
invoked once *per tool call*, whereas the lock must span *all steps of a plan*. Acquiring
and releasing a lock per call cannot provide plan-level mutual exclusion, and a per-call
`SET NX` would collide with the plan-level lock the Execution Agent already holds (causing
false `RESOURCE_LOCKED` failures on the legitimate path). The non-destructive peek closes
the real bypass gap — a direct caller cannot act on a resource another remediation is
holding — without disturbing the plan-level hold. Acquisition therefore stays at the
plan level (the choke-point); only the *conflict check* is duplicated into the gateway.

---

## ADR-004: One Canonical GitHub Path — `github_service.py` Direct; `mcp-github` is a Simulation Fixture

- **Status**: Accepted
- **Date**: 2026-09-24
- **Context**: RISE had two parallel GitHub integration paths; the redundant one broke real success reporting

### Context & Problem Statement
RISE contained two GitHub integration surfaces:

1. **`apps/api/src/services/github_service.py`** (`commit_remediation_to_github`) — performs
   **real** GitHub writes (branch → commit → PR) via the GitHub REST API, and independently
   re-fetches the created PR to confirm it is genuinely open before returning success.
2. **`packages/mcp-servers/mcp-github/github_server.py`** (`MCPGitHubServer`) — an in-memory
   **mock** whose write tools return `is_test_fixture: True` and fail-close (raise) in
   staging/production and whenever `allow_test_mock` is not set.

The real remediation flow in `apps/api/src/routers/actions.py` (`approve_action`) called
`github_service.commit_remediation_to_github` **directly** — the MCP gateway/`mcp-github`
facade was never the real GitHub writer.

**Bug found (verified) during this reconciliation:** after `commit_remediation_to_github`
created a real PR, `approve_action` then built a synthetic `create_pr` ActionPlan and ran it
through `run_execution_agent` → `MCPGateway` → `mcp-github`. Because the mock fail-closes in
`staging`/`production` (`_assert_write_allowed` raises when `allow_test_mock` is false), the
Execution Agent step over an **already-created real PR** would raise, mark execution
`failed`, and the endpoint would return `requires_human` / `execution_status: failed` — i.e.
a genuine, verified remediation was reported as a failure. No test caught this: existing
approval tests exercise only the no-token path (which returns `requires_human` *before*
reaching this block) or use a `MagicMock` gateway, so the real gateway → mock-facade
interaction was never executed.

### Decision
Adopt **option (b): one real path, mark the facade as a simulation fixture, and remove the
redundant/broken second path** (rather than option (a): wiring `mcp-github` to call
`github_service`, which would duplicate the write and require restructuring the whole
approval flow around an impedance-mismatched tool-dispatch model for a non-MCP integration).

1. **`github_service.py` is the single canonical GitHub path.** It already owns the real
   write *and* its own independent PR re-verification.
2. **`approve_action` no longer re-dispatches `create_pr` through the gateway** for the
   code-fix path. It constructs the success `ExecutionLog` directly from the real
   `github_result`, writes an immutable `remediation.github_pr_created` audit event (for
   DB-backed incidents), and runs the Verification Agent — which performs its own
   independent live GitHub API confirmation of the PR (`verify_github_pr_live`).
3. **`mcp-github` is documented as a simulation/test fixture only** (module docstring) and is
   deprecated as a real execution path. It remains useful for offline orchestration/CI tests
   and stays fail-closed in staging/production.

The simulated-security-action path and the K8s/AWS tool paths are unaffected — they
legitimately dispatch through the gateway to their respective (real or simulated) servers.

### Consequences
- A successful real GitHub remediation now correctly reports `execution_status:
  verified_success` / `status: approved` instead of a spurious `requires_human`.
- Audit coverage is preserved via an explicit `remediation.github_pr_created` event written
  in the API layer (the direct `github_service` path previously wrote no audit row; the only
  audit came from the broken gateway step).
- There is now exactly one place that writes to GitHub for remediation, eliminating the
  undocumented, inconsistent second path.
- Regression coverage added in `tests/test_github_path_reconciliation.py`: a mocked-success
  `commit_remediation_to_github` must yield `verified_success` and must not route through the
  `mcp-github` fail-closed mock.

### Guardrail Parity on the Direct GitHub Write Path (follow-up)

Because `github_service` is a direct, non-gateway integration, the MCP gateway's own controls
(plan-hash re-verification, per-resource concurrency lock, fail-loud audit) do **not** run for
it automatically. This was previously an accepted gap. It is now closed: `approve_action`
applies the equivalent controls to the code-fix path itself, before and around the real
GitHub write. These are **not** an "accepted gap" — they are enforced on this path specifically:

1. **Plan-hash integrity (HTTP 409 `ACTION_PLAN_CHANGED`).** Before calling
   `commit_remediation_to_github`, the handler rebuilds the canonical code-fix `ActionPlan`
   and computes `compute_action_plan_hash(...)` — the same primitive the Execution Agent uses.
   When the approval request carries the approved `plan_hash`, a mismatch against the current
   plan halts the write (identical semantics to `execution.py`'s approved-vs-current check).
2. **Per-resource concurrency lock (HTTP 409 `RESOURCE_LOCKED`).** A `ResourceLockManager`
   lock keyed on `{repo}:{target_file}` is acquired around the GitHub write and released in a
   `finally`. File-level (not branch-level) granularity is deliberate: the remediation branch
   is per-incident (`fix/remediation-{id}`), so a branch key could never detect two
   remediations racing on the same file. A concurrent approval targeting the same file is
   rejected rather than allowed to race.
3. **Fail-loud audit parity.** The path already wrote its audit row via the same hash-chained
   primitive as the gateway (`write_audit_event` → `create_audit_event`); it now also matches
   the gateway's fail-loud stance — a genuine audit-write failure raises
   `AUDIT_WRITE_FAILED` (HTTP 500) instead of being logged and swallowed, since an unrecorded
   remediation write is an integrity violation.

Regression coverage: `tests/test_github_path_reconciliation.py::test_concurrent_github_approval_blocked_by_resource_lock`
and `::test_github_approval_rejects_stale_plan_hash`. The primary architecture doc's guardrail
table (`RISE_ARCHITECTURE_AND_STATUS.md` §6) and the README deployment diagram are updated to
scope which controls apply via the gateway vs. this direct path.

---

## ADR-005: Persisted Human-Approval Anchor — Bind the Approver to a Specific Plan Hash

- **Status**: Accepted
- **Date**: 2026-09-25
- **Context**: Plan-hash integrity checks proved *transport integrity*, not *human authorization*

### Context & Problem Statement
The plan-hash guardrail (ADR-003, ADR-004) blocks a plan that changed between approval and
execution. But its anchor — the "approved" hash it compares against — was never persisted at
the moment of the human decision. In every enforcement site the anchor arrived **in-flight on
the execution request itself** or was **recomputed server-side from a plan built at execution
time**:

| Site | Source of `approved_hash` | What it actually proves |
|------|---------------------------|-------------------------|
| `approve_action` code-fix path | `req.plan_hash` (optional; **the dashboard omits it** — both `action-modals.tsx` callers pass no hash) | nothing when absent; when present, only "client's claim == current plan" |
| `approve_action` simulated path | `compute_action_plan_hash(sim_plan)` where `sim_plan` is built moments earlier server-side | tautology — hashes a plan and compares it to itself |
| `/actions/{id}/execute` | `req.plan_hash or compute_action_plan_hash(req.action_plan)` | both derive from the same client request |
| `execution.py` | `state["approved_plan_hash"]`, only checked `if approved_hash` present | skips silently when absent |
| MCP gateway re-verify | `approved_plan` + `approved_plan_hash`, both passed together by the caller | in-flight consistency, defense-in-depth |

Net: the mechanism proved *a payload wasn't garbled within one request*. It did **not** prove
*a specific human approved this specific plan* — there was no durable binding of approver
identity + timestamp to a hash, and nothing to compare a later execution against. This is a
TOCTOU gap: a plan swapped between the human seeing it and the write executing would pass.

Notably, the schema already provided the anchor: `Approval.plan_hash` (`db/models.py`,
`nullable=False`) exists and is read by `report_generator.py` for compliance reports — but
**no production code path ever wrote an `Approval` row** (only tests constructed one). The
persistence slot was designed and left unwired.

### Decision
Persist the approval anchor at the moment of the human decision and compare later executions
against the **persisted** value, not an in-flight one:

1. **`approve_action` persists an `Approval` row** (`user_id`, `decision`, `note`, `plan_hash`,
   `decided_at`) for DB-backed actions, on both the code-fix and simulated paths. The
   `plan_hash` is the hash of the exact plan that executed. On the code-fix path it is written
   in the **same fail-loud commit** as the `remediation.github_pr_created` audit event; a
   failure to record it raises rather than executing on an unrecorded approval. It is a no-op
   for demo/non-DB actions (no `remediation_actions` row to satisfy the FK).
2. **Durable-anchor drift check (409 `ACTION_PLAN_CHANGED`).** Before writing, `approve_action`
   loads the most recent persisted `Approval` for the action and rejects if its `plan_hash` no
   longer matches the current canonical plan — the plan drifted from what the human durably
   approved. This compares against **server state**, closing the "trust the client's claim" gap
   for any re-approval of an action.
3. **Client-supplied hash is verified on the simulated path too** (previously only the code-fix
   path checked `req.plan_hash`), so a mismatched in-flight claim is refused everywhere.
4. **`execution.py` fails closed on a missing anchor when required.** A new
   `state["require_approved_hash"]` flag makes an approval-bearing execution refuse to run
   un-anchored (`ACTION_PLAN_CHANGED`), closing the "only enforced when a hash happens to be
   present" gap. Default is off, so the raw staging harness and existing graph callers are
   unaffected; `approve_action`'s simulated path sets it on.

### Deliberate scope
- **`/actions/{id}/execute` stays un-anchored by design.** It is a raw staging execution
  harness whose plan and hash both come from the caller; it carries no human-approval anchor
  and is documented as such. The canonical, anchored human decision lives in `approve_action`.
- **The dashboard is not yet wired to echo the displayed hash.** The durable server-side anchor
  is the substantive closure (it binds approver → hash → time and is compared on re-approval).
  Having the dashboard surface and echo the canonical hash would additionally strengthen the
  *in-flight* claim on the first approval; it is left as follow-up hardening, not a correctness
  gap in the anchor itself.

### Consequences
- `Approval.plan_hash` is now populated in production; `report_generator.py`'s
  "Human Approval … Hash" line reflects real recorded decisions instead of never-written rows.
- A remediation whose plan drifted from the recorded human approval is rejected with
  409 `ACTION_PLAN_CHANGED` (drift) rather than silently executing.
- Regression coverage: `tests/test_approval_anchor_persistence.py` — a successful DB-backed
  remediation persists exactly one `Approval` anchor with the canonical `plan_hash`; a plan
  that drifts from a persisted anchor is rejected `ACTION_PLAN_CHANGED` before any GitHub write;
  and `run_execution_agent` fails closed when `require_approved_hash` is set without an anchor.


