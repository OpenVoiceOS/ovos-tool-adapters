"""Live round-trip test for MCPToolBox against a real ``mcp`` stdio server.

Unlike test_mcp.py (which mocks all MCP I/O), this spins up a tiny real MCP
server (test/_live_mcp_server.py) as a stdio subprocess and drives it through
the actual ``mcp`` client SDK, proving MCPToolBox works end-to-end against
whatever ``mcp`` version is installed (1.x or 2.x).
"""
import sys
from pathlib import Path

import pytest

from ovos_tool_adapters.mcp import MCPToolBox
from ovos_tool_adapters._schema import AdapterToolOutput

pytest.importorskip("mcp")

_SERVER_SCRIPT = str(Path(__file__).parent / "_live_mcp_server.py")


@pytest.fixture()
def live_toolbox():
    tb = MCPToolBox(config={
        "transport": "stdio",
        "command": sys.executable,
        "args": [_SERVER_SCRIPT],
        "timeout": 30,
    })
    try:
        yield tb
    finally:
        tb.close()


def test_live_discover_tools(live_toolbox):
    tools = list(live_toolbox.tools.values())
    assert len(tools) == 1
    assert tools[0].name == "echo"


def test_live_call_tool_round_trip(live_toolbox):
    result = live_toolbox.call_tool("echo", {"text": "hello-mcp"})
    assert isinstance(result, AdapterToolOutput)
    assert result.is_error is False
    assert "echo:hello-mcp" in result.content
