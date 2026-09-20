"""GitHub File Preview Router.

Provides a lightweight endpoint for the dashboard to fetch live GitHub file
status for monitor-detected patterns.

``GET /github/file-preview?file_path=...&pattern_id=...``

Returns:
  - ``is_bug_present``: whether the anti-pattern is still in the current file
  - ``is_fixed``: whether the fix has already been applied
  - ``current_content_snippet``: the relevant lines from the live file
  - ``proposed_diff``: unified diff of the proposed automated fix
  - ``github_url``: direct link to the file on GitHub
  - ``file_sha``: current commit SHA for the file
"""

from __future__ import annotations

import difflib
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Query

from apps.api.src.deps import require_role, UserContext
from apps.api.src.middleware.envelope import build_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["GitHub File Preview"])


@router.get("/file-preview")
async def get_github_file_preview(
    file_path: str = Query(..., description="Repo-relative file path, e.g. apps/api/src/deps/redis.py"),
    pattern_id: Optional[str] = Query(None, description="Monitor pattern ID to evaluate"),
    user: UserContext = Depends(require_role("viewer")),
):
    """Fetch the live GitHub file and evaluate it against the named monitor pattern.

    This is a READ-ONLY operation — nothing is written to GitHub.
    The response lets the dashboard show the operator:
      1. Whether the bug is still present in the current GitHub file
      2. The relevant buggy lines
      3. The exact diff that will be applied when they click Approve
    """
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_READ_TOKEN", "")
    github_repo = os.getenv("GITHUB_REPO", "Viresh2408/RISE")
    ref = os.getenv("GITHUB_MONITOR_REF", "main")

    owner_repo = github_repo.split("/", 1)
    owner = owner_repo[0] if len(owner_repo) == 2 else "Viresh2408"
    repo = owner_repo[1] if len(owner_repo) == 2 else "RISE"

    clean_path = file_path.lstrip("/").replace("\\", "/")
    github_url = f"https://github.com/{owner}/{repo}/blob/{ref}/{clean_path}"

    # -- Fetch current file from GitHub ----------------------------------------
    file_result = None
    try:
        from apps.agents.src.nodes.github_file_fetcher import fetch_github_file_content
        file_result = fetch_github_file_content(
            clean_path,
            repo=github_repo,
            ref=ref,
            github_token=github_token,
            timeout_s=10.0,
        )
    except Exception as exc:
        logger.warning("[file-preview] Could not fetch %s: %s", clean_path, exc)

    if file_result is None:
        return build_response(data={
            "file_path": clean_path,
            "github_url": github_url,
            "error": "Could not fetch file from GitHub. Check GITHUB_TOKEN and file path.",
            "is_bug_present": None,
            "is_fixed": None,
            "current_content_snippet": None,
            "proposed_diff": None,
            "file_sha": None,
        })

    current_content = file_result.content
    file_sha = file_result.sha

    # -- Evaluate against known monitor patterns --------------------------------
    is_bug_present = None
    is_fixed = None
    matched_pattern = None

    try:
        from apps.api.src.services.github_monitor import _make_patterns
        patterns = _make_patterns()
        for p in patterns:
            if p.file_path != clean_path:
                continue
            if pattern_id and p.pattern_id != pattern_id:
                continue
            is_bug_present = p.detect(current_content)
            is_fixed = p.is_fixed(current_content)
            matched_pattern = p
            break
    except Exception as exc:
        logger.debug("[file-preview] Pattern eval error: %s", exc)

    # -- Extract the buggy snippet ---------------------------------------------
    current_content_snippet = None
    if matched_pattern:
        try:
            from apps.api.src.services.github_monitor import _extract_buggy_context
            current_content_snippet = _extract_buggy_context(current_content, matched_pattern)
        except Exception:
            pass

    # -- Compute proposed diff -------------------------------------------------
    proposed_diff = None
    if is_bug_present and not is_fixed and matched_pattern:
        try:
            from apps.api.src.services.github_service import apply_patch_to_text
            proposed_content = apply_patch_to_text(
                current_content, clean_path, matched_pattern.title
            )
            if proposed_content != current_content:
                before_lines = current_content.splitlines(keepends=True)
                after_lines = proposed_content.splitlines(keepends=True)
                diff_lines = list(
                    difflib.unified_diff(
                        before_lines,
                        after_lines,
                        fromfile=f"a/{clean_path}",
                        tofile=f"b/{clean_path}",
                        lineterm="",
                    )
                )
                proposed_diff = "\n".join(diff_lines)
        except Exception as exc:
            logger.debug("[file-preview] Diff compute error: %s", exc)

    return build_response(data={
        "file_path": clean_path,
        "github_url": github_url,
        "file_sha": file_sha,
        "ref": ref,
        "is_bug_present": is_bug_present,
        "is_fixed": is_fixed,
        "pattern_id": matched_pattern.pattern_id if matched_pattern else pattern_id,
        "pattern_title": matched_pattern.title if matched_pattern else None,
        "pattern_description": matched_pattern.description if matched_pattern else None,
        "current_content_snippet": current_content_snippet,
        "proposed_diff": proposed_diff,
    })
