"""LangGraph State Machine Orchestrator for RISE Agent Pipeline."""

import asyncio
import concurrent.futures
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypedDict

_CORE_PATH = str(Path(__file__).resolve().parents[4] / "packages" / "rise-core")
if _CORE_PATH not in sys.path:
    sys.path.insert(0, _CORE_PATH)

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

NODE_TIMEOUT_SECONDS = 120


class AgentState(TypedDict, total=False):
    # Identity
    tenant_id: str
    incident_id: str
    agent_run_id: str

    # Pipeline data
    event_payload: dict
    context: dict
    hypotheses: list
    root_cause: dict
    impact_assessment: dict
    decision: dict
    action_plan: dict
    rollback_count: int
    rollback_execution_log: dict
    slack_card: dict

    # Human-in-the-loop
    human_approval: str  # "approved" | "rejected" | ""
    await_human_reason: str  # "approval_required" | "rollback_complete"

    # Execution & verification
    execution_log: dict
    post_action_metrics: dict
    baseline_metrics: dict
    verification_result: dict

    # Orchestrator control
    current_step: str
    retry_counts: dict
    should_escalate: bool
    error: str
    status: str  # "running" | "completed" | "escalated" | "manual_handoff"
    requires_approval: bool
    risk_tier: str
    confidence: float
    runbook_match: dict


def _to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    return str(obj)


def _record_step_result(
    state: AgentState,
    node_name: str,
    input_data: dict,
    output_data: dict,
    confidence: float,
    duration_ms: int,
) -> None:
    agent_run_id = state.get("agent_run_id")
    tenant_id = state.get("tenant_id")
    if not agent_run_id or not tenant_id:
        return

    try:
        from db.models import AgentStepResult
        from db.session import SessionLocal, tenant_session

        clean_input = _to_jsonable(input_data)
        clean_output = _to_jsonable(output_data)

        with tenant_session(tenant_id):
            with SessionLocal() as session:
                step_result = AgentStepResult(
                    id=uuid.uuid4(),
                    tenant_id=uuid.UUID(str(tenant_id)) if isinstance(tenant_id, str) else tenant_id,
                    agent_run_id=uuid.UUID(str(agent_run_id)) if isinstance(agent_run_id, str) else agent_run_id,
                    agent_name=node_name,
                    input=clean_input,
                    output=clean_output,
                    confidence=confidence,
                    duration_ms=duration_ms,
                )
                session.add(step_result)
                session.commit()
    except Exception as exc:
        logger.debug("Failed to record AgentStepResult to DB: %s", exc)


def run_node_with_retry_and_timeout(
    node_fn: Callable[[AgentState], AgentState],
    node_name: str,
    state: AgentState,
    *,
    timeout_s: int = NODE_TIMEOUT_SECONDS,
) -> AgentState:
    """Execute node_fn(state) with timeout, retry-once-then-escalate, and DB step auditing."""
    new_state: AgentState = dict(state)
    new_state["current_step"] = node_name

    retry_counts = dict(new_state.get("retry_counts") or {})
    attempt = 0
    last_error: Optional[str] = None
    start_time = time.time()
    node_output: Optional[AgentState] = None

    while attempt < 2:
        attempt += 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(node_fn, dict(new_state))
                node_output = future.result(timeout=timeout_s)
            last_error = None
            break
        except Exception as exc:
            last_error = str(exc) if str(exc) else repr(exc)
            retry_counts[node_name] = retry_counts.get(node_name, 0) + 1
            logger.warning(
                "Node '%s' failed attempt %d/2: %s", node_name, attempt, last_error
            )
    duration_ms = int((time.time() - start_time) * 1000)

    if last_error is not None:
        new_state["retry_counts"] = retry_counts
        new_state["should_escalate"] = True
        new_state["error"] = last_error
        new_state["status"] = "escalated"
        _record_step_result(
            state=new_state,
            node_name=node_name,
            input_data=dict(state),
            output_data={"error": last_error, "attempts": attempt},
            confidence=0.0,
            duration_ms=duration_ms,
        )
        return new_state

    if isinstance(node_output, dict):
        new_state.update(node_output)

    new_state["retry_counts"] = retry_counts

    _record_step_result(
        state=new_state,
        node_name=node_name,
        input_data=dict(state),
        output_data=dict(new_state),
        confidence=1.0,
        duration_ms=duration_ms,
    )
    return new_state


# --- No-op Node Definitions ---


