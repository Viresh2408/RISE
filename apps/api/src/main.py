import sys
import os
from pathlib import Path

root_dir = Path(__file__).resolve().parents[3]
rise_core_dir = root_dir / "packages" / "rise-core"
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(rise_core_dir) not in sys.path:
    sys.path.insert(0, str(rise_core_dir))

from dotenv import load_dotenv
env_path = root_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=False)



def _assert_safe_test_mode() -> None:
    """Refuse to start if RISE_TEST_MODE=1 outside a local/test environment.

    RISE_TEST_MODE skips Supabase JWT signature verification entirely.  It
    exists solely for unit tests and must *never* reach staging or production.

    Safe environments (case-insensitive):
        local, test, development, dev, ci

    Any other ENVIRONMENT value (staging, production, prod, release, …) causes
    a hard RuntimeError at import time so the process exits before accepting
    a single request.

    Environment variables read:
        RISE_TEST_MODE  – "1" to enable test mode (default "0").
        ENVIRONMENT     – deployment environment name (default "local").
    """
    test_mode = os.getenv("RISE_TEST_MODE", "0") == "1"
    if not test_mode:
        return  # nothing to check

    _SAFE_ENVIRONMENTS = {"local", "test", "development", "dev", "ci"}
    environment = os.getenv("ENVIRONMENT", "local").lower().strip()

    if environment not in _SAFE_ENVIRONMENTS:
        raise RuntimeError(
            f"SECURITY VIOLATION: RISE_TEST_MODE=1 is set but ENVIRONMENT='{environment}' "
            f"is not a recognised safe environment ({', '.join(sorted(_SAFE_ENVIRONMENTS))}). "
            "JWT signature verification is disabled — refusing to start. "
            "Unset RISE_TEST_MODE before deploying to non-local environments."
        )


import hashlib
import json
import time

_CACHE_DIR = root_dir / ".cache"
_PROBE_CACHE_FILE = _CACHE_DIR / "github_scope_probe.json"
_DEFAULT_PROBE_TTL_SECONDS = 3600  # 1 hour TTL default


