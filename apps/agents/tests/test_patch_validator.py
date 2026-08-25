"""Unit tests for Patch Validator (apps/agents/src/engines/patch_validator.py)."""

from __future__ import annotations

import pytest

from apps.agents.src.engines.patch_validator import (
    PatchError,
    apply_unified_diff,
    syntax_check_python,
)


def test_apply_unified_diff_success() -> None:
    """Test applying a valid unified diff to original content."""
    original = """def get_pool():
    TIMEOUT_MS = 2000
    MAX_RETRIES = 1
    return True
"""
    diff = """@@ -1,4 +1,5 @@
 def get_pool():
-    TIMEOUT_MS = 2000
-    MAX_RETRIES = 1
+    TIMEOUT_MS = 10000
+    MAX_RETRIES = 3
+    CIRCUIT_BREAKER = True
     return True
"""
    result = apply_unified_diff(original, diff)
    assert not isinstance(result, PatchError)
    assert "TIMEOUT_MS = 10000" in result
    assert "CIRCUIT_BREAKER = True" in result
    assert "TIMEOUT_MS = 2000" not in result


def test_apply_unified_diff_context_mismatch_returns_error() -> None:
    """Context mismatch returns PatchError with expected vs actual."""
    original = """def get_pool():
    TIMEOUT_MS = 5000
    return True
"""
    diff = """@@ -1,3 +1,3 @@
 def get_pool():
-    TIMEOUT_MS = 2000
+    TIMEOUT_MS = 10000
     return True
"""
    result = apply_unified_diff(original, diff)
    assert isinstance(result, PatchError)
    assert "context/removal line does not match file content" in result.reason
    assert "2000" in (result.expected_line or "")
    assert "5000" in (result.actual_line or "")


def test_apply_unified_diff_no_hunk_header_returns_error() -> None:
    """Diff without @@ hunk headers returns PatchError."""
    original = "a = 1\n"
    diff = "some random text without hunk\n"
    result = apply_unified_diff(original, diff)
    assert isinstance(result, PatchError)
    assert "contains no @@ hunk headers" in result.reason


def test_syntax_check_python() -> None:
    """Check python syntax validation."""
    valid_py = "def foo():\n    return 42\n"
    invalid_py = "def foo(\n    return 42\n"

    assert syntax_check_python(valid_py, "test.py") is None
    syntax_err = syntax_check_python(invalid_py, "test.py")
    assert syntax_err is not None

    # Non-python files are ignored
    assert syntax_check_python("invalid json {", "config.json") is None
