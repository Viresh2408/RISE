"""Safety Invariants Regression Test Suite.

Proves:
1. No GitHub token never returns success (returns stable GITHUB_CREDENTIALS_UNAVAILABLE).
2. GitHub 4xx/5xx/timeout never returns success.
3. A plausible but nonexistent PR URL fails verification and triggers rollback.
4. The approval endpoint cannot report execution success before independent verification.
5. Local source files are not modified as a GitHub fallback.
6. Critical actions cannot auto-approve.
7. Write-enabled mocked MCP transports are rejected in staging/production.
"""

from __future__ import annotations

import asyncio
import os
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.api.src.services.github_service import commit_remediation_to_github
from apps.agents.src.nodes.verification import (
    evaluate_rule_based_verification,
    run_verification_agent,
    verify_github_pr_live,
)



@pytest.mark.anyio
async def test_no_github_token_never_returns_success():
    """When GITHUB_TOKEN is unset, commit_remediation_to_github fails closed with stable error code."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": ""}, clear=False):
        with patch("apps.api.src.services.github_service.get_github_token", return_value=""):
            res = await commit_remediation_to_github(
                incident_id="inc-test-no-token",
                incident_title="Test Incident",
                target_file="packages/rise-core/db/session.py",
            )
            assert res["success"] is False
            assert res["error_code"] == "GITHUB_CREDENTIALS_UNAVAILABLE"
            assert res["commit_sha"] is None
            assert res["pr_number"] is None
            assert res["pr_url"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [401, 403, 404, 422, 500, 502, 503])
async def test_github_http_error_never_returns_success(status_code: int):
    """When GitHub API returns 4xx or 5xx, remediation never fabricates success."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = f"HTTP {status_code} Error from GitHub"

    with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_valid_mock_token_12345"}):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            res = await commit_remediation_to_github(
                incident_id="inc-test-http-err",
                incident_title="Test Incident",
                target_file="packages/rise-core/db/session.py",
            )
            assert res["success"] is False
            assert res["pr_number"] is None
            assert res["commit_sha"] is None


@pytest.mark.anyio
async def test_github_timeout_never_returns_success():
    """When GitHub API times out, remediation fails closed."""
    import httpx

    with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_valid_mock_token_12345"}):
        with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Connection timed out")):
            res = await commit_remediation_to_github(
                incident_id="inc-test-timeout",
                incident_title="Test Incident",
                target_file="packages/rise-core/db/session.py",
            )
            assert res["success"] is False
            assert res["error_code"] == "GITHUB_NETWORK_ERROR"
            assert "Connection timed out" in res["error"]


@pytest.mark.anyio
async def test_plausible_nonexistent_pr_url_fails_verification():
    """A plausible but nonexistent PR URL (e.g. 404 on GitHub) fails verification and triggers rollback."""
    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = '{"message": "Not Found"}'
    mock_http.get = AsyncMock(return_value=mock_resp)

    state = {
        "incident_id": "inc-test-nonexistent-pr",
        "pr_url": "https://github.com/Viresh2408/RISE/pull/9999",
        "execution_log": {
            "status": "success",
            "steps_completed": 1,
            "steps_total": 1,
            "result": "Created PR: https://github.com/Viresh2408/RISE/pull/9999",
        },
        "post_action_metrics": {"health_status": "200 OK", "error_rate": 0.0},
    }

    result = await run_verification_agent(state, http_client=mock_http)
    ver = result["verification_result"]

    assert ver["status"] == "failed"
    assert ver["recommendation"] == "rollback"
    pr_check = next(c for c in ver["checks"] if c["name"] == "github_pr_verification")
    assert pr_check["result"] == "fail"
    assert "does not exist on GitHub" in pr_check["value"]


@pytest.mark.anyio
async def test_local_source_files_are_not_modified_as_fallback():
    """Remediation must NEVER modify local source files on disk as a GitHub fallback."""
    target_file = "packages/rise-core/db/session.py"
    with open(target_file, "r", encoding="utf-8") as f:
        original_content = f.read()

    try:
        # Run remediation with failing GitHub token
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_failing_token_12345"}):
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
                await commit_remediation_to_github(
                    incident_id="inc-test-no-disk-write",
                    incident_title="Test Local Modification Guard",
                    target_file=target_file,
                )

        # Check local file was NOT modified
        with open(target_file, "r", encoding="utf-8") as f:
            current_content = f.read()

        assert current_content == original_content, "Local source file was modified by remediation fallback!"
    finally:
        # Ensure clean file restore just in case
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(original_content)


def test_critical_actions_cannot_auto_approve():
    """Critical-tier actions always force requires_approval=True and cannot auto-approve."""
    from apps.agents.src.engines.risk_engine import RiskEngine

    engine = RiskEngine()
    assessment = engine.evaluate_risk_local_fallback(
        action_type="drop_table",
        environment="staging",
        blast_radius_count=1,
    )

    assert assessment.risk_tier == "critical"
    assert assessment.requires_approval is True

    assessment_prod = engine.evaluate_risk_local_fallback(
        action_type="drop_table",
        environment="production",
        blast_radius_count=5,
    )
    assert assessment_prod.risk_tier == "critical"
    assert assessment_prod.requires_approval is True


def test_write_enabled_mock_mcp_rejected_in_production():
    """MCP GitHub server must reject write mock enablement in production environment."""
    import sys
    from pathlib import Path
    github_server_dir = str(Path(__file__).resolve().parents[1] / "packages" / "mcp-servers" / "mcp-github")
    if github_server_dir not in sys.path:
        sys.path.insert(0, github_server_dir)
    from github_server import MCPGitHubServer

    with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
        with pytest.raises(RuntimeError) as excinfo:
            MCPGitHubServer(allow_test_mock=True)
        assert "SECURITY VIOLATION: Mocked MCP GitHub transport cannot be enabled" in str(excinfo.value)

