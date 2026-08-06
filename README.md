# RISE — Resilient Incident & Remediation System Engine

RISE is an autonomous, stateful multi-agent incident investigation and remediation platform powered by LangGraph, FastAPI, and Next.js.

## Monorepo Architecture

- **`apps/api`**: FastAPI HTTP backend & webhook receivers.
- **`apps/agents`**: LangGraph agent runtime worker service.
- **`apps/dashboard`**: Next.js operator frontend interface.
- **`packages/rise-core`**: Core Python models, schemas, and LLM gateway client.
- **`packages/mcp-servers`**: Custom MCP (Model Context Protocol) servers.
- **`prompts`**: Version-controlled prompt engineering registry.
- **`policies`**: OPA Rego safety and approval policies.
- **`infra`**: Terraform, Kubernetes, and n8n workflow definitions.

## Getting Started

### Python Dependencies
```bash
poetry install
```

### Frontend / JS Workspaces
```bash
pnpm install
```

