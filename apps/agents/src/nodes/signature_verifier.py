"""Webhook Signature Verification — Protocol + Implementations.

Architecture
------------
``SignatureVerifier`` is a typed ``Protocol``.  Production code wires in the
``Real*Verifier`` classes.  Tests inject ``FakeVerifier`` or ``FakeSNSVerifier``
via ``app.dependency_overrides`` — **no env-flag bypass exists** in this module.

The absence of a bypass code-path (rather than a guarded bypass) is deliberate:
for safety-critical controls, structural removal is stronger than a guarded flag
that can be misconfigured or accidentally enabled in production.

Implementations
---------------
- ``RealGitHubVerifier``       — HMAC-SHA256 raw body vs X-Hub-Signature-256
- ``RealAlertmanagerVerifier`` — constant-time compare X-RISE-Secret header
- ``RealSlackVerifier``        — HMAC-SHA256 "v0:{ts}:{body}" + 5-min replay window
- ``RealSNSVerifier``          — fetches signing cert from AWS, verifies RSA signature
- ``FakeVerifier``             — always passes (tests only; injected, never shipped)
- ``FakeSNSVerifier``          — verifies against an in-process test keypair fixture
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

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate
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


def _hmac_sha256(secret: str, message: bytes) -> str:
    """Return lowercase hex HMAC-SHA256."""
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


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
        header = request.headers.get("x-hub-signature-256", "")
        if not header.startswith("sha256="):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": "Missing or malformed X-Hub-Signature-256 header.",
                    "details": {"source": "github"},
                },
            )
        if not self._secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "WEBHOOK_SECRET_NOT_CONFIGURED",
                    "message": "GITHUB_WEBHOOK_SECRET is not configured.",
                    "details": {"source": "github"},
                },
            )
        expected = "sha256=" + _hmac_sha256(self._secret, raw_body)
        if not _constant_time_equal(expected, header):
            logger.warning("GitHub webhook signature mismatch")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": "GitHub webhook signature verification failed.",
                    "details": {"source": "github"},
                },
            )


# ---------------------------------------------------------------------------
# Alertmanager
# ---------------------------------------------------------------------------


class RealAlertmanagerVerifier:
    """Shared-secret verification via ``X-RISE-Secret`` header.

    Secret: ``ALERTMANAGER_WEBHOOK_SECRET`` env var.
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret or os.environ.get("ALERTMANAGER_WEBHOOK_SECRET", "")

    async def verify(self, request: Request, raw_body: bytes) -> None:
        if not self._secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "WEBHOOK_SECRET_NOT_CONFIGURED",
                    "message": "ALERTMANAGER_WEBHOOK_SECRET is not configured.",
                    "details": {"source": "alertmanager"},
                },
            )
        provided = request.headers.get("x-rise-secret", "")
        if not _constant_time_equal(self._secret, provided):
            logger.warning("Alertmanager webhook secret mismatch")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": "Alertmanager X-RISE-Secret verification failed.",
                    "details": {"source": "alertmanager"},
                },
            )


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

_SLACK_REPLAY_WINDOW_SECONDS = 300  # 5 minutes


