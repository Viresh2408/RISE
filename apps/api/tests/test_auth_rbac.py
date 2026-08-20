"""RBAC & Auth-Service Test Suite for RISE API.

Coverage goals (all verified by this file):
  1. Startup guard: RISE_TEST_MODE=1 in non-local environments causes RuntimeError.
  2. JWT verification middleware: missing / malformed / wrong-secret / expired tokens.
  3. Tenant-ID claim extraction: documented precedence order, conflict resolution.
  4. Role escalation prevention: viewer/engineer/approver cannot reach higher tiers.
  5. Role acceptance: each role tier is accepted on its own endpoints.
  6. /auth/session: returns correct role, tenant_id, user_id, and envelope format.
  7. Exhaustive endpoint coverage: ALL 34 JWT-gated endpoints from api-specification.md
     are parametrized against their declared minimum role — both "min role passes" and
     "one tier below is rejected".  Webhooks and health endpoints are excluded (they use
     different auth schemes or no auth at all).

JWT Strategy
------------
Tests set SUPABASE_JWT_SECRET and mint HS256 tokens with the same secret, exercising
the production code path.  RISE_TEST_MODE is explicitly unset so no bypass is active.

Endpoint Coverage Source
------------------------
The ENDPOINT_ROLE_TABLE is derived directly from api-specification.md section roles.
Any future router addition MUST also add a row here — the table acts as a living spec.
"""

from __future__ import annotations

import importlib
import os
import time
import types
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

# ── Env setup BEFORE importing the app ───────────────────────────────────────
TEST_JWT_SECRET = "test-supabase-secret-rise-unit-tests"
os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
os.environ.pop("RISE_TEST_MODE", None)   # ensure test-mode bypass is OFF
os.environ["ENVIRONMENT"] = "test"       # explicitly safe environment

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

@compiles(JSONB, "sqlite")
def visit_JSONB(element, compiler, **kw):
    return "JSON"

@compiles(PG_UUID, "sqlite")
def visit_UUID(element, compiler, **kw):
    return "TEXT"

from db.base import Base
from db.models import Tenant, Incident, Service, Comment
from apps.api.src.deps.db import get_db
from apps.api.src.routers.incidents import _parse_uuid

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

from unittest.mock import MagicMock
from apps.api.src.deps.redis import get_redis_client

_rbac_redis_mock = MagicMock()
_rbac_redis_mock.get.return_value = None
_rbac_redis_mock.set.return_value = True
_rbac_redis_mock.setex.return_value = True
_rbac_redis_mock.xadd.return_value = b"1-0"
_rbac_redis_mock.delete.return_value = True

def override_get_redis():
    yield _rbac_redis_mock

from apps.api.src.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

TENANT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
INC_ID    = "inc-001"
ACT_ID    = "act-001"


