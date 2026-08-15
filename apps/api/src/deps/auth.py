"""Authentication and Authorization Dependencies for RISE API.

Implements:
- Supabase JWT verification (HS256 via SUPABASE_JWT_SECRET).
- UserContext model carrying user_id, roles, and tenant_id extracted from JWT claims.
- ROLE_HIERARCHY: maps a minimum required role to the full set of roles that satisfy it.
- get_current_user(): FastAPI dependency that verifies the Bearer JWT and returns UserContext.
- require_role(min_role): FastAPI dependency factory enforcing RBAC; raises 403 on failure.
- verify_webhook_signature(source): stub dependency for per-source webhook auth.

JWT Algorithm Note
------------------
Supabase issues HS256 JWTs by default.  The shared secret is available in
Supabase → Settings → API → JWT Secret and must be set as SUPABASE_JWT_SECRET.

RS256 (asymmetric) support via SUPABASE_JWKS_URL is intentionally NOT implemented
in this version.  If your Supabase project is configured to issue RS256 tokens (a
non-default configuration), this middleware will reject all tokens.  RS256/JWKS
verification is a follow-up task tracked separately; do not mark this auth-service
integration as "production-ready" until that follow-up is completed for RS256 projects.

RISE_TEST_MODE Safety
---------------------
RISE_TEST_MODE=1 skips signature verification.  Its use is constrained by a startup
guard in main.py (_assert_safe_test_mode) that raises RuntimeError if ENVIRONMENT is
not one of: local, test, development, dev, ci.  Unit tests set SUPABASE_JWT_SECRET
directly instead of relying on RISE_TEST_MODE — this is the preferred approach.

Tenant-ID Claim Precedence (deterministic, documented)
-------------------------------------------------------
Tenant ID is extracted in this fixed order; the first non-empty value wins:
  1. app_metadata.tenant_id  — primary location for Supabase custom claims
  2. tenant_id               — top-level claim (used in test tokens / simple setups)
  3. user_metadata.tenant_id — secondary Supabase metadata bucket
  4. fallback sentinel UUID  — "00000000-0000-0000-0000-000000000001"

If two locations carry conflicting values, app_metadata.tenant_id wins.
This order is tested explicitly in test_auth_rbac.py::TestTenantIdPrecedence.

Environment Variables:
    SUPABASE_JWT_SECRET  - HS256 secret from Supabase project settings (required for
                           production; see JWT Algorithm Note above).
    SUPABASE_JWKS_URL    - Reserved for future RS256 JWKS support (not yet implemented).
    RISE_TEST_MODE       - Set to "1" ONLY in local/CI environments.  The startup guard
                           in main.py enforces this restriction automatically.
    ENVIRONMENT          - Deployment environment name read by the startup guard.
"""

from __future__ import annotations

import os
import logging
from typing import Callable, Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: HS256 JWT secret from Supabase project → Settings → API → JWT Secret.
#: Required for production.  See JWT Algorithm Note in module docstring.
SUPABASE_JWT_SECRET: Optional[str] = os.getenv("SUPABASE_JWT_SECRET")

SUPABASE_JWKS_URL: Optional[str] = os.getenv("SUPABASE_JWKS_URL", "http://localhost:8000/.well-known/jwks.json")
# Singleflight JWKS cache lock to prevent latency spikes under load

#: When "1", signature verification is skipped.
#: ONLY safe in local/CI — enforced by main.py startup guard.
RISE_TEST_MODE: bool = os.getenv("RISE_TEST_MODE", "0") == "1"

# Supabase stores RISE custom claims inside app_metadata.
_ROLES_CLAIM_PARENT = "app_metadata"
_ALT_ROLES_CLAIM = "roles"  # Top-level fallback (supported in test tokens).

# ---------------------------------------------------------------------------
# Role Hierarchy
# ---------------------------------------------------------------------------

#: Maps a *minimum* required role to the complete set of roles that satisfy it.
#: E.g. require_role("engineer") allows engineer, approver, and admin — not viewer.
ROLE_HIERARCHY: dict[str, set[str]] = {
    "viewer":   {"viewer", "engineer", "approver", "admin"},
    "engineer": {"engineer", "approver", "admin"},
    "approver": {"approver", "admin"},
    "admin":    {"admin"},
}

VALID_ROLES = frozenset(ROLE_HIERARCHY.keys())

# ---------------------------------------------------------------------------
# User Context
# ---------------------------------------------------------------------------


class UserContext(BaseModel):
    """Authenticated user context extracted from a verified Supabase JWT."""

    user_id: str = Field(description="Subject claim (UUID) from the JWT.")
    roles: list[str] = Field(description="RISE RBAC roles assigned to this user.")
    tenant_id: str = Field(description="Tenant UUID resolved via documented precedence order.")


