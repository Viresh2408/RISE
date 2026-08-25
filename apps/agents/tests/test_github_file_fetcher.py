"""Unit tests for GitHub File Fetcher (apps/agents/src/nodes/github_file_fetcher.py)."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch
import httpx
import pytest

from apps.agents.src.nodes.github_file_fetcher import (
    GitHubFileContent,
    _extract_file_paths_from_root_cause,
    fetch_files_for_action_plan,
    fetch_github_file_content,
)


def test_fetch_github_file_content_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful file fetch and base64 decode from GitHub API."""
    monkeypatch.setenv("GITHUB_REPO", "Viresh2408/RISE")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    file_content = "def hello():\n    return 'world'\n"
    b64_content = base64.b64encode(file_content.encode()).decode()

    def mock_get(url: str, **kwargs: dict) -> httpx.Response:
        req = httpx.Request("GET", url)
        if "contents" in url:
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "content": b64_content,
                    "encoding": "base64",
                    "sha": "blob_sha_12345",
                },
                request=req,
            )
        elif "commits" in url:
            return httpx.Response(
                200,
                json={"sha": "commit_sha_67890"},
                request=req,
            )
        return httpx.Response(404, request=req)

    with patch("httpx.Client.get", side_effect=mock_get):
        res = fetch_github_file_content("apps/api/src/deps/redis.py")
        assert res is not None
        assert isinstance(res, GitHubFileContent)
        assert res.path == "apps/api/src/deps/redis.py"
        assert res.content == file_content
        assert res.sha == "blob_sha_12345"
        assert res.commit_sha == "commit_sha_67890"
        assert res.line_count == 3


def test_fetch_github_file_content_404_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 Not Found returns None as a hard gate."""
    monkeypatch.setenv("GITHUB_REPO", "Viresh2408/RISE")

    def mock_get(url: str, **kwargs: dict) -> httpx.Response:
        req = httpx.Request("GET", url)
        return httpx.Response(404, request=req)

    with patch("httpx.Client.get", side_effect=mock_get):
        res = fetch_github_file_content("nonexistent/file.py")
        assert res is None


def test_fetch_github_file_content_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout returns None as a hard gate."""
    monkeypatch.setenv("GITHUB_REPO", "Viresh2408/RISE")

    with patch("httpx.Client.get", side_effect=httpx.TimeoutException("timeout")):
        res = fetch_github_file_content("apps/api/src/deps/redis.py")
        assert res is None


def test_extract_file_paths_from_root_cause() -> None:
    """Extract file paths from explicit file_path and regex in reference."""
    rc = {
        "evidence": [
            {
                "type": "deploy",
                "file_path": "apps/api/src/deps/redis.py",
                "reference": "commit a1b2c3d",
            },
            {
                "type": "log",
                "reference": "Error trace in apps/api/src/routers/auth.py at line 42",
                "excerpt": "Timeout in packages/rise-core/db/session.py",
            },
        ]
    }
    paths = _extract_file_paths_from_root_cause(rc)
    assert "apps/api/src/deps/redis.py" in paths
    assert "apps/api/src/routers/auth.py" in paths
    assert "packages/rise-core/db/session.py" in paths


def test_fetch_files_for_action_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_files_for_action_plan returns mapped files dictionary."""
    monkeypatch.setenv("GITHUB_REPO", "Viresh2408/RISE")

    rc = {
        "evidence": [
            {
                "type": "code_file",
                "file_path": "apps/api/src/deps/redis.py",
                "reference": "ref",
            }
        ]
    }

    dummy_content = GitHubFileContent(
        path="apps/api/src/deps/redis.py",
        content="line1\nline2\n",
        sha="sha1",
        commit_sha="csha1",
        line_count=2,
        ref="main",
        repo="Viresh2408/RISE",
    )

    with patch(
        "apps.agents.src.nodes.github_file_fetcher.fetch_github_file_content",
        return_value=dummy_content,
    ):
        result = fetch_files_for_action_plan(rc)
        assert "apps/api/src/deps/redis.py" in result
        assert result["apps/api/src/deps/redis.py"] == dummy_content
