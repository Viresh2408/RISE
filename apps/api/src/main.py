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


# Run the guard before anything else is imported so a misconfigured deploy
# fails immediately, not after the first authenticated request arrives.
_assert_safe_test_mode()

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
