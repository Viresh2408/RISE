"""Unit tests for Slack History Fetcher (apps/agents/src/nodes/slack_history_fetcher.py)."""

from __future__ import annotations

from unittest.mock import patch
import httpx
import pytest

from apps.agents.src.nodes.slack_history_fetcher import (
    SlackThread,
    _extract_error_pattern,
    search_slack_history,
)


def test_extract_error_pattern() -> None:
    """Sanitises and truncates error patterns."""
    raw = "Redis connection pool <script>alert(1)</script> saturated after spike"
    extracted = _extract_error_pattern(raw)
    assert "<" not in extracted
    assert ">" not in extracted
    assert len(extracted) <= 60


def test_search_slack_history_no_token_returns_empty_not_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When SLACK_API_TOKEN is not set, returns empty list without marking source missing."""
    monkeypatch.delenv("SLACK_API_TOKEN", raising=False)

    threads, is_missing = search_slack_history("auth-service", "503 timeout")
    assert threads == []
    assert is_missing is False


def test_search_slack_history_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SLACK_API_TOKEN is set and API succeeds, returns parsed threads."""
    monkeypatch.setenv("SLACK_API_TOKEN", "xoxb-fake-token")

    def mock_get(url: str, **kwargs: dict) -> httpx.Response:
        req = httpx.Request("GET", url)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "messages": {
                    "matches": [
                        {
                            "ts": "1722800000.000100",
                            "channel": {"name": "incidents"},
                            "permalink": "https://slack.com/archives/C123/p1722800000000100",
                            "text": "We saw auth-service connection timeouts earlier today as well.",
                        }
                    ]
                },
            },
            request=req,
        )

    with patch("httpx.Client.get", side_effect=mock_get):
        threads, is_missing = search_slack_history("auth-service", "connection timeout")
        assert is_missing is False
        assert len(threads) == 1
        assert isinstance(threads[0], SlackThread)
        assert threads[0].channel == "incidents"
        assert "timeouts" in threads[0].snippet


def test_search_slack_history_api_error_marks_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When token is set but API returns error, is_missing is True."""
    monkeypatch.setenv("SLACK_API_TOKEN", "xoxb-fake-token")

    def mock_get(url: str, **kwargs: dict) -> httpx.Response:
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"}, request=req)

    with patch("httpx.Client.get", side_effect=mock_get):
        threads, is_missing = search_slack_history("auth-service", "connection timeout")
        assert threads == []
        assert is_missing is True