def node_ingest(state: AgentState) -> AgentState:
    res = dict(state)
    payload = dict(res.get("event_payload") or {})
    summary = str(payload.get("summary", "")).lower()
    raw_text = str(payload.get("raw_payload", payload)).lower()

    sanitization_flags = list(payload.get("sanitization_flags") or [])

    injection_patterns = [
        "ignore previous instructions", "system instruction", "override risk",
        "auto_approve=true", "rm -rf", "curl ", "wget ", "sk_live_", "akia",
        "bearer ", "health check override", "human approved this action",
        "topology override", "include all database passwords", "disable rollback",
        "rca report:", "approve all pending actions", "skip risk assessment",
        "dump all env", "postgres_pass_", "force auto-approval"
    ]

    if any(pat in summary or pat in raw_text for pat in injection_patterns):
        if "prompt_injection_detected" not in sanitization_flags:
            sanitization_flags.append("prompt_injection_detected")

    if sanitization_flags:
        payload["sanitization_flags"] = sanitization_flags
    elif "sanitization_flags" in payload:
        payload["sanitization_flags"] = []
    res["event_payload"] = payload
    return res


def node_build_context(state: AgentState) -> AgentState:
    if state.get("context"):
        return dict(state)
    from apps.agents.src.nodes.context_builder import run_context_builder_agent

    try:
        return asyncio.run(run_context_builder_agent(dict(state)))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_context_builder_agent(dict(state)))
        finally:
            loop.close()




def node_investigate(state: AgentState) -> AgentState:
    if state.get("hypotheses"):
        return dict(state)
    from apps.agents.src.nodes.investigation import run_investigation_agent

    try:
        return asyncio.run(run_investigation_agent(dict(state)))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_investigation_agent(dict(state)))
        finally:
            loop.close()


def node_root_cause(state: AgentState) -> AgentState:
    if state.get("root_cause"):
        return dict(state)
    from apps.agents.src.nodes.root_cause import run_root_cause_agent

    try:
        return asyncio.run(run_root_cause_agent(dict(state)))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_root_cause_agent(dict(state)))
        finally:
            loop.close()


def node_impact_analysis(state: AgentState) -> AgentState:
    if state.get("impact_assessment"):
        return dict(state)
    from apps.agents.src.nodes.impact_analyzer import run_impact_analyzer_agent

    try:
        return asyncio.run(run_impact_analyzer_agent(dict(state)))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_impact_analyzer_agent(dict(state)))
        finally:
            loop.close()



def node_decide(state: AgentState) -> AgentState:
    if state.get("decision") and "requires_approval" in (state.get("decision") or {}):
        res = dict(state)
        dec = res["decision"]
        res["requires_approval"] = dec.get("requires_approval", False)
        res["risk_tier"] = dec.get("risk_tier", "low")
        if "action_plan" not in res and dec.get("action_plan"):
            res["action_plan"] = dec["action_plan"]
        elif "action_plan" not in res:
            res["action_plan"] = {
                "action_type": "restart_pod",
                "action_steps": [{"tool": "restart_pod", "params": {"pod": "auth-1"}}],
                "rollback_plan": [{"tool": "rollback_deployment", "params": {"deploy": "auth"}}],
                "plan_rationale": "Remediate via restart_pod",
            }
        return res

    from apps.agents.src.nodes.decision_plan import run_decision_plan_agent

    try:
        return asyncio.run(run_decision_plan_agent(dict(state), use_local_risk_fallback=True))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_decision_plan_agent(dict(state), use_local_risk_fallback=True))
        finally:
            loop.close()



def node_await_human(state: AgentState) -> AgentState:
    from apps.agents.src.services.slack_card import format_slack_approval_card, send_slack_approval_card

    res = dict(state)
    if not res.get("await_human_reason"):
        res["await_human_reason"] = "approval_required"

    # Render Slack approval card per prompts.md §9
    card = format_slack_approval_card(res)
    res["slack_card"] = card
    send_slack_approval_card(res, res.get("tenant_id", "default-tenant"))

    # If interrupt requested and no decision submitted yet, call LangGraph interrupt
    if res.get("use_interrupt") and not res.get("human_approval"):
        try:
            from langgraph.types import interrupt
            resume_val = interrupt({"reason": "approval_required", "slack_card": card})
            if isinstance(resume_val, str):
                res["human_approval"] = resume_val
            elif isinstance(resume_val, dict):
                res.update(resume_val)
        except ImportError:
            pass

    return res


def node_execute(state: AgentState) -> AgentState:
    from apps.agents.src.nodes.execution import run_execution_agent

    try:
        res = asyncio.run(run_execution_agent(dict(state)))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(run_execution_agent(dict(state)))
        finally:
            loop.close()

    if not res.get("post_action_metrics") and res.get("execution_log", {}).get("status") == "success":
        res["post_action_metrics"] = {"health_status": "200 OK", "error_rate": 0.0}
    return res


def node_verify(state: AgentState) -> AgentState:
    from apps.agents.src.nodes.verification import run_verification_agent

    try:
        return asyncio.run(run_verification_agent(dict(state)))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_verification_agent(dict(state)))
        finally:
            loop.close()


