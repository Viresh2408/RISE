"""Tenant resolution from IntegrationConfig for unauthenticated webhook requests.

Webhook requests authenticate via HMAC/signature — there is no JWT and therefore
no ``user.tenant_id`` claim.  Instead, each source's payload carries a
source-specific identifier (GitHub org, AWS account ID, Slack team_id, etc.)
that we match against the ``integration_configs`` table to resolve a tenant.

If the identifier has no matching row, the request is **rejected with 400 and
audit-logged** — there is no fallback tenant, no single-tenant env var.  Unknown
source ≠ default tenant (a global fallback would re-introduce the multi-tenant
gap the design deliberately avoids).

Identifier extraction
---------------------
| Source       | Extracted from payload             | ``IntegrationConfig.type`` |
|--------------|------------------------------------|---------------------------|
| github       | ``repository.owner.login``         | ``github``                |
| cloudwatch   | account ID from SNS ``TopicArn``   | ``cloudwatch``            |
| slack        | ``team_id`` (top-level or event)   | ``slack``                 |
| alertmanager | ``groupLabels.cluster`` or label   | ``alertmanager``          |
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import IntegrationConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source-specific identifier extractors
# ---------------------------------------------------------------------------


def _extract_github_identifier(payload: Dict[str, Any]) -> Optional[str]:
    """Return the GitHub org/owner login from the webhook payload."""
    # Standard push/PR/check events
    repo = payload.get("repository") or {}
    owner = repo.get("owner") or {}
    login = owner.get("login") or owner.get("name")
    if login:
        return str(login)
    # GitHub App installation events
    installation = payload.get("installation") or {}
    account = installation.get("account") or {}
    return account.get("login")


def _extract_cloudwatch_identifier(payload: Dict[str, Any]) -> Optional[str]:
    """Return the AWS account ID from the SNS ``TopicArn``.

    SNS TopicArn format: ``arn:aws:sns:{region}:{account-id}:{topic-name}``
    The account-id is always at colon-index 4 (zero-based).  This is the
    single, deterministic identifier we store in IntegrationConfig so that
    each AWS account maps to exactly one IntegrationConfig row.

    We do NOT fall back to any other field — if the payload lacks a valid
    ``TopicArn``, the caller receives ``None`` and rejects the request.
    """
    topic_arn = payload.get("TopicArn", "")
    if not topic_arn:
        return None
    parts = topic_arn.split(":")
    # arn:aws:sns:{region}:{account-id}:{topic-name} → index 4 is account-id
    if len(parts) >= 5 and parts[4]:
        return parts[4]
    return None


def _extract_slack_identifier(payload: Dict[str, Any]) -> Optional[str]:
    """Return the Slack workspace team_id."""
    team_id = payload.get("team_id")
    if team_id:
        return str(team_id)
    # Events API wraps payloads under an ``event`` key; team_id at top level
    event = payload.get("event") or {}
    return event.get("team") or payload.get("team", {}).get("id") if isinstance(payload.get("team"), dict) else payload.get("team")


def _extract_alertmanager_identifier(payload: Dict[str, Any]) -> Optional[str]:
    """Return the Alertmanager cluster identifier from groupLabels.

    Alertmanager webhook payload has a ``groupLabels`` dict.  By convention,
    RISE uses the ``cluster`` label as the unique identifier per integration.
    Operators that don't set ``cluster`` can use any single custom label value
    as long as their IntegrationConfig.credential_ref encodes the same value.

    Fallback order: ``groupLabels.cluster`` → ``groupLabels.namespace`` →
    ``externalURL`` host (the Alertmanager instance URL).
    """
    group_labels: Dict[str, Any] = payload.get("groupLabels") or {}
    cluster = group_labels.get("cluster") or group_labels.get("namespace")
    if cluster:
        return str(cluster)
    # Use the Alertmanager instance URL as a last-resort identifier
    external_url = payload.get("externalURL", "")
    if external_url:
        # Extract host from URL
        m = re.match(r"https?://([^/]+)", external_url)
        if m:
            return m.group(1)
    return None


_EXTRACTORS = {
    "github": _extract_github_identifier,
    "cloudwatch": _extract_cloudwatch_identifier,
    "slack": _extract_slack_identifier,
    "alertmanager": _extract_alertmanager_identifier,
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_source_identifier(source: str, payload: Dict[str, Any]) -> Optional[str]:
    """Extract the source-specific identifier from a webhook payload.

    Returns ``None`` if the source is unknown or the identifier cannot be
    determined from the payload structure.
    """
    extractor = _EXTRACTORS.get(source)
    if extractor is None:
        logger.warning("No identifier extractor registered for source=%s", source)
        return None
    return extractor(payload)


def resolve_tenant_from_integration(
    db: Session,
    source: str,
    identifier: str,
) -> Optional[uuid.UUID]:
    """Look up the tenant_id for a webhook source + identifier pair.

    The ``IntegrationConfig.credential_ref`` column is used as the matching
    field because it already stores the per-tenant integration identifier
    (e.g., the GitHub org name, AWS account ID, Slack team ID).

    Returns
    -------
    uuid.UUID
        The tenant_id of the matching IntegrationConfig row.
    None
        No matching row found — caller must reject the request.
    """
    stmt = (
        select(IntegrationConfig)
        .where(
            IntegrationConfig.type == source,
            IntegrationConfig.credential_ref == identifier,
        )
        .limit(1)
    )
    config = db.execute(stmt).scalar_one_or_none()
    if config is None:
        logger.warning(
            "No IntegrationConfig found for source=%s identifier=%r", source, identifier
        )
        return None
    return config.tenant_id
