"""Tenant resolution from IntegrationConfig for unauthenticated webhook requests.

Webhooks authenticate via HMAC/signature — there is no JWT and therefore no
``user.tenant_id`` claim.  Instead, each source's payload carries a
source-specific identifier that we match against ``integration_configs`` to
resolve a tenant.

If no match is found, the request is **rejected with 400 and audit-logged**.
There is no fallback tenant — unknown source ≠ default tenant.

Identifier extraction
---------------------
| Source       | Identifier                                | Stored in                          |
|--------------|-------------------------------------------|------------------------------------|
| github       | ``repository.owner.login`` (org/user)     | IntegrationConfig.credential_ref   |
| cloudwatch   | AWS account-id from SNS ``TopicArn[4]``   | IntegrationConfig.credential_ref   |
| slack        | ``team_id`` (top-level)                   | IntegrationConfig.credential_ref   |
| alertmanager | ``groupLabels.cluster`` label             | IntegrationConfig.credential_ref   |
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
    """Return the GitHub org/owner login (``repository.owner.login``)."""
    repo = payload.get("repository") or {}
    owner = repo.get("owner") or {}
    login = owner.get("login") or owner.get("name")
    if login:
        return str(login)
    # GitHub App installation events carry the account under ``installation``
    installation = payload.get("installation") or {}
    account = installation.get("account") or {}
    return account.get("login")


def _extract_cloudwatch_identifier(payload: Dict[str, Any]) -> Optional[str]:
    """Return the AWS account-id from SNS ``TopicArn`` (colon-index 4).

    SNS TopicArn format: ``arn:aws:sns:{region}:{account-id}:{topic-name}``

    This is the single, deterministic identifier — we do NOT fall back to any
    other field.  A payload without a valid TopicArn is rejected.
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
    """Return the Slack workspace ``team_id`` (top-level field)."""
    team_id = payload.get("team_id")
    return str(team_id) if team_id else None


def _extract_alertmanager_identifier(payload: Dict[str, Any]) -> Optional[str]:
    """Return the Alertmanager cluster identifier from ``groupLabels.cluster``.

    If no ``cluster`` label is present, falls back to the ``externalURL`` host
    (the Alertmanager instance URL), which operators can use as a stable
    identifier per their integration registration.
    """
    group_labels: Dict[str, Any] = payload.get("groupLabels") or {}
    cluster = group_labels.get("cluster")
    if cluster:
        return str(cluster)
    external_url = payload.get("externalURL", "")
    if external_url:
        m = re.match(r"https?://([^/:]+)", external_url)
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
    determined from the payload.
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

    Matches ``IntegrationConfig`` rows by ``type=source`` and
    ``credential_ref=identifier``.  The ``credential_ref`` column stores the
    per-tenant integration identifier (org name, AWS account ID, Slack team ID,
    Alertmanager host) set when the operator connects the integration.

    Returns
    -------
    uuid.UUID
        The tenant_id of the matching row.
    None
        No match — the caller must reject the request and audit-log the attempt.
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
            "No IntegrationConfig found for source=%s identifier=%r — rejecting",
            source,
            identifier,
        )
        return None
    return config.tenant_id