class RealSlackVerifier:
    """Slack signing secret verification.

    Slack computes: ``HMAC-SHA256("v0:{timestamp}:{body}", signing_secret)``
    and sends it as ``X-Slack-Signature: v0={hex}``.
    The ``X-Slack-Request-Timestamp`` must be within 5 minutes to prevent replay.
    Secret: ``SLACK_SIGNING_SECRET`` env var.
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret or os.environ.get("SLACK_SIGNING_SECRET", "")

    async def verify(self, request: Request, raw_body: bytes) -> None:
        if not self._secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "WEBHOOK_SECRET_NOT_CONFIGURED",
                    "message": "SLACK_SIGNING_SECRET is not configured.",
                    "details": {"source": "slack"},
                },
            )

        ts_str = request.headers.get("x-slack-request-timestamp", "")
        sig = request.headers.get("x-slack-signature", "")

        if not ts_str or not sig:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": "Missing Slack signature headers.",
                    "details": {"source": "slack"},
                },
            )

        # Replay window check
        try:
            ts = int(ts_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": "Malformed X-Slack-Request-Timestamp header.",
                    "details": {"source": "slack"},
                },
            )

        age = abs(int(time.time()) - ts)
        if age > _SLACK_REPLAY_WINDOW_SECONDS:
            logger.warning("Slack webhook timestamp too old: age=%ds", age)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "REPLAY_ATTACK_DETECTED",
                    "message": "Slack request timestamp is outside the 5-minute replay window.",
                    "details": {"source": "slack", "age_seconds": age},
                },
            )

        base_string = f"v0:{ts_str}:{raw_body.decode('utf-8', errors='replace')}"
        expected = "v0=" + _hmac_sha256(self._secret, base_string.encode())
        if not _constant_time_equal(expected, sig):
            logger.warning("Slack webhook signature mismatch")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": "Slack webhook signature verification failed.",
                    "details": {"source": "slack"},
                },
            )


# ---------------------------------------------------------------------------
# CloudWatch / SNS
# ---------------------------------------------------------------------------

_SNS_SIGNABLE_KEYS_NOTIFICATION = [
    "Message",
    "MessageId",
    "Subject",
    "SubscribeURL",
    "Timestamp",
    "TopicArn",
    "Type",
]
_SNS_SIGNABLE_KEYS_SUBSCRIPTION = [
    "Message",
    "MessageId",
    "SubscribeURL",
    "Timestamp",
    "Token",
    "TopicArn",
    "Type",
]


def _sns_build_string_to_sign(msg: dict) -> bytes:
    msg_type = msg.get("Type", "")
    if msg_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        keys = _SNS_SIGNABLE_KEYS_SUBSCRIPTION
    else:
        keys = _SNS_SIGNABLE_KEYS_NOTIFICATION

    parts: list[str] = []
    for key in keys:
        if key in msg:
            parts.append(key)
            parts.append(msg[key])
    return "\n".join(parts).encode("utf-8") + b"\n"


async def _fetch_sns_signing_cert(cert_url: str) -> bytes:
    """Fetch and cache the AWS SNS signing certificate.

    Only URLs ending in ``.amazonaws.com`` are allowed.
    """
    if not cert_url.startswith("https://"):
        raise ValueError(f"SNS SigningCertURL must use HTTPS: {cert_url!r}")

    # Validate host is an AWS domain
    from urllib.parse import urlparse
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
        cert_pem = resp.content

    _SNS_SIGNING_CERT_CACHE[cert_url] = cert_pem
    return cert_pem


class RealSNSVerifier:
    """AWS SNS message signature verification.

    Fetches the signing certificate from the URL embedded in the SNS message
    (validated to be an amazonaws.com domain), extracts the RSA public key,
    and verifies the message signature.

    There is no runtime flag to skip this verification.  Tests that need to
    avoid network calls inject ``FakeSNSVerifier`` via dependency_overrides.
    """

    async def verify(self, request: Request, raw_body: bytes) -> None:
        # Validate SNS content-type header
        content_type = request.headers.get("content-type", "")
        if "text/plain" not in content_type and "application/json" not in content_type:
            # SNS sends text/plain; be lenient for integration testing
            pass

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
        signature_b64 = msg.get("Signature", "")

        if not cert_url or not signature_b64:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": "SNS message missing SigningCertURL or Signature fields.",
                    "details": {"source": "cloudwatch"},
                },
            )

        try:
            cert_pem = await _fetch_sns_signing_cert(cert_url)
        except (ValueError, httpx.HTTPError) as exc:
            logger.error("Failed to fetch SNS signing cert: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": f"Could not fetch SNS signing certificate: {exc}",
                    "details": {"source": "cloudwatch"},
                },
            )

        try:
            cert = load_pem_x509_certificate(cert_pem)
            pub_key = cert.public_key()
            string_to_sign = _sns_build_string_to_sign(msg)
            signature_bytes = base64.b64decode(signature_b64)
            pub_key.verify(signature_bytes, string_to_sign, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303 — AWS SNS uses SHA1
        except Exception as exc:
            logger.warning("SNS signature verification failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": "SNS message signature verification failed.",
                    "details": {"source": "cloudwatch"},
                },
            )


# ---------------------------------------------------------------------------
# Test-only verifiers (injected via dependency_overrides — never shipped)
# ---------------------------------------------------------------------------


class FakeVerifier:
    """Always passes. Inject in tests via app.dependency_overrides.

    NEVER register this in production app startup.  It has no guard because
    it is intended to be injected directly in tests, not selected via config.
    """

    async def verify(self, request: Request, raw_body: bytes) -> None:
        pass  # always succeeds


class FakeFailVerifier:
    """Always raises 401. Used to test rejection paths."""

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
    """Verifies against a caller-provided test public key.

    Allows SNS-specific endpoint tests to exercise the full SNS parsing code
    path without network calls, by injecting a pre-signed test fixture.

    Usage in tests::

        verifier = FakeSNSVerifier(public_key_pem=TEST_PUB_KEY_PEM)
        app.dependency_overrides[get_sns_verifier] = lambda: verifier
    """

    def __init__(self, public_key_pem: bytes | None = None) -> None:
        self._pub_key_pem = public_key_pem

    async def verify(self, request: Request, raw_body: bytes) -> None:
        if self._pub_key_pem is None:
            # No key provided → unconditionally pass (simplest test mode)
            return

        try:
            msg = json.loads(raw_body)
            signature_b64 = msg.get("Signature", "")
            string_to_sign = _sns_build_string_to_sign(msg)
            signature_bytes = base64.b64decode(signature_b64)

            from cryptography.hazmat.primitives.serialization import load_pem_public_key

            pub_key = load_pem_public_key(self._pub_key_pem)
            pub_key.verify(signature_bytes, string_to_sign, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_SIGNATURE",
                    "message": f"SNS test signature verification failed: {exc}",
                    "details": {},
                },
            )
