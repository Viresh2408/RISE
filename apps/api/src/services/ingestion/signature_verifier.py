"""Webhook Signature Verification — Protocol + Implementations.

Architecture
------------
``SignatureVerifier`` is a typed ``Protocol``.  Production code wires in the
``Real*Verifier`` classes via FastAPI dependency factory functions.  Tests
inject ``FakeVerifier`` or ``FakeSNSVerifier`` via ``app.dependency_overrides``.

**There is no env-flag bypass in this module.**  Structural removal of the
bypass path is stronger than a guarded flag: a nonexistent code path cannot
be misconfigured, forgotten, or accidentally enabled in production, whereas
a guarded bypass can be.

Implementations
---------------
``RealGitHubVerifier``       — HMAC-SHA256 raw body vs X-Hub-Signature-256
``RealAlertmanagerVerifier`` — constant-time compare X-RISE-Secret header
``RealSlackVerifier``        — HMAC-SHA256 "v0:{ts}:{body}" + 5-min replay window
``RealSNSVerifier``          — fetches signing cert from amazonaws.com, verifies RSA
``FakeVerifier``             — always passes  (inject in tests only)
``FakeFailVerifier``         — always raises 401  (inject in tests only)
``FakeSNSVerifier``          — verifies against an in-process test keypair fixture
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx
try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.x509 import load_pem_x509_certificate
except ImportError:
    hashes = None  # type: ignore
    padding = None  # type: ignore
    load_pem_x509_certificate = None  # type: ignore

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SignatureVerifier(Protocol):
    """Verify an inbound webhook request's authenticity.

    Raises ``HTTPException(401)`` on failure.
    Returns ``None`` on success (no exception = verified).
    """

    async def verify(self, request: Request, raw_body: bytes) -> None:
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SNS_SIGNING_CERT_CACHE: dict[str, bytes] = {}
_SNS_CERT_ALLOWED_HOST_SUFFIX = ".amazonaws.com"


def _constant_time_equal(a: str, b: str) -> bool:
    """Constant-time string comparison (safe against timing attacks)."""
    return hmac.compare_digest(a.encode(), b.encode())


def _hmac_sha256_hex(secret: str, message: bytes) -> str:
    """Return lowercase hex HMAC-SHA256."""
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _reject(source: str, code: str, message: str, status_code: int = status.HTTP_401_UNAUTHORIZED) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": {"source": source}},
    )


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class RealGitHubVerifier:
    """HMAC-SHA256 verification per GitHub webhook docs.

    Header: ``X-Hub-Signature-256: sha256=<hex>``
    Secret: ``GITHUB_WEBHOOK_SECRET`` env var.
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret or os.environ.get("GITHUB_WEBHOOK_SECRET", "")

    async def verify(self, request: Request, raw_body: bytes) -> None:
        if not self._secret:
            _reject("github", "WEBHOOK_SECRET_NOT_CONFIGURED",
                    "GITHUB_WEBHOOK_SECRET is not configured.")

        header = request.headers.get("x-hub-signature-256", "")
        if not header.startswith("sha256="):
            _reject("github", "INVALID_SIGNATURE",
                    "Missing or malformed X-Hub-Signature-256 header.")

        expected = "sha256=" + _hmac_sha256_hex(self._secret, raw_body)
        if not _constant_time_equal(expected, header):
            logger.warning("GitHub webhook signature mismatch")
            _reject("github", "INVALID_SIGNATURE",
                    "GitHub webhook signature verification failed.")


# ---------------------------------------------------------------------------
# Alertmanager
# ---------------------------------------------------------------------------


