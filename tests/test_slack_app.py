"""Tests for Slack App ChatOps, Slash Commands, Interactive Approval Cards, and MCP-Slack Server.

Validates Definition of Done:
1. `/rise status <incident_id>` returns correct live data in Slack.
2. Approval card buttons correctly call real approve/reject/modify API and enforce single-use approval locking (409 Conflict).
3. Card content matches template in prompts.md §9 field-for-field.
4. MCP Slack Server integration dispatches tools cleanly through MCPGateway.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):
    return "JSON"

@compiles(PG_UUID, "sqlite")
def _uuid_sqlite(element, compiler, **kw):
    return "TEXT"

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-secret-rise-unit-tests")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-slack-signing-secret")

from db.base import Base
from db.models import Incident
from apps.api.src.deps.db import get_db
from apps.api.src.deps.redis import get_redis_client
from apps.api.src.services.ingestion.signature_verifier import FakeVerifier, get_slack_verifier
from apps.api.src.services.approval_lock import reset_approval_locks_for_testing
from apps.agents.src.services.slack_card import format_slack_approval_card
import sys
from pathlib import Path
_ROOT_DIR = Path(__file__).resolve().parents[1]
_SLACK_DIR = _ROOT_DIR / "packages" / "mcp-servers" / "mcp-slack"
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))
if str(_SLACK_DIR) not in sys.path:
    sys.path.insert(0, str(_SLACK_DIR))

try:
    from slack_server import MCPSlackServer
except ImportError:
    from packages.mcp_servers.mcp_slack.slack_server import MCPSlackServer  # type: ignore
from mcp_client.gateway import MCPGateway
from apps.api.src.main import app

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
redis_mock = MagicMock()
redis_mock.get.return_value = None
redis_mock.set.return_value = True
redis_mock.delete.return_value = True


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_redis():
    yield redis_mock


@pytest.fixture(autouse=True)
def setup_slack_app_overrides():
    reset_approval_locks_for_testing()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis_client] = override_get_redis
    app.dependency_overrides[get_slack_verifier] = lambda: FakeVerifier()
    yield
    app.dependency_overrides.clear()


client = TestClient(app, raise_server_exceptions=False)


def setup_function():
    reset_approval_locks_for_testing()
    redis_mock.get.return_value = None
    redis_mock.set.return_value = True
    redis_mock.delete.return_value = True
    with TestingSessionLocal() as db:
        db.query(Incident).delete()
        db.commit()


# =============================================================================
# DoD 1: `/rise status <incident_id>` returns correct live data in Slack
# =============================================================================

def test_slash_command_rise_status_returns_live_incident_data():
    """DoD 1: /rise status <incident_id> queries DB and returns formatted live data."""
    inc_id = uuid.uuid4()
    with TestingSessionLocal() as db:
        inc = Incident(
            id=inc_id,
            tenant_id=TENANT_ID,
            title="High Latency in Payment Service",
            description="Database connection pool exhausted",
            status="open",
            severity="SEV1",
        )
        db.add(inc)
        db.commit()

    body = f"command=%2Frise&text=status+{inc_id}"
    resp = client.post(
        "/api/v1/webhooks/slack",
        content=body.encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["incident_id"] == str(inc_id)
    assert data["status"] == "open"
    assert data["severity"] == "SEV1"
    assert data["title"] == "High Latency in Payment Service"
    assert "Incident Status:" in data["text"]


def test_slash_command_rise_status_non_existent_id():
    """/rise status <invalid_id> returns 200 with clear NOT_FOUND message."""
    body = "command=%2Frise&text=status+non-existent-123"
    resp = client.post(
        "/api/v1/webhooks/slack",
        content=body.encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["error"] == "NOT_FOUND"
    assert "not found" in data["text"]


# =============================================================================
# DoD 2: Approval card buttons call real approve/reject/modify API + idempotency
# =============================================================================

def test_approval_card_button_approve():
    """DoD 2: Approve button executes approval flow and marks action approved."""
    inc_id = "inc-slack-approve-001"
    payload = {
        "type": "block_actions",
        "actions": [{"action_id": "approve_action", "value": f"approve:{inc_id}"}],
    }
    body = f"payload={json.dumps(payload)}"

    resp = client.post(
        "/api/v1/webhooks/slack",
        content=body.encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "approved"
    assert data["incident_id"] == inc_id
    assert "APPROVED" in data["text"]


def test_approval_card_button_double_click_returns_409_conflict():
    """DoD 2: Second click on Approve returns 409 Conflict (single-use lock)."""
    inc_id = "inc-slack-double-click-002"
    payload = {
        "type": "block_actions",
        "actions": [{"action_id": "approve_action", "value": f"approve:{inc_id}"}],
    }
    body = f"payload={json.dumps(payload)}"

    # 1st click -> approved
    resp1 = client.post(
        "/api/v1/webhooks/slack",
        content=body.encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp1.status_code == 200

    # 2nd click -> 409 Conflict
    resp2 = client.post(
        "/api/v1/webhooks/slack",
        content=body.encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp2.status_code == 409
    err = resp2.json()["error"]
    assert err["code"] == "ALREADY_DECIDED"


def test_approval_card_button_reject():
    """DoD 2: Reject button marks action rejected."""
    inc_id = "inc-slack-reject-003"
    payload = {
        "type": "block_actions",
        "actions": [{"action_id": "reject_action", "value": f"reject:{inc_id}"}],
    }
    body = f"payload={json.dumps(payload)}"

    resp = client.post(
        "/api/v1/webhooks/slack",
        content=body.encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "rejected"
    assert "REJECTED" in data["text"]


def test_approval_card_button_modify():
    """DoD 2: Modify button marks action for re-evaluation."""
    inc_id = "inc-slack-modify-004"
    payload = {
        "type": "block_actions",
        "actions": [{"action_id": "modify_action", "value": f"modify:{inc_id}"}],
    }
    body = f"payload={json.dumps(payload)}"

    resp = client.post(
        "/api/v1/webhooks/slack",
        content=body.encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "re-evaluated"
    assert "MODIFIED" in data["text"]


# =============================================================================
# DoD 3: Card content matches template in prompts.md §9 field-for-field
# =============================================================================

def test_slack_approval_card_prompts_sec9_template_match():
    """DoD 3: Card content matches prompts.md §9 template field-for-field."""
    state = {
        "incident_id": "inc-prompts-sec9-100",
        "severity": "SEV1",
        "root_cause": {
            "cause_summary": "Deadlock in Postgres database transaction pool",
            "confidence": 0.95,
        },
        "impact_assessment": {
            "blast_radius_services": ["payment-service", "checkout-api"],
            "estimated_users_affected": 12500,
        },
        "action_plan": {
            "action_type": "restart_pod",
            "action_steps": [{"tool": "restart_pod", "params": {"namespace": "prod", "pod_name": "payment-api-1"}}],
            "rollback_plan": [{"tool": "rollback_deployment", "params": {"namespace": "prod", "deployment_name": "payment-api"}}],
        },
        "risk_tier": "critical",
        "sla_minutes": 10,
    }

    card = format_slack_approval_card(state)

    # Field-for-field assertion
    assert card["incident_id"] == "inc-prompts-sec9-100"
    assert card["severity"] == "SEV1"
    assert card["confidence"] == 95
    assert card["cause_summary"] == "Deadlock in Postgres database transaction pool"
    assert card["blast_radius_services"] == "payment-service, checkout-api"
    assert card["estimated_users_affected"] == 12500
    assert card["action_type"] == "restart_pod"
    assert card["risk_tier"] == "critical"
    assert card["sla_minutes"] == 10

    # Text formatting verification
    text = card["text"]
    assert "*Incident inc-prompts-sec9-100 — SEV1 — Approval Needed*" in text
    assert "*Root Cause* (95% confidence): Deadlock in Postgres database transaction pool" in text
    assert "*Impact*: payment-service, checkout-api · Est. 12500 users" in text
    assert "*Proposed Action*: restart_pod" in text
    assert "*Rollback Plan*:" in text
    assert "*Risk Tier*: critical" in text
    assert "[Approve] [Reject] [Modify] [View Full Details]" in text
    assert "_This approval expires in 10 minutes and is bound to this exact plan._" in text


# =============================================================================
# MCP-Slack Server Integration Tests
# =============================================================================

import asyncio

def test_mcp_slack_server_tool_dispatch():
    """MCPSlackServer tools dispatch through MCPGateway allowlist."""
    async def _test():
        slack_srv = MCPSlackServer()
        gateway = MCPGateway(slack_server=slack_srv)

        # 1. post_interactive_approval tool
        res = await gateway.dispatch_tool_call(
            agent_identity="orchestrator-agent",
            tool_name="post_interactive_approval",
            params={
                "channel": "incidents",
                "incident_data": {
                    "incident_id": "inc-mcp-test-1",
                    "severity": "SEV2",
                    "cause_summary": "High CPU utilization on auth node",
                    "confidence": 0.88,
                },
            },
        )
        assert res["status"] == "success"
        assert res["incident_id"] == "inc-mcp-test-1"

        # 2. post_message tool
        res_msg = await gateway.dispatch_tool_call(
            agent_identity="notification-service",
            tool_name="post_message",
            params={"channel": "incidents", "text": "Test notification message"},
        )
        assert res_msg["status"] == "success"
        assert res_msg["text"] == "Test notification message"

        # 3. read_thread tool
        res_thread = await gateway.dispatch_tool_call(
            agent_identity="orchestrator-agent",
            tool_name="read_thread",
            params={"channel": "incidents", "thread_ts": "1600000000.000100"},
        )
        assert res_thread["status"] == "success"
        assert len(res_thread["messages"]) > 0

    asyncio.run(_test())
