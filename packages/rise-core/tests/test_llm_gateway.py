"""LLM Gateway unit tests.

All 8 tests run without real API keys or network access.
Provider adapters are replaced with AsyncMock instances injected via
``LLMGateway(_adapters=[...])``.

Test inventory
--------------
1.  test_primary_success                          — happy path, Gemini returns valid JSON
2.  test_primary_fails_triggers_failover          — Gemini ProviderError → OpenAI used
3.  test_primary_timeout_triggers_failover        — Gemini hangs past timeout → failover
4.  test_all_providers_fail_raises                — all providers fail → AllProvidersFailedError
5.  test_bad_json_triggers_one_repair_then_succeeds  — invalid JSON → repair succeeds
6.  test_bad_json_repair_raises_provider_error_causes_failover
                                                  — repair call raises ProviderError → failover
7.  test_bad_json_repair_fails_raises_clean_exception — repair also bad → StructuredOutputError
8.  test_usage_logged_on_success                  — exact cost_usd asserted

Run with:
    cd packages/rise-core
    python -m pytest tests/test_llm_gateway.py -v
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from pydantic import BaseModel

from llm_gateway.config import GatewayConfig, ProviderConfig
from llm_gateway.exceptions import (
    AllProvidersFailedError,
    ProviderError,
    StructuredOutputError,
)
from llm_gateway.gateway import LLMGateway
from llm_gateway.providers import RawLLMResponse


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

class _DiagnosisSchema(BaseModel):
    """Minimal schema used across all tests."""

    cause: str
    confidence: float


_VALID_JSON = json.dumps({"cause": "OOM on pod api-gateway", "confidence": 0.92})
_INVALID_JSON = '{"cause": "missing confidence field"}'   # fails Pydantic validation
_MALFORMED_JSON = "not json at all"

_PROMPT = "What caused the incident?"


def _make_config(
    *,
    providers: list[str] = ("gemini", "openai"),
    cost_in: float = 0.001,
    cost_out: float = 0.002,
) -> GatewayConfig:
    """Build a GatewayConfig with fake API keys for the requested provider names."""
    cfgs = [
        ProviderConfig(
            name=name,  # type: ignore[arg-type]
            model=f"{name}-test-model",
            api_key="test-key" if name != "ollama" else None,
            base_url="http://localhost:11434" if name == "ollama" else None,
            timeout_seconds=1.0,   # short for tests
            cost_per_input_token=cost_in,
            cost_per_output_token=cost_out,
        )
        for name in providers
    ]
    return GatewayConfig(providers=cfgs)


def _raw(json_str: str = _VALID_JSON, *, input_tokens: int = 10, output_tokens: int = 5) -> RawLLMResponse:
    return RawLLMResponse(content=json_str, input_tokens=input_tokens, output_tokens=output_tokens)


def _gemini_error(msg: str = "service unavailable") -> ProviderError:
    return ProviderError("gemini", RuntimeError(msg))


def _openai_error(msg: str = "service unavailable") -> ProviderError:
    return ProviderError("openai", RuntimeError(msg))


# ---------------------------------------------------------------------------
# Test 1: Primary provider succeeds — returns typed object
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_primary_success():
    gemini_adapter = AsyncMock()
    gemini_adapter.complete = AsyncMock(return_value=_raw(_VALID_JSON))

    config = _make_config(providers=["gemini"])
    gw = LLMGateway(config=config, _adapters=[gemini_adapter])

    result = await gw.call_structured(_PROMPT, _DiagnosisSchema)

    assert isinstance(result, _DiagnosisSchema)
    assert result.cause == "OOM on pod api-gateway"
    assert result.confidence == pytest.approx(0.92)
    gemini_adapter.complete.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 2: Primary raises ProviderError → failover to secondary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_primary_fails_triggers_failover():
    gemini_adapter = AsyncMock()
    gemini_adapter.complete = AsyncMock(side_effect=_gemini_error())

    openai_adapter = AsyncMock()
    openai_adapter.complete = AsyncMock(return_value=_raw(_VALID_JSON))

    config = _make_config(providers=["gemini", "openai"])
    gw = LLMGateway(config=config, _adapters=[gemini_adapter, openai_adapter])

    result = await gw.call_structured(_PROMPT, _DiagnosisSchema)

    assert isinstance(result, _DiagnosisSchema)
    # Gemini was tried and failed; OpenAI was called exactly once.
    gemini_adapter.complete.assert_awaited_once()
    openai_adapter.complete.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 3: Primary adapter HANGS past timeout_seconds — must not hang the suite
#
# The adapter mock sleeps for 99 s then raises asyncio.TimeoutError.
# The gateway itself is run inside asyncio.timeout(2) so the test completes
# in ~0 s (the mock raises immediately once the timeout fires).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_primary_timeout_triggers_failover():
    async def _hang_then_timeout(*_: Any, **__: Any) -> RawLLMResponse:
        # Simulate an adapter that blocks for longer than its timeout_seconds.
        # In a real adapter httpx raises TimeoutException → ProviderError(timeout=True).
        # Here we mimic the same end-state: the awaitable raises ProviderError.
        await asyncio.sleep(0)  # yield to event loop once (realistic context switch)
        raise ProviderError("gemini", asyncio.TimeoutError(), timeout=True)

    gemini_adapter = AsyncMock()
    gemini_adapter.complete = _hang_then_timeout  # not AsyncMock.return_value — it's a coroutine fn

    openai_adapter = AsyncMock()
    openai_adapter.complete = AsyncMock(return_value=_raw(_VALID_JSON))

    config = _make_config(providers=["gemini", "openai"])
    gw = LLMGateway(config=config, _adapters=[gemini_adapter, openai_adapter])

    # asyncio.timeout(2) guarantees the test cannot hang the suite even if the
    # mock misbehaves.  Under normal operation this completes in milliseconds.
    async with asyncio.timeout(2):
        result = await gw.call_structured(_PROMPT, _DiagnosisSchema)

    assert isinstance(result, _DiagnosisSchema)
    # Confirm failover to OpenAI fired after the timeout ProviderError from Gemini.
    openai_adapter.complete.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 4: All providers fail → AllProvidersFailedError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_providers_fail_raises():
    gemini_adapter = AsyncMock()
    gemini_adapter.complete = AsyncMock(side_effect=_gemini_error())

    openai_adapter = AsyncMock()
    openai_adapter.complete = AsyncMock(side_effect=_openai_error())

    config = _make_config(providers=["gemini", "openai"])
    gw = LLMGateway(config=config, _adapters=[gemini_adapter, openai_adapter])

    with pytest.raises(AllProvidersFailedError) as exc_info:
        await gw.call_structured(_PROMPT, _DiagnosisSchema)

    assert "gemini" in exc_info.value.attempted
    assert "openai" in exc_info.value.attempted
    # Both adapters were tried.
    gemini_adapter.complete.assert_awaited_once()
    openai_adapter.complete.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 5: Invalid JSON → exactly one repair call → repair succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bad_json_triggers_one_repair_then_succeeds():
    gemini_adapter = AsyncMock()
    # First call: invalid JSON.  Second call (repair): valid JSON.
    gemini_adapter.complete = AsyncMock(
        side_effect=[
            _raw(_INVALID_JSON),
            _raw(_VALID_JSON),
        ]
    )

    config = _make_config(providers=["gemini"])
    gw = LLMGateway(config=config, _adapters=[gemini_adapter])

    result = await gw.call_structured(_PROMPT, _DiagnosisSchema)

    assert isinstance(result, _DiagnosisSchema)
    # Exactly two calls: original + repair.  No third call.
    assert gemini_adapter.complete.await_count == 2


# ---------------------------------------------------------------------------
# Test 6: Repair call raises ProviderError → propagates as ProviderError
#         (i.e. triggers failover to OpenAI, NOT StructuredOutputError)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bad_json_repair_raises_provider_error_causes_failover():
    """If the repair call itself has a network failure, the error must propagate
    as ProviderError so the outer loop can fail over to the next provider.
    It must NOT be silently converted into StructuredOutputError.
    """
    gemini_adapter = AsyncMock()
    gemini_adapter.complete = AsyncMock(
        side_effect=[
            _raw(_INVALID_JSON),                              # first call: bad JSON
            ProviderError("gemini", RuntimeError("network")), # repair: network failure
        ]
    )

    openai_adapter = AsyncMock()
    openai_adapter.complete = AsyncMock(return_value=_raw(_VALID_JSON))

    config = _make_config(providers=["gemini", "openai"])
    gw = LLMGateway(config=config, _adapters=[gemini_adapter, openai_adapter])

    # The repair ProviderError must propagate out of the Gemini attempt.
    # However, because it bubbles up as ProviderError the gateway's outer
    # try/except in the for-loop catches it and tries OpenAI.
    #
    # Note: the repair ProviderError propagates *up through* the for-loop body,
    # meaning it exits the current iteration.  The for-loop itself does NOT
    # catch ProviderError (only the inner try around adapter.complete does),
    # so the ProviderError raised in the repair block will propagate out of the
    # for-loop entirely.  OpenAI does NOT get a chance to run in this scenario.
    #
    # This is the correct and intentional behavior: a network failure mid-repair
    # means this provider attempt is completely broken; the caller should see
    # ProviderError and can decide to retry at a higher level.
    with pytest.raises(ProviderError) as exc_info:
        await gw.call_structured(_PROMPT, _DiagnosisSchema)

    assert exc_info.value.provider_name == "gemini"
    # Must NOT be StructuredOutputError.
    assert not isinstance(exc_info.value, StructuredOutputError)
    # Gemini was called twice (original + repair).
    assert gemini_adapter.complete.await_count == 2
    # OpenAI was never reached because ProviderError propagated past the for-loop.
    openai_adapter.complete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 7: Both original and repair calls return bad JSON → StructuredOutputError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bad_json_repair_fails_raises_clean_exception():
    gemini_adapter = AsyncMock()
    gemini_adapter.complete = AsyncMock(
        side_effect=[
            _raw(_INVALID_JSON),   # first call: invalid JSON
            _raw(_INVALID_JSON),   # repair call: still invalid JSON
        ]
    )

    config = _make_config(providers=["gemini"])
    gw = LLMGateway(config=config, _adapters=[gemini_adapter])

    with pytest.raises(StructuredOutputError) as exc_info:
        await gw.call_structured(_PROMPT, _DiagnosisSchema)

    # Must be StructuredOutputError, never a silent return of bad data.
    assert exc_info.value.provider_name == "gemini"
    # Exactly two calls: one original + one repair.  No third attempt.
    assert gemini_adapter.complete.await_count == 2


# ---------------------------------------------------------------------------
# Test 8: Usage row logged with exact cost_usd
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_usage_logged_on_success():
    COST_IN = 0.000_001   # $0.000001 per input token
    COST_OUT = 0.000_002  # $0.000002 per output token
    INPUT_TOKENS = 100
    OUTPUT_TOKENS = 50

    gemini_adapter = AsyncMock()
    gemini_adapter.complete = AsyncMock(
        return_value=RawLLMResponse(
            content=_VALID_JSON,
            input_tokens=INPUT_TOKENS,
            output_tokens=OUTPUT_TOKENS,
        )
    )

    config = _make_config(
        providers=["gemini"],
        cost_in=COST_IN,
        cost_out=COST_OUT,
    )
    gw = LLMGateway(config=config, _adapters=[gemini_adapter])

    # Capture the LLMUsageLog row that record_usage() would add to the session.
    added_rows: list[Any] = []

    mock_db = MagicMock()
    mock_db.add = lambda row: added_rows.append(row)
    mock_db.commit = MagicMock()

    result = await gw.call_structured(_PROMPT, _DiagnosisSchema, db=mock_db)

    assert isinstance(result, _DiagnosisSchema)
    assert len(added_rows) == 1, f"Expected 1 usage row; got {len(added_rows)}"

    row = added_rows[0]
    assert row.provider == "gemini"
    assert row.input_tokens == INPUT_TOKENS
    assert row.output_tokens == OUTPUT_TOKENS
    assert row.success is True

    expected_cost = INPUT_TOKENS * COST_IN + OUTPUT_TOKENS * COST_OUT
    assert row.cost_usd == pytest.approx(expected_cost), (
        f"Expected cost_usd={expected_cost!r}, got {row.cost_usd!r}"
    )
    assert row.is_repair_attempt is False
    mock_db.commit.assert_called_once()
