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
   - All tool calls pass through `evaluate_opa_allowlist()` against Open Policy Agent (`policies/tool_allowlist.rego`).
   - Action plan step parameters and names are verified before dispatch.
   - Resource locking (`MCPDistributedLock`) and execution timeouts (`default_timeout_seconds=30.0`) prevent runaway tool executions.
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
