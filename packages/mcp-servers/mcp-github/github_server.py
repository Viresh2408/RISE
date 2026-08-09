"""MCP GitHub Server (`mcp-github`).

Exposes GitHub commits, PRs, and workflow tools per mcp.md §2.
Includes idempotent `create_pr` handling on retry.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Registry for open PRs to ensure idempotency on retry
_GITHUB_OPEN_PRS: Dict[str, Dict[str, Any]] = {}


class MCPGitHubServer:
    """Isolated MCP GitHub Server."""

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
        return {
            "repo": repo,
            "branch": branch,
            "commits": [
                {"sha": "a1b2c3d4", "author": "dev", "message": "fix: update memory limits"}
            ][:limit],
        }

    def get_pr_diff(self, repo: str = "", pr_number: int = 1) -> Dict[str, Any]:
        return {
            "repo": repo,
            "pr_number": pr_number,
            "diff": "--- a/deploy.yaml\n+++ b/deploy.yaml\n@@ -10,3 +10,3 @@\n- replicas: 1\n+ replicas: 3\n",
        }

    def create_branch(self, repo: str = "", branch_name: str = "", base_branch: str = "main") -> Dict[str, Any]:
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
        """Create a pull request with idempotency handling on retry."""
        pr_key = f"{repo}:{head_branch}:{base_branch}"

        # Check if PR already exists for this branch (idempotent retry)
        if pr_key in _GITHUB_OPEN_PRS:
            logger.info("PR already exists for %s, returning existing PR (idempotent retry)", pr_key)
            existing_pr = _GITHUB_OPEN_PRS[pr_key]
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
        }

        _GITHUB_OPEN_PRS[pr_key] = pr_data
        return pr_data

    def run_workflow(self, repo: str = "", workflow_id: str = "", ref: str = "main") -> Dict[str, Any]:
        return {
            "status": "success",
            "repo": repo,
            "workflow_id": workflow_id,
            "run_id": 987654,
        }

    def get_workflow_status(self, repo: str = "", run_id: str = "987654") -> Dict[str, Any]:
        return {
            "repo": repo,
            "run_id": run_id,
            "status": "completed",
            "conclusion": "success",
        }
