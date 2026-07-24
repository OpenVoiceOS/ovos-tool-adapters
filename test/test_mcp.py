"""Tests for MCPToolBox — all MCP I/O is mocked."""
import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ovos_tool_adapters.mcp import MCPToolBox
from ovos_tool_adapters._schema import AdapterToolOutput


def _make_mcp_tool(name: str, description: str, schema: Dict[str, Any]) -> SimpleNamespace:
    """Helper: build a fake mcp.types.Tool-like object."""
    return SimpleNamespace(name=name, description=description, inputSchema=schema)


def _make_content_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text, model_dump=lambda: {"type": "text", "text": text})


def _make_call_result(content: List[Any], is_error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(content=content, isError=is_error)


class _FakeRunner:
    """Synchronous stand-in for _AsyncRunner."""

    def __init__(self) -> None:
        self._coros: List[Any] = []

    def run(self, coro: Any, timeout: int = 30) -> Any:
        return asyncio.run(coro)

    def close(self) -> None:
        pass


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
def mcp_toolbox(fake_mcp_tools, monkeypatch):
    """Patch _AsyncRunner and MCP internals; return a configured MCPToolBox."""

    class _FakeSession:
        async def initialize(self):
            pass

        async def list_tools(self):
            return SimpleNamespace(tools=fake_mcp_tools)

        async def call_tool(self, name, args):
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

    # Patch _AsyncRunner to use the synchronous loop executor
    monkeypatch.setattr("ovos_tool_adapters.mcp._AsyncRunner", _FakeRunner)

    # Patch MCP imports inside mcp.py
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
    return tb


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
    monkeypatch.setattr("ovos_tool_adapters.mcp._AsyncRunner", _FakeRunner)

    class _FailRunner(_FakeRunner):
        def run(self, coro, timeout=30):
            raise ImportError("mcp not installed")

    monkeypatch.setattr("ovos_tool_adapters.mcp._AsyncRunner", _FailRunner)
    tb = MCPToolBox(config={"transport": "stdio", "command": "uvx", "args": []})
    assert tb.tools == {}
