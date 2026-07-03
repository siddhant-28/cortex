"""The MCP server registers exactly the two intended tools with short descriptions."""

import asyncio


def test_registers_exactly_two_tools():
    from cortex import mcp_server

    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {"search_code", "index_status"}
    # Descriptions cost context every session — keep them short (first line under ~120 chars).
    for t in tools:
        assert t.description
        assert len(t.description.splitlines()[0]) < 120
