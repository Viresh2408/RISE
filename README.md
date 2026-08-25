<div align="center">

<img src="docs/rise_banner.jpg" alt="RISE — Resilient Incident & Remediation System Engine" width="100%"/>

<br/>
<br/>

<img src="docs/rise_logo.jpg" alt="RISE Logo" width="180"/>

<br/>
<br/>

# RISE — Resilient Incident & Remediation System Engine

**An autonomous, multi-agent AIOps platform for AI-driven incident triage, root-cause analysis,**  
**risk-governed remediation, and verified self-healing — built on LangGraph, FastAPI, and Next.js,**  
**with structural default-deny safety guarantees.**

> *"It was fixed while you were asleep."*

<br/>

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.10-FF6B35.svg?style=for-the-badge)](https://github.com/langchain-ai/langgraph)
[![Next.js 14](https://img.shields.io/badge/Next.js-14.1.0-000000.svg?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Qdrant](https://img.shields.io/badge/Qdrant-v1.9.0-DC143C.svg?style=for-the-badge)](https://qdrant.tech/)
[![OPA](https://img.shields.io/badge/OPA-Policy%20Engine-7D3F98.svg?style=for-the-badge)](https://www.openpolicyagent.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-F7C948.svg?style=for-the-badge)](LICENSE)

</div>

---

## Table of Contents

1. [What RISE Actually Does](#what-rise-actually-does)
2. [Why It's Different From a Typical AIOps Demo](#why-its-different-from-a-typical-aiops-demo)
3. [System Architecture](#system-architecture)
4. [Multi-Agent Orchestration Flow](#multi-agent-orchestration-flow)
5. [Data & Evidence Flow](#data--evidence-flow)
6. [Deployment Architecture](#deployment-architecture)
7. [Monorepo Layout](#monorepo-layout)
8. [Prerequisites](#prerequisites)
9. [Quickstart](#quickstart)
10. [Environment Variables](#environment-variables)
11. [Security, Governance & Guardrails](#security-governance--guardrails)
12. [Evaluation & Verification](#evaluation--verification)
13. [Running Tests](#running-tests)
14. [API & Dashboard Reference](#api--dashboard-reference)
15. [Known Limitations & Roadmap](#known-limitations--roadmap)
16. [Troubleshooting](#troubleshooting)
17. [Contributing & License](#contributing--license)

---

## What RISE Actually Does

Engineering teams lose time to a repetitive loop: an alert fires, an engineer wakes up (or drops what they're doing), digs through logs and metrics across five different tools, forms a hypothesis, checks it, writes a fix, and deploys it — often **45+ minutes end to end**, for problems that are frequently the same handful of root causes recurring across services.

RISE automates that loop with a **supervised multi-agent pipeline**:

```
Detect → Gather real evidence → Diagnose with confidence scoring
  → Assess blast radius → Decide (auto vs. human-approval)
    → Execute → Verify → Learn
```

Every stage is designed around one governing principle:

> **The system should never be more confident in its own output than the evidence actually supports.**

---

## Why It's Different From a Typical AIOps Demo

Most "AI incident response" projects stop at "an LLM reads the logs and suggests something." RISE is built around the harder, less flashy problem: making sure the AI's output is actually grounded in real data before anything gets shown to a human or executed.

Concretely, this project enforces:

- **No code fix is ever generated without the LLM seeing the real, current file content first.** If the exact file can't be fetched from GitHub, the LLM is never called for that fix — the incident is routed to a human with an honest "no verified fix available" message. There is no fallback path that fabricates a plausible-looking diff.

- **Every generated patch is programmatically validated against the real file before a PR opens.** A diff with wrong line numbers or non-existent code is rejected and never reaches GitHub.

- **The system cannot mark a remediation "successful" without independently re-checking the real system of record.** A PR is only considered real once RISE calls GitHub's API back and confirms it's genuinely open — not because the creation call didn't throw an error.

- **Autonomous execution has no master on/off switch.** There is no `AUTOPILOT_ENABLED` flag anywhere in the system. Auto-remediation is only possible when an admin has explicitly created a scoped `RiskPolicy` row permitting it for a specific action type, environment, and confidence threshold — and critical-risk actions are hardcoded, at the code level, to always require human approval, regardless of what any policy says.

- **Every decision is independently, cryptographically auditable.** Every agent decision and tool execution writes an immutable, hash-chained audit event — tampering with any single row breaks the chain and is programmatically detectable.

---

## System Architecture

```mermaid
flowchart TB
    subgraph SOURCES["Data Sources"]
        direction LR
        GH[GitHub]
        SLK[Slack]
        CW[CloudWatch]
        AM[Alertmanager]
        K8SEVT[Kubernetes Events]
        PROM[Prometheus / Loki]
    end

    subgraph INGEST["Ingestion Layer"]
        WH["Webhook Receivers<br/>HMAC / SNS / Signature Verified"]
        DEDUP["Dedup + Correlation<br/>Redis"]
    end

    subgraph CORE["AI Incident Intelligence Engine — LangGraph"]
        direction TB
        ORCH(("Orchestrator<br/>Durable State Machine"))
        CTX["Context Builder Agent<br/>real logs, metrics, code, Slack, past incidents"]
        INV["Investigation Agent<br/>ranked hypotheses, evidence-backed"]
        RC["Root Cause Agent<br/>confidence-scored"]
        IMP["Impact Analyzer<br/>deterministic blast radius"]
        DEC["Decision & Plan Agent<br/>Risk + Confidence Engines + OPA"]
        EXEC["Execution Agent<br/>plan-hash verified, allow-listed tools"]
        VER["Verification Agent<br/>independent live re-check"]
        ORCH --> CTX --> INV --> RC --> IMP --> DEC --> EXEC --> VER
    end

    subgraph KNOWLEDGE["Knowledge & Memory Layer"]
        QD[("Qdrant<br/>Vector Similarity")]
        PG[("PostgreSQL<br/>System of Record + RLS")]
        NEO[("Service Topology<br/>Blast Radius Graph")]
    end

    subgraph GUARD["Safety & Governance"]
        OPA["OPA Policy Engine<br/>Structural Default-Deny"]
        AUDIT[("Hash-Chained<br/>Audit Log")]
        MCP["MCP Tool Gateway<br/>Allow-list + Plan-hash Check"]
    end

    subgraph ACT["Action & Integration Layer"]
        PR["GitHub PR Creation<br/>Patch-Validated"]
        K8SACT[Kubernetes Actions]
        NOTIFY["Slack / Email / SMS"]
    end

    subgraph UX["Presentation Layer"]
        DASH[Next.js Dashboard]
        CHATOPS["Slack ChatOps + Approval Cards"]
    end

    SOURCES --> INGEST --> ORCH
    CORE <--> KNOWLEDGE
    DEC --> OPA
    EXEC --> MCP --> ACT
    CORE --> AUDIT
    DEC -.needs approval.-> CHATOPS
    CHATOPS -.approve/reject.-> ORCH
    ACT --> UX
    KNOWLEDGE --> UX
```

---

## Multi-Agent Orchestration Flow

```mermaid
flowchart TD
    A["Webhook Ingestion<br/>Alertmanager / GitHub / Slack / CloudWatch"] --> B["Signature Verification & Dedup"]
    B --> C["Context Builder Node<br/>real files, logs, metrics, Slack history, similar past incidents"]
    C --> D["Investigation Node<br/>ranked, evidence-cited hypotheses"]
    D --> E["Root Cause Node<br/>confidence-scored, honestly calibrated"]
    E --> F["Impact Analyzer Node<br/>deterministic blast radius — never LLM-guessed"]
    F --> G{Decision Engine<br/>Risk + Confidence + OPA}

    G -->|Requires Approval / Critical Risk| H["Human-in-the-Loop Gate<br/>Dashboard + Slack Interactive Card"]
    G -->|Explicit Auto-Approval Policy Exists| I["Execution Agent<br/>plan-hash verified, allow-listed tools only"]

    H -->|Approved| I
    H -->|Rejected / Modified| J["Audit Log & Manual Handoff"]

    I --> K{Real file content available<br/>for code-fix steps?}
    K -->|No| L["requires_manual_plan = true<br/>No LLM call. No fabricated diff."]
    K -->|Yes| M["Patch generated against real bytes,<br/>validated, syntax-checked"]

    M --> N["Verification Agent<br/>independent live re-check against GitHub / metrics"]
    N -->|Confirmed Resolved| O["Post-Mortem & Knowledge Base Write-back"]
    N -->|"Failed / Unconfirmed"| P["Auto-Rollback → Re-escalate to Human"]
```

---

## Data & Evidence Flow

Every proposed fix is traceable end-to-end through a single queryable evidence chain — no step is re-derived or summarized by an LLM at display time; the dashboard renders exactly what was fetched and decided.

```mermaid
sequenceDiagram
    participant Src as Alert Source
    participant Ctx as Context Builder
    participant GH as GitHub API
    participant RC as Root Cause Agent
    participant Plan as Action Planner
    participant Val as Patch Validator
    participant Exec as Execution Agent
    participant Ver as Verification Agent

    Src->>Ctx: Incident event
    Ctx->>GH: Fetch real file content + commit SHA
    GH-->>Ctx: Verbatim source, real SHA
    Ctx->>RC: Logs, metrics, real code, Slack history, similar incidents
    RC->>Plan: Root cause + confidence + evidence

    alt Real file content unavailable
        Plan->>Plan: requires_manual_plan = true — LLM never called for this step
    else Real file content available
        Plan->>Val: Generated diff + real file bytes
        Val->>Val: Apply diff programmatically + syntax check
        alt Patch does not apply cleanly
            Val-->>Plan: Reject — retry once, then escalate
        else Patch applies cleanly
            Val-->>Exec: Verified patch
            Exec->>GH: Create branch + commit + open PR
            GH-->>Exec: Real PR number / URL
            Exec->>Ver: Execution log
            Ver->>GH: Independently re-fetch PR — confirm still open
            GH-->>Ver: Live confirmation
        end
    end
```

---

## Deployment Architecture

```mermaid
flowchart TB
    subgraph EDGE["Edge"]
        CF["Cloudflare — DNS / WAF"]
    end

    subgraph K8S["Kubernetes Cluster"]
        subgraph NS_API["rise-api"]
            API[FastAPI Pods]
        end
        subgraph NS_AGENTS["rise-agents"]
            WORK["LangGraph Worker Pods<br/>Celery + Celery Beat"]
        end
        subgraph NS_MCP["MCP Tool Servers"]
            MCPK[mcp-kubernetes]
            MCPA[mcp-aws]
            MCPG[mcp-github]
        end
        subgraph NS_DASH["rise-dashboard"]
            DASH[Next.js Pods]
        end
        subgraph NS_OBS["Observability"]
            PROMK[Prometheus]
            GRAF[Grafana]
            LOKI[Loki]
            LF[Langfuse]
        end
    end

    subgraph DATA["Managed Data Stores"]
        PG[("PostgreSQL + RLS")]
        RD[(Redis)]
        QD[(Qdrant)]
        S3[("S3 Artifacts")]
    end

    subgraph EXT["External Providers"]
        GEM[Gemini]
        OAI[OpenAI]
        BR[AWS Bedrock]
        GH[GitHub]
        SLK[Slack]
    end

    CF --> API --> WORK
    API --> DASH
    WORK --> MCPK & MCPA & MCPG
    WORK --> PG & RD & QD & S3
    WORK --> GEM & OAI & BR
    MCPG --> GH
    WORK --> SLK
    NS_OBS -.monitors.-> K8S
```

> **Note on MCP server isolation:** MCP tool servers are currently deployed as in-process modules within the agent worker rather than as fully isolated processes/pods with independently scoped credentials. Tool-call safety today is enforced via the allow-list middleware, OPA policy checks, and plan-hash verification — not via process-level sandboxing. Full MCP process isolation (separate pods, separate IAM/credentials per server) is a documented, tracked improvement — see [Known Limitations & Roadmap](#known-limitations--roadmap).

---

## Monorepo Layout

```
RISE/
├── apps/
│   ├── api/               # FastAPI backend — REST API, webhook receivers, middleware
│   ├── agents/            # LangGraph orchestrator, agent nodes, decision engines
│   └── dashboard/         # Next.js 14 operator dashboard (marketing site + authenticated app)
├── packages/
│   ├── rise-core/         # Shared schemas, DB models, LLM Gateway, MCP client, audit logger
│   └── mcp-servers/       # Tool servers: kubernetes, aws, github, slack, observability
├── policies/              # OPA Rego — risk tiers, approval rules, tool allow-lists
├── eval/                  # Golden-path (20) + adversarial (10) evaluation harness & datasets
├── infra/
│   ├── terraform/         # AWS/EKS IaC — least-privilege IAM, no wildcard actions/resources
│   ├── k8s/               # Kustomize/Helm manifests, canary rollout config
│   └── monitoring/        # Grafana dashboards, Prometheus alert rules
├── prompts/               # Versioned agent system/user prompts, security preamble
├── scripts/               # Knowledge seeding, hash-chain verification, weekly reports
├── db/migrations/         # Alembic schema migrations
├── tests/                 # Integration, chaos, e2e, and security test suites
├── docker-compose.yml     # Local dev stack: PostgreSQL 16, Redis 7, Qdrant
├── pyproject.toml         # Poetry workspace
└── package.json           # pnpm workspace
```

---

## Prerequisites

| Dependency | Required Version | Purpose |
| :--- | :--- | :--- |
| **Python** | `>= 3.11` | Backend API, LangGraph agent runtime |
| **Poetry** | `>= 1.8.0` | Python dependency management |
| **Node.js** | `>= 18.17` (LTS 20 recommended) | Dashboard runtime |
| **pnpm** (or `npm`) | `>= 8.0.0` | Frontend package management |
| **Docker & Docker Compose** | Latest | PostgreSQL, Redis, Qdrant containers |
| **Git** | `>= 2.30` | Source control |

---

## Quickstart

```bash
# 1. Clone
git clone https://github.com/Viresh2408/RISE.git
cd RISE

# 2. Configure environment
cp .env.example .env          # macOS/Linux
# Copy-Item .env.example .env # Windows PowerShell
# Fill in at minimum: DATABASE_URL, REDIS_URL, QDRANT_URL, GEMINI_API_KEY (or OPENAI_API_KEY)

# 3. Start backing services
docker-compose up -d
docker-compose ps   # confirm postgres, redis, qdrant are all "Up (healthy)"

# 4. Install Python dependencies
poetry install

# 5. Run database migrations
poetry run alembic upgrade head

# 6. Seed the knowledge base + vector index
poetry run python scripts/seed_knowledge.py
# verify: http://localhost:6333/dashboard#/collections/incidents_v1

# 7. Install dashboard dependencies
pnpm install

# 8. Start the API (terminal 1)
poetry run uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8000 --reload

# 9. Start the dashboard (terminal 2)
pnpm --filter rise-dashboard dev
```

Then open:

| Service | URL |
| :--- | :--- |
| **Dashboard** | http://localhost:3000 |
| **API Docs (Swagger)** | http://localhost:8000/docs |
| **API Health** | http://localhost:8000/healthz · http://localhost:8000/readyz |

---

## Environment Variables

| Variable | Description | Example |
| :--- | :--- | :--- |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:postgres@localhost:5432/rise_dev` |
| `REDIS_URL` | Redis broker & lock manager | `redis://localhost:6379/0` |
| `QDRANT_URL` | Qdrant vector DB endpoint | `http://localhost:6333` |
| `QDRANT_API_KEY` | Optional, for hosted Qdrant | — |
| `GEMINI_API_KEY` | Primary reasoning model | `AIzaSy...` |
| `OPENAI_API_KEY` | Fallback reasoning model | `sk-...` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | Bedrock & CloudWatch | — |
| `OLLAMA_BASE_URL` | Self-hosted local LLM (dev/offline) | `http://localhost:11434` |
| `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` | GitHub App auth (preferred) | — |
| `GITHUB_TOKEN` | PAT fallback — requires `repo` or fine-grained `contents:write` + `pull_requests:write` | `ghp_...` / `github_pat_...` |
| `GITHUB_WEBHOOK_SECRET` | HMAC validation for inbound GitHub webhooks | — |
| `SLACK_BOT_TOKEN` | ChatOps + approval cards | `xoxb-...` |
| `SLACK_SIGNING_SECRET` | Inbound Slack event/interaction validation | — |
| `SLACK_API_TOKEN` | Slack search API (`search:read`) for related-discussion evidence | — |
| `SUPABASE_URL` / `SUPABASE_JWT_SECRET` | Auth | — |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | LLM tracing/observability | — |
| `ENVIRONMENT` | `local` / `staging` / `production` | `local` |
| `RISE_TEST_MODE` | Disables JWT signature checks — hard-blocked outside `local`/`test` by a startup guard | `0` |
| `GITHUB_SCOPE_PROBE_TTL_SECONDS` | Cache TTL for the GitHub write-permission startup probe | `3600` |

> Full list documented inline in [.env.example](.env.example) — every variable there has a placeholder and a comment; no real secret values are ever committed.

---

## Security, Governance & Guardrails

### Structural Default-Deny — No Autopilot Switch

There is no global flag that enables autonomous remediation. Auto-execution requires an admin to have explicitly created a `RiskPolicy` row scoped to a specific `action_pattern` + `environment` + `risk_tier`, with `requires_approval = false`. Critical-risk actions and any plan missing a rollback strategy are hardcoded (not policy-configurable) to always require human approval. If the OPA policy engine is unreachable, the system **fails closed** — every action requires approval.

**Emergency stop** — revert to full human-in-the-loop by deactivating the auto-approval policy:

```bash
curl -X PUT "http://localhost:8000/api/v1/policies/{policy_id}" \
  -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  -d '{"requires_approval": true}'
```

### Grounded, Verified Remediation — Not LLM Approximation

- Code fixes are only generated when the LLM has been shown the **real, current file content** fetched from GitHub. If that fetch fails, the fix is not generated — the incident routes to a human with an honest "no verified fix available" message.
- Every generated diff is **programmatically validated** (applies cleanly against the real file, passes a syntax check) before a PR is opened.
- The Verification Agent **independently re-fetches** the created PR from GitHub's API before allowing an incident to close — a stored success claim is never trusted on its own.

### Cryptographic Webhook Verification

| Source | Method |
| :--- | :--- |
| **GitHub** | HMAC-SHA256 (`X-Hub-Signature-256`) |
| **Slack** | HMAC-SHA256 + 5-minute replay window (`X-Slack-Signature`) |
| **AWS SNS/CloudWatch** | Certificate-chain verification against AWS's signing cert |
| **Alertmanager** | Shared-secret header |

Tenant resolution for inbound webhooks is derived from the connected `IntegrationConfig` matching the payload's source identity — an unrecognized source is rejected and audit-logged, never defaulted to a fallback tenant.

### Immutable, Hash-Chained Audit Log

Every agent decision, policy check, and tool execution writes an append-only `audit_events` row:

```
hash[n] = SHA256(hash[n-1] || event_data)
```

Chains are scoped per tenant and serialized against concurrent writers to prevent forking. Verify integrity at any time:

```bash
poetry run python scripts/verify_chain.py --tenant-id <tenant_uuid>
```

### Startup Credential Validation

The API refuses to boot in `staging`/`production` if GitHub credentials are missing or lack real write permission — verified via a live, TTL-cached probe against GitHub's API (not just checking that a token string is present).

---

## Evaluation & Verification

```bash
poetry run python eval/run_eval.py
```

Runs the full agent pipeline against a **golden-path dataset** (auto-remediation, human-approval, PR-creation, and rollback scenarios) and an **adversarial dataset** targeting each safety guardrail individually — blast-radius integrity, approval spoofing, rollback-plan suppression, and secret exfiltration attempts, among others.

**Methodology, not a marketing number:** RCA accuracy is measured against a human-labeled `ground_truth_root_cause` per incident, determined independently of the agent's own output. Adversarial "resistance" is asserted per-scenario against the specific guardrail it targets (e.g., exact-equality of blast radius against the deterministic topology calculation), not a holistic pass/fail judgment. Current results are tracked in [BENCHMARKS.md](BENCHMARKS.md) as they're produced — this repository does not assert a specific accuracy figure here until that file reflects a confirmed, non-circular run.

**Target gates:**

| Gate | Threshold |
| :--- | :--- |
| RCA accuracy | >= 80% against independently-labeled ground truth |
| False auto-approvals | Zero across the full scenario set |
| Adversarial resistance | All adversarial scenarios resisted per their specific, named assertion |
| Audit trail | Full human-reviewable `eval/audit_trail.json` / `.md` generated |

---

## Running Tests

```bash
# Full Python suite
poetry run pytest

# With integration tests (requires live Postgres/Redis/Qdrant)
poetry run pytest -v -m integration

# Specific suites
poetry run pytest apps/agents/tests/test_execution_agent_mcp.py
poetry run pytest apps/agents/tests/test_patch_validator.py
poetry run pytest apps/api/tests/test_webhooks_ingestion.py
poetry run pytest apps/api/tests/test_evidence_chain_endpoint.py

# Frontend
pnpm --filter rise-dashboard test
pnpm --filter rise-dashboard build
```

---

## API & Dashboard Reference

### REST API (`/api/v1`)

| Path | Purpose |
| :--- | :--- |
| `/incidents` | Query, filter, create, and manage incident lifecycle |
| `/incidents/{id}/evidence-chain` | Full, DB-only evidence trail — no display-time LLM re-derivation |
| `/agent-runs` | LangGraph execution traces and per-node results |
| `/actions` | Approve / reject / modify pending remediation actions |
| `/policies` | Manage risk policies (versioned, never edited in place) |
| `/knowledge` | Semantic search over runbooks and resolved incidents |
| `/webhooks` | Inbound alert ingestion (GitHub, Slack, Alertmanager, CloudWatch) |
| `/reports` | MTTR, autonomy rate, and reliability reporting |
| `/audit` | Query the hash-chained audit log |

### Dashboard Routes

| Route | Purpose |
| :--- | :--- |
| `/` | Marketing / project overview |
| `/incidents` | Live incident feed |
| `/incidents/[id]` | Full investigation view — timeline, RCA, evidence, action plan, approvals, verification |
| `/reports` | MTTR trends and autonomy analytics |
| `/policies` | Risk policy management (admin) |
| `/knowledge` | Runbook and past-incident browser |
| `/integrations` | GitHub, Slack, AWS, Kubernetes connection status (admin) |

---

## Known Limitations & Roadmap

Documented honestly rather than omitted:

| Item | Status |
| :--- | :--- |
| **MCP server process isolation** | Not yet implemented. Tool servers run in-process within the agent worker rather than as separately-credentialed, sandboxed processes. Safety today relies on the allow-list middleware, OPA policy checks, and plan-hash verification rather than process-level isolation. **Planned:** split each MCP server into its own pod with its own scoped IAM/credentials. |
| **Single-tenant deployment model** | The schema is tenant-ready (RLS, `tenant_id` scoping throughout), but multi-tenant SaaS operation has not been exercised end-to-end. |
| **Shadow-mode burn-in** | Currently a manual, human-reviewed process — not yet automated with statistical confidence thresholds for auto-promotion. |

---

## Troubleshooting

<details>
<summary><b>Database connection fails on startup</b></summary>

```bash
docker-compose up -d postgres
```

Confirm port `5432` is not already in use by another local Postgres instance.
</details>

<details>
<summary><b>GitHub startup scope probe fails</b></summary>

RISE validates GitHub write permissions on boot to fail loudly before attempting remediation. Ensure `GITHUB_TOKEN` has `repo` scope (classic) or `contents:write` + `pull_requests:write` (fine-grained). This check is non-fatal in `local`/`test` environments and fatal in `staging`/`production`.
</details>

<details>
<summary><b>Qdrant search returns no results</b></summary>

```bash
poetry run python scripts/seed_knowledge.py
```
</details>

<details>
<summary><b><code>RISE_TEST_MODE=1</code> causes a startup error</b></summary>

This is intentional — `RISE_TEST_MODE` disables JWT verification and is hard-blocked outside `ENVIRONMENT=local`/`test` by a startup guard, to prevent it from ever being accidentally left on in a real deployment.
</details>

---

## Contributing & License

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [SECURITY.md](SECURITY.md) for vulnerability reporting.

Licensed under the [MIT License](LICENSE).

---

<div align="center">

<sub>Built with lightning by the RISE team &nbsp;&middot;&nbsp; <a href="https://github.com/Viresh2408/RISE">github.com/Viresh2408/RISE</a></sub>

</div>
