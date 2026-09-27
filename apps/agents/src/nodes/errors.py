"""Shared error types for RISE agent nodes.

`AgentLLMError` marks an LLM/infra failure inside an agent node. It exists so
callers that must NOT mask an infra failure as a diagnostic answer (the RCA
benchmark, integration eval harnesses) can opt into fail-loud behaviour, while
the production orchestrator keeps its graceful-degradation fallback by default.
See ADR-005 and eval/rca_judge.py: an infra failure recorded as a diagnostic
FAIL corrupts the accuracy metric, so the eval path re-raises this instead.
"""

from __future__ import annotations


class AgentLLMError(RuntimeError):
    """Raised when an agent's LLM Gateway call fails and the caller opted in to
    fail-loud (``raise_on_llm_failure=True``) instead of the canned fallback."""