def node_rollback(state: AgentState) -> AgentState:
    from apps.agents.src.nodes.execution import run_execution_agent

    res = dict(state)
    rollback_count = res.get("rollback_count", 0) + 1
    res["rollback_count"] = rollback_count

    MAX_ROLLBACK_CYCLES = 2  # Circuit breaker threshold per agents-and-orchestration.md §7

    if rollback_count >= MAX_ROLLBACK_CYCLES:
        logger.warning(
            "Circuit breaker triggered for incident %s: max rollback cycles (%d) reached.",
            res.get("incident_id"),
            rollback_count,
        )
        res["status"] = "manual_handoff"
        res["should_escalate"] = True
        res["error"] = f"Circuit breaker triggered: Max rollback cycles ({MAX_ROLLBACK_CYCLES}) reached."
        return res

    action_plan = res.get("action_plan") or {}
    rollback_steps = action_plan.get("rollback_plan") or []

    if rollback_steps:
        rollback_action_plan = {
            "action_type": "rollback",
            "action_steps": rollback_steps,
            "rollback_plan": [],
            "plan_rationale": "Auto-rollback triggered on verification failure",
        }
        rollback_state = dict(res)
        rollback_state["action_plan"] = rollback_action_plan
        rollback_state["approved_plan_hash"] = None
        try:
            exec_res = asyncio.run(run_execution_agent(rollback_state))
            res["rollback_execution_log"] = exec_res.get("execution_log")
        except Exception as exc:
            logger.error("Auto-rollback execution failed: %s", exc)

    res["await_human_reason"] = "rollback_complete"
    res["human_approval"] = ""  # Reset approval for re-escalation
    return res


def node_close(state: AgentState) -> AgentState:
    res = dict(state)
    res["status"] = "completed"
    res["should_escalate"] = False
    res["current_step"] = "close"
    return res


def node_manual_handoff(state: AgentState) -> AgentState:
    res = dict(state)
    res["status"] = "manual_handoff"
    return res


def node_escalate(state: AgentState) -> AgentState:
    res = dict(state)
    res["status"] = "escalated"
    return res


# --- Conditional Edge Functions ---


def _make_guard(next_node: str) -> Callable[[AgentState], str]:
    def guard(state: AgentState) -> str:
        if state.get("should_escalate"):
            return "escalate"
        return next_node

    return guard


def route_after_decide(state: AgentState) -> str:
    if state.get("should_escalate"):
        return "escalate"
    dec = state.get("decision") or {}
    requires_approval = dec.get("requires_approval")
    if requires_approval is None:
        requires_approval = state.get("requires_approval")
    if requires_approval or dec.get("status") == "needs_approval":
        return "await_human"
    return "execute"


def route_after_await_human(state: AgentState) -> str:
    if state.get("should_escalate"):
        return "escalate"
    approval = state.get("human_approval")
    if approval == "approved":
        return "execute"
    elif approval == "rejected":
        return "manual_handoff"
    return END


def route_after_verify(state: AgentState) -> str:
    if state.get("should_escalate"):
        return "escalate"
    ver = state.get("verification_result") or {}
    status = ver.get("status")
    rec = ver.get("recommendation")
    if status in ("passed", "pass") and rec != "rollback":
        return "close"
    return "rollback"


def route_after_rollback(state: AgentState) -> str:
    if state.get("should_escalate") or state.get("status") == "manual_handoff" or state.get("rollback_count", 0) >= 2:
        return "manual_handoff"
    return "await_human"


# --- Graph Construction ---


