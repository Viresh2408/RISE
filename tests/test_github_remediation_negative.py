"""Negative & Verification Tests for Autonomous GitHub PR Remediation.

Covers:
1. Execution agent strict response verification (fails if no valid PR/commit is returned).
2. Verification agent checks that PR genuinely exists.
3. Negative simulation of GitHub API failure (invalid token, 403, 422, rate limit).
4. Confirmation that RISE_TEST_MODE is unset/false for production auth path.
5. Startup credential validation.
"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock
# pyrefly: ignore [missing-import]
from schemas.agent_state import ActionPlan, ActionStep, ExecutionLog
from apps.agents.src.nodes.execution import run_execution_agent
from apps.agents.src.nodes.verification import evaluate_rule_based_verification
from apps.api.src.services.github_service import commit_remediation_to_github
# pyrefly: ignore [missing-import]
from mcp_client.hash import compute_action_plan_hash


def test_execution_fails_when_github_tool_returns_error():
    """ExecutionLog.status must be 'failed' when GitHub tool returns an error response."""
    async def _run():
        plan = ActionPlan(
            action_type="code_fix_pr",
            action_steps=[ActionStep(tool="create_pr", params={"repo": "Viresh2408/RISE", "title": "fix"})],
            rollback_plan=[ActionStep(tool="git_revert", params={"commit": "HEAD"})],
            plan_rationale="Fix issue",
        )
        plan_hash = compute_action_plan_hash(plan)

        state = {
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "incident_id": "inc-test-negative-01",
            "action_plan": plan,
            "approved_plan_hash": plan_hash,
            "environment": "staging",
        }

        mock_gw = MagicMock()
        # Simulate GitHub tool returning failed result
        mock_gw.dispatch_tool_call = AsyncMock(return_value={"status": "failed", "error": "GitHub API rate limit exceeded"})

        result_state = await run_execution_agent(state, gateway=mock_gw)
        exec_log = result_state["execution_log"]

        assert exec_log["status"] == "failed"
        assert exec_log["steps_completed"] == 0
        assert "GitHub API rate limit exceeded" in exec_log["error"]

    asyncio.run(_run())


def test_execution_fails_when_github_tool_missing_pr_details():
    """ExecutionLog.status must be 'failed' when response does not contain a real PR or commit."""
    async def _run():
        plan = ActionPlan(
            action_type="code_fix_pr",
            action_steps=[ActionStep(tool="create_pr", params={"repo": "Viresh2408/RISE", "title": "fix"})],
            rollback_plan=[ActionStep(tool="git_revert", params={"commit": "HEAD"})],
            plan_rationale="Fix issue",
        )
        plan_hash = compute_action_plan_hash(plan)

        state = {
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "incident_id": "inc-test-negative-02",
            "action_plan": plan,
            "approved_plan_hash": plan_hash,
            "environment": "staging",
        }

        mock_gw = MagicMock()
        # Simulate empty response without PR URL or number
        mock_gw.dispatch_tool_call = AsyncMock(return_value={"status": "success"})

        result_state = await run_execution_agent(state, gateway=mock_gw)
        exec_log = result_state["execution_log"]

        assert exec_log["status"] == "failed"
        assert "missing a genuine Pull Request entity" in exec_log["error"]

    asyncio.run(_run())


from apps.agents.src.nodes.verification import evaluate_rule_based_verification, run_verification_agent, verify_github_pr_live


def test_verification_agent_checks_github_pr_existence():
    """Verification Agent verifies that GitHub PR genuinely exists in execution log."""
    # Case A: Success with valid PR
    exec_log_success = {
        "status": "success",
        "steps_completed": 1,
        "steps_total": 1,
        "result": "Successfully executed. Created PR: https://github.com/Viresh2408/RISE/pull/42",
    }
    metrics_ok = {"health_status": "200 OK", "error_rate": 0.0}
    res_success = evaluate_rule_based_verification(exec_log_success, metrics_ok, {})
    assert res_success.status == "passed"
    pr_checks = [c for c in res_success.checks if c.name == "github_pr_verification"]
    assert len(pr_checks) == 1
    assert pr_checks[0].result == "pass"

    # Case B: Execution failed
    exec_log_failed = {
        "status": "failed",
        "steps_completed": 0,
        "steps_total": 1,
        "error": "GitHub API 403 Forbidden",
    }
    res_failed = evaluate_rule_based_verification(exec_log_failed, metrics_ok, {})
    assert res_failed.status == "failed"
    assert res_failed.recommendation == "rollback"


def test_verification_agent_live_github_api_confirms_open_pr():
    """Verification Agent makes an independent GitHub API call and confirms PR is genuinely open."""
    async def _run():
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "number": 42,
            "state": "open",
            "title": "fix(remediation): auth pool fix",
            "html_url": "https://github.com/Viresh2408/RISE/pull/42",
        }
        mock_http.get = AsyncMock(return_value=mock_resp)

        state = {
            "incident_id": "inc-live-pr-01",
            "pr_url": "https://github.com/Viresh2408/RISE/pull/42",
            "execution_log": {
                "status": "success",
                "steps_completed": 1,
                "steps_total": 1,
                "result": "Created PR: https://github.com/Viresh2408/RISE/pull/42",
            },
            "post_action_metrics": {"health_status": "200 OK", "error_rate": 0.0},
        }

        res = await run_verification_agent(state, http_client=mock_http)
        ver_res = res["verification_result"]

        assert ver_res["status"] == "passed"
        assert ver_res["recommendation"] == "close"
        pr_check = next(c for c in ver_res["checks"] if c["name"] == "github_pr_verification")
        assert pr_check["result"] == "pass"
        assert "verified open on GitHub" in pr_check["value"]

    asyncio.run(_run())


def test_verification_agent_fails_when_pr_is_closed_or_deleted_on_github():
    """Verification Agent detects deleted/closed PR on GitHub and triggers rollback, refusing to close."""
    async def _run():
        # Simulate PR was closed on GitHub
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "number": 42,
            "state": "closed",
            "title": "fix(remediation): auth pool fix",
            "html_url": "https://github.com/Viresh2408/RISE/pull/42",
        }
        mock_http.get = AsyncMock(return_value=mock_resp)

        state = {
            "incident_id": "inc-live-pr-02",
            "pr_url": "https://github.com/Viresh2408/RISE/pull/42",
            "execution_log": {
                "status": "success",
                "steps_completed": 1,
                "steps_total": 1,
                "result": "Created PR: https://github.com/Viresh2408/RISE/pull/42",
            },
            "post_action_metrics": {"health_status": "200 OK", "error_rate": 0.0},
        }

        res = await run_verification_agent(state, http_client=mock_http)
        ver_res = res["verification_result"]

        assert ver_res["status"] == "failed"
        assert ver_res["recommendation"] == "rollback"
        pr_check = next(c for c in ver_res["checks"] if c["name"] == "github_pr_verification")
        assert pr_check["result"] == "fail"
        assert "closed" in pr_check["value"]

    asyncio.run(_run())


def test_rise_test_mode_is_not_enabled_by_default():
    """Confirm RISE_TEST_MODE is disabled (0/False) in normal environment."""
    assert os.getenv("RISE_TEST_MODE", "0") in ("0", "false", "")


from unittest.mock import patch
from apps.api.src.main import _validate_github_configuration


def test_startup_validation_rejects_insufficient_oauth_scopes():
    """Startup validation must raise RuntimeError when X-OAuth-Scopes lacks write/repo scope."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-oauth-scopes": "read:user, user:email"}  # Missing repo / public_repo
    mock_resp.json.return_value = {}

    with patch.dict(os.environ, {"ENVIRONMENT": "production", "GITHUB_TOKEN": "gho_test_insufficient_scope_12345"}):
        with patch("httpx.get", return_value=mock_resp):
            with pytest.raises(RuntimeError) as excinfo:
                _validate_github_configuration()
            assert "lacks required repository write scope" in str(excinfo.value)