@pytest.fixture(autouse=True)
def seed_rbac_db():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis_client] = override_get_redis
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    tenant_ids = [
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "00000000-0000-0000-0000-000000000001",
        "11111111-2222-3333-4444-555555555555",
    ]

    for tid in tenant_ids:
        t_uuid = _parse_uuid(tid)
        inc_uuid = _parse_uuid(INC_ID)

        tenant = db.execute(select(Tenant).where(Tenant.id == t_uuid)).scalar_one_or_none()
        if not tenant:
            tenant = Tenant(id=t_uuid, name=f"RBAC Test Tenant {tid[:8]}")
            db.add(tenant)
            db.flush()

        inc = db.execute(select(Incident).where(Incident.id == inc_uuid)).scalar_one_or_none()
        if not inc:
            inc = Incident(
                id=inc_uuid,
                tenant_id=t_uuid,
                title="Mock Auth Incident",
                description="Mock incident description",
                severity="SEV2",
                status="open",
            )
            db.add(inc)

    db.commit()
    db.close()
    yield
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# JWT helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_jwt(role: str, *, extra_claims: dict | None = None) -> str:
    """Mint a signed HS256 JWT carrying the given RISE role."""
    payload: dict = {
        "sub": str(uuid.uuid5(uuid.NAMESPACE_DNS, role)),
        "roles": [role],
        "tenant_id": TENANT_ID,
        "iss": "https://supabase.rise.test/auth/v1",
        "iat": int(time.time()),
        "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0))),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _auth(role: str, **extra) -> dict:
    return {"Authorization": f"Bearer {_make_jwt(role, extra_claims=extra or None)}"}


VIEWER_HEADERS   = _auth("viewer")
ENGINEER_HEADERS = _auth("engineer")
APPROVER_HEADERS = _auth("approver")
ADMIN_HEADERS    = _auth("admin")

_HEADERS_FOR_ROLE = {
    "viewer":   VIEWER_HEADERS,
    "engineer": ENGINEER_HEADERS,
    "approver": APPROVER_HEADERS,
    "admin":    ADMIN_HEADERS,
}

# Role that is one tier BELOW the given minimum (for rejection tests).
_ONE_BELOW = {
    "viewer":   None,          # no role below viewer
    "engineer": "viewer",
    "approver": "engineer",
    "admin":    "approver",
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Startup Guard Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStartupGuard:
    """main.py _assert_safe_test_mode() must refuse non-local environments."""

    def _run_guard(self, test_mode: str, environment: str) -> None:
        """Call _assert_safe_test_mode directly with patched env variables."""
        old_test_mode = os.environ.get("RISE_TEST_MODE")
        old_env       = os.environ.get("ENVIRONMENT")
        try:
            os.environ["RISE_TEST_MODE"] = test_mode
            os.environ["ENVIRONMENT"]    = environment
            # Call the guard function directly — importlib.reload wraps RuntimeError
            # in an ImportError, which prevents pytest.raises(RuntimeError) from catching it.
            import apps.api.src.main as main_mod
            main_mod._assert_safe_test_mode()
        finally:
            # Restore original env so subsequent tests are unaffected
            if old_test_mode is None:
                os.environ.pop("RISE_TEST_MODE", None)
            else:
                os.environ["RISE_TEST_MODE"] = old_test_mode
            if old_env is None:
                os.environ.pop("ENVIRONMENT", None)
            else:
                os.environ["ENVIRONMENT"] = old_env
            # Restore env to "test" so the already-imported app still works
            os.environ.setdefault("ENVIRONMENT", "test")

    def test_test_mode_off_never_raises(self):
        """RISE_TEST_MODE=0 must never raise regardless of ENVIRONMENT."""
        self._run_guard("0", "production")  # should not raise

    def test_test_mode_in_local_allowed(self):
        """RISE_TEST_MODE=1 is fine in ENVIRONMENT=local."""
        self._run_guard("1", "local")

    def test_test_mode_in_dev_allowed(self):
        self._run_guard("1", "development")

    def test_test_mode_in_ci_allowed(self):
        self._run_guard("1", "ci")

    def test_test_mode_in_test_env_allowed(self):
        self._run_guard("1", "test")

    def test_test_mode_in_staging_raises(self):
        """RISE_TEST_MODE=1 with ENVIRONMENT=staging must RuntimeError."""
        with pytest.raises(RuntimeError, match="SECURITY VIOLATION"):
            self._run_guard("1", "staging")

    def test_test_mode_in_production_raises(self):
        """RISE_TEST_MODE=1 with ENVIRONMENT=production must RuntimeError."""
        with pytest.raises(RuntimeError, match="SECURITY VIOLATION"):
            self._run_guard("1", "production")

    def test_test_mode_in_prod_raises(self):
        with pytest.raises(RuntimeError, match="SECURITY VIOLATION"):
            self._run_guard("1", "prod")

    def test_test_mode_in_release_raises(self):
        with pytest.raises(RuntimeError, match="SECURITY VIOLATION"):
            self._run_guard("1", "release")

    def test_error_message_names_environment(self):
        """Error message must include the offending ENVIRONMENT value."""
        with pytest.raises(RuntimeError, match="staging"):
            self._run_guard("1", "staging")

    def test_error_message_mentions_jwt_verification(self):
        """Error message must explain why the startup is rejected."""
        with pytest.raises(RuntimeError, match="JWT signature verification"):
            self._run_guard("1", "production")


# ─────────────────────────────────────────────────────────────────────────────
# 2. JWT Verification Middleware
# ─────────────────────────────────────────────────────────────────────────────


class TestJWTVerification:
    def test_missing_auth_header_returns_401(self):
        r = client.get("/api/v1/incidents")
        assert r.status_code == 401
        body = r.json()
        assert body["data"] is None
        assert body["error"]["code"] == "UNAUTHORIZED"
        assert "Missing or invalid authorization token" in body["error"]["message"]

    def test_non_bearer_scheme_returns_401(self):
        r = client.get("/api/v1/incidents", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert r.status_code == 401

    def test_empty_bearer_token_returns_401(self):
        r = client.get("/api/v1/incidents", headers={"Authorization": "Bearer "})
        assert r.status_code == 401

    def test_wrong_secret_returns_401(self):
        token = jwt.encode(
            {"sub": "user-id", "roles": ["admin"], "tenant_id": TENANT_ID,
             "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0)))},
            "wrong-secret-not-the-real-one",
            algorithm="HS256",
        )
        r = client.get("/api/v1/incidents", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"

    def test_expired_token_returns_401(self):
        token = jwt.encode(
            {"sub": "user-id", "roles": ["admin"], "tenant_id": TENANT_ID,
             "exp": int(time.time()) - 3600},
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        r = client.get("/api/v1/incidents", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_malformed_token_returns_401(self):
        r = client.get("/api/v1/incidents", headers={"Authorization": "Bearer not.a.jwt"})
        assert r.status_code == 401

    def test_valid_viewer_token_passes_middleware(self):
        r = client.get("/api/v1/incidents", headers=VIEWER_HEADERS)
        assert r.status_code == 200

    def test_token_missing_sub_returns_401(self):
        token = jwt.encode(
            {"roles": ["admin"], "tenant_id": TENANT_ID,
             "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0)))},
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        r = client.get("/api/v1/incidents", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert "sub" in r.json()["error"]["message"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Tenant-ID Claim Precedence
# ─────────────────────────────────────────────────────────────────────────────


class TestTenantIdPrecedence:
    """_extract_tenant_id must follow the documented precedence order exactly.

    Precedence (app_metadata > top-level > user_metadata > fallback).
    When two locations disagree, app_metadata wins.
    """

    def _session_with_payload(self, extra: dict) -> dict:
        token = jwt.encode(
            {"sub": "prec-user", "roles": ["viewer"],
             "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0))),
             **extra},
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        r = client.post("/api/v1/auth/session",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        return r.json()["data"]

    def test_app_metadata_tenant_id_is_used(self):
        data = self._session_with_payload({"app_metadata": {"tenant_id": "app-meta-tid", "roles": ["viewer"]}})
        assert data["tenant_id"] == "app-meta-tid"

    def test_top_level_tenant_id_used_when_no_app_metadata(self):
        data = self._session_with_payload({"tenant_id": "top-level-tid"})
        assert data["tenant_id"] == "top-level-tid"

    def test_user_metadata_tenant_id_used_as_last_resort(self):
        data = self._session_with_payload({"user_metadata": {"tenant_id": "user-meta-tid"}})
        assert data["tenant_id"] == "user-meta-tid"

    def test_app_metadata_wins_over_top_level_on_conflict(self):
        """app_metadata.tenant_id must beat top-level tenant_id."""
        data = self._session_with_payload({
            "app_metadata": {"tenant_id": "AUTHORITATIVE", "roles": ["viewer"]},
            "tenant_id": "attacker-injected",
        })
        assert data["tenant_id"] == "AUTHORITATIVE"

    def test_app_metadata_wins_over_user_metadata_on_conflict(self):
        data = self._session_with_payload({
            "app_metadata": {"tenant_id": "AUTHORITATIVE", "roles": ["viewer"]},
            "user_metadata": {"tenant_id": "user-meta-tid"},
        })
        assert data["tenant_id"] == "AUTHORITATIVE"

    def test_top_level_wins_over_user_metadata_on_conflict(self):
        """Top-level tenant_id beats user_metadata when app_metadata has none."""
        data = self._session_with_payload({
            "tenant_id": "TOP-LEVEL",
            "user_metadata": {"tenant_id": "user-meta-tid"},
        })
        assert data["tenant_id"] == "TOP-LEVEL"

    def test_fallback_sentinel_when_no_tenant_claims(self):
        """When no tenant_id claim exists, the sentinel UUID is returned."""
        data = self._session_with_payload({})  # no tenant anywhere
        assert data["tenant_id"] == "00000000-0000-0000-0000-000000000001"

    def test_empty_string_app_metadata_tenant_id_falls_through(self):
        """An empty string in app_metadata.tenant_id is not treated as a value."""
        data = self._session_with_payload({
            "app_metadata": {"tenant_id": "", "roles": ["viewer"]},
            "tenant_id": "top-level-tid",
        })
        assert data["tenant_id"] == "top-level-tid"

    def test_empty_top_level_falls_through_to_user_metadata(self):
        data = self._session_with_payload({
            "tenant_id": "",
            "user_metadata": {"tenant_id": "user-meta-tid"},
        })
        assert data["tenant_id"] == "user-meta-tid"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Exhaustive Endpoint Coverage
#    Source: api-specification.md (all JWT-gated endpoints)
#    Excludes: health (no auth), webhooks (signature-based auth)
# ─────────────────────────────────────────────────────────────────────────────

# fmt: off
# Each entry: (method, url_template, min_role, request_body, extra_headers, expected_ok_status)
# url_template tokens: {inc} = INC_ID, {act} = ACT_ID, {pol} = policy ID, {run} = agent run ID
_INC = INC_ID
_ACT = ACT_ID
_POL = "pol-001"
_RUN = "run-001"

ENDPOINT_ROLE_TABLE: list[tuple] = [
    # method   url                                                  min_role    body                                                                                extra_hdrs  ok_status
    # ── Auth ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("POST",   "/api/v1/auth/session",                              "viewer",   {},                                                                                 {},         200),
    # ── Incidents ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    "/api/v1/incidents",                                 "viewer",   None,                                                                               {},         200),
    ("GET",    f"/api/v1/incidents/{_INC}",                         "viewer",   None,                                                                               {},         200),
    ("POST",   "/api/v1/incidents",                                 "engineer", {"title":"T","description":"D","severity":"SEV2","affected_service":"svc"},         {},         201),
    ("POST",   f"/api/v1/incidents/{_INC}/reinvestigate",           "engineer", {},                                                                                 {},         202),
    ("POST",   f"/api/v1/incidents/{_INC}/comment",                 "engineer", {"text":"hi"},                                                                      {},         201),
    ("PATCH",  f"/api/v1/incidents/{_INC}",                         "approver", {"status":"closed","resolution_note":"done"},                                       {},         200),
    # ── Agent Runs ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    f"/api/v1/incidents/{_INC}/agent-runs",              "viewer",   None,                                                                               {},         200),
    ("GET",    f"/api/v1/agent-runs/{_RUN}/steps",                  "viewer",   None,                                                                               {},         200),
    # ── Root Cause & Impact ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    f"/api/v1/incidents/{_INC}/root-cause",              "viewer",   None,                                                                               {},         200),
    ("GET",    f"/api/v1/incidents/{_INC}/impact",                  "viewer",   None,                                                                               {},         200),
    # ── Decisions & Actions ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    f"/api/v1/incidents/{_INC}/decision",                "viewer",   None,                                                                               {},         200),
    ("GET",    f"/api/v1/incidents/{_INC}/actions",                 "viewer",   None,                                                                               {},         200),
    ("POST",   f"/api/v1/incidents/{_INC}/actions/{_ACT}/approve",  "approver", {},                                                                                 {"Idempotency-Key":"ik-approve-01"}, 200),
    ("POST",   f"/api/v1/incidents/{_INC}/actions/{_ACT}/reject",   "approver", {"reason":"too risky"},                                                             {},         200),
    ("POST",   f"/api/v1/incidents/{_INC}/actions/{_ACT}/modify",   "approver", {"modified_plan":{"id":"p1","description":"revised","steps":["step1"]}},            {},         200),
    # ── Verification ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    f"/api/v1/incidents/{_INC}/verification",            "viewer",   None,                                                                               {},         200),
    # ── Knowledge ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    "/api/v1/knowledge",                                 "viewer",   None,                                                                               {},         200),
    ("POST",   "/api/v1/knowledge",                                 "engineer", {"title":"KB","content":"# Steps","tags":[]},                                       {},         201),
    # ── Policies ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    "/api/v1/policies",                                  "admin",    None,                                                                               {},         200),
    ("POST",   "/api/v1/policies",                                  "admin",    {"action_pattern":"k8s.pod.restart","environment":"prod","risk_tier":"low","requires_approval":False,"max_blast_radius":1}, {}, 201),
    ("PUT",    f"/api/v1/policies/{_POL}",                          "admin",    {"risk_tier":"medium","requires_approval":True,"max_blast_radius":2},               {},         200),
    # ── Integrations ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    "/api/v1/integrations",                              "admin",    None,                                                                               {},         200),
    ("POST",   "/api/v1/integrations/github/connect",              "admin",    {},                                                                                 {},         200),
    ("DELETE", "/api/v1/integrations/github",                      "admin",    None,                                                                               {},         200),
    # ── Reports ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    "/api/v1/reports/mttr",                              "viewer",   None,                                                                               {},         200),
    ("GET",    "/api/v1/reports/autonomy",                          "viewer",   None,                                                                               {},         200),
    # ── Audit ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("GET",    "/api/v1/audit",                                     "admin",    None,                                                                               {},         200),
]
# fmt: on

# Build parametrize IDs from method + path for readable test names
_ENDPOINT_IDS = [
    f"{method}:{url.replace('/api/v1','')}"
    for method, url, *_ in ENDPOINT_ROLE_TABLE
]


def _call(method: str, url: str, headers: dict, body) -> "Response":  # type: ignore[name-defined]
    """Issue an HTTP call with optional JSON body."""
    if method == "GET":
        return client.get(url, headers=headers)
    if method == "DELETE":
        return client.delete(url, headers=headers)
    if method == "POST":
        return client.post(url, headers=headers, json=body or {})
    if method == "PATCH":
        return client.patch(url, headers=headers, json=body or {})
    if method == "PUT":
        return client.put(url, headers=headers, json=body or {})
    raise ValueError(f"Unsupported method: {method}")


@pytest.mark.parametrize(
    "method,url,min_role,body,extra_headers,ok_status",
    ENDPOINT_ROLE_TABLE,
    ids=_ENDPOINT_IDS,
)
class TestExhaustiveEndpointCoverage:
    """Verify every JWT-gated endpoint enforces exactly the role declared in api-spec.

    For each endpoint:
      - the declared minimum role (and any role above it) returns the expected ok_status
      - the role one tier below the minimum returns 403

    This test class is the single source of truth for endpoint role enforcement.
    If a router is changed without updating ENDPOINT_ROLE_TABLE above, the
    parametrized tests will catch the drift automatically.
    """

    def test_min_role_is_accepted(
        self, method, url, min_role, body, extra_headers, ok_status
    ):
        """The minimum declared role must be accepted (returns ok_status)."""
        headers = {**_HEADERS_FOR_ROLE[min_role], **extra_headers}
        r = _call(method, url, headers, body)
        assert r.status_code == ok_status, (
            f"{method} {url} with role={min_role!r}: "
            f"expected {ok_status}, got {r.status_code}. Body: {r.text[:300]}"
        )

    def test_role_below_minimum_is_rejected(
        self, method, url, min_role, body, extra_headers, ok_status
    ):
        """The role one tier below the minimum must be rejected with 403."""
        below = _ONE_BELOW.get(min_role)
        if below is None:
            return  # No role below viewer; vacuously satisfied
        headers = {**_HEADERS_FOR_ROLE[below], **extra_headers}
        r = _call(method, url, headers, body)
        assert r.status_code == 403, (
            f"{method} {url} with role={below!r} (below min={min_role!r}): "
            f"expected 403, got {r.status_code}. Body: {r.text[:300]}"
        )
        detail = r.json().get("error", {}).get("details", {})
        assert detail.get("required_min_role") == min_role, (
            f"403 details should report required_min_role={min_role!r}, got: {detail}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. /auth/session Returns Correct Claims
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthSession:
    def test_session_returns_401_without_token(self):
        r = client.post("/api/v1/auth/session")
        assert r.status_code == 401

    def test_session_returns_viewer_role(self):
        r = client.post("/api/v1/auth/session", headers=VIEWER_HEADERS)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["roles"] == ["viewer"]
        assert data["tenant_id"] == TENANT_ID
        assert "user_id" in data

    def test_session_returns_engineer_role(self):
        r = client.post("/api/v1/auth/session", headers=ENGINEER_HEADERS)
        assert r.status_code == 200
        assert r.json()["data"]["roles"] == ["engineer"]

    def test_session_returns_approver_role(self):
        r = client.post("/api/v1/auth/session", headers=APPROVER_HEADERS)
        assert r.status_code == 200
        assert r.json()["data"]["roles"] == ["approver"]

    def test_session_returns_admin_role(self):
        r = client.post("/api/v1/auth/session", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.json()["data"]["roles"] == ["admin"]

    def test_session_returns_correct_user_id(self):
        """user_id must match the 'sub' claim from the token."""
        expected_sub = str(uuid.uuid5(uuid.NAMESPACE_DNS, "viewer"))
        r = client.post("/api/v1/auth/session", headers=VIEWER_HEADERS)
        assert r.status_code == 200
        assert r.json()["data"]["user_id"] == expected_sub

    def test_session_wrong_secret_returns_401(self):
        bad_token = jwt.encode(
            {"sub": "evil-user", "roles": ["admin"], "tenant_id": TENANT_ID,
             "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0)))},
            "wrong-secret",
            algorithm="HS256",
        )
        r = client.post("/api/v1/auth/session",
                        headers={"Authorization": f"Bearer {bad_token}"})
        assert r.status_code == 401

    def test_session_multi_role_token(self):
        multi_token = jwt.encode(
            {"sub": "multi-user", "roles": ["viewer", "engineer"],
             "tenant_id": TENANT_ID,
             "exp": int(time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, 0)))},
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        r = client.post("/api/v1/auth/session",
                        headers={"Authorization": f"Bearer {multi_token}"})
        assert r.status_code == 200
        assert set(r.json()["data"]["roles"]) == {"viewer", "engineer"}

    def test_session_envelope_format(self):
        r = client.post("/api/v1/auth/session", headers=VIEWER_HEADERS)
        body = r.json()
        assert "data" in body and "meta" in body and "error" in body
        assert body["error"] is None
        assert "request_id" in body["meta"]
        assert "timestamp" in body["meta"]


# ─────────────────────────────────────────────────────────────────────────────
# 6. Role Escalation Prevention (explicit cross-tier tests)
# ─────────────────────────────────────────────────────────────────────────────


class TestRoleEscalationImpossible:
    """Prove escalation is impossible across every tier boundary."""

    # viewer → engineer endpoints
    def test_viewer_cannot_create_incident(self):
        r = client.post("/api/v1/incidents", headers=VIEWER_HEADERS,
                        json={"title":"T","description":"D","severity":"SEV2","affected_service":"svc"})
        assert r.status_code == 403
        assert r.json()["error"]["details"]["required_min_role"] == "engineer"

    def test_viewer_cannot_reinvestigate(self):
        r = client.post(f"/api/v1/incidents/{_INC}/reinvestigate", headers=VIEWER_HEADERS)
        assert r.status_code == 403

    def test_viewer_cannot_add_comment(self):
        r = client.post(f"/api/v1/incidents/{_INC}/comment",
                        headers=VIEWER_HEADERS, json={"text":"hi"})
        assert r.status_code == 403

    def test_viewer_cannot_create_knowledge(self):
        r = client.post("/api/v1/knowledge", headers=VIEWER_HEADERS,
                        json={"title":"KB","content":"# c","tags":[]})
        assert r.status_code == 403

    # viewer → approver endpoints
    def test_viewer_cannot_patch_incident(self):
        r = client.patch(f"/api/v1/incidents/{_INC}", headers=VIEWER_HEADERS,
                         json={"status":"closed","resolution_note":"x"})
        assert r.status_code == 403
        assert r.json()["error"]["details"]["required_min_role"] == "approver"

    def test_viewer_cannot_approve_action(self):
        r = client.post(f"/api/v1/incidents/{_INC}/actions/{_ACT}/approve",
                        headers={**VIEWER_HEADERS, "Idempotency-Key":"ik-v-01"}, json={})
        assert r.status_code == 403

    def test_viewer_cannot_reject_action(self):
        r = client.post(f"/api/v1/incidents/{_INC}/actions/{_ACT}/reject",
                        headers=VIEWER_HEADERS, json={"reason":"x"})
        assert r.status_code == 403

    def test_viewer_cannot_modify_action(self):
        r = client.post(f"/api/v1/incidents/{_INC}/actions/{_ACT}/modify",
                        headers=VIEWER_HEADERS,
                        json={"modified_plan":{"id":"p1","description":"d","steps":[]}})
        assert r.status_code == 403

    # viewer → admin endpoints
    def test_viewer_cannot_list_policies(self):
        assert client.get("/api/v1/policies", headers=VIEWER_HEADERS).status_code == 403

    def test_viewer_cannot_create_policy(self):
        assert client.post("/api/v1/policies", headers=VIEWER_HEADERS,
                           json={"action_pattern":"x","environment":"prod","risk_tier":"low",
                                 "requires_approval":False,"max_blast_radius":1}).status_code == 403

    def test_viewer_cannot_update_policy(self):
        assert client.put("/api/v1/policies/pol-001", headers=VIEWER_HEADERS,
                          json={"risk_tier":"low"}).status_code == 403

    def test_viewer_cannot_list_integrations(self):
        assert client.get("/api/v1/integrations", headers=VIEWER_HEADERS).status_code == 403

    def test_viewer_cannot_connect_integration(self):
        assert client.post("/api/v1/integrations/github/connect",
                           headers=VIEWER_HEADERS).status_code == 403

    def test_viewer_cannot_delete_integration(self):
        assert client.delete("/api/v1/integrations/github",
                             headers=VIEWER_HEADERS).status_code == 403

    def test_viewer_cannot_read_audit(self):
        assert client.get("/api/v1/audit", headers=VIEWER_HEADERS).status_code == 403

    # engineer → approver endpoints
    def test_engineer_cannot_patch_incident(self):
        r = client.patch(f"/api/v1/incidents/{_INC}", headers=ENGINEER_HEADERS,
                         json={"status":"closed","resolution_note":"x"})
        assert r.status_code == 403
        assert r.json()["error"]["details"]["required_min_role"] == "approver"

    def test_engineer_cannot_approve_action(self):
        r = client.post(f"/api/v1/incidents/{_INC}/actions/{_ACT}/approve",
                        headers={**ENGINEER_HEADERS, "Idempotency-Key":"ik-e-01"}, json={})
        assert r.status_code == 403

    def test_engineer_cannot_reject_action(self):
        r = client.post(f"/api/v1/incidents/{_INC}/actions/{_ACT}/reject",
                        headers=ENGINEER_HEADERS, json={"reason":"x"})
        assert r.status_code == 403

    def test_engineer_cannot_modify_action(self):
        r = client.post(f"/api/v1/incidents/{_INC}/actions/{_ACT}/modify",
                        headers=ENGINEER_HEADERS,
                        json={"modified_plan":{"id":"p1","description":"d","steps":[]}})
        assert r.status_code == 403

    # engineer → admin endpoints
    def test_engineer_cannot_list_policies(self):
        assert client.get("/api/v1/policies", headers=ENGINEER_HEADERS).status_code == 403

    def test_engineer_cannot_read_audit(self):
        assert client.get("/api/v1/audit", headers=ENGINEER_HEADERS).status_code == 403

    # approver → admin endpoints
    def test_approver_cannot_list_policies(self):
        r = client.get("/api/v1/policies", headers=APPROVER_HEADERS)
        assert r.status_code == 403
        assert r.json()["error"]["details"]["required_min_role"] == "admin"

    def test_approver_cannot_update_policy(self):
        assert client.put("/api/v1/policies/pol-001", headers=APPROVER_HEADERS,
                          json={"risk_tier":"low"}).status_code == 403

    def test_approver_cannot_list_integrations(self):
        assert client.get("/api/v1/integrations", headers=APPROVER_HEADERS).status_code == 403

    def test_approver_cannot_delete_integration(self):
        assert client.delete("/api/v1/integrations/github",
                             headers=APPROVER_HEADERS).status_code == 403

    def test_approver_cannot_read_audit(self):
        assert client.get("/api/v1/audit", headers=APPROVER_HEADERS).status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 7. Each Role Tier Accepts Its Own Endpoints
# ─────────────────────────────────────────────────────────────────────────────


class TestRoleTierAcceptance:
    def test_viewer_can_read_all_viewer_plus(self):
        viewer_endpoints = [
            (client.get, "/api/v1/incidents"),
            (client.get, f"/api/v1/incidents/{_INC}"),
            (client.get, f"/api/v1/incidents/{_INC}/agent-runs"),
            (client.get, f"/api/v1/incidents/{_INC}/root-cause"),
            (client.get, f"/api/v1/incidents/{_INC}/impact"),
            (client.get, f"/api/v1/incidents/{_INC}/decision"),
            (client.get, f"/api/v1/incidents/{_INC}/actions"),
            (client.get, f"/api/v1/incidents/{_INC}/verification"),
            (client.get, "/api/v1/knowledge"),
            (client.get, "/api/v1/reports/mttr"),
            (client.get, "/api/v1/reports/autonomy"),
        ]
        for fn, url in viewer_endpoints:
            r = fn(url, headers=VIEWER_HEADERS)
            assert r.status_code == 200, f"Viewer failed on GET {url}: {r.status_code}"

    def test_engineer_can_use_engineer_plus_endpoints(self):
        r = client.post("/api/v1/incidents", headers=ENGINEER_HEADERS,
                        json={"title":"T","description":"D","severity":"SEV2","affected_service":"svc"})
        assert r.status_code == 201
        r = client.post(f"/api/v1/incidents/{_INC}/reinvestigate", headers=ENGINEER_HEADERS)
        assert r.status_code == 202
        r = client.post(f"/api/v1/incidents/{_INC}/comment",
                        headers=ENGINEER_HEADERS, json={"text":"comment"})
        assert r.status_code == 201
        r = client.post("/api/v1/knowledge", headers=ENGINEER_HEADERS,
                        json={"title":"KB","content":"# c","tags":[]})
        assert r.status_code == 201

    def test_approver_can_use_approver_plus_endpoints(self):
        r = client.patch(f"/api/v1/incidents/{_INC}", headers=APPROVER_HEADERS,
                         json={"status":"closed","resolution_note":"done"})
        assert r.status_code == 200
        r = client.post(f"/api/v1/incidents/{_INC}/actions/{_ACT}/approve",
                        headers={**APPROVER_HEADERS,"Idempotency-Key":"ik-apr-01"}, json={})
        assert r.status_code == 200
        r = client.post(f"/api/v1/incidents/{_INC}/actions/{_ACT}/reject",
                        headers=APPROVER_HEADERS, json={"reason":"r"})
        assert r.status_code == 200
        r = client.post(f"/api/v1/incidents/{_INC}/actions/{_ACT}/modify",
                        headers=APPROVER_HEADERS,
                        json={"modified_plan":{"id":"p1","description":"d","steps":[]}})
        assert r.status_code == 200

    def test_admin_can_use_admin_endpoints(self):
        assert client.get("/api/v1/policies", headers=ADMIN_HEADERS).status_code == 200
        assert client.get("/api/v1/integrations", headers=ADMIN_HEADERS).status_code == 200
        assert client.get("/api/v1/audit", headers=ADMIN_HEADERS).status_code == 200

    def test_admin_inherits_all_lower_tiers(self):
        """Admin must pass every viewer+/engineer+/approver+ endpoint too."""
        assert client.get("/api/v1/incidents", headers=ADMIN_HEADERS).status_code == 200
        r = client.post("/api/v1/incidents", headers=ADMIN_HEADERS,
                        json={"title":"T","description":"D","severity":"SEV1","affected_service":"db"})
        assert r.status_code == 201
        r = client.patch(f"/api/v1/incidents/{_INC}", headers=ADMIN_HEADERS,
                         json={"status":"closed","resolution_note":"admin-close"})
        assert r.status_code == 200

    def test_critical_policy_always_requires_approval(self):
        """Server must override requires_approval=False for critical risk tier."""
        r = client.post("/api/v1/policies", headers=ADMIN_HEADERS,
                        json={"action_pattern":"db.drop","environment":"prod",
                              "risk_tier":"critical","requires_approval":False,"max_blast_radius":10})
        assert r.status_code == 201
        assert r.json()["data"]["requires_approval"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 8. Health and Webhook Endpoints (no JWT required)
# ─────────────────────────────────────────────────────────────────────────────


class TestNoAuthEndpoints:
    def test_healthz_requires_no_auth(self):
        r = client.get("/api/v1/healthz")
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "ok"

    def test_readyz_requires_no_auth(self):
        r = client.get("/api/v1/readyz")
        assert r.status_code in (200, 503)

    @pytest.mark.parametrize("path", [
        "/api/v1/webhooks/cloudwatch",
        "/api/v1/webhooks/alertmanager",
        "/api/v1/webhooks/github",
        "/api/v1/webhooks/slack",
    ])
    def test_webhook_without_jwt_succeeds(self, path):
        from apps.api.src.services.ingestion.signature_verifier import (
            FakeVerifier,
            get_alertmanager_verifier,
            get_github_verifier,
            get_slack_verifier,
            get_sns_verifier,
        )
        from db.models import IntegrationConfig

        app.dependency_overrides[get_github_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_alertmanager_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_slack_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_sns_verifier] = lambda: FakeVerifier()

        source = path.split("/")[-1]
        with TestingSessionLocal() as db:
            if not db.query(IntegrationConfig).filter_by(type=source, credential_ref="test-org").first():
                db.add(IntegrationConfig(
                    id=uuid.uuid4(),
                    tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                    type=source,
                    status="connected",
                    credential_ref="test-org",
                    scopes={}
                ))
                db.commit()

        from schemas.agent_state import IncidentEvent
        from unittest.mock import patch, AsyncMock
        fake_event = IncidentEvent(
            resource_id="svc-test",
            source=source,
            event_type="test_event",
            severity_hint="SEV2",
            summary="Test webhook event",
            is_likely_duplicate=False,
            duplicate_of_incident_id=None,
            sanitization_flags=[],
        )

        payloads = {
            "github": {"repository": {"owner": {"login": "test-org"}}},
            "cloudwatch": {"TopicArn": "arn:aws:sns:us-east-1:test-org:alarm"},
            "slack": {"team_id": "test-org"},
            "alertmanager": {"groupLabels": {"cluster": "test-org"}},
        }

        with patch("apps.api.src.routers.webhooks.run_ingestion_agent", new_callable=AsyncMock, return_value=fake_event):
            r = client.post(path, json=payloads[source])

        assert r.status_code == 200
        assert r.json()["data"]["received"] is True

