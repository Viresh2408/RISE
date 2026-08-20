"""Integrations Router.

Manages connections to external infrastructure and SaaS tools.
Uses an in-process store (upgradeable to DB) for the demo environment.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from schemas import IntegrationConnectResponse, IntegrationDTO
from apps.api.src.deps import require_role, UserContext
from apps.api.src.middleware.envelope import build_response

router = APIRouter(prefix="/integrations", tags=["Integrations"])

# ---------------------------------------------------------------------------
# Catalog & in-memory state (persists for lifetime of the server process)
# ---------------------------------------------------------------------------

CATALOG = {
    "github": {
        "name": "GitHub Repository & App",
        "description": "Pull request creation, automated code diff analysis, and commit context ingestion.",
        "icon": "github",
        "scopes": ["repo", "workflow", "read:org"],
    },
    "slack": {
        "name": "Slack Workspace ChatOps",
        "description": "Real-time alert notifications, interactive approval cards, and operator slash commands.",
        "icon": "slack",
        "scopes": ["chat:write", "channels:read", "app_mentions:read"],
    },
    "cloudwatch": {
        "name": "AWS CloudWatch Metrics & Logs",
        "description": "Inbound alarm webhooks, CloudWatch logs correlation, and EC2/Lambda execution telemetry.",
        "icon": "cloudwatch",
        "scopes": ["logs:DescribeLogGroups", "cloudwatch:GetMetricData"],
    },
    "alertmanager": {
        "name": "Prometheus Alertmanager",
        "description": "Prometheus metric stream alerts, firing rule webhook receiver, and target health state.",
        "icon": "alertmanager",
        "scopes": ["webhook:receiver"],
    },
}

# Keyed by type: {"status": "connected" | "disconnected", "connected_at": ISO str | None}
_store: dict[str, dict] = {
    "github": {"status": "connected", "connected_at": "2026-08-10T00:00:00Z"},
    "slack": {"status": "disconnected", "connected_at": None},
    "cloudwatch": {"status": "disconnected", "connected_at": None},
    "alertmanager": {"status": "disconnected", "connected_at": None},
}


def _build_dto(type_: str) -> dict:
    meta = CATALOG.get(type_, {})
    state = _store.get(type_, {"status": "disconnected", "connected_at": None})
    return IntegrationDTO(
        type=type_,
        name=meta.get("name", type_),
        description=meta.get("description", ""),
        status=state["status"],
        scopes=meta.get("scopes", []),
        connected_at=state.get("connected_at"),
        icon=meta.get("icon"),
    ).model_dump()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def list_integrations(
    user: UserContext = Depends(require_role("admin")),
):
    """Return all integration cards with current connection status."""
    integrations = [_build_dto(t) for t in CATALOG]
    return build_response(data=integrations)


@router.post("/{type}/connect")
async def connect_integration(
    type: str,
    user: UserContext = Depends(require_role("admin")),
):
    """Connect an integration. OAuth providers return a redirect_url.
    Webhook-based providers (alertmanager, cloudwatch) are marked as connected directly."""
    if type not in CATALOG:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Unknown integration type: {type}", "details": {}},
        )

    now = datetime.now(timezone.utc).isoformat()
    _store[type] = {"status": "connected", "connected_at": now}

    if type in ("github", "slack"):
        # Demo environment: mark as connected directly (no real OAuth app registered)
        res = IntegrationConnectResponse(
            redirect_url=None,
            success=True,
            message=f"{CATALOG[type]['name']} connected successfully via demo credentials.",
        ).model_dump()
    else:
        # Webhook-based: mark connected immediately, no OAuth redirect needed
        res = IntegrationConnectResponse(
            redirect_url=None,
            success=True,
            message=f"{CATALOG[type]['name']} connected successfully. Configure your webhook endpoint to forward alerts.",
        ).model_dump()

    return build_response(data=res)


@router.delete("/{type}")
async def disconnect_integration(
    type: str,
    user: UserContext = Depends(require_role("admin")),
):
    """Disconnect an integration."""
    if type not in CATALOG:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Unknown integration type: {type}", "details": {}},
        )

    _store[type] = {"status": "disconnected", "connected_at": None}
    return build_response(data={"disconnected": True, "type": type})

