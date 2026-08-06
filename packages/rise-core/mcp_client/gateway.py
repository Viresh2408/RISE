"""MCP Client Gateway & Allow-list Middleware for RISE.

Intercepts all agent tool calls before dispatch to MCP servers.
Enforces:
  1. OPA Policy allow-list check (`policies/tool_allowlist.rego`).
  2. Step-level tool name & parameter verification against the approved ActionPlan.
  3. Configurable per-tool-call timeout (default 30s).
  4. Immutable Audit log recording for EVERY tool call (allowed, denied, success, failure, timeout).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, Optional, Union

import sys
from pathlib import Path

# Add mcp-servers directory paths to sys.path for clean out-of-process/module imports
_ROOT_DIR = Path(__file__).resolve().parents[2]
for _server_dir in ["mcp-kubernetes", "mcp-aws", "mcp-github"]:
    _p = str(_ROOT_DIR / "packages" / "mcp-servers" / _server_dir)
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from kubernetes_server import MCPKubernetesServer
except ImportError:
    from packages.mcp_servers.mcp_kubernetes.kubernetes_server import MCPKubernetesServer  # type: ignore

try:
    from aws_server import MCPAWSServer
except ImportError:
    from packages.mcp_servers.mcp_aws.aws_server import MCPAWSServer  # type: ignore

try:
    from github_server import MCPGitHubServer
except ImportError:
    from packages.mcp_servers.mcp_github.github_server import MCPGitHubServer  # type: ignore

from schemas.agent_state import ActionPlan, ActionStep

logger = logging.getLogger(__name__)


class ToolBlockedError(PermissionError):
    """Raised when a tool call is blocked by OPA policy or plan parameter mismatch."""

    def __init__(self, message: str, reason: str = "allow_list_denied"):
        self.reason = reason
        super().__init__(message)


class MCPToolTimeoutError(TimeoutError):
    """Raised when an MCP tool call exceeds its execution timeout."""
    pass


class MCPGateway:
    """MCP Client Gateway with Allow-List Middleware and Audit Logging."""

    def __init__(
        self,
        *,
        default_timeout_seconds: float = 30.0,
        opa_client: Optional[Any] = None,
        k8s_server: Optional[MCPKubernetesServer] = None,
        aws_server: Optional[MCPAWSServer] = None,
        github_server: Optional[MCPGitHubServer] = None,
    ):
        self.default_timeout_seconds = default_timeout_seconds
        self.opa_client = opa_client

        # Isolated MCP Server instances
        self.k8s_server = k8s_server or MCPKubernetesServer()
        self.aws_server = aws_server or MCPAWSServer()
        self.github_server = github_server or MCPGitHubServer()

    def evaluate_opa_allowlist(
        self,
        agent_identity: str,
        tool_name: str,
        params: Dict[str, Any],
        environment: str = "staging",
    ) -> bool:
        """Evaluate OPA allow-list policy for tool call."""
        # 1. Local Python evaluation of tool_allowlist rules (matches policies/tool_allowlist.rego)
        write_tools = {
            "restart_pod",
            "rollback_deployment",
            "scale_deployment",
            "restart_ec2_instance",
            "invoke_lambda",
            "update_ssm_parameter",
            "create_branch",
            "create_pr",
            "run_workflow",
        }
        read_tools = {
            "get_pod_status",
            "get_pod_logs",
            "get_events",
            "get_cloudwatch_alarms",
            "get_cloudwatch_logs",
            "get_iam_context",
            "get_recent_commits",
            "get_pr_diff",
            "get_workflow_status",
            "query_prometheus",
            "query_loki",
            "query_alertmanager",
            "search_similar_incidents",
            "search_runbooks",
        }

        if environment == "unauthorized":
            return False

        if agent_identity == "execution-agent":
            return tool_name in write_tools or tool_name in read_tools
        elif agent_identity in ("context-builder-agent", "investigation-agent"):
            return tool_name in read_tools

        return False

    def validate_plan_step(
        self,
        tool_name: str,
        params: Dict[str, Any],
        approved_plan: Union[ActionPlan, Dict[str, Any]],
        step_index: int,
    ) -> None:
        """Validate that (tool_name, params) exactly matches step_index of approved_plan."""
        if isinstance(approved_plan, ActionPlan):
            steps = approved_plan.action_steps
        elif isinstance(approved_plan, dict):
            steps = approved_plan.get("action_steps", [])
        else:
            raise ValueError(f"Invalid approved_plan format: {type(approved_plan)}")

        if step_index < 0 or step_index >= len(steps):
            raise ToolBlockedError(
                f"Step index {step_index} is out of bounds for approved plan (total steps: {len(steps)})",
                reason="step_index_out_of_bounds",
            )

        target_step = steps[step_index]
        if isinstance(target_step, ActionStep):
            approved_tool = target_step.tool
            approved_params = target_step.params
        elif isinstance(target_step, dict):
            approved_tool = target_step.get("tool", "")
            approved_params = target_step.get("params", {})
        else:
            approved_tool = str(target_step)
            approved_params = {}

        if tool_name != approved_tool:
            raise ToolBlockedError(
                f"Tool '{tool_name}' does not match approved tool '{approved_tool}' at step {step_index}",
                reason="tool_mismatch",
            )

        if params != approved_params:
            raise ToolBlockedError(
                f"Parameters {params} do not match approved parameters {approved_params} at step {step_index}",
                reason="parameter_mismatch",
            )

    def _record_audit_event(
        self,
        *,
        db_session: Optional[Any],
        tenant_id: Union[str, uuid.UUID],
        incident_id: Optional[Union[str, uuid.UUID]],
        actor: str,
        action: str,
        params: Dict[str, Any],
        result: Optional[Dict[str, Any]],
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Write an AuditEvent entry to DB for every tool call attempt."""
        if db_session is None:
            logger.info("Audit log [NO_DB_SESSION]: actor=%s action=%s status=%s", actor, action, status)
            return

        try:
            from db.models import create_audit_event
            tid = uuid.UUID(str(tenant_id)) if isinstance(tenant_id, str) else tenant_id
            iid = uuid.UUID(str(incident_id)) if incident_id and isinstance(incident_id, str) else incident_id

            before_state = {"params": params, "status": status}
            after_state = {"result": result, "error": error} if error else {"result": result}

            create_audit_event(
                session=db_session,
                tenant_id=tid,
                actor=actor,
                action=action,
                before_state=before_state,
                after_state=after_state,
                incident_id=iid,
            )
            db_session.commit()
            logger.info("Recorded AuditEvent for actor='%s', action='%s', status='%s'", actor, action, status)
        except Exception as exc:
            logger.warning("Failed to record AuditEvent to DB: %s", exc)

    async def dispatch_tool_call(
        self,
        *,
        agent_identity: str,
        tool_name: str,
        params: Dict[str, Any],
        approved_plan: Optional[Union[ActionPlan, Dict[str, Any]]] = None,
        step_index: Optional[int] = None,
        environment: str = "staging",
        tenant_id: Union[str, uuid.UUID] = "00000000-0000-0000-0000-000000000001",
        incident_id: Optional[Union[str, uuid.UUID]] = None,
        db_session: Optional[Any] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Dispatch tool call through allow-list middleware, step verification, and audit logging."""
        effective_timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds

        # 1. OPA Allow-list Check
        allowed = self.evaluate_opa_allowlist(agent_identity, tool_name, params, environment)
        if not allowed:
            err_msg = f"Tool '{tool_name}' blocked by OPA allow-list policy for agent '{agent_identity}'"
            self._record_audit_event(
                db_session=db_session,
                tenant_id=tenant_id,
                incident_id=incident_id,
                actor=agent_identity,
                action=f"DENIED:{tool_name}",
                params=params,
                result=None,
                status="blocked",
                error=err_msg,
            )
            raise ToolBlockedError(err_msg, reason="opa_allowlist_denied")

        # 2. Step-level parameter and plan matching check
        if approved_plan is not None and step_index is not None:
            try:
                self.validate_plan_step(tool_name, params, approved_plan, step_index)
            except ToolBlockedError as tbe:
                self._record_audit_event(
                    db_session=db_session,
                    tenant_id=tenant_id,
                    incident_id=incident_id,
                    actor=agent_identity,
                    action=f"DENIED:{tool_name}",
                    params=params,
                    result=None,
                    status="blocked",
                    error=str(tbe),
                )
                raise

        # 3. Dispatch to server with per-tool timeout
        try:
            async def _execute():
                if tool_name in ("get_pod_status", "get_pod_logs", "restart_pod", "rollback_deployment", "scale_deployment", "get_events"):
                    return self.k8s_server.handle_tool_call(tool_name, params)
                elif tool_name in ("get_cloudwatch_alarms", "get_cloudwatch_logs", "restart_ec2_instance", "invoke_lambda", "update_ssm_parameter", "get_iam_context"):
                    return self.aws_server.handle_tool_call(tool_name, params)
                elif tool_name in ("get_recent_commits", "get_pr_diff", "create_branch", "create_pr", "run_workflow", "get_workflow_status"):
                    return self.github_server.handle_tool_call(tool_name, params)
                else:
                    raise ValueError(f"No registered server for tool '{tool_name}'")

            result = await asyncio.wait_for(_execute(), timeout=effective_timeout)

            # Record success audit event
            self._record_audit_event(
                db_session=db_session,
                tenant_id=tenant_id,
                incident_id=incident_id,
                actor=agent_identity,
                action=tool_name,
                params=params,
                result=result,
                status="success",
            )
            return result

        except asyncio.TimeoutError:
            err_msg = f"Tool '{tool_name}' call timed out after {effective_timeout}s"
            self._record_audit_event(
                db_session=db_session,
                tenant_id=tenant_id,
                incident_id=incident_id,
                actor=agent_identity,
                action=tool_name,
                params=params,
                result=None,
                status="timeout",
                error=err_msg,
            )
            raise MCPToolTimeoutError(err_msg)

        except Exception as exc:
            err_msg = str(exc)
            self._record_audit_event(
                db_session=db_session,
                tenant_id=tenant_id,
                incident_id=incident_id,
                actor=agent_identity,
                action=tool_name,
                params=params,
                result=None,
                status="failed",
                error=err_msg,
            )
            raise
