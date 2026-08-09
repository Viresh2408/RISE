"""Provider adapters — thin httpx wrappers, one per LLM provider.

Every adapter implements the ``ProviderAdapter`` Protocol::

    async def complete(self, prompt: str) -> RawLLMResponse

On any network, timeout, or HTTP error the adapter raises ``ProviderError``
(with ``timeout=True`` when the failure is specifically a timeout).  The gateway
catches only ``ProviderError``; all other exceptions (programming errors, etc.)
propagate naturally.

No vendor SDKs are used intentionally — plain httpx keeps the adapters trivially
mockable in tests and avoids pinning to provider SDK release cycles.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel

from llm_gateway.config import ProviderConfig
from llm_gateway.exceptions import ProviderError


class RawLLMResponse(BaseModel):
    """Carrier for a raw provider response before schema validation."""

    content: str          # The raw text content (expected to be JSON for structured calls)
    input_tokens: int
    output_tokens: int


@runtime_checkable
class ProviderAdapter(Protocol):
    """Structural protocol all adapters satisfy."""

    async def complete(self, prompt: str) -> RawLLMResponse:
        """Send *prompt* and return the raw text response + token counts."""
        ...


# ---------------------------------------------------------------------------
# Gemini adapter
# ---------------------------------------------------------------------------

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

_GEMINI_SYSTEM_INSTRUCTION = (
    "You are a structured-output assistant. "
    "Always respond with valid JSON matching the requested schema. "
    "Do not include markdown code fences or any text outside the JSON object."
)


class GeminiAdapter:
    """Calls the Gemini generateContent REST endpoint."""

    def __init__(self, cfg: ProviderConfig) -> None:
        if not cfg.api_key:
            raise ValueError("GeminiAdapter requires api_key")
        self._cfg = cfg
        self._url = (
            f"{cfg.base_url or _GEMINI_BASE}/models/{cfg.model}:generateContent"
            f"?key={cfg.api_key}"
        )

    async def complete(self, prompt: str) -> RawLLMResponse:
        body: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": _GEMINI_SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        try:
            async with httpx.AsyncClient(timeout=self._cfg.timeout_seconds) as client:
                resp = await client.post(self._url, json=body)
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError(self._cfg.name, exc, timeout=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self._cfg.name, exc) from exc

        data = resp.json()
        try:
            candidate = data["candidates"][0]
            content = candidate["content"]["parts"][0]["text"]
            usage = data.get("usageMetadata", {})
            input_tokens = int(usage.get("promptTokenCount", 0))
            output_tokens = int(usage.get("candidatesTokenCount", 0))
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                self._cfg.name,
                ValueError(f"Unexpected Gemini response shape: {data}"),
            ) from exc

        return RawLLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


# ---------------------------------------------------------------------------
# OpenAI adapter
# ---------------------------------------------------------------------------

_OPENAI_BASE = "https://api.openai.com/v1"

_OPENAI_SYSTEM_MSG = (
    "You are a structured-output assistant. "
    "Always respond with valid JSON matching the requested schema. "
    "Do not include markdown code fences or any text outside the JSON object."
)


class OpenAIAdapter:
    """Calls the OpenAI chat completions endpoint."""

    def __init__(self, cfg: ProviderConfig) -> None:
        if not cfg.api_key:
            raise ValueError("OpenAIAdapter requires api_key")
        self._cfg = cfg
        self._base = cfg.base_url or _OPENAI_BASE

    async def complete(self, prompt: str) -> RawLLMResponse:
        body: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": _OPENAI_SYSTEM_MSG},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._cfg.timeout_seconds) as client:
                resp = await client.post(
                    f"{self._base}/chat/completions",
                    json=body,
                    headers=headers,
                )
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError(self._cfg.name, exc, timeout=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self._cfg.name, exc) from exc

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                self._cfg.name,
                ValueError(f"Unexpected OpenAI response shape: {data}"),
            ) from exc

        return RawLLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


# ---------------------------------------------------------------------------
# Ollama adapter
# ---------------------------------------------------------------------------

_OLLAMA_DEFAULT_BASE = "http://localhost:11434"

_OLLAMA_SYSTEM_MSG = (
    "You are a structured-output assistant. "
    "Always respond with valid JSON matching the requested schema. "
    "Do not include markdown code fences or any text outside the JSON object."
)


class OllamaAdapter:
    """Calls a locally-running Ollama instance via its REST chat endpoint."""

    def __init__(self, cfg: ProviderConfig) -> None:
        self._cfg = cfg
        self._base = cfg.base_url or _OLLAMA_DEFAULT_BASE

    async def complete(self, prompt: str) -> RawLLMResponse:
        body: dict[str, Any] = {
            "model": self._cfg.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": _OLLAMA_SYSTEM_MSG},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self._cfg.timeout_seconds) as client:
                resp = await client.post(f"{self._base}/api/chat", json=body)
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError(self._cfg.name, exc, timeout=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self._cfg.name, exc) from exc

        data = resp.json()
        try:
            content = data["message"]["content"]
            # Ollama counts tokens under prompt_eval_count / eval_count.
            input_tokens = int(data.get("prompt_eval_count", 0))
            output_tokens = int(data.get("eval_count", 0))
        except (KeyError, TypeError) as exc:
            raise ProviderError(
                self._cfg.name,
                ValueError(f"Unexpected Ollama response shape: {data}"),
            ) from exc

        return RawLLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


# ---------------------------------------------------------------------------
# Groq adapter  (OpenAI-compatible)
# ---------------------------------------------------------------------------

_GROQ_BASE = "https://api.groq.com/openai/v1"

_GROQ_SYSTEM_MSG = (
    "You are a structured-output assistant. "
    "Always respond with valid JSON matching the requested schema. "
    "Do not include markdown code fences or any text outside the JSON object."
)


class GroqAdapter:
    """Calls Groq Cloud via its OpenAI-compatible chat completions endpoint."""

    def __init__(self, cfg: ProviderConfig) -> None:
        if not cfg.api_key:
            raise ValueError("GroqAdapter requires api_key")
        self._cfg = cfg
        self._base = cfg.base_url or _GROQ_BASE

    async def complete(self, prompt: str) -> RawLLMResponse:
        body: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": _GROQ_SYSTEM_MSG},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._cfg.timeout_seconds) as client:
                resp = await client.post(
                    f"{self._base}/chat/completions",
                    json=body,
                    headers=headers,
                )
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError(self._cfg.name, exc, timeout=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self._cfg.name, exc) from exc

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                self._cfg.name,
                ValueError(f"Unexpected Groq response shape: {data}"),
            ) from exc

        return RawLLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def make_adapter(cfg: ProviderConfig) -> ProviderAdapter:
    """Return the correct adapter instance for the given provider config."""
    if cfg.name == "groq":
        return GroqAdapter(cfg)
    if cfg.name == "gemini":
        return GeminiAdapter(cfg)
    if cfg.name == "openai":
        return OpenAIAdapter(cfg)
    if cfg.name == "ollama":
        return OllamaAdapter(cfg)
    raise ValueError(f"Unknown provider: {cfg.name!r}")  # pragma: no cover
