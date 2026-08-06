"""Core LLM Gateway orchestrator.

Entry points
------------
Module-level convenience (reads config from env)::

    from llm_gateway import call_structured
    result = await call_structured(prompt, MySchema, db=session)

Class-level (explicit config, useful in tests)::

    from llm_gateway.gateway import LLMGateway
    from llm_gateway.config import GatewayConfig, ProviderConfig

    gw = LLMGateway(config=GatewayConfig(providers=[...]))
    result = await gw.call_structured(prompt, MySchema)

Repair semantics (spec: "exactly 1 repair retry then escalate")
---------------------------------------------------------------
If a provider returns a non-empty string that fails Pydantic validation, the
gateway issues exactly one repair call to the SAME provider with the bad JSON
and the target schema embedded in a repair prompt.

_MAX_REPAIR_ATTEMPTS = 1 is a module constant, NOT a config field.  Making it
configurable would risk silent misconfiguration (0 → pass bad data, >1 → unbounded
retries), which violates the spec.

Failover semantics
------------------
- ProviderError on the PRIMARY call  → skip to the next provider.
- ProviderError on the REPAIR call   → re-raise as ProviderError (NOT
  StructuredOutputError), which propagates out and causes failover to the next
  provider at the outer loop.
- ValidationError on the REPAIR call → raise StructuredOutputError (repair
  exhausted; no further retry or failover for this provider).
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel, ValidationError

from llm_gateway.config import GatewayConfig, ProviderConfig
from llm_gateway.exceptions import (
    AllProvidersFailedError,
    ProviderError,
    StructuredOutputError,
)
from llm_gateway.providers import ProviderAdapter, RawLLMResponse, make_adapter
from llm_gateway.usage import record_usage

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

T = TypeVar("T", bound=BaseModel)

# Enforces the spec: "exactly 1 repair retry".  NOT configurable — see module docstring.
_MAX_REPAIR_ATTEMPTS: int = 1

_REPAIR_PROMPT_TEMPLATE = """\
The following JSON output did not conform to the required schema.
Please correct it and return ONLY the valid JSON object, with no markdown or extra text.

--- SCHEMA (JSON Schema) ---
{schema}

--- BAD OUTPUT ---
{bad_json}