class RealAlertmanagerVerifier:
    """Shared-secret via ``X-RISE-Secret`` header (constant-time compare).

    Secret: ``ALERTMANAGER_WEBHOOK_SECRET`` env var.
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret or os.environ.get("ALERTMANAGER_WEBHOOK_SECRET", "")

    async def verify(self, request: Request, raw_body: bytes) -> None:
        if not self._secret:
            _reject("alertmanager", "WEBHOOK_SECRET_NOT_CONFIGURED",
                    "ALERTMANAGER_WEBHOOK_SECRET is not configured.")

        provided = request.headers.get("x-rise-secret", "")
        if not _constant_time_equal(self._secret, provided):
            logger.warning("Alertmanager webhook secret mismatch")
            _reject("alertmanager", "INVALID_SIGNATURE",
                    "Alertmanager X-RISE-Secret verification failed.")


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

_SLACK_REPLAY_WINDOW_SECONDS = 300  # 5 minutes


class RealSlackVerifier:
    """Slack signing secret verification.

    Slack computes: ``HMAC-SHA256("v0:{timestamp}:{body}", signing_secret)``
    and sends it as ``X-Slack-Signature: v0={hex}``.
    ``X-Slack-Request-Timestamp`` must be within 5 minutes to prevent replay attacks.
    Secret: ``SLACK_SIGNING_SECRET`` env var.
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret or os.environ.get("SLACK_SIGNING_SECRET", "")

    async def verify(self, request: Request, raw_body: bytes) -> None:
        if not self._secret:
            _reject("slack", "WEBHOOK_SECRET_NOT_CONFIGURED",
                    "SLACK_SIGNING_SECRET is not configured.")

        ts_str = request.headers.get("x-slack-request-timestamp", "")
        sig = request.headers.get("x-slack-signature", "")

        if not ts_str or not sig:
            _reject("slack", "INVALID_SIGNATURE",
                    "Missing X-Slack-Request-Timestamp or X-Slack-Signature header.")

        try:
            ts = int(ts_str)
        except ValueError:
            _reject("slack", "INVALID_SIGNATURE",
                    "Malformed X-Slack-Request-Timestamp header (not an integer).")
            return  # unreachable; satisfies type checkers

        age = abs(int(time.time()) - ts)
        if age > _SLACK_REPLAY_WINDOW_SECONDS:
            logger.warning("Slack webhook timestamp too old: age=%ds", age)
            _reject(
                "slack",
                "REPLAY_ATTACK_DETECTED",
                f"Slack request timestamp is {age}s old; outside the 5-minute replay window.",
            )

        base_str = f"v0:{ts_str}:{raw_body.decode('utf-8', errors='replace')}"
        expected = "v0=" + _hmac_sha256_hex(self._secret, base_str.encode())
        if not _constant_time_equal(expected, sig):
            logger.warning("Slack webhook signature mismatch")
            _reject("slack", "INVALID_SIGNATURE",
                    "Slack webhook signature verification failed.")


# ---------------------------------------------------------------------------
# CloudWatch / SNS
# ---------------------------------------------------------------------------

_SNS_SIGNABLE_KEYS_NOTIFICATION = [
    "Message", "MessageId", "Subject", "SubscribeURL",
    "Timestamp", "TopicArn", "Type",
]
_SNS_SIGNABLE_KEYS_SUBSCRIPTION = [
    "Message", "MessageId", "SubscribeURL",
    "Timestamp", "Token", "TopicArn", "Type",
]


def _sns_string_to_sign(msg: dict) -> bytes:
    msg_type = msg.get("Type", "")
    keys = (
        _SNS_SIGNABLE_KEYS_SUBSCRIPTION
        if msg_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation")
        else _SNS_SIGNABLE_KEYS_NOTIFICATION
    )
    parts: list[str] = []
    for key in keys:
        if key in msg:
            parts.extend([key, msg[key]])
    return "\n".join(parts).encode("utf-8") + b"\n"


async def _fetch_sns_cert(cert_url: str) -> bytes:
    """Fetch and cache the AWS SNS signing certificate.

    Only HTTPS URLs whose host ends with ``.amazonaws.com`` are accepted.
    """
    if not cert_url.startswith("https://"):
        raise ValueError(f"SNS SigningCertURL must be HTTPS: {cert_url!r}")
    host = urlparse(cert_url).netloc
    if not host.endswith(_SNS_CERT_ALLOWED_HOST_SUFFIX):
        raise ValueError(
            f"SNS SigningCertURL host '{host}' is not an amazonaws.com domain."
        )
    if cert_url in _SNS_SIGNING_CERT_CACHE:
        return _SNS_SIGNING_CERT_CACHE[cert_url]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(cert_url)
        resp.raise_for_status()
        pem = resp.content
    _SNS_SIGNING_CERT_CACHE[cert_url] = pem
    return pem


