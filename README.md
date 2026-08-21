# RISE — Resilient Incident & Remediation System Engine

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.10-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Next.js 14](https://img.shields.io/badge/Next.js-14.1.0-black.svg?logo=next.js)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql)](https://www.postgresql.org/)
[![Qdrant](https://img.shields.io/badge/Qdrant-v1.9.0-red.svg?logo=qdrant)](https://qdrant.tech/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**RISE (Resilient Incident & Remediation System Engine)** is an enterprise-grade, autonomous multi-agent platform designed for automated incident triage, root cause analysis (RCA), risk-governed remediation execution, and post-incident verification. Powered by **LangGraph**, **FastAPI**, **Next.js 14**, and the **Model Context Protocol (MCP)**, RISE enforces structural default-deny security policies via **Open Policy Agent (OPA)**, provides tamper-proof hash-chained audit logging, and integrates seamlessly with Slack, GitHub, Kubernetes, AWS, and modern observability stacks.

---

## Table of Contents

1. [Key Features](#key-features)
2. [Monorepo Architecture](#monorepo-architecture)
3. [Multi-Agent Orchestration Flow](#multi-agent-orchestration-flow)
4. [Prerequisites](#prerequisites)
5. [End-to-End Installation & Quickstart](#end-to-end-installation--quickstart)
   - [Step 1: Clone Repository & Environment Setup](#step-1-clone-repository--environment-setup)
   - [Step 2: Start Backing Services (Docker Compose)](#step-2-start-backing-services-docker-compose)
   - [Step 3: Install Python Dependencies](#step-3-install-python-dependencies)
   - [Step 4: Run Database Migrations](#step-4-run-database-migrations)
   - [Step 5: Seed Historical Knowledge Base & Vector Index](#step-5-seed-historical-knowledge-base--vector-index)
   - [Step 6: Install Frontend Dependencies](#step-6-install-frontend-dependencies)
6. [Running the Application](#running-the-application)
   - [Starting the FastAPI Backend](#starting-the-fastapi-backend)
   - [Starting the Next.js Dashboard](#starting-the-nextjs-dashboard)
7. [Environment Variables Reference](#environment-variables-reference)
8. [Security, Governance & OPA Guardrails](#security-governance--opa-guardrails)
   - [Default-Deny Shadow Mode](#default-deny-shadow-mode)
   - [Cryptographic Webhook Signature Verification](#cryptographic-webhook-signature-verification)
   - [Immutable Hash-Chained Audit Logs](#immutable-hash-chained-audit-logs)
   - [Emergency Stop Procedure](#emergency-stop-procedure)
9. [Evaluation Suite & Verification Gates](#evaluation-suite--verification-gates)
10. [Running Automated Tests](#running-automated-tests)
11. [API & Dashboard Navigation](#api--dashboard-navigation)
12. [Troubleshooting & FAQ](#troubleshooting--faq)
13. [Contributing & License](#contributing--license)

---

## Key Features

- **Autonomous Multi-Agent Triage (LangGraph)**: Stateful graph orchestration transitioning through Ingestion, Context Building, Investigation, Root Cause Identification, Impact Assessment, Decisioning, Execution, and Verification.
- **Model Context Protocol (MCP) Process Isolation**: Granular tool execution servers (Kubernetes, AWS, GitHub, Slack, Observability) running with per-resource Redis distributed locks and plan-hash tampering prevention.
- **Policy-Governed Execution (OPA Rego)**: Strict policy evaluation ensuring safety boundaries, confidence thresholds, blast-radius limits, and mandatory Human-in-the-Loop (HITL) approval.
- **Interactive ChatOps & HITL Approvals**: Real-time Slack interactive cards and Next.js operator dashboard for approval, rejection, modification, and rollbacks.
- **Hybrid Semantic Memory (Qdrant & PostgreSQL)**: Embedding-based similarity search over past incidents, runbooks, service topologies, and post-mortems using Sentence Transformers.
- **Cryptographic Tamper-Evidence**: Continuous SHA-256 hash chains (`audit_events`) guaranteeing non-repudiation of every agent decision and tool execution.
- **Enterprise Multi-LLM Gateway**: Multi-provider resilience with automatic fallback across Google Gemini, OpenAI, AWS Bedrock, and self-hosted Ollama.

---

## Monorepo Architecture

```
RISE/
├── apps/
│   ├── api/                 # FastAPI REST backend, webhook receivers & middleware
│   ├── agents/              # LangGraph agent state machine, orchestrator & nodes
│   └── dashboard/           # Next.js 14 operator web interface (React, Tailwind CSS, Lucide)
├── packages/
│   ├── rise-core/           # Shared models, SQLAlchemy 2.0 schemas, LLM gateway, MCP client
│   └── mcp-servers/         # Isolated MCP servers (k8s, AWS, GitHub, Slack, Observability)
├── policies/                # Open Policy Agent (OPA) Rego safety, risk & allowlist policies
├── eval/                    # Phase 5 Golden path (20) & Adversarial attack (10) eval dataset & harness
├── infra/                   # Terraform, Kubernetes manifests (OPA, canary, ingress), n8n workflows
├── prompts/                 # Version-controlled prompt engineering registry
├── scripts/                 # Knowledge seeding, vector reconciliation, hash-chain verifier, reports
├── tests/                   # Monorepo unit, integration, chaos, e2e, and security test suites
├── docker-compose.yml       # Backing service containers (PostgreSQL 16, Redis 7, Qdrant)
├── pyproject.toml           # Poetry monorepo workspace dependencies
└── package.json             # pnpm workspace configuration
```

---

## Multi-Agent Orchestration Flow

```mermaid
flowchart TD
    A["Webhook Ingestion\n(Alertmanager / GitHub / Slack / CloudWatch)"] --> B["Signature Verification & Dedup"]
    B --> C["Context Builder Node\n(Topology, Historical Incidents, Telemetry)"]
    C --> D["Investigation Node\n(Hypothesis Generation & Metric Probing)"]
    D --> E["Root Cause Analysis (RCA) Node\n(Confidence Scoring & Evidence Synthesis)"]
    E --> F["Impact Analyzer Node\n(Blast Radius & Affected Services)"]
    F --> G["Decision Engine & OPA Policy Guardrail"]
    
    G -->|Requires Approval / Critical Risk| H["Human-in-the-Loop Gate\n(Dashboard & Slack Card)"]
    G -->|Explicit Auto-Approval Policy| I["Execution Agent\n(MCP Tool Gateway & Resource Locks)"]
    
    H -->|Approved| I
    H -->|Rejected / Modified| J["Audit Log & Closed/Manual"]
    
    I --> K["Verification Agent\n(Telemetry Health-Checks & LLM Validation)"]
    K -->|Resolved| L["Post-Mortem & Knowledge Ingestion"]
    K -->|Unresolved / Degraded| M["Automated Rollback Trigger"]
```

---

## Prerequisites

Before setting up RISE, ensure your environment meets the following requirements:

| Dependency | Required Version | Purpose |
| :--- | :--- | :--- |
| **Python** | `>= 3.11` | Backend API, LangGraph agent runtime, and Core libraries |
| **Poetry** | `>= 1.8.0` / `2.0+` | Python dependency & virtual environment management |
| **Node.js** | `>= 18.17.0` (LTS 20 recommended) | Frontend Dashboard runtime |
| **pnpm** (or `npm`) | `>= 8.0.0` | Frontend package management |
| **Docker & Docker Compose** | Latest | Container runtime for PostgreSQL, Redis, and Qdrant |
| **Git** | `>= 2.30` | Source code control |

---

## End-to-End Installation & Quickstart

Follow these steps sequentially to set up and run RISE locally from scratch:

### Step 1: Clone Repository & Environment Setup

Clone the repository and create your local environment configuration file:

```bash
git clone https://github.com/Viresh2408/RISE.git
cd RISE
```

Copy the example configuration to `.env`:

```bash
# Linux / macOS
cp .env.example .env

# Windows (PowerShell)
Copy-Item .env.example .env
```

Open `.env` and fill in your LLM API keys and credentials (at minimum, set `GEMINI_API_KEY` or `OPENAI_API_KEY`):

```ini
# Minimal required settings in .env for local development:
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rise_dev
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333
GEMINI_API_KEY=your_gemini_api_key_here
ENVIRONMENT=local
```

---

### Step 2: Start Backing Services (Docker Compose)

Launch the containerized PostgreSQL database, Redis cache/broker, and Qdrant vector database:

```bash
docker-compose up -d
```

Verify that all three containers are healthy:

```bash
docker-compose ps
```

*Expected output: `rise_postgres` (port 5432), `rise_redis` (port 6379), and `rise_qdrant` (ports 6333, 6334) running with status `Up (healthy)`.*

---

### Step 3: Install Python Dependencies

RISE uses Poetry for Python workspace dependency resolution:

```bash
poetry install
```

This installs all core dependencies (`fastapi`, `langgraph`, `sqlalchemy`, `qdrant-client`, `psycopg2-binary`, etc.) and links `packages/rise-core` in editable development mode.

---

### Step 4: Run Database Migrations

Apply the Alembic database migrations to initialize all tables (tenants, users, incidents, agent runs, action plans, policies, and hash-chained audit events):

```bash
poetry run alembic upgrade head
```

---

### Step 5: Seed Historical Knowledge Base & Vector Index

Populate the database and Qdrant vector index with baseline historical incidents, runbooks, and topology schemas for the RAG / Context Builder engine:

```bash
poetry run python scripts/seed_knowledge.py
```

*You can verify the created vector collection at [http://localhost:6333/dashboard#/collections/incidents_v1](http://localhost:6333/dashboard#/collections/incidents_v1).*

---

### Step 6: Install Frontend Dependencies

Install the Next.js dashboard workspace dependencies using `pnpm` (or `npm`):

```bash
pnpm install
```

---

## Running the Application

### Starting the FastAPI Backend

Run the API service locally with auto-reloading enabled:

```bash
poetry run uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8000 --reload
```

Once started:
- **API Documentation (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Checks**: [http://localhost:8000/healthz](http://localhost:8000/healthz) and [http://localhost:8000/readyz](http://localhost:8000/readyz)

---

### Starting the Next.js Dashboard

In a separate terminal, launch the Next.js operator dashboard:

```bash
# From repository root:
pnpm --filter rise-dashboard dev

# Or navigate directly to the dashboard package:
cd apps/dashboard
pnpm dev
```

Open your browser and navigate to:
👉 **[http://localhost:3000](http://localhost:3000)**

---

## Environment Variables Reference

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:postgres@localhost:5432/rise_dev` |
| `REDIS_URL` | Redis broker & lock manager URL | `redis://localhost:6379/0` |
| `QDRANT_URL` | Qdrant vector database endpoint | `http://localhost:6333` |
| `QDRANT_API_KEY` | Optional Qdrant API key (cloud / authenticated instances) | `your_qdrant_api_key` |
| `GEMINI_API_KEY` | Google Gemini API key (primary reasoning & RCA model) | `AIzaSy...` |
| `OPENAI_API_KEY` | OpenAI API key (fallback reasoning & embeddings) | `sk-...` |
| `AWS_ACCESS_KEY_ID` | AWS Credentials for Amazon Bedrock & CloudWatch | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | AWS Secret Key for Amazon Bedrock & CloudWatch | `wJalr...` |
| `AWS_REGION` | AWS Region for Bedrock / CloudWatch | `us-east-1` |
| `OLLAMA_BASE_URL` | Base URL for self-hosted Ollama local LLMs | `http://localhost:11434` |
| `GITHUB_APP_ID` | GitHub App ID for automated PRs and commits | `123456` |
| `GITHUB_APP_PRIVATE_KEY` | RSA Private Key for GitHub App authentication | `-----BEGIN RSA PRIVATE KEY-----...` |
| `GITHUB_TOKEN` | Personal Access Token (fallback with `repo` scope) | `ghp_...` |
| `GITHUB_WEBHOOK_SECRET` | Secret token for validating incoming GitHub webhook HMACs | `webhook_secret_key` |
| `SLACK_BOT_TOKEN` | Slack Bot OAuth Token for ChatOps & approval cards | `xoxb-...` |
| `SLACK_SIGNING_SECRET` | Slack signing secret for validating incoming events | `slack_secret_key` |
| `SUPABASE_URL` | Supabase Project URL for authentication | `https://xyz.supabase.co` |
| `SUPABASE_JWT_SECRET` | JWT secret for validating user Bearer tokens | `supabase_jwt_secret` |
| `LANGFUSE_PUBLIC_KEY` | Public key for Langfuse LLM observability & tracing | `pk-lf-...` |
| `LANGFUSE_SECRET_KEY` | Secret key for Langfuse LLM observability & tracing | `sk-lf-...` |
| `ENVIRONMENT` | Environment type (`local`, `dev`, `staging`, `production`) | `local` |
| `RISE_TEST_MODE` | Test bypass for JWT verification (strictly blocked in prod) | `0` |

---

## Security, Governance & OPA Guardrails

### Default-Deny Shadow Mode

RISE is architected with a **structural default-deny posture**:
- **No master autopilot flag**: Autonomous remediation cannot be enabled globally.
- **Explicit policy requirement**: Remediation execution *only* proceeds autonomously if an explicit `RiskPolicy` exists with `requires_approval = false` matching the specific `action_pattern` + `environment` + `risk_tier` and the confidence meets the threshold.
- In production, all unconfigured actions default to **Human-in-the-Loop (HITL)** approval.

### Cryptographic Webhook Signature Verification

All webhook ingestion endpoints strictly reject unsigned or tampered requests:
- **GitHub**: `X-Hub-Signature-256` computed with HMAC-SHA256.
- **Slack**: `X-Slack-Signature` with timestamp replay protection (5-minute window).
- **AWS SNS / CloudWatch**: SHA256withRSA certificate verification against official AWS certificates.
- **Alertmanager**: Shared secret authorization header.

### Immutable Hash-Chained Audit Logs

Every decision, policy check, and tool execution is recorded in the `audit_events` table with a cryptographic SHA-256 hash chaining mechanism:
$$\text{hash}_n = \text{SHA256}(\text{hash}_{n-1} \parallel \text{event\_data})$$

You can verify the audit chain integrity at any time:

```bash
poetry run python scripts/verify_chain.py --tenant-id <tenant_uuid>
```

### Emergency Stop Procedure

To instantly halt all autonomous remediations and force 100% manual human review:

```bash
# Update auto-execution policy to require approval (requires Admin JWT)
curl -X PUT "http://localhost:8000/api/v1/policies/pol-001" \
  -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  -d '{"action_pattern": "k8s.pod.restart", "risk_tier": "critical", "requires_approval": true, "max_blast_radius": 0}'
```

---

## Evaluation Suite & Verification Gates

RISE includes a comprehensive evaluation harness assessing accuracy across 20 ground-truth golden path incidents and 10 adversarial prompt-injection attacks:

```bash
poetry run python eval/run_eval.py
```

### Gate Certification Standards

- **RCA Accuracy**: $\ge 80\%$ against ground truth (currently achieving 100%).
- **False-Auto-Approvals**: Exactly **0** false-auto-approvals across all scenarios.
- **Adversarial Invariance**: All 10 injection attack scenarios (`INJ-001` through `INJ-010`) successfully resisted.
- **Audit Output**: Generates `eval/audit_trail.json` and `eval/audit_trail.md`.

To run the production readiness gate test:

```bash
poetry run python scripts/run_phase8_prod_readiness.py
```

---

## Running Automated Tests

RISE contains an extensive test suite across Python and TypeScript workspaces:

```bash
# Run all Python unit and integration tests
poetry run pytest

# Run with verbose output and integration tests
poetry run pytest -v -m integration

# Run specific agent MCP tests
poetry run pytest apps/agents/tests/test_execution_agent_mcp.py

# Run API webhook signature verification tests
poetry run pytest apps/api/tests/test_webhooks_ingestion.py

# Run frontend Vitest suite
pnpm --filter rise-dashboard test

# Verify frontend Next.js production build
pnpm --filter rise-dashboard build
```

---

## API & Dashboard Navigation

### REST API Endpoints (`/api/v1`)

- **`/incidents`**: Query, filter, and inspect incidents and their life-cycle status.
- **`/agent-runs`**: Retrieve LangGraph execution traces, active checkpoints, and node transitions.
- **`/actions`**: Review proposed action plans, approve/reject human-in-the-loop requests.
- **`/policies`**: Manage OPA risk policies, confidence thresholds, and blast radius rules.
- **`/knowledge`**: Semantic vector search and ingestion for runbooks and historical incidents.
- **`/webhooks`**: Ingest alerts from GitHub, Alertmanager, Slack, and CloudWatch.
- **`/reports`**: Generate weekly SLA, MTTR, and incident post-mortem summaries.
- **`/audit`**: Query tamper-proof hash-chained event logs.

### Operator Dashboard Routes

- **`/`**: Overview dashboard showing real-time incident counters, MTTR trends, active agent executions, and system health.
- **`/incidents`**: Incident explorer with severity filters, timeline view, and detailed investigation drawer.
- **`/incidents/[id]`**: Deep incident investigation interface, RCA graph, live node progression, and action approval card.
- **`/policies`**: Risk rules matrix editor and blast-radius configuration.
- **`/knowledge`**: Runbook and past incident vector database management.
- **`/integrations`**: Integration status for GitHub, Slack, Kubernetes, AWS, and Alertmanager.
- **`/reports`**: Reliability reports, post-mortem generation, and weekly digest view.

---

## Troubleshooting & FAQ

<details>
<summary><b>1. Database connection fails on startup (`psycopg2.OperationalError`)</b></summary>

Ensure Docker Compose services are running:
```bash
docker-compose up -d postgres
```
Verify port 5432 is not occupied by another local PostgreSQL instance.
</details>

<details>
<summary><b>2. GitHub startup scope verification probe fails</b></summary>

RISE validates GitHub token permissions on startup to fail loudly before taking remediation actions. Ensure your `GITHUB_TOKEN` has `repo` (or fine-grained `pull_requests:write` + `contents:write`) permissions. In local development with non-production environments, scope warnings are non-fatal unless running in staging/prod.
</details>

<details>
<summary><b>3. Qdrant vector search returns no results</b></summary>

Run the knowledge seeding script to populate initial embeddings:
```bash
poetry run python scripts/seed_knowledge.py
```
</details>

<details>
<summary><b>4. `RISE_TEST_MODE=1` causes startup RuntimeError</b></summary>

`RISE_TEST_MODE=1` disables JWT signature verification and is strictly restricted to `ENVIRONMENT=local` or `test`. If running in `staging` or `production`, unset `RISE_TEST_MODE` or set `ENVIRONMENT=local` in your `.env`.
</details>

---

## Contributing & License

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines, coding standards, and branch policies.  
Security vulnerability reporting instructions are outlined in [SECURITY.md](SECURITY.md).

This project is licensed under the [MIT License](LICENSE).