def _get_cached_scope_probe(token: str, owner: str, repo: str, ttl_seconds: int) -> bool:
    """Check if a valid, non-expired scope probe result exists in cache for this token and repo."""
    try:
        if not _PROBE_CACHE_FILE.is_file():
            return False
        with open(_PROBE_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if (
            data.get("token_hash") == token_hash
            and data.get("repo") == f"{owner}/{repo}"
            and data.get("is_valid") is True
        ):
            cached_time = data.get("timestamp", 0)
            if time.time() - cached_time < ttl_seconds:
                return True
    except Exception:
        pass
    return False


def _save_cached_scope_probe(token: str, owner: str, repo: str) -> None:
    """Save successful scope probe outcome to local durable cache."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        cache_data = {
            "token_hash": token_hash,
            "repo": f"{owner}/{repo}",
            "is_valid": True,
            "timestamp": time.time(),
        }
        with open(_PROBE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
    except Exception:
        pass


def _validate_github_configuration() -> None:
    """Validate GitHub integration credentials and write scopes on startup to fail loudly if misconfigured."""
    environment = os.getenv("ENVIRONMENT", "local").lower().strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    app_id = os.getenv("GITHUB_APP_ID", "").strip()
    app_key = os.getenv("GITHUB_APP_PRIVATE_KEY", "").strip()
    owner = os.getenv("GITHUB_OWNER", "Viresh2408")
    repo = os.getenv("GITHUB_REPO", "RISE")

    # In production/staging (or when GITHUB_TOKEN is provided), ensure integration credentials and write scopes are valid
    is_prod_env = environment in ("production", "prod", "staging")
    has_token = bool(token and len(token) > 10 and not token.startswith("your_"))
    has_app = bool(app_id and app_key and not app_id.startswith("123456"))

    if is_prod_env and not has_token and not has_app:
        raise RuntimeError(
            f"CONFIGURATION ERROR: ENVIRONMENT='{environment}' requires valid GitHub App or GITHUB_TOKEN credentials. "
            "Failing startup loudly to prevent runtime failure during incident remediation."
        )

    if has_token:
        try:
            import httpx
            resp = httpx.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "RISE-Startup-Validator",
                },
                timeout=5.0,
            )
            if resp.status_code == 401:
                raise RuntimeError(
                    "CONFIGURATION ERROR: GITHUB_TOKEN is invalid or expired (HTTP 401 Unauthorized from GitHub API)."
                )
            if resp.status_code == 404:
                raise RuntimeError(
                    f"CONFIGURATION ERROR: Repository {owner}/{repo} was not found or GITHUB_TOKEN has no access (HTTP 404)."
                )

            # Inspect X-OAuth-Scopes header (present on OAuth and classic tokens)
            oauth_scopes = resp.headers.get("x-oauth-scopes", "")
            if oauth_scopes:
                scopes_list = [s.strip() for s in oauth_scopes.split(",")]
                has_write_scope = any(s in ("repo", "public_repo", "write:discussion") for s in scopes_list)
                if not has_write_scope:
                    raise RuntimeError(
                        f"CONFIGURATION ERROR: GITHUB_TOKEN lacks required repository write scope. "
                        f"Found X-OAuth-Scopes: '{oauth_scopes}'. Required: 'repo' or 'public_repo' to open PRs and push commits."
                    )
            else:
                # Fine-grained PATs do not return x-oauth-scopes header, and GET /repos permissions reflects user role
                # rather than fine-grained token-level restrictions.
                # Check cache first to avoid unbounded real GitHub API probe calls on every restart/redeploy.
                ttl_seconds = int(os.getenv("GITHUB_SCOPE_PROBE_TTL_SECONDS", str(_DEFAULT_PROBE_TTL_SECONDS)))
                if _get_cached_scope_probe(token, owner, repo, ttl_seconds):
                    return

                # Send a probe to POST /repos/{owner}/{repo}/pulls to definitively verify pull_requests:write permission.
                probe_resp = httpx.post(
                    f"https://api.github.com/repos/{owner}/{repo}/pulls",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "RISE-Startup-Validator",
                    },
                    json={
                        "title": "RISE startup scope verification probe",
                        "head": "rise-startup-scope-probe-nonexistent",
                        "base": "main",
                    },
                    timeout=5.0,
                )
                if probe_resp.status_code == 403:
                    raise RuntimeError(
                        f"CONFIGURATION ERROR: GITHUB_TOKEN fine-grained PAT lacks 'pull_requests:write' permission. "
                        f"GitHub rejected POST /repos/{owner}/{repo}/pulls with HTTP 403 Forbidden: {probe_resp.text}. "
                        "Refusing to start."
                    )
                if probe_resp.status_code in (422, 201):
                    # Verify 422 specifically confirms validation on head branch
                    if probe_resp.status_code == 422:
                        probe_data = probe_resp.json() if probe_resp.content else {}
                        errors = probe_data.get("errors", [])
                        is_head_err = any(isinstance(e, dict) and e.get("field") == "head" for e in errors)
                        msg = probe_data.get("message", "")
                        if not is_head_err and "Validation Failed" not in msg and "head" not in str(probe_data):
                            raise RuntimeError(
                                f"CONFIGURATION ERROR: GITHUB_TOKEN probe returned unexpected 422 error: {probe_resp.text}"
                            )
                    # Cache successful probe result
                    _save_cached_scope_probe(token, owner, repo)
                else:
                    raise RuntimeError(
                        f"CONFIGURATION ERROR: Unexpected response from GitHub pulls endpoint (HTTP {probe_resp.status_code}): {probe_resp.text}"
                    )
        except RuntimeError:
            raise
        except Exception as e:
            if is_prod_env:
                raise RuntimeError(
                    f"CONFIGURATION ERROR: Failed to verify GitHub credentials on startup: {e}"
                ) from e


# Run the guards before anything else is imported so misconfigured deploys fail immediately
_assert_safe_test_mode()
_validate_github_configuration()

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.src.middleware.envelope import (
    http_exception_handler,
    validation_exception_handler,
)
from apps.api.src.routers import ALL_ROUTERS

app = FastAPI(
    title="RISE API",
    description="RISE — Autonomous Incident Remediation System API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

from fastapi.middleware.cors import CORSMiddleware

# Enable CORS for frontend dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handlers for standard envelope response
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# Include all routers under /api/v1 prefix (health checks also available at root)
for r in ALL_ROUTERS:
    app.include_router(r, prefix="/api/v1")
    if r.prefix in ("", "/healthz", "/readyz"):
        app.include_router(r)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("apps.api.src.main:app", host="0.0.0.0", port=8000, reload=True)
