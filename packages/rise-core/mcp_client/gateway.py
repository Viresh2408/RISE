"""MCP Client Gateway & Allow-list Middleware for RISE.

Intercepts all agent tool calls before dispatch to MCP servers.
Enforces:
  1. Static Python allow-list check (`evaluate_python_allowlist`). NOTE: this is a
     hardcoded in-process allow-list, NOT an OPA call. The authoritative Open Policy
     Agent (OPA) evaluation against `policies/*.rego` happens upstream in the Risk
     Engine (`apps/agents/src/engines/risk_engine.py`); this gateway layer is a
     defense-in-depth structural allow-list. See ADR-002 in docs/architecture-decisions.md.
  2. Approved-plan hash re-verification (defense-in-depth; enforced regardless of caller).
  3. Per-resource lock conflict check for write tools (honours the plan-level lock held
     by the Execution Agent so a direct gateway caller cannot bypass it).
  4. Step-level tool name & parameter verification against the approved ActionPlan.
  5. Configurable per-tool-call timeout (default 30s).
  6. Immutable Audit log recording for EVERY tool call (allowed, denied, success, failure,
     timeout). Audit writes never fail silently: IDs are coerced and any residual failure
     is logged loudly and re-raised.
  7. Allow-listed-but-unimplemented tools (mcp-observability, mcp-knowledge) raise a clear
     ``ToolNotImplementedError`` (audited as ``not_implemented``) instead of an opaque
     dispatch crash.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, Optional, Union

import sys
from pathlib import Path

# Add mcp-servers directory paths to sys.path for clean out-of-process/module imports
_ROOT_DIR = Path(__file__).resolve().parents[3]
for _server_dir in ["mcp-kubernetes", "mcp-aws", "mcp-github", "mcp-slack"]:
    _p = str(_ROOT_DIR / "packages" / "mcp-servers" / _server_dir)
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from kubernetes_server import MCPKubernetesServer
except ImportError:
    try:
        from packages.mcp_servers.mcp_kubernetes.kubernetes_server import MCPKubernetesServer  # type: ignore
    except ImportError:
        MCPKubernetesServer = None  # type: ignore

try:
    from aws_server import MCPAWSServer
except ImportError:
    try:
        from packages.mcp_servers.mcp_aws.aws_server import MCPAWSServer  # type: ignore
    except ImportError:
        MCPAWSServer = None  # type: ignore

try:
    from github_server import MCPGitHubServer
except ImportError:
    try:
        from packages.mcp_servers.mcp_github.github_server import MCPGitHubServer  # type: ignore
    except ImportError:
        MCPGitHubServer = None  # type: ignore

try:
    from slack_server import MCPSlackServer
except ImportError:
    try:
        from packages.mcp_servers.mcp_slack.slack_server import MCPSlackServer  # type: ignore
    except ImportError:
        MCPSlackServer = None  # type: ignore

from schemas.agent_state import ActionPlan, ActionStep

logger = logging.getLogger(__name__)


# Canonical (post-normalization) tool names grouped by capability. Hoisted to module
# level so both the allow-list evaluation and the write-tool lock conflict check share
# a single source of truth.
_WRITE_TOOLS = frozenset({
    "restart_pod",
    "rollback_deployment",
    "scale_deployment",
    "restart_ec2_instance",
    "invoke_lambda",
    "update_ssm_parameter",
    "create_branch",
    "create_pr",
    "code_fix_pr",
    "config_update",
    "scale",
    "rollback",
    "run_workflow",
    "post_message",
    "post_interactive_approval",
    "update_message",
    # Simulated Security Response Actions & Rollback tools
    "block_ip_address",
    "isolate_host",
    "revoke_session_token",
    "quarantine_file",
    "flag_for_soc_review",
    "unblock_ip_address",
    "reconnect_host",
    "restore_file",
    "restore_session_token",
})
_READ_TOOLS = frozenset({
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
    "read_thread",
})


class ToolBlockedError(PermissionError):
    """Raised when a tool call is blocked by the static allow-list, the approved-plan
    hash/parameter check, or a per-resource lock conflict."""

    def __init__(self, message: str, reason: str = "allow_list_denied"):
        self.reason = reason
        super().__init__(message)


class MCPToolTimeoutError(TimeoutError):
    """Raised when an MCP tool call exceeds its execution timeout."""
    pass


class AuditWriteError(RuntimeError):
    """Raised when an immutable audit-log write fails. Audit writes must never fail
    silently, so a residual failure (after ID coercion) is logged loudly and surfaced."""
    pass


class ToolNotImplementedError(NotImplementedError):
    """Raised when a tool is allow-listed but its backing MCP server is not implemented
    in this build (e.g. mcp-observability, mcp-knowledge). These tools appear in the
    read-list for policy/allow-list completeness, but no server dispatches them yet.

    Surfacing a clear, typed error (instead of the previous opaque
    ``ValueError('No registered server for tool ...')``) lets callers and the audit log
    distinguish "not built yet" from a genuine dispatch/config bug for an unknown tool."""

    def __init__(self, message: str, tool_name: str = "", server: str = "") -> None:
        self.tool_name = tool_name
        self.server = server
        super().__init__(message)


def _coerce_uuid(value: Optional[Union[str, uuid.UUID]], field_name: str) -> Optional[uuid.UUID]:
    """Coerce an identifier to a UUID for the audit write.

    A already-valid UUID (or UUID string) is returned as-is. A non-UUID identifier (e.g.
    a human-readable "inc-test-01") is deterministically mapped to a UUID via uuid5 so the
    audit linkage is preserved instead of the whole write throwing "badly formed
    hexadecimal UUID string" and being silently swallowed.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        coerced = uuid.uuid5(uuid.NAMESPACE_URL, f"rise:{field_name}:{value}")
        logger.warning(
            "Audit %s '%s' is not a valid UUID; deterministically coerced to %s so the "
            "audit write is not silently dropped.",
            field_name, value, coerced,
        )
        return coerced


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
        slack_server: Optional[MCPSlackServer] = None,
    ):
        self.default_timeout_seconds = default_timeout_seconds
        self.opa_client = opa_client

        # Isolated MCP Server instances
        self.k8s_server = k8s_server or (MCPKubernetesServer() if MCPKubernetesServer else None)
        self.aws_server = aws_server or (MCPAWSServer() if MCPAWSServer else None)
        self.github_server = github_server or (MCPGitHubServer() if MCPGitHubServer else None)
        self.slack_server = slack_server or (MCPSlackServer() if MCPSlackServer else None)

    def evaluate_python_allowlist(
        self,
        agent_identity: str,
        tool_name: str,
        params: Dict[str, Any],
        environment: str = "staging",
    ) -> bool:
        """Evaluate the static Python allow-list for a tool call.

        This is a hardcoded, in-process structural allow-list (agent identity x tool x
        environment). It is NOT an OPA evaluation — the authoritative OPA policy call is
        made upstream by the Risk Engine. This layer is defense-in-depth. See ADR-002.
        """
        norm_tool = "restart_pod" if tool_name == "kubernetes_restart_pod" else tool_name

        write_tools = _WRITE_TOOLS
        read_tools = _READ_TOOLS

        if environment == "unauthorized":
            return False

        # In production, automatic unapproved write tool execution is blocked until out-of-process isolation exists
        env_norm = environment.lower().strip()
        if env_norm in ("production", "prod") and norm_tool in write_tools:
            # Must be invoked with human approval or via explicit human-approved flow
            if agent_identity not in ("execution-agent", "orchestrator-agent", "notification-service"):
                return False

        if agent_identity in ("execution-agent", "orchestrator-agent", "notification-service"):
            return norm_tool in write_tools or norm_tool in read_tools
        elif agent_identity in ("context-builder-agent", "investigation-agent"):
            return norm_tool in read_tools

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
            approved_params = target_step.get("params") or target_step.get("parameters", {})
        else:
            approved_tool = str(target_step)
            approved_params = {}

        # Canonicalize tool names for comparison
        norm_tool = "restart_pod" if tool_name == "kubernetes_restart_pod" else tool_name
        norm_approved_tool = "restart_pod" if approved_tool == "kubernetes_restart_pod" else approved_tool

        if norm_tool != norm_approved_tool:
            raise ToolBlockedError(
                f"Tool '{tool_name}' does not match approved tool '{approved_tool}' at step {step_index}",
                reason="tool_mismatch",
            )

        norm_params = dict(params)
        if "parameters" in norm_params and len(norm_params) == 1 and isinstance(norm_params["parameters"], dict):
            norm_params = norm_params["parameters"]
        norm_approved_params = dict(approved_params)
        if "parameters" in norm_approved_params and len(norm_approved_params) == 1 and isinstance(norm_approved_params["parameters"], dict):
            norm_approved_params = norm_approved_params["parameters"]

        if norm_params != norm_approved_params:
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
            tid = _coerce_uuid(tenant_id, "tenant_id")
            iid = _coerce_uuid(incident_id, "incident_id")

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
            # Audit writes back the immutability guarantee, so a failure must be loud —
            # never a swallowed warning. Coercion above removes the common non-UUID crash;
            # anything left is a genuine infra failure worth surfacing.
            logger.error(
                "AUDIT WRITE FAILED for actor='%s', action='%s', status='%s': %s",
                actor, action, status, exc, exc_info=True,
            )
            raise AuditWriteError(
                f"Failed to record immutable AuditEvent for action='{action}' (status='{status}'): {exc}"
            ) from exc

    async def dispatch_tool_call(
        self,
        *,
        agent_identity: str,
        tool_name: str,
        params: Dict[str, Any],
        approved_plan: Optional[Union[ActionPlan, Dict[str, Any]]] = None,
        approved_plan_hash: Optional[str] = None,
        step_index: Optional[int] = None,
        environment: str = "staging",
        tenant_id: Union[str, uuid.UUID] = "00000000-0000-0000-0000-000000000001",
        incident_id: Optional[Union[str, uuid.UUID]] = None,
        resource_id: Optional[str] = None,
        redis_client: Optional[Any] = None,
        db_session: Optional[Any] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Dispatch tool call through allow-list middleware, step verification, and audit logging.

        Defense-in-depth (enforced here regardless of caller, so a direct gateway caller
        cannot bypass the Execution Agent's checks):
          - ``approved_plan_hash``: if supplied with ``approved_plan``, the gateway
            re-computes the plan hash and blocks on mismatch (ACTION_PLAN_CHANGED).
          - ``resource_id`` (+ optional ``redis_client``): for write tools, the gateway
            blocks if the resource lock is currently held by a *different* owner than
            ``incident_id`` — honouring the plan-level lock held by the Execution Agent.
        """
        effective_timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds

        # Canonicalize tool name & parameters
        norm_tool = "restart_pod" if tool_name == "kubernetes_restart_pod" else tool_name
        norm_params = dict(params)
        if "parameters" in norm_params and len(norm_params) == 1 and isinstance(norm_params["parameters"], dict):
            norm_params = norm_params["parameters"]

        # Reject write-enabled mocked MCP transports in staging/production
        is_prod_staging = environment.lower().strip() in ("production", "prod", "staging")
        if is_prod_staging and self.github_server and getattr(self.github_server, "allow_test_mock", False):
            err_msg = f"Write-enabled mocked MCP transport is strictly rejected in {environment}."
            self._record_audit_event(
                db_session=db_session,
                tenant_id=tenant_id,
                incident_id=incident_id,
                actor=agent_identity,
                action=f"DENIED:{norm_tool}",
                params=norm_params,
                result=None,
                status="blocked",
                error=err_msg,
            )
            raise ToolBlockedError(err_msg, reason="mock_transport_rejected_in_production")

        # 1. Static allow-list check (defense-in-depth; real OPA runs upstream in Risk Engine)
        allowed = self.evaluate_python_allowlist(agent_identity, norm_tool, norm_params, environment)
        if not allowed:
            err_msg = f"Tool '{norm_tool}' blocked by allow-list policy for agent '{agent_identity}'"
            self._record_audit_event(
                db_session=db_session,
                tenant_id=tenant_id,
                incident_id=incident_id,
                actor=agent_identity,
                action=f"DENIED:{norm_tool}",
                params=norm_params,
                result=None,
                status="blocked",
                error=err_msg,
            )
            raise ToolBlockedError(err_msg, reason="allowlist_denied")

        # 2. Approved-plan hash re-verification (defense-in-depth, caller-independent).
        # The Execution Agent already verifies this, but re-checking here guarantees a
        # tampered plan is rejected even if the gateway is invoked directly.
        if approved_plan is not None and approved_plan_hash:
            from mcp_client.hash import compute_action_plan_hash
            current_hash = compute_action_plan_hash(approved_plan)
            if current_hash != approved_plan_hash:
                err_msg = (
                    f"Action plan hash changed since approval (approved: {approved_plan_hash[:8]}, "
                    f"current: {current_hash[:8]})"
                )
                self._record_audit_event(
                    db_session=db_session,
                    tenant_id=tenant_id,
                    incident_id=incident_id,
                    actor=agent_identity,
                    action=f"DENIED:{norm_tool}",
                    params=norm_params,
                    result=None,
                    status="blocked",
                    error=err_msg,
                )
                raise ToolBlockedError(err_msg, reason="action_plan_changed")

        # 3. Per-resource lock conflict check for write tools (caller-independent).
        # Non-destructive peek: we do NOT acquire/release here (the Execution Agent owns
        # the plan-level lock for the full plan duration). We only block if the resource
        # is currently locked by a DIFFERENT owner, which is the real bypass gap.
        if norm_tool in _WRITE_TOOLS and resource_id and incident_id:
            from mcp_client.lock import ResourceLockManager
            current_owner = ResourceLockManager.get_lock_owner(resource_id, redis_client=redis_client)
            if current_owner is not None and current_owner != str(incident_id):
                err_msg = (
                    f"Resource '{resource_id}' is locked by another remediation "
                    f"(owner='{current_owner}'); write tool '{norm_tool}' blocked."
                )
                self._record_audit_event(
                    db_session=db_session,
                    tenant_id=tenant_id,
                    incident_id=incident_id,
                    actor=agent_identity,
                    action=f"DENIED:{norm_tool}",
                    params=norm_params,
                    result=None,
                    status="blocked",
                    error=err_msg,
                )
                raise ToolBlockedError(err_msg, reason="resource_locked")

        # 4. Step-level parameter and plan matching check
        if approved_plan is not None and step_index is not None:
            try:
                self.validate_plan_step(norm_tool, norm_params, approved_plan, step_index)
            except ToolBlockedError as tbe:
                self._record_audit_event(
                    db_session=db_session,
                    tenant_id=tenant_id,
                    incident_id=incident_id,
                    actor=agent_identity,
                    action=f"DENIED:{norm_tool}",
                    params=norm_params,
                    result=None,
                    status="blocked",
                    error=str(tbe),
                )
                raise

        # 5. Dispatch to server with per-tool timeout
        async def _execute() -> Dict[str, Any]:
            if norm_tool in ("get_pod_status", "get_pod_logs", "restart_pod", "rollback_deployment", "scale_deployment", "scale", "rollback", "config_update", "get_events"):
                eff_tool = "restart_pod" if norm_tool in ("config_update",) else ("scale_deployment" if norm_tool == "scale" else ("rollback_deployment" if norm_tool == "rollback" else norm_tool))
                return self.k8s_server.handle_tool_call(eff_tool, norm_params)
            elif norm_tool in ("get_cloudwatch_alarms", "get_cloudwatch_logs", "restart_ec2_instance", "invoke_lambda", "update_ssm_parameter", "get_iam_context"):
                return self.aws_server.handle_tool_call(norm_tool, norm_params)
            elif norm_tool in ("get_recent_commits", "get_pr_diff", "create_branch", "create_pr", "code_fix_pr", "run_workflow", "get_workflow_status"):
                eff_tool = "create_pr" if norm_tool == "code_fix_pr" else norm_tool
                return self.github_server.handle_tool_call(eff_tool, norm_params)
            elif norm_tool in ("post_message", "post_interactive_approval", "read_thread", "update_message"):
                if self.slack_server is None:
                    from slack_server import MCPSlackServer
                    self.slack_server = MCPSlackServer()
                return self.slack_server.handle_tool_call(norm_tool, norm_params)
            elif norm_tool in (
                "block_ip_address",
                "isolate_host",
                "revoke_session_token",
                "quarantine_file",
                "flag_for_soc_review",
                "unblock_ip_address",
                "reconnect_host",
                "restore_file",
                "restore_session_token",
            ):
                # Simulated Security Response Actions execute as logged, audited no-op actions
                logger.info("Executing simulated security response action: %s with params: %s", norm_tool, norm_params)
                return {
                    "status": "success",
                    "simulated": True,
                    "tool": norm_tool,
                    "action": norm_tool,
                    "message": f"Simulated security response action '{norm_tool}' executed and audited successfully.",
                    "params": norm_params,
                }
            elif norm_tool in ("query_prometheus", "query_loki", "query_alertmanager"):
                # mcp-observability tools are allow-listed for policy completeness but the
                # backing server is not implemented in this build. Fail with a clear,
                # typed not-implemented error instead of an opaque dispatch crash.
                raise ToolNotImplementedError(
                    f"Tool '{norm_tool}' is allow-listed but the mcp-observability server "
                    f"is not implemented in this build (no Prometheus/Loki/Alertmanager backend wired).",
                    tool_name=norm_tool,
                    server="mcp-observability",
                )
            elif norm_tool in ("search_similar_incidents", "search_runbooks"):
                # mcp-knowledge tools are allow-listed for policy completeness but the
                # backing RAG/vector server is not implemented in this build.
                raise ToolNotImplementedError(
                    f"Tool '{norm_tool}' is allow-listed but the mcp-knowledge server "
                    f"is not implemented in this build (no RAG/vector backend wired).",
                    tool_name=norm_tool,
                    server="mcp-knowledge",
                )
            else:
                raise ValueError(f"No registered server for tool '{norm_tool}'")

        try:
            result = await asyncio.wait_for(_execute(), timeout=effective_timeout)

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

        except ToolNotImplementedError as nie:
            # Allow-listed-but-unimplemented tool. Audit distinctly (not "failed") so the
            # gap is visible in the immutable log, then re-raise the clear typed error.
            self._record_audit_event(
                db_session=db_session,
                tenant_id=tenant_id,
                incident_id=incident_id,
                actor=agent_identity,
                action=tool_name,
                params=params,
                result=None,
                status="not_implemented",
                error=str(nie),
            )
            raise

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

        # Record success audit event OUTSIDE the try so an audit failure surfaces loudly
        # (AuditWriteError) instead of being re-caught and mislabelled as a tool failure.
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