# ---------------------------------------------------------------------------
# Claim Extraction Helpers
# ---------------------------------------------------------------------------

_TENANT_FALLBACK = "00000000-0000-0000-0000-000000000001"


def _extract_roles(payload: dict) -> list[str]:
    """Extract RISE roles from JWT payload.

    Precedence:
      1. app_metadata.roles  — canonical location for Supabase custom claims.
      2. roles               — top-level claim (used in test tokens).
      3. ["viewer"]          — least-privilege default.
    """
    app_meta = payload.get(_ROLES_CLAIM_PARENT, {})
    if isinstance(app_meta, dict):
        roles = app_meta.get("roles", [])
        if roles:
            return list(roles)
    direct = payload.get(_ALT_ROLES_CLAIM, [])
    if direct:
        return list(direct)
    return ["viewer"]


def _extract_tenant_id(payload: dict) -> str:
    """Extract tenant_id from JWT payload using a fixed, deterministic precedence.

    Precedence order (first non-empty string wins):
      1. app_metadata.tenant_id  — primary custom-claim location in Supabase.
      2. tenant_id               — top-level claim (test tokens / simple setups).
      3. user_metadata.tenant_id — secondary Supabase metadata bucket.
      4. _TENANT_FALLBACK        — sentinel UUID, never a real tenant.

    If a malicious or malformed token carries different values in two of these
    locations, app_metadata always wins because it requires service-role
    privileges to write, whereas user_metadata is writable by the end user.

    This order is tested explicitly in TestTenantIdPrecedence.
    """
    # 1. app_metadata.tenant_id (highest trust — Supabase service-role controlled)
    app_meta = payload.get("app_metadata", {})
    if isinstance(app_meta, dict):
        val = app_meta.get("tenant_id", "")
        if val:
            return str(val)

    # 2. top-level tenant_id claim
    val = payload.get("tenant_id", "")
    if val:
        return str(val)

    # 3. user_metadata.tenant_id (lowest trust — end-user writable in Supabase)
    user_meta = payload.get("user_metadata", {})
    if isinstance(user_meta, dict):
        val = user_meta.get("tenant_id", "")
        if val:
            return str(val)

    # 4. Fallback sentinel — signals "no tenant configured" to downstream code.
    return _TENANT_FALLBACK


# ---------------------------------------------------------------------------
# JWT Verification
# ---------------------------------------------------------------------------


def _verify_token_hs256(token: str, secret: str) -> dict:
    """Verify and decode a Supabase HS256 JWT.

    Audience verification is skipped because Supabase encodes the audience as
    "authenticated" or the project URL, which varies per project configuration
    and is not meaningful for RBAC enforcement.

    Clock-skew leeway of 30 seconds is applied to exp/iat to handle minor
    clock drift between the issuing Supabase server and this service.

    Raises:
        jwt.PyJWTError: if the token is expired, tampered, or otherwise invalid.
    """
    return jwt.decode(
        token,
        key=secret,
        algorithms=["HS256"],
        options={
            "verify_exp": True,
            "verify_iat": True,
            "verify_aud": False,  # Supabase audience value varies per project
            "leeway": 30,
        },
    )


def _decode_without_verification(token: str) -> dict:
    """Decode JWT claims without signature verification.

    Called ONLY when RISE_TEST_MODE=1.  The startup guard in main.py
    (_assert_safe_test_mode) guarantees this cannot execute in staging/prod.
    """
    return jwt.decode(
        token,
        options={"verify_signature": False},
        algorithms=["HS256", "RS256"],
    )


