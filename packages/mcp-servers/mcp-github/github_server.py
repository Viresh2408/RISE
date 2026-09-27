"""MCP GitHub Server (`mcp-github`) — SIMULATION / TEST FIXTURE ONLY.

Exposes GitHub commit, PR, and workflow tool *shapes* (see ADR-004 in
`docs/architecture-decisions.md`) for local development, CI evaluation, and
orchestration tests. Its write tools return
in-memory fixtures (`is_test_fixture: True`) and are fail-closed: they raise in
staging/production and whenever `allow_test_mock` is not explicitly enabled.

This server is DEPRECATED as a real execution path and is intentionally NOT wired
to perform live GitHub writes. RISE's single canonical GitHub integration is
`apps/api/src/services/github_service.py` (`commit_remediation_to_github`), which
the API approval flow calls directly to create real branches/commits/PRs via the
GitHub REST API. See ADR-004 in `docs/architecture-decisions.md` for the decision
to keep one real path and treat this module as a simulation fixture rather than
maintaining two parallel, inconsistent GitHub integrations.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Registry for open PRs to ensure idempotency on retry (test fixtures only)
_GITHUB_OPEN_PRS: Dict[str, Dict[str, Any]] = {}


def reset_test_fixtures() -> None:
    """Clear in-memory PR registry between test runs."""
    _GITHUB_OPEN_PRS.clear()


class MCPGitHubServer:
    """Isolated MCP GitHub Server."""

    def __init__(self, *, allow_test_mock: bool = False):
        env = os.getenv("ENVIRONMENT", "local").lower().strip()
        is_prod = env in ("production", "prod", "staging")

        if is_prod and allow_test_mock:
            raise RuntimeError(
                f"SECURITY VIOLATION: Mocked MCP GitHub transport cannot be enabled in ENVIRONMENT='{env}'."
            )

        # Allow test mocks only when explicitly requested in test/local/dev/ci environments
        self.allow_test_mock = allow_test_mock or (
            not is_prod and os.getenv("RISE_ALLOW_MCP_TEST_MOCKS", "0") == "1"
        )

    def _assert_write_allowed(self, tool_name: str) -> None:
        if not self.allow_test_mock:
            raise RuntimeError(
                f"MCP GitHub write tool '{tool_name}' rejected: in-memory mock transport is disabled. "
                "Production and staging require live GitHub credentials or out-of-process MCP isolation."
            )

    def handle_tool_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "get_recent_commits": self.get_recent_commits,
            "get_pr_diff": self.get_pr_diff,
            "create_branch": self.create_branch,
            "create_pr": self.create_pr,
            "run_workflow": self.run_workflow,
            "get_workflow_status": self.get_workflow_status,
        }

        if tool_name not in handlers:
            raise ValueError(f"Unknown tool '{tool_name}' on mcp-github server")

        return handlers[tool_name](**params)

    def get_recent_commits(self, repo: str = "", branch: str = "main", limit: int = 10) -> Dict[str, Any]:
        if not self.allow_test_mock:
            raise RuntimeError(
                "MCP GitHub tool 'get_recent_commits' requires live credentials or explicit test fixture."
            )
        return {
            "repo": repo,
            "branch": branch,
            "commits": [
                {"sha": "a1b2c3d4", "author": "dev", "message": "fix: update memory limits"}
            ][:limit],
        }

    def get_pr_diff(self, repo: str = "", pr_number: int = 1) -> Dict[str, Any]:
        if not self.allow_test_mock:
            raise RuntimeError(
                "MCP GitHub tool 'get_pr_diff' requires live credentials or explicit test fixture."
            )
        return {
            "repo": repo,
            "pr_number": pr_number,
            "diff": "--- a/deploy.yaml\n+++ b/deploy.yaml\n@@ -10,3 +10,3 @@\n- replicas: 1\n+ replicas: 3\n",
        }

    def create_branch(self, repo: str = "", branch_name: str = "", base_branch: str = "main") -> Dict[str, Any]:
        self._assert_write_allowed("create_branch")
        return {
            "status": "success",
            "repo": repo,
            "branch_name": branch_name,
            "base_branch": base_branch,
            "ref": f"refs/heads/{branch_name}",
        }

    def create_pr(
        self,
        repo: str = "",
        title: str = "",
        head_branch: str = "",
        base_branch: str = "main",
        body: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Create a pull request with idempotency handling on retry (test fixtures only)."""
        self._assert_write_allowed("create_pr")
        pr_key = f"{repo}:{head_branch}:{base_branch}"

        # Check if PR already exists for this branch (idempotent retry)
        if pr_key in _GITHUB_OPEN_PRS:
            logger.info("PR already exists for %s, returning existing PR (idempotent retry)", pr_key)
            existing_pr = dict(_GITHUB_OPEN_PRS[pr_key])
            existing_pr["is_existing"] = True
            return existing_pr

        pr_number = len(_GITHUB_OPEN_PRS) + 101
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"

        pr_data = {
            "status": "success",
            "pr_number": pr_number,
            "pr_url": pr_url,
            "title": title,
            "repo": repo,
            "head_branch": head_branch,
            "base_branch": base_branch,
            "body": body,
            "is_existing": False,
            # Explicit marker: this PR entity is a TEST FIXTURE only.
            # It does NOT correspond to a real GitHub PR and must NEVER be
            # used in production or staging flows.
            "is_test_fixture": True,
        }

        _GITHUB_OPEN_PRS[pr_key] = pr_data
        return pr_data

    def run_workflow(self, repo: str = "", workflow_id: str = "", ref: str = "main") -> Dict[str, Any]:
        self._assert_write_allowed("run_workflow")
        return {
            "status": "success",
            "repo": repo,
            "workflow_id": workflow_id,
            "run_id": 987654,
        }

    def get_workflow_status(self, repo: str = "", run_id: str = "987654") -> Dict[str, Any]:
        if not self.allow_test_mock:
            raise RuntimeError(
                "MCP GitHub tool 'get_workflow_status' requires live credentials or explicit test fixture."
            )
        return {
            "repo": repo,
            "run_id": run_id,
            "status": "completed",
            "conclusion": "success",
        }
