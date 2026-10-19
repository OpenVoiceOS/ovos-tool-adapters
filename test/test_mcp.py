"""Tests for MCPToolBox — all MCP I/O is mocked."""
import asyncio
import re
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ovos_plugin_manager.templates.agent_tools import ToolBox

from ovos_tool_adapters.mcp import MCPToolBox
from ovos_tool_adapters._schema import AdapterToolOutput


def _make_mcp_tool(name: str, description: str, schema: Dict[str, Any]) -> SimpleNamespace:
    """Helper: build a fake mcp.types.Tool-like object."""
    return SimpleNamespace(name=name, description=description, inputSchema=schema)


def _make_content_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text, model_dump=lambda: {"type": "text", "text": text})


def _make_call_result(content: List[Any], is_error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(content=content, isError=is_error)


@pytest.fixture()
def fake_mcp_tools():
    return [
        _make_mcp_tool(
            "fetch",
            "Fetch a URL",
            {"properties": {"url": {"type": "string", "description": "URL"}}, "required": ["url"]},
        )
    ]


@pytest.fixture()
def mcp_calls():
    """The tool names the fake MCP session was asked to call."""
    return []


@pytest.fixture()
def mcp_errors(monkeypatch):
    """The messages MCPToolBox logs at ERROR level; request it before mcp_toolbox."""
    messages = []
    monkeypatch.setattr("ovos_tool_adapters.mcp.LOG.error", lambda msg, *a, **kw: messages.append(msg))
    return messages


@pytest.fixture()
def mcp_toolbox(fake_mcp_tools, mcp_calls, monkeypatch):
    """Patch _AsyncRunner and MCP internals; return a configured MCPToolBox."""

    class _FakeSession:
        async def initialize(self):
            pass

        async def list_tools(self):
            return SimpleNamespace(tools=fake_mcp_tools)

        async def call_tool(self, name, args):
            mcp_calls.append(name)
            return _make_call_result([_make_content_block(f"fetched:{args.get('url', '')}")])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class _FakeTransport:
        async def __aenter__(self):
            return (None, None)  # (read, write)

        async def __aexit__(self, *args):
            pass

    # Patch MCP imports inside mcp.py. The real _AsyncRunner (a background
    # asyncio loop) is used as-is — only the `mcp` package itself is faked —
    # since the teardown fix relies on real asyncio Task semantics that a
    # synchronous stand-in can't reproduce.
    fake_mcp_mod = MagicMock()
    fake_mcp_mod.ClientSession.return_value = _FakeSession()
    fake_mcp_mod.client.stdio.StdioServerParameters = SimpleNamespace
    fake_mcp_mod.client.stdio.stdio_client = lambda params: _FakeTransport()

    with patch.dict("sys.modules", {
        "mcp": fake_mcp_mod,
        "mcp.client": fake_mcp_mod.client,
        "mcp.client.stdio": fake_mcp_mod.client.stdio,
    }):
        tb = MCPToolBox(config={"transport": "stdio", "command": "uvx", "args": ["mcp-server-fetch"]})
    yield tb
    tb.close()


def test_mcp_toolbox_id_default(mcp_toolbox):
    assert mcp_toolbox.toolbox_id == "ovos-mcp-toolbox"


def test_mcp_discovers_tools(mcp_toolbox):
    tools = list(mcp_toolbox.tools.values())
    assert len(tools) == 1
    assert tools[0].name == "fetch"
    assert "URL" in tools[0].argument_schema.model_json_schema()["properties"]["url"]["description"]


def test_mcp_tool_json_list(mcp_toolbox):
    jl = mcp_toolbox.tool_json_list
    assert len(jl) == 1
    assert jl[0]["name"] == "fetch"
    assert "argument_schema" in jl[0]


def test_mcp_call_tool_returns_adapter_output(mcp_toolbox):
    result = mcp_toolbox.call_tool("fetch", {"url": "https://example.com"})
    assert isinstance(result, AdapterToolOutput)
    assert "fetched:https://example.com" in result.content
    assert result.is_error is False


def test_mcp_unknown_tool_raises(mcp_toolbox):
    with pytest.raises(ValueError, match="Unknown tool"):
        mcp_toolbox.call_tool("no_such_tool", {})


def test_mcp_missing_package_returns_empty(monkeypatch):
    # Simulate the `mcp` package not being installed: the driver task's
    # `from mcp import ClientSession` raises ImportError, which is routed
    # back through the `ready` future to discover_tools().
    with patch.dict("sys.modules", {"mcp": None}):
        tb = MCPToolBox(config={"transport": "stdio", "command": "uvx", "args": []})
        try:
            assert tb.tools == {}
        finally:
            tb.close()


_URL_SCHEMA = {"properties": {"url": {"type": "string"}}, "required": ["url"]}


@pytest.mark.parametrize("fake_mcp_tools", [[_make_mcp_tool("admin.tools.list", "List tools", _URL_SCHEMA)]])
def test_mcp_dotted_name_is_exposed_in_the_provider_charset(mcp_toolbox, mcp_calls):
    # MCP allows a dot in tool names; OpenAI-style providers reject it.
    assert list(mcp_toolbox.tools) == ["admin_tools_list"]
    sent = ToolBox.normalize_tools([mcp_toolbox])
    assert [t["function"]["name"] for t in sent] == ["admin_tools_list"]
    assert re.match(r"^[A-Za-z0-9_-]{1,64}$", sent[0]["function"]["name"])
    result = mcp_toolbox.call_tool("admin_tools_list", {"url": "u"})
    assert mcp_calls == ["admin.tools.list"]
    assert result.content == "fetched:u"


@pytest.mark.parametrize("fake_mcp_tools", [[_make_mcp_tool("a.b", "first", _URL_SCHEMA),
                                             _make_mcp_tool("a_b", "second", _URL_SCHEMA)]])
def test_mcp_names_that_collide_after_sanitising_are_an_error(mcp_errors, mcp_toolbox, mcp_calls):
    assert list(mcp_toolbox.tools) == ["a_b"]
    mcp_toolbox.call_tool("a_b", {"url": "x"})
    assert mcp_calls == ["a.b"]
    assert mcp_errors == ["MCPToolBox: tools 'a.b' and 'a_b' both become 'a_b'; 'a_b' skipped."]


@pytest.mark.parametrize("fake_mcp_tools", [[_make_mcp_tool("a_b", "listed first", _URL_SCHEMA),
                                             _make_mcp_tool("a.b", "listed second", _URL_SCHEMA)]])
def test_mcp_collision_winner_does_not_depend_on_server_order(mcp_toolbox, mcp_calls):
    mcp_toolbox.call_tool("a_b", {"url": "x"})
    assert mcp_calls == ["a.b"]