def test_startup_validation_passes_with_valid_repo_scope():
    """Startup validation passes when token has 'repo' scope."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-oauth-scopes": "repo, workflow"}
    mock_resp.json.return_value = {"permissions": {"push": True, "admin": True}}

    with patch.dict(os.environ, {"ENVIRONMENT": "production", "GITHUB_TOKEN": "gho_valid_token_123456789"}):
        with patch("httpx.get", return_value=mock_resp):
            _validate_github_configuration()  # Should not raise


def test_startup_validation_rejects_fine_grained_pat_lacking_pr_write():
    """Startup validation rejects fine-grained PAT when POST /pulls probe returns HTTP 403."""
    mock_get = MagicMock()
    mock_get.status_code = 200
    mock_get.headers = {}  # Fine-grained PATs do not return x-oauth-scopes
    mock_get.json.return_value = {"permissions": {"admin": True, "push": True}}

    mock_probe = MagicMock()
    mock_probe.status_code = 403
    mock_probe.text = '{"message":"Resource not accessible by personal access token"}'

    with patch.dict(os.environ, {"ENVIRONMENT": "production", "GITHUB_TOKEN": "github_pat_restricted_12345"}):
        with patch("httpx.get", return_value=mock_get):
            with patch("httpx.post", return_value=mock_probe):
                with pytest.raises(RuntimeError) as excinfo:
                    _validate_github_configuration()
                assert "lacks 'pull_requests:write' permission" in str(excinfo.value)


def test_startup_validation_passes_fine_grained_pat_with_pr_write(tmp_path):
    """Startup validation passes fine-grained PAT when POST /pulls probe is accepted (HTTP 422 specifically for invalid head ref)."""
    mock_get = MagicMock()
    mock_get.status_code = 200
    mock_get.headers = {}
    mock_get.json.return_value = {"permissions": {"admin": True, "push": True}}

    mock_probe = MagicMock()
    mock_probe.status_code = 422
    mock_probe.content = b'{"message":"Validation Failed","errors":[{"resource":"PullRequest","field":"head","code":"invalid"}]}'
    mock_probe.json.return_value = {
        "message": "Validation Failed",
        "errors": [{"resource": "PullRequest", "field": "head", "code": "invalid"}],
    }
    mock_probe.text = '{"message":"Validation Failed","errors":[{"resource":"PullRequest","field":"head","code":"invalid"}]}'

    cache_file = tmp_path / "github_scope_probe.json"
    with patch("apps.api.src.main._PROBE_CACHE_FILE", cache_file):
        with patch("apps.api.src.main._CACHE_DIR", tmp_path):
            with patch.dict(os.environ, {"ENVIRONMENT": "production", "GITHUB_TOKEN": "github_pat_valid_123456789"}):
                with patch("httpx.get", return_value=mock_get):
                    with patch("httpx.post", return_value=mock_probe):
                        _validate_github_configuration()  # Should not raise


def test_startup_validation_uses_cache_on_subsequent_runs(tmp_path):
    """Startup validation caches probe result and skips live POST on subsequent runs within TTL."""
    mock_get = MagicMock()
    mock_get.status_code = 200
    mock_get.headers = {}
    mock_get.json.return_value = {"permissions": {"admin": True, "push": True}}

    mock_probe = MagicMock()
    mock_probe.status_code = 422
    mock_probe.content = b'{"message":"Validation Failed","errors":[{"resource":"PullRequest","field":"head","code":"invalid"}]}'
    mock_probe.json.return_value = {
        "message": "Validation Failed",
        "errors": [{"resource": "PullRequest", "field": "head", "code": "invalid"}],
    }
    mock_probe.text = '{"message":"Validation Failed","errors":[{"resource":"PullRequest","field":"head","code":"invalid"}]}'

    cache_file = tmp_path / "github_scope_probe.json"
    with patch("apps.api.src.main._PROBE_CACHE_FILE", cache_file):
        with patch("apps.api.src.main._CACHE_DIR", tmp_path):
            with patch.dict(os.environ, {"ENVIRONMENT": "production", "GITHUB_TOKEN": "github_pat_cached_test_token"}):
                with patch("httpx.get", return_value=mock_get):
                    with patch("httpx.post", return_value=mock_probe) as mock_post:
                        # First invocation: cache empty -> live probe called
                        _validate_github_configuration()
                        assert mock_post.call_count == 1

                        # Second invocation: valid cache present -> probe skipped (call_count remains 1)
                        _validate_github_configuration()
                        assert mock_post.call_count == 1

                        # Confirm cache file exists and stores hashed token, not plaintext
                        assert cache_file.is_file()
                        import json
                        with open(cache_file, "r") as f:
                            cdata = json.load(f)
                        assert "github_pat_cached_test_token" not in str(cdata)
                        assert "token_hash" in cdata
                        assert cdata["is_valid"] is True
