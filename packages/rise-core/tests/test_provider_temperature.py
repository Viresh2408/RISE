"""Provider adapter temperature forwarding tests.

Verifies that ``ProviderConfig.temperature`` is forwarded verbatim into each
provider's request body when set, and omitted entirely when None (so the
provider applies its own default).  A temperature of 0.0 is what the RCA
benchmark sets for maximally deterministic scoring (docs/evaluation-methodology.md
§2), so "0.0 present, None absent" is the exact contract under test.

No network access: httpx.AsyncClient.post is monkeypatched to capture the
outgoing JSON body and return a canned, well-formed provider response.
"""

from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from llm_gateway.config import ProviderConfig
from llm_gateway.providers import (
    GeminiAdapter,
    GroqAdapter,
    OllamaAdapter,
    OpenAIAdapter,
)


class _FakeResp:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


def _patch_post(monkeypatch: pytest.MonkeyPatch, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Capture every POST body; return canned *payload*.  Returns the capture list."""
    captured: List[Dict[str, Any]] = []

    async def _fake_post(self: Any, url: str, json: Any = None, headers: Any = None, **_: Any) -> _FakeResp:
        captured.append(json)
        return _FakeResp(payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    return captured


_GEMINI_PAYLOAD = {
    "candidates": [{"content": {"parts": [{"text": '{"x": 1}'}]}}],
    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
}
_OPENAI_PAYLOAD = {
    "choices": [{"message": {"content": '{"x": 1}'}}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
}
_OLLAMA_PAYLOAD = {
    "message": {"content": '{"x": 1}'},
    "prompt_eval_count": 3,
    "eval_count": 2,
}


# ---------------------------------------------------------------------------
# temperature SET (0.0) -> forwarded into the request body
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_gemini_forwards_temperature(monkeypatch):
    captured = _patch_post(monkeypatch, _GEMINI_PAYLOAD)
    cfg = ProviderConfig(name="gemini", model="gemini-2.0-flash", api_key="k", temperature=0.0)
    await GeminiAdapter(cfg).complete("prompt")
    assert captured[0]["generationConfig"]["temperature"] == 0.0


@pytest.mark.anyio
async def test_openai_forwards_temperature(monkeypatch):
    captured = _patch_post(monkeypatch, _OPENAI_PAYLOAD)
    cfg = ProviderConfig(name="openai", model="gpt-4o", api_key="k", temperature=0.0)
    await OpenAIAdapter(cfg).complete("prompt")
    assert captured[0]["temperature"] == 0.0


@pytest.mark.anyio
async def test_groq_forwards_temperature(monkeypatch):
    captured = _patch_post(monkeypatch, _OPENAI_PAYLOAD)
    cfg = ProviderConfig(name="groq", model="llama-3.3-70b-versatile", api_key="k", temperature=0.0)
    await GroqAdapter(cfg).complete("prompt")
    assert captured[0]["temperature"] == 0.0


@pytest.mark.anyio
async def test_ollama_forwards_temperature(monkeypatch):
    captured = _patch_post(monkeypatch, _OLLAMA_PAYLOAD)
    cfg = ProviderConfig(name="ollama", model="llama3", base_url="http://localhost:11434", temperature=0.0)
    await OllamaAdapter(cfg).complete("prompt")
    assert captured[0]["options"]["temperature"] == 0.0


# ---------------------------------------------------------------------------
# temperature None -> omitted (provider default applies)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_gemini_omits_temperature_when_none(monkeypatch):
    captured = _patch_post(monkeypatch, _GEMINI_PAYLOAD)
    cfg = ProviderConfig(name="gemini", model="gemini-2.0-flash", api_key="k")
    await GeminiAdapter(cfg).complete("prompt")
    assert "temperature" not in captured[0]["generationConfig"]


@pytest.mark.anyio
async def test_openai_omits_temperature_when_none(monkeypatch):
    captured = _patch_post(monkeypatch, _OPENAI_PAYLOAD)
    cfg = ProviderConfig(name="openai", model="gpt-4o", api_key="k")
    await OpenAIAdapter(cfg).complete("prompt")
    assert "temperature" not in captured[0]


@pytest.mark.anyio
async def test_ollama_omits_options_when_none(monkeypatch):
    captured = _patch_post(monkeypatch, _OLLAMA_PAYLOAD)
    cfg = ProviderConfig(name="ollama", model="llama3", base_url="http://localhost:11434")
    await OllamaAdapter(cfg).complete("prompt")
    assert "options" not in captured[0]
