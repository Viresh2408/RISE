"""GitHub File Fetcher — grounding module for RISE Action Planner.

Fetches real file content from the GitHub REST API at a specific ref (branch/commit)
*before* the Action Planner builds its prompt. A None return value is a hard gate:
the Action Planner must not generate a diff when content is unavailable.

This module is intentionally read-only. It never writes to GitHub.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class GitHubFileContent:
    """Real file content fetched from GitHub at a specific commit ref."""

    path: str
    content: str
    sha: str           # blob SHA (file-level)
    commit_sha: str    # HEAD commit SHA for this ref
    line_count: int
    ref: str
    repo: str


def fetch_github_file_content(
    path: str,
    *,
    repo: Optional[str] = None,
    ref: str = "main",
    github_token: Optional[str] = None,
    github_api_url: Optional[str] = None,
    timeout_s: float = 10.0,
) -> Optional[GitHubFileContent]:
    """Fetch the content of a single file from the GitHub Contents API.

    Returns:
        GitHubFileContent on success.
        None on any failure (timeout, auth error, 404, decode error).
        None is a HARD GATE — callers must not proceed with LLM generation
        for this file if the result is None.

    Args:
        path: File path relative to repo root (e.g. "apps/api/src/deps/redis.py").
        repo: GitHub repo in "owner/name" format. Defaults to GITHUB_REPO env var.
        ref: Branch name or commit SHA to fetch from. Defaults to "main".
        github_token: Optional PAT / token. Falls back to GITHUB_READ_TOKEN or GITHUB_TOKEN.
        github_api_url: Base URL for GitHub API. Defaults to "https://api.github.com".
        timeout_s: Request timeout in seconds.
    """
    effective_repo = repo or os.getenv("GITHUB_REPO", "")
    if not effective_repo:
        logger.warning(
            "fetch_github_file_content: GITHUB_REPO not configured, cannot fetch %s", path
        )
        return None

    token = github_token or os.getenv("GITHUB_READ_TOKEN") or os.getenv("GITHUB_TOKEN")
    base_url = (github_api_url or os.getenv("GITHUB_API_URL", "https://api.github.com")).rstrip("/")

    headers: Dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    contents_url = f"{base_url}/repos/{effective_repo}/contents/{path.lstrip('/')}"
    commits_url = f"{base_url}/repos/{effective_repo}/commits/{ref}"

    try:
        with httpx.Client(timeout=timeout_s) as client:
            # Fetch file content
            content_resp = client.get(contents_url, headers=headers, params={"ref": ref})
            if content_resp.status_code == 404:
                logger.warning(
                    "fetch_github_file_content: %s not found in %s@%s (404)", path, effective_repo, ref
                )
                return None
            content_resp.raise_for_status()
            content_data = content_resp.json()

            if content_data.get("type") != "file":
                logger.warning(
                    "fetch_github_file_content: %s is not a file (type=%s)", path, content_data.get("type")
                )
                return None

            import base64
            raw_content: str
            encoding = content_data.get("encoding", "")
            if encoding == "base64":
                raw_content = base64.b64decode(content_data["content"]).decode("utf-8", errors="replace")
            else:
                raw_content = content_data.get("content", "")

            blob_sha = content_data.get("sha", "")

            # Fetch HEAD commit SHA for the ref
            commit_resp = client.get(commits_url, headers=headers)
            commit_sha = ""
            if commit_resp.status_code == 200:
                commit_sha = commit_resp.json().get("sha", "")[:40]

            return GitHubFileContent(
                path=path,
                content=raw_content,
                sha=blob_sha,
                commit_sha=commit_sha,
                line_count=raw_content.count("\n") + 1,
                ref=ref,
                repo=effective_repo,
            )

    except httpx.TimeoutException as exc:
        logger.warning("fetch_github_file_content: timeout fetching %s: %s", path, exc)
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "fetch_github_file_content: HTTP %s fetching %s: %s",
            exc.response.status_code, path, exc,
        )
        return None
    except Exception as exc:
        logger.warning("fetch_github_file_content: unexpected error fetching %s: %s", path, exc)
        return None


def fetch_files_for_action_plan(
    root_cause: Dict[str, Any],
    *,
    repo: Optional[str] = None,
    ref: str = "main",
    github_token: Optional[str] = None,
    github_api_url: Optional[str] = None,
    timeout_s: float = 10.0,
) -> Dict[str, Optional[GitHubFileContent]]:
    """Extract file paths from root cause evidence, fetch each from GitHub.

    Returns a dict of ``{path: GitHubFileContent | None}``.
    A None value means the fetch failed — the Action Planner MUST NOT
    generate a diff for that file.

    File paths are extracted from evidence items whose type is "deploy"
    or where the reference field contains a recognisable file extension.
    """
    paths = _extract_file_paths_from_root_cause(root_cause)
    if not paths:
        logger.debug("fetch_files_for_action_plan: no file paths found in root cause evidence")
        return {}

    result: Dict[str, Optional[GitHubFileContent]] = {}
    for path in paths:
        result[path] = fetch_github_file_content(
            path,
            repo=repo,
            ref=ref,
            github_token=github_token,
            github_api_url=github_api_url,
            timeout_s=timeout_s,
        )
        if result[path] is None:
            logger.warning(
                "fetch_files_for_action_plan: could not fetch %s — "
                "action planner will not generate a diff for this file",
                path,
            )

    return result


def _extract_file_paths_from_root_cause(root_cause: Dict[str, Any]) -> List[str]:
    """Extract file paths referenced in root cause evidence.

    Looks in:
    - evidence[].file_path (from structured EvidenceItem)
    - evidence[].reference (free-text, parsed for path-like patterns)
    """
    import re

    paths: List[str] = []
    seen: set = set()

    # Pattern: matches paths like "apps/foo/bar.py", "src/index.js", etc.
    _path_pattern = re.compile(
        r'(?:^|[\s"\'\(])('
        r'(?:apps|src|packages|services|lib|internal|cmd|pkg)/[^\s"\'\)\>]+'
        r'\.[a-zA-Z]{1,6}'
        r')',
        re.MULTILINE,
    )

    evidence_list = root_cause.get("evidence", [])
    if not isinstance(evidence_list, list):
        return paths

    for item in evidence_list:
        if not isinstance(item, dict):
            continue

        # Prefer explicit file_path field (from grounded EvidenceItem)
        explicit = item.get("file_path", "")
        if explicit and explicit not in seen:
            paths.append(explicit)
            seen.add(explicit)
            continue

        # Fall back to parsing reference text
        reference = item.get("reference", "")
        excerpt = item.get("excerpt", "")
        combined = f"{reference} {excerpt}"
        for match in _path_pattern.finditer(combined):
            candidate = match.group(1).strip().rstrip(".,;:")
            if candidate not in seen:
                paths.append(candidate)
                seen.add(candidate)

    return paths