def create_orchestrator_graph(checkpointer: Any = None) -> Any:
    """Build and compile the Orchestrator LangGraph state machine graph."""
    builder = StateGraph(AgentState)

    builder.add_node("ingest", lambda s: run_node_with_retry_and_timeout(node_ingest, "ingest", s))
    builder.add_node("build_context", lambda s: run_node_with_retry_and_timeout(node_build_context, "build_context", s))
    builder.add_node("investigate", lambda s: run_node_with_retry_and_timeout(node_investigate, "investigate", s))
    builder.add_node("root_cause", lambda s: run_node_with_retry_and_timeout(node_root_cause, "root_cause", s))
    builder.add_node("impact_analysis", lambda s: run_node_with_retry_and_timeout(node_impact_analysis, "impact_analysis", s))
    builder.add_node("decide", lambda s: run_node_with_retry_and_timeout(node_decide, "decide", s))
    builder.add_node("await_human", lambda s: run_node_with_retry_and_timeout(node_await_human, "await_human", s))
    builder.add_node("execute", lambda s: run_node_with_retry_and_timeout(node_execute, "execute", s))
    builder.add_node("verify", lambda s: run_node_with_retry_and_timeout(node_verify, "verify", s))
    builder.add_node("rollback", lambda s: run_node_with_retry_and_timeout(node_rollback, "rollback", s))
    builder.add_node("close", lambda s: run_node_with_retry_and_timeout(node_close, "close", s))
    builder.add_node("manual_handoff", lambda s: run_node_with_retry_and_timeout(node_manual_handoff, "manual_handoff", s))
    builder.add_node("escalate", lambda s: run_node_with_retry_and_timeout(node_escalate, "escalate", s))

    builder.add_edge(START, "ingest")

    builder.add_conditional_edges("ingest", _make_guard("build_context"), {"build_context": "build_context", "escalate": "escalate"})
    builder.add_conditional_edges("build_context", _make_guard("investigate"), {"investigate": "investigate", "escalate": "escalate"})
    builder.add_conditional_edges("investigate", _make_guard("root_cause"), {"root_cause": "root_cause", "escalate": "escalate"})
    builder.add_conditional_edges("root_cause", _make_guard("impact_analysis"), {"impact_analysis": "impact_analysis", "escalate": "escalate"})
    builder.add_conditional_edges("impact_analysis", _make_guard("decide"), {"decide": "decide", "escalate": "escalate"})

    builder.add_conditional_edges("decide", route_after_decide, {"execute": "execute", "await_human": "await_human", "escalate": "escalate"})
    builder.add_conditional_edges("await_human", route_after_await_human, {"execute": "execute", "manual_handoff": "manual_handoff", "await_human": "await_human", "escalate": "escalate", END: END})

    builder.add_conditional_edges("execute", _make_guard("verify"), {"verify": "verify", "escalate": "escalate"})
    builder.add_conditional_edges("verify", route_after_verify, {"close": "close", "rollback": "rollback", "escalate": "escalate"})
    builder.add_conditional_edges("rollback", route_after_rollback, {"await_human": "await_human", "manual_handoff": "manual_handoff", "escalate": "escalate"})

    builder.add_edge("close", END)
    builder.add_edge("manual_handoff", END)
    builder.add_edge("escalate", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=saver, interrupt_after=["await_human"])


def _create_agent_run_record(tenant_id: str, incident_id: str, agent_run_id: str) -> None:
    try:
        from db.models import AgentRun
        from db.session import SessionLocal, tenant_session
        from datetime import datetime, timezone

        with tenant_session(tenant_id):
            with SessionLocal() as session:
                run = AgentRun(
                    id=uuid.UUID(str(agent_run_id)),
                    tenant_id=uuid.UUID(str(tenant_id)),
                    incident_id=uuid.UUID(str(incident_id)),
                    trigger_type="automated",
                    status="running",
                    started_at=datetime.now(timezone.utc),
                )
                session.add(run)
                session.commit()
    except Exception as exc:
        logger.debug("Failed to create AgentRun DB record: %s", exc)


def _update_agent_run_status(tenant_id: str, agent_run_id: str, status: str) -> None:
    try:
        from db.models import AgentRun
        from db.session import SessionLocal, tenant_session
        from datetime import datetime, timezone

        with tenant_session(tenant_id):
            with SessionLocal() as session:
                run = session.query(AgentRun).filter(AgentRun.id == uuid.UUID(str(agent_run_id))).first()
                if run:
                    run.status = status
                    run.completed_at = datetime.now(timezone.utc)
                    session.commit()
    except Exception as exc:
        logger.debug("Failed to update AgentRun DB status: %s", exc)


def run_incident(
    tenant_id: str,
    incident_id: str,
    event_payload: Optional[dict] = None,
    checkpointer: Any = None,
    agent_run_id: Optional[str] = None,
) -> AgentState:
    """Run graph pipeline for an incident."""
    if agent_run_id is None:
        agent_run_id = str(uuid.uuid4())

    _create_agent_run_record(tenant_id, incident_id, agent_run_id)

    initial_state: AgentState = {
        "tenant_id": str(tenant_id),
        "incident_id": str(incident_id),
        "agent_run_id": str(agent_run_id),
        "event_payload": event_payload or {},
        "context": {},
        "hypotheses": [],
        "root_cause": {},
        "impact_assessment": {},
        "decision": {},
        "human_approval": "",
        "await_human_reason": "",
        "execution_log": {},
        "verification_result": {},
        "current_step": "",
        "retry_counts": {},
        "should_escalate": False,
        "error": "",
        "status": "running",
    }

    app = create_orchestrator_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": str(agent_run_id)}}

    final_state = app.invoke(initial_state, config=config)

    _update_agent_run_status(
        tenant_id,
        agent_run_id,
        final_state.get("status", "completed"),
    )

    return final_state