class RealSNSVerifier:
    """AWS SNS message signature verification.

    Fetches the signing certificate from the URL embedded in the SNS message
    (validated to end in ``.amazonaws.com``), extracts the RSA public key, and
    verifies the RSA-SHA1 signature per the SNS documentation.

    **There is no runtime flag to skip this step.**  Tests inject
    ``FakeSNSVerifier`` via ``app.dependency_overrides`` — the bypass does not
    exist as a reachable branch in this class.
    """

    async def verify(self, request: Request, raw_body: bytes) -> None:
        try:
            msg = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_PAYLOAD",
                    "message": "SNS message body is not valid JSON.",
                    "details": {"source": "cloudwatch", "error": str(exc)},
                },
            )

        cert_url = msg.get("SigningCertURL", "")
        sig_b64 = msg.get("Signature", "")
        if not cert_url or not sig_b64:
            _reject("cloudwatch", "INVALID_SIGNATURE",
                    "SNS message missing SigningCertURL or Signature.")

        try:
            cert_pem = await _fetch_sns_cert(cert_url)
        except (ValueError, httpx.HTTPError) as exc:
            logger.error("Failed to fetch SNS signing cert: %s", exc)
            _reject("cloudwatch", "INVALID_SIGNATURE",
                    f"Could not fetch SNS signing certificate: {exc}")

        try:
            cert = load_pem_x509_certificate(cert_pem)
            pub_key = cert.public_key()
            string_to_sign = _sns_string_to_sign(msg)
            sig_bytes = base64.b64decode(sig_b64)
            pub_key.verify(sig_bytes, string_to_sign, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303 — AWS SNS uses SHA1
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("SNS signature verification failed: %s", exc)
            _reject("cloudwatch", "INVALID_SIGNATURE",
                    "SNS message signature verification failed.")


# ---------------------------------------------------------------------------
# Dependency factories (for FastAPI Depends — overridable in tests)
# ---------------------------------------------------------------------------


def get_github_verifier() -> SignatureVerifier:
    return RealGitHubVerifier()


def get_alertmanager_verifier() -> SignatureVerifier:
    return RealAlertmanagerVerifier()


def get_slack_verifier() -> SignatureVerifier:
    return RealSlackVerifier()


def get_sns_verifier() -> SignatureVerifier:
    return RealSNSVerifier()


# ---------------------------------------------------------------------------
# Test-only verifiers (inject via app.dependency_overrides — never shipped)
# ---------------------------------------------------------------------------


class FakeVerifier:
    """Always passes.  Inject in tests via ``app.dependency_overrides``.

    NEVER register this in production app startup.  It has no guard because
    it is designed to be injected directly in tests, not selected via config.
    """

    async def verify(self, request: Request, raw_body: bytes) -> None:
        pass  # always succeeds


class FakeFailVerifier:
    """Always raises 401.  Used to test rejection paths in all 4 sources."""

    async def verify(self, request: Request, raw_body: bytes) -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_SIGNATURE",
                "message": "Signature verification failed (test stub).",
                "details": {},
            },
        )


class FakeSNSVerifier:
    """Verifies against a caller-provided RSA test public key.

    Allows SNS-specific endpoint tests to exercise the full SNS JSON parsing
    and string-to-sign construction without network calls.

    Usage in tests::

        verifier = FakeSNSVerifier(public_key_pem=TEST_PUB_KEY_PEM)
        app.dependency_overrides[get_sns_verifier] = lambda: verifier
    """

    def __init__(self, public_key_pem: bytes | None = None) -> None:
        self._pub_key_pem = public_key_pem

    async def verify(self, request: Request, raw_body: bytes) -> None:
        if self._pub_key_pem is None:
            return  # no key provided → unconditionally pass

        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        try:
            msg = json.loads(raw_body)
            sig_bytes = base64.b64decode(msg.get("Signature", ""))
            string_to_sign = _sns_string_to_sign(msg)
            pub_key = load_pem_public_key(self._pub_key_pem)
            pub_key.verify(sig_bytes, string_to_sign, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": f"SNS test signature verification failed: {exc}",
                    "details": {},
                },
            )
