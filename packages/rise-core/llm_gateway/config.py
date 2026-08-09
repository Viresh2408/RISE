"""LLM Gateway configuration.

Supports two loading modes:

1. Explicit construction::

    cfg = GatewayConfig(providers=[
        ProviderConfig(name="gemini", model="gemini-2.0-flash", api_key="..."),
        ProviderConfig(name="openai",  model="gpt-4o",           api_key="..."),
    ])

2. From environment via ``GatewayConfig.from_env()``::

    LLM_GATEWAY_CONFIG_JSON='[{"name":"gemini","model":"gemini-2.0-flash","api_key":"..."}]'

   Or individual vars (fallback when the JSON blob is absent)::

    GEMINI_API_KEY=...
    OPENAI_API_KEY=...
    OLLAMA_BASE_URL=http://localhost:11434   # enables Ollama as third provider

Design note: ``max_repair_attempts`` is intentionally NOT a config field.
The spec mandates *exactly 1 repair retry* and that is enforced via a module
constant in gateway.py.  Making it configurable would risk accidental
misconfiguration (e.g. 0 = silently pass bad data, >1 = unbounded retries).
"""

from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Config for a single provider in the failover chain."""

    name: Literal["groq", "gemini", "openai", "ollama"]
    model: str
    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 30.0
    # USD per token — set to 0.0 if pricing is unknown; used only for logging.
    cost_per_input_token: float = Field(default=0.0, ge=0.0)
    cost_per_output_token: float = Field(default=0.0, ge=0.0)


# Sensible public model defaults used when building config from individual env vars.
_DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"   # fast, free-tier Groq default
_DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
_DEFAULT_OPENAI_MODEL = "gpt-4o"
_DEFAULT_OLLAMA_MODEL = "llama3"

# Approximate public pricing (USD / token) as of mid-2025; update as needed.
# These are used only for the usage log estimate.
_GROQ_INPUT_COST = 0.000_000_059    # $0.059 / 1M input tokens (llama-3.3-70b)
_GROQ_OUTPUT_COST = 0.000_000_079   # $0.079 / 1M output tokens
_GEMINI_FLASH_INPUT_COST = 0.000_000_075   # $0.075 / 1M input tokens
_GEMINI_FLASH_OUTPUT_COST = 0.000_000_300  # $0.300 / 1M output tokens
_GPT4O_INPUT_COST = 0.000_002_500          # $2.500 / 1M input tokens
_GPT4O_OUTPUT_COST = 0.000_010_000         # $10.00 / 1M output tokens


class GatewayConfig(BaseModel):
    """Ordered list of providers; first = primary, rest = fallbacks."""

    providers: list[ProviderConfig] = Field(min_length=1)

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        """Build config from environment variables.

        Priority:
        1. ``LLM_GATEWAY_CONFIG_JSON`` — full JSON array of ProviderConfig dicts.
        2. Individual ``GEMINI_API_KEY``, ``OPENAI_API_KEY``, ``OLLAMA_BASE_URL`` vars
           (Ollama only included if OLLAMA_BASE_URL is set).
        """
        json_blob = os.environ.get("LLM_GATEWAY_CONFIG_JSON", "").strip()
        if json_blob:
            raw = json.loads(json_blob)
            providers = [ProviderConfig(**p) for p in raw]
            return cls(providers=providers)

        providers: list[ProviderConfig] = []

        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            providers.append(
                ProviderConfig(
                    name="groq",
                    model=os.environ.get("GROQ_MODEL", _DEFAULT_GROQ_MODEL),
                    api_key=groq_key,
                    timeout_seconds=float(os.environ.get("GROQ_TIMEOUT", "30")),
                    cost_per_input_token=_GROQ_INPUT_COST,
                    cost_per_output_token=_GROQ_OUTPUT_COST,
                )
            )

        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            providers.append(
                ProviderConfig(
                    name="gemini",
                    model=os.environ.get("GEMINI_MODEL", _DEFAULT_GEMINI_MODEL),
                    api_key=gemini_key,
                    timeout_seconds=float(os.environ.get("GEMINI_TIMEOUT", "30")),
                    cost_per_input_token=_GEMINI_FLASH_INPUT_COST,
                    cost_per_output_token=_GEMINI_FLASH_OUTPUT_COST,
                )
            )

        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            providers.append(
                ProviderConfig(
                    name="openai",
                    model=os.environ.get("OPENAI_MODEL", _DEFAULT_OPENAI_MODEL),
                    api_key=openai_key,
                    timeout_seconds=float(os.environ.get("OPENAI_TIMEOUT", "30")),
                    cost_per_input_token=_GPT4O_INPUT_COST,
                    cost_per_output_token=_GPT4O_OUTPUT_COST,
                )
            )

        ollama_url = os.environ.get("OLLAMA_BASE_URL", "")
        if ollama_url:
            providers.append(
                ProviderConfig(
                    name="ollama",
                    model=os.environ.get("OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL),
                    base_url=ollama_url,
                    timeout_seconds=float(os.environ.get("OLLAMA_TIMEOUT", "60")),
                    # Ollama is self-hosted — cost is zero (infra cost tracked separately).
                    cost_per_input_token=0.0,
                    cost_per_output_token=0.0,
                )
            )

        if not providers:
            raise RuntimeError(
                "LLM Gateway: no providers configured. "
                "Set LLM_GATEWAY_CONFIG_JSON or at least GEMINI_API_KEY."
            )

        return cls(providers=providers)