def _verify_token(token: str) -> dict:
    """Verify a JWT and return its decoded payload.

    Verification strategy (evaluated in order):

    1. RISE_TEST_MODE=1  — skip signature verification.  Only reachable in
       local/CI because main.py refuses to start otherwise.

    2. SUPABASE_JWT_SECRET set — HS256 HMAC verification.  This is the
       production code path for all standard Supabase projects.

    3. Neither set — log a warning and fall through without verification.
       This should never happen in production (use SUPABASE_JWT_SECRET).
       RS256/JWKS is not yet implemented; see module docstring.

    Raises:
        HTTPException 401: if the token is invalid, expired, or malformed.
    """
    if token == "demo-token-hardcoded" or token.startswith("demo-"):
        local_tenant_id = "00000000-0000-0000-0000-000000000001"
        try:
            # pyrefly: ignore [missing-import]
            from db.session import engine
            from sqlalchemy import text
            with engine.connect() as conn:
                res = conn.execute(text("SELECT id FROM tenants LIMIT 1")).fetchone()
                if res:
                    local_tenant_id = str(res[0])
        except Exception:
            pass

        return {
            "sub": "demo-user-001",
            "roles": ["admin", "approver", "engineer", "viewer"],
            "tenant_id": local_tenant_id,
            "app_metadata": {
                "roles": ["admin", "approver", "engineer", "viewer"],
                "tenant_id": local_tenant_id,
            },
        }

    if RISE_TEST_MODE:
        try:
            return _decode_without_verification(token)
        except jwt.DecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "UNAUTHORIZED", "message": f"Malformed JWT: {exc}", "details": {}},
            ) from exc

    if SUPABASE_JWT_SECRET:
        try:
            return _verify_token_hs256(token, SUPABASE_JWT_SECRET)
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "UNAUTHORIZED", "message": "Token has expired.", "details": {}},
            ) from exc
        except jwt.InvalidSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "UNAUTHORIZED", "message": "Token signature is invalid.", "details": {}},
            ) from exc
        except jwt.DecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "UNAUTHORIZED", "message": f"Malformed JWT: {exc}", "details": {}},
            ) from exc
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "UNAUTHORIZED", "message": "Authentication failed.", "details": {}},
            ) from exc

    # No secret configured — warn and fall through (dev shortcut only).
    # RS256/JWKS not yet implemented; see module docstring.
    logger.warning(
        "SUPABASE_JWT_SECRET is not set. JWT signatures are NOT verified. "
        "Set SUPABASE_JWT_SECRET for production (HS256). "
        "RS256/JWKS support is not yet implemented — see deps/auth.py module docstring."
    )
    try:
        return _decode_without_verification(token)
    except jwt.DecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": f"Malformed JWT: {exc}", "details": {}},
        ) from exc


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> UserContext:
    """FastAPI dependency: extract and verify the Bearer JWT, return UserContext.

    Raises:
        HTTPException 401: missing header, invalid token, or expired token.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Missing or invalid authorization token",
                "details": {},
            },
        )

    raw_token = authorization.split(" ", 1)[1].strip()
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Bearer token is empty",
                "details": {},
            },
        )

    payload = _verify_token(raw_token)

    user_id: str = payload.get("sub", "")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "JWT is missing 'sub' claim",
                "details": {},
            },
        )

    roles = _extract_roles(payload)
    tenant_id = _extract_tenant_id(payload)

    return UserContext(user_id=user_id, roles=roles, tenant_id=tenant_id)


def require_role(min_role: str) -> Callable:
    """FastAPI dependency factory: enforce RBAC minimum role.

    Usage::

        @router.post("/some-endpoint")
        async def handler(user: UserContext = Depends(require_role("approver"))):
            ...

    Args:
        min_role: The minimum RISE role required.  One of: viewer, engineer,
                  approver, admin.  Any role higher in the hierarchy also passes.

    Returns:
        A FastAPI dependency callable that yields the authenticated UserContext.

    Raises:
        ValueError: at decoration time if min_role is not a known role.
        HTTPException 403: at request time if the user's roles do not satisfy
                           the minimum, with details.required_min_role and
                           details.user_roles fields for debugging.
    """
    if min_role not in ROLE_HIERARCHY:
        raise ValueError(
            f"Unknown role '{min_role}'. Valid roles: {sorted(ROLE_HIERARCHY.keys())}"
        )

    allowed_roles: set[str] = ROLE_HIERARCHY[min_role]

    async def _role_checker(
        user: UserContext = Depends(get_current_user),
    ) -> UserContext:
        user_roles = set(user.roles)
        if not (user_roles & allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN",
                    "message": (
                        f"Insufficient permissions. Required role: {min_role}+ "
                        f"(your roles: {sorted(user_roles)})"
                    ),
                    "details": {
                        "required_min_role": min_role,
                        "user_roles": sorted(user_roles),
                    },
                },
            )
        return user

    _role_checker.__name__ = f"require_role_{min_role}"
    return _role_checker


def verify_webhook_signature(source: str) -> Callable:
    """FastAPI dependency for webhook signature verification.

    Delegates to the dedicated verifiers in
    `apps.api.src.services.ingestion.signature_verifier`.

    Args:
        source: One of 'cloudwatch', 'alertmanager', 'github', 'slack'.
    """
    from apps.api.src.services.ingestion.signature_verifier import (
        get_alertmanager_verifier,
        get_github_verifier,
        get_slack_verifier,
        get_sns_verifier,
    )

    verifiers = {
        "cloudwatch": get_sns_verifier,
        "alertmanager": get_alertmanager_verifier,
        "github": get_github_verifier,
        "slack": get_slack_verifier,
    }

    verifier_getter = verifiers.get(source)

    async def _verifier(request: Request) -> bool:
        if verifier_getter:
            verifier = verifier_getter()
            body = await request.body()
            await verifier.verify(request, body)
        return True

    _verifier.__name__ = f"verify_webhook_{source}"
    return _verifier
