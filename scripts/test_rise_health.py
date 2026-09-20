#!/usr/bin/env python3
"""
RISE Website Health & Integration Test Script
=============================================
Run this to verify the backend API and dashboard are working correctly.

Usage
-----
  python scripts/test_rise_health.py

Requirements
------------
  pip install httpx  (or: the script falls back to urllib if httpx is absent)

Environment (reads from .env automatically)
-------------------------------------------
  API_BASE_URL       Backend URL  (default: http://localhost:8000)
  DASHBOARD_URL      Frontend URL (default: http://localhost:3000)
  RISE_TEST_TOKEN    JWT token for authenticated tests (default: demo-token-hardcoded)
  GITHUB_TOKEN       Used to test the GitHub file-preview endpoint
  GITHUB_REPO        Primary repo  (default: Viresh2408/RISE)
  GITHUB_MONITOR_REPO_2  Secondary repo slug to test (optional)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Tuple

# -- Load .env from the repo root ---------------------------------------------
_root = Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().split("#")[0].strip())

# -- Config -------------------------------------------------------------------
API_BASE    = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
DASH_BASE   = os.getenv("DASHBOARD_URL", "http://localhost:3000").rstrip("/")
TOKEN       = os.getenv("RISE_TEST_TOKEN", "demo-token-hardcoded")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Viresh2408/RISE")
REPO2       = os.getenv("GITHUB_MONITOR_REPO_2", "").strip()

# -- HTTP helper (httpx -> urllib fallback) -----------------------------------
try:
    import httpx
    def _get(url: str, headers: dict = {}, timeout: float = 10.0) -> Tuple[int, Any]:
        try:
            r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            try:
                body = r.json()
            except Exception:
                body = r.text
            return r.status_code, body
        except Exception as e:
            return 0, str(e)
except ImportError:
    import urllib.request
    import urllib.error
    def _get(url: str, headers: dict = {}, timeout: float = 10.0) -> Tuple[int, Any]:  # type: ignore
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode()
                try:
                    return resp.status, json.loads(body)
                except Exception:
                    return resp.status, body
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except Exception as ex:
            return 0, str(ex)


__test__ = False


def run_health_checks() -> int:
    results: list = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        symbol = "PASS" if ok else "FAIL"
        print(f"  [{symbol}]  {name}" + (f"  -- {detail}" if detail else ""))
        results.append({"name": name, "ok": ok, "detail": detail})
        return ok

    def section(title: str) -> None:
        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")

    AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}

    # -- 1. Backend reachability --------------------------------------------------
    section("1. Backend API - Reachability")

    code, body = _get(f"{API_BASE}/healthz")
    check("GET /healthz -> 200", code == 200, f"HTTP {code}")

    code, body = _get(f"{API_BASE}/readyz")
    check("GET /readyz -> 200", code == 200, f"HTTP {code}")

    code, body = _get(f"{API_BASE}/api/v1/healthz")
    check("GET /api/v1/healthz -> 200", code == 200, f"HTTP {code}")

    # -- 2. Unauthenticated access returns 401 ------------------------------------
    section("2. Backend API - Auth Guard")

    code, body = _get(f"{API_BASE}/api/v1/incidents")
    check(
        "GET /incidents without token -> 401 or 403",
        code in (401, 403),
        f"HTTP {code} (expected 401 or 403)",
    )

    # -- 3. Authenticated incidents endpoint --------------------------------------
    section("3. Backend API - Incidents")

    code, body = _get(f"{API_BASE}/api/v1/incidents", headers=AUTH_HEADERS)
    ok = code == 200
    check("GET /incidents -> 200", ok, f"HTTP {code}")
    if ok and isinstance(body, dict):
        data = body.get("data", [])
        check(
            "Response has 'data' array",
            isinstance(data, list),
            f"len={len(data)}",
        )
        if data:
            first_id = data[0].get("id", "")
            check("First incident has an id field", bool(first_id), first_id)

            code2, body2 = _get(f"{API_BASE}/api/v1/incidents/{first_id}", headers=AUTH_HEADERS)
            check("GET /incidents/{id} -> 200", code2 == 200, f"HTTP {code2}")
            if code2 == 200 and isinstance(body2, dict):
                detail = body2.get("data", {})
                check("Detail has 'decision' field", "decision" in detail, str(list(detail.keys()))[:80])
                check("Detail has 'root_cause' field", "root_cause" in detail, "")
                check("Detail has 'impact' field", "impact" in detail, "")

                rc_action = detail.get("decision", {}).get("recommended_action", {})
                snippet = rc_action.get("code_fix_snippet", {})
                if snippet:
                    is_monitor = snippet.get("is_monitor_detected", False)
                    print(f"  [INFO]  code_fix_snippet present | is_monitor_detected={is_monitor}")
                    if is_monitor:
                        check(
                            "Monitor incident has 'diff' in code_fix_snippet",
                            bool(snippet.get("diff")),
                            "diff present" if snippet.get("diff") else "diff MISSING",
                        )

    # -- 4. GitHub file-preview endpoint ------------------------------------------
    section("4. GitHub Integration - /github/file-preview")

    test_files = [
        ("apps/api/src/deps/redis.py", "redis_no_pool"),
        ("packages/rise-core/db/session.py", "db_small_pool"),
    ]
    for fpath, pid in test_files:
        url = f"{API_BASE}/api/v1/github/file-preview?file_path={fpath}&pattern_id={pid}"
        code, body = _get(url, headers=AUTH_HEADERS)
        ok = code == 200
        check(f"file-preview: {fpath} -> 200", ok, f"HTTP {code}")
        if ok and isinstance(body, dict):
            d = body.get("data", {})
            bug = d.get("is_bug_present")
            fixed = d.get("is_fixed")
            sha = (d.get("file_sha") or "")[:10]
            print(f"  [INFO]  is_bug_present={bug}  is_fixed={fixed}  sha={sha}")
            if d.get("error"):
                print(f"  [WARN]  GitHub error: {d['error']}")

    # -- 5. Secondary repo (if configured) ----------------------------------------
    if REPO2:
        section(f"5. Secondary Repo - {REPO2}")
        url = (
            f"{API_BASE}/api/v1/github/file-preview"
            f"?file_path=src/routes/debug.py&pattern_id=ext_debug_route_exposed"
        )
        code, body = _get(url, headers=AUTH_HEADERS)
        check(
            "file-preview endpoint reachable for secondary repo pattern",
            code in (200, 404),
            f"HTTP {code}",
        )
        if code == 200 and isinstance(body, dict):
            d = body.get("data", {})
            print(f"  [INFO]  is_bug_present={d.get('is_bug_present')}  is_fixed={d.get('is_fixed')}")
    else:
        section("5. Secondary Repo (skipped - GITHUB_MONITOR_REPO_2 not set)")
        print("  [INFO]  Set GITHUB_MONITOR_REPO_2=owner/repo in .env to enable this test.")

    # -- 6. Dashboard frontend ----------------------------------------------------
    section("6. Dashboard Frontend")

    code, body = _get(DASH_BASE, timeout=15.0)
    ok = code == 200
    check(f"GET {DASH_BASE} -> 200", ok, f"HTTP {code}")
    if ok and isinstance(body, str):
        check("Response contains <html", "<html" in body.lower(), "")
        check("Response contains 'RISE'", "rise" in body.lower(), "")

    code, body = _get(f"{DASH_BASE}/incidents", timeout=10.0)
    check("GET /incidents page -> 200", code == 200, f"HTTP {code}")

    # -- 7. API schema ------------------------------------------------------------
    section("7. API Schema - OpenAPI")

    code, body = _get(f"{API_BASE}/openapi.json")
    check("GET /openapi.json -> 200", code == 200, f"HTTP {code}")
    if code == 200 and isinstance(body, dict):
        paths = list(body.get("paths", {}).keys())
        check(
            "/api/v1/incidents in OpenAPI paths",
            any("/incidents" in p for p in paths),
            f"{len(paths)} paths found",
        )
        check(
            "/api/v1/github/file-preview in OpenAPI paths",
            any("file-preview" in p for p in paths),
            "",
        )

    # -- Summary ------------------------------------------------------------------
    section("Summary")
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = total - passed

    print(f"\n  Passed : {passed}/{total}")
    if failed:
        print(f"  Failed : {failed}/{total}")
        print("\n  Failed checks:")
        for r in results:
            if not r["ok"]:
                print(f"    [FAIL]  {r['name']}" + (f" -- {r['detail']}" if r["detail"] else ""))

    print()
    if failed == 0:
        print("  All checks passed - RISE is healthy!\n")
        return 0
    elif passed / total >= 0.8:
        print("  Most checks passed - review warnings above.\n")
        return 1
    else:
        print("  Multiple checks failed - RISE may not be running.\n")
        return 2


if __name__ == "__main__":
    sys.exit(run_health_checks())

