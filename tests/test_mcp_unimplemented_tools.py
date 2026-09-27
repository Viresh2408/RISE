"""Phase 6 regression: allow-listed-but-unimplemented MCP tools.

The mcp-observability (`query_prometheus`/`query_loki`/`query_alertmanager`) and
mcp-knowledge (`search_similar_incidents`/`search_runbooks`) tools are present in the
gateway read allow-list for policy completeness, but their backing servers are not
implemented in this build. Previously dispatching them fell through to
``raise ValueError("No registered server ...")`` — an opaque crash.

These tests lock in the Phase 6 minimum fix: a clear, typed ``ToolNotImplementedError``
that is audited distinctly as ``not_implemented``.
"""

import pytest
from unittest.mock import MagicMock

from mcp_client.gateway import MCPGateway, ToolNotImplementedError


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool_name,expected_server",
    [
        ("query_prometheus", "mcp-observability"),
        ("query_loki", "mcp-observability"),
        ("query_alertmanager", "mcp-observability"),
        ("search_similar_incidents", "mcp-knowledge"),
        ("search_runbooks", "mcp-knowledge"),
    ],
)
async def test_unimplemented_read_tool_raises_typed_not_implemented(tool_name, expected_server):
    gw = MCPGateway()
    with pytest.raises(ToolNotImplementedError) as exc_info:
        await gw.dispatch_tool_call(
            agent_identity="investigation-agent",
            tool_name=tool_name,
            params={"query": "up"},
            environment="dev",
            incident_id="inc-phase6-01",
            db_session=None,
        )
    # Typed error carrying provenance, NOT an opaque ValueError.
    assert not isinstance(exc_info.value, ValueError)
    assert exc_info.value.tool_name == tool_name
    assert exc_info.value.server == expected_server


@pytest.mark.anyio
async def test_unimplemented_tool_audited_as_not_implemented():
    gw = MCPGateway()
    gw._record_audit_event = MagicMock()

    with pytest.raises(ToolNotImplementedError):
        await gw.dispatch_tool_call(
            agent_identity="investigation-agent",
            tool_name="query_prometheus",
            params={"query": "up"},
            environment="dev",
            incident_id="inc-phase6-02",
            db_session=None,
        )

    gw._record_audit_event.assert_called_once()
    assert gw._record_audit_event.call_args.kwargs.get("status") == "not_implemented"