--- CORRECTED OUTPUT ---"""


def _parse_and_validate(content: str, schema: type[T]) -> T:
    """Attempt JSON decode then Pydantic validation.  Raises ValidationError on failure."""
    data = json.loads(content)  # raises json.JSONDecodeError (subclass of ValueError)
    return schema.model_validate(data)


class LLMGateway:
    """Provider-agnostic LLM client with automatic failover, repair, and usage logging."""

    def __init__(
        self,
        config: GatewayConfig,
        *,
        # Inject adapters for testing without touching the HTTP layer.
        _adapters: list[ProviderAdapter] | None = None,
    ) -> None:
        self._config = config
        if _adapters is not None:
            self._adapters: list[tuple[ProviderConfig, ProviderAdapter]] = list(
                zip(config.providers, _adapters)
            )
        else:
            self._adapters = [
                (pcfg, make_adapter(pcfg)) for pcfg in config.providers
            ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def call_structured(
        self,
        prompt: str,
        output_schema: type[T],
        db: "Session | None" = None,
    ) -> T:
        """Call the LLM chain and return a validated *output_schema* instance.

        Raises
        ------
        StructuredOutputError
            The provider responded but validation failed after the repair attempt.
        AllProvidersFailedError
            Every provider in the chain raised ProviderError.
        """
        schema_json = json.dumps(output_schema.model_json_schema(), indent=2)
        attempted_providers: list[str] = []

        for pcfg, adapter in self._adapters:
            attempted_providers.append(pcfg.name)

            # ── Primary attempt ────────────────────────────────────────────
            t0 = time.monotonic()
            try:
                raw = await adapter.complete(prompt)
            except ProviderError as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                record_usage(
                    db,
                    provider=pcfg.name,
                    model=pcfg.model,
                    prompt=prompt,
                    input_tokens=0,
                    output_tokens=0,
                    cost_per_input_token=pcfg.cost_per_input_token,
                    cost_per_output_token=pcfg.cost_per_output_token,
                    latency_ms=latency_ms,
                    success=False,
                    error_type="provider_error",
                )
                # Try next provider.
                continue

            latency_ms = int((time.monotonic() - t0) * 1000)

            try:
                obj = _parse_and_validate(raw.content, output_schema)
            except (ValidationError, ValueError, KeyError):
                # Validation failed — attempt exactly one repair on the SAME provider.
                record_usage(
                    db,
                    provider=pcfg.name,
                    model=pcfg.model,
                    prompt=prompt,
                    input_tokens=raw.input_tokens,
                    output_tokens=raw.output_tokens,
                    cost_per_input_token=pcfg.cost_per_input_token,
                    cost_per_output_token=pcfg.cost_per_output_token,
                    latency_ms=latency_ms,
                    success=False,
                    error_type="validation_error",
                )

                repair_prompt = _REPAIR_PROMPT_TEMPLATE.format(
                    schema=schema_json,
                    bad_json=raw.content,
                )
                t1 = time.monotonic()

                # ── Repair attempt ─────────────────────────────────────────
                # NOTE: ProviderError from the repair call is intentionally NOT
                # caught here — it propagates up to the outer except clause of
                # the for-loop, which will re-raise it so the caller can
                # distinguish it from StructuredOutputError.  This also means
                # a repair ProviderError triggers failover to the next provider.
                try:
                    repair_raw = await adapter.complete(repair_prompt)
                except ProviderError:
                    # Re-raise: repair call had a network/timeout failure.
                    # This propagates out of the for-loop body so the caller
                    # sees ProviderError, not StructuredOutputError.
                    raise

                repair_latency_ms = int((time.monotonic() - t1) * 1000)

                try:
                    obj = _parse_and_validate(repair_raw.content, output_schema)
                except (ValidationError, ValueError, KeyError):
                    record_usage(
                        db,
                        provider=pcfg.name,
                        model=pcfg.model,
                        prompt=repair_prompt,
                        input_tokens=repair_raw.input_tokens,
                        output_tokens=repair_raw.output_tokens,
                        cost_per_input_token=pcfg.cost_per_input_token,
                        cost_per_output_token=pcfg.cost_per_output_token,
                        latency_ms=repair_latency_ms,
                        success=False,
                        error_type="repair_failed",
                        is_repair_attempt=True,
                    )
                    raise StructuredOutputError(pcfg.name, raw.content)

                # Repair succeeded.
                record_usage(
                    db,
                    provider=pcfg.name,
                    model=pcfg.model,
                    prompt=repair_prompt,
                    input_tokens=repair_raw.input_tokens,
                    output_tokens=repair_raw.output_tokens,
                    cost_per_input_token=pcfg.cost_per_input_token,
                    cost_per_output_token=pcfg.cost_per_output_token,
                    latency_ms=repair_latency_ms,
                    success=True,
                    is_repair_attempt=True,
                )
                return obj

            # Primary succeeded.
            record_usage(
                db,
                provider=pcfg.name,
                model=pcfg.model,
                prompt=prompt,
                input_tokens=raw.input_tokens,
                output_tokens=raw.output_tokens,
                cost_per_input_token=pcfg.cost_per_input_token,
                cost_per_output_token=pcfg.cost_per_output_token,
                latency_ms=latency_ms,
                success=True,
            )
            return obj

        raise AllProvidersFailedError(attempted=attempted_providers)


# ---------------------------------------------------------------------------
# Module-level convenience — reads config from environment
# ---------------------------------------------------------------------------

async def call_structured(
    prompt: str,
    output_schema: type[T],
    db: "Session | None" = None,
) -> T:
    """Call the gateway with config loaded from environment variables.

    See ``GatewayConfig.from_env()`` for the supported env var names.
    """
    config = GatewayConfig.from_env()
    gw = LLMGateway(config=config)
    return await gw.call_structured(prompt, output_schema, db=db)
