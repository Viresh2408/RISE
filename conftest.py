import os
import sys

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-secret-rise-unit-tests")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-slack-signing-secret")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-github-secret")
os.environ.setdefault("ALERTMANAGER_WEBHOOK_SECRET", "test-alertmanager-secret")
os.environ.setdefault("ENVIRONMENT", "test")

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

sys.path.insert(0, os.path.abspath("packages/rise-core"))
sys.path.insert(0, os.path.abspath("."))

@compiles(JSONB, "sqlite")
def visit_JSONB(element, compiler, **kw):
    return "JSON"

@compiles(PG_UUID, "sqlite")
def visit_UUID(element, compiler, **kw):
    return "TEXT"

from db.base import Base

def _patch_metadata_for_sqlite(metadata):
    for table in metadata.tables.values():
        for col in table.columns:
            if col.server_default is None:
                continue
            try:
                raw = str(col.server_default.arg)
            except Exception:
                raw = ""
            if "gen_random_uuid" in raw:
                col.server_default = None

_patch_metadata_for_sqlite(Base.metadata)


import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def offline_agent_io(monkeypatch):
    """Routing tests exercise real nodes without live LLMs, telemetry or embeddings.

    This fixture is opt-in: agent, gateway and integration-contract tests retain
    their own injected boundaries. It is not an RCA accuracy or live load result.
    """
    from apps.agents.src.nodes import context_builder, investigation, root_cause, impact_analyzer, verification

    for name in ("fetch_loki_logs", "fetch_prometheus_metrics", "fetch_github_deploys"):
        monkeypatch.setattr(context_builder, name, lambda *args, **kwargs: ("[]", False))
    monkeypatch.setattr(context_builder, "fetch_similar_incidents", lambda *args, **kwargs: ([], False))
    monkeypatch.setattr(investigation, "fetch_runbook_snippets", lambda *args, **kwargs: ("No matching runbooks.", False))
    for node in (context_builder, investigation, root_cause, impact_analyzer, verification):
        monkeypatch.setattr(node, "call_structured", AsyncMock(side_effect=RuntimeError("offline routing fixture")))
