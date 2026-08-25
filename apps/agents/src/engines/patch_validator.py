"""Patch Validator — second-pass safety net for Action Planner diffs.

This module is the SECOND line of defence only. It validates a diff after
the LLM has already seen the real file content (which was fetched by
github_file_fetcher.py and injected into the prompt). It is NOT a substitute
for having real file content — if fetch returned None, the Action Planner
gates before the LLM is called and this module is never reached.

Responsibilities:
  1. Apply a unified diff string to the original file content, verifying that
     each hunk's context lines match the original exactly.
  2. Syntax-check the resulting patched content for .py files.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PatchError:
    """Describes a patch application failure."""

    reason: str
    hunk_index: int = -1
    expected_line: Optional[str] = None
    actual_line: Optional[str] = None

    def __str__(self) -> str:
        parts = [f"Patch failed: {self.reason}"]
        if self.hunk_index >= 0:
            parts.append(f"(hunk {self.hunk_index})")
        if self.expected_line is not None:
            parts.append(f"expected line: {self.expected_line!r}")
        if self.actual_line is not None:
            parts.append(f"actual line: {self.actual_line!r}")
        return " | ".join(parts)


@dataclass
class HunkBlock:
    """Parsed representation of a single @@ hunk."""

    orig_start: int      # 1-indexed start line in original
    orig_count: int
    new_start: int
    new_count: int
    lines: List[str]     # raw lines of the hunk (including the @@ header)


def _parse_hunks(diff_text: str) -> Tuple[List[HunkBlock], Optional[PatchError]]:
    """Parse unified diff text into HunkBlock list.

    Returns (hunks, error). error is None on success.
    """
    hunks: List[HunkBlock] = []
    current_hunk: Optional[HunkBlock] = None

    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    for raw_line in diff_text.splitlines(keepends=False):
        m = hunk_re.match(raw_line)
        if m:
            if current_hunk is not None:
                hunks.append(current_hunk)
            orig_start = int(m.group(1))
            orig_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            current_hunk = HunkBlock(
                orig_start=orig_start,
                orig_count=orig_count,
                new_start=new_start,
                new_count=new_count,
                lines=[],
            )
        elif current_hunk is not None:
            current_hunk.lines.append(raw_line)

    if current_hunk is not None:
        hunks.append(current_hunk)

    return hunks, None


def apply_unified_diff(original: str, diff_text: str) -> "str | PatchError":
    """Apply a unified diff to original file content.

    Each hunk's context lines (lines starting with ' ') are verified
    against the original. A mismatch returns a PatchError with the
    exact expected vs actual line content so the caller can include it
    in a retry prompt.

    Returns:
        The patched content string on success.
        PatchError on any mismatch, missing hunk header, or structural error.
    """
    if not diff_text or not diff_text.strip():
        return original  # no-op diff is valid

    hunks, parse_err = _parse_hunks(diff_text)
    if parse_err:
        return parse_err

    if not hunks:
        # diff has no @@ hunks — treat as invalid
        return PatchError(reason="diff contains no @@ hunk headers")

    orig_lines = original.splitlines(keepends=False)
    # Working copy (0-indexed list)
    result_lines = list(orig_lines)
    # Track offset accumulation as we apply hunks in order
    offset = 0

    for hunk_idx, hunk in enumerate(hunks):
        # orig_start is 1-indexed; convert to 0-indexed
        apply_at = hunk.orig_start - 1 + offset

        if apply_at < 0 or apply_at > len(result_lines):
            return PatchError(
                reason=(
                    f"hunk start line {hunk.orig_start} is out of range "
                    f"(file has {len(orig_lines)} lines, current offset {offset})"
                ),
                hunk_index=hunk_idx,
            )

        # Reconstruct what context+removal lines expect in the original
        expected_orig: List[str] = []
        replacement_lines: List[str] = []
        for ln in hunk.lines:
            if ln.startswith(" ") or ln.startswith("-"):
                expected_orig.append(ln[1:])  # strip the diff sigil
            if ln.startswith(" ") or ln.startswith("+"):
                replacement_lines.append(ln[1:])

        # Verify context+removal lines match the real file at this position
        for rel_idx, expected in enumerate(expected_orig):
            file_idx = apply_at + rel_idx
            if file_idx >= len(result_lines):
                return PatchError(
                    reason="hunk extends beyond end of file",
                    hunk_index=hunk_idx,
                    expected_line=expected,
                    actual_line="<EOF>",
                )
            actual = result_lines[file_idx]
            if actual != expected:
                return PatchError(
                    reason="context/removal line does not match file content",
                    hunk_index=hunk_idx,
                    expected_line=expected,
                    actual_line=actual,
                )

        # Apply: replace the orig span with the replacement
        result_lines[apply_at : apply_at + len(expected_orig)] = replacement_lines
        offset += len(replacement_lines) - len(expected_orig)

    return "\n".join(result_lines)


def syntax_check_python(source: str, path: str) -> Optional[SyntaxError]:
    """Check that `source` is syntactically valid Python.

    Returns None if valid, SyntaxError if not.
    Only called for .py files; no-op for other extensions.
    """
    if not path.endswith(".py"):
        return None
    try:
        ast.parse(source, filename=path)
        return None
    except SyntaxError as exc:
        logger.warning("syntax_check_python: syntax error in patched %s: %s", path, exc)
        return exc
