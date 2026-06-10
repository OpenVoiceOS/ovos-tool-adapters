"""Tests for UTCPToolBox — all UTCP I/O is mocked."""
import asyncio
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from ovos_tool_adapters.utcp import UTCPToolBox
from ovos_tool_adapters._schema import AdapterToolOutput


def _make_utcp_tool(name: str, description: str, schema: Dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=description, input_schema=schema)


class _FakeRunner:
    def run(self, coro: Any, timeout: int = 30) -> Any:
        return asyncio.run(coro)

    def close(self) -> None:
        pass


@pytest.fixture()
def utcp_toolbox(monkeypatch):
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)

    tools_list = [
        _make_utcp_tool(
            "search",
            "Search the web",
            {"properties": {"query": {"type": "string"}}, "required": ["query"]},
        )
    ]

    class _FakeClient:
        async def get_tools(self):
            return tools_list

        async def call_tool(self, name, args):
            return {"text": f"result for {args.get('query', '')}", "is_error": False}

    class _FakeUtcpClient:
        @staticmethod
        async def create(config):
            return _FakeClient()

    class _FakeConfig:
        def __init__(self, **kwargs):
            pass

    fake_utcp_mod = MagicMock()
    fake_utcp_mod.client.UtcpClient = _FakeUtcpClient
    fake_utcp_mod.client.utcp_client_config.UtcpClientConfig = _FakeConfig

    with patch.dict("sys.modules", {
        "utcp": fake_utcp_mod,
        "utcp.client": fake_utcp_mod.client,
        "utcp.client.utcp_client_config": fake_utcp_mod.client.utcp_client_config,
    }):
        tb = UTCPToolBox(config={"utcp_config": {}})
    return tb


def test_utcp_discovers_tools(utcp_toolbox):
    tools = list(utcp_toolbox.tools.values())
    assert len(tools) == 1
    assert tools[0].name == "search"


def test_utcp_tool_json_list(utcp_toolbox):
    jl = utcp_toolbox.tool_json_list
    assert len(jl) == 1
    assert jl[0]["name"] == "search"


def test_utcp_call_tool_returns_adapter_output(utcp_toolbox):
    result = utcp_toolbox.call_tool("search", {"query": "hello"})
    assert isinstance(result, AdapterToolOutput)
    assert "result for hello" in result.content
    assert result.is_error is False


def test_utcp_unknown_tool_raises(utcp_toolbox):
    with pytest.raises(ValueError, match="Unknown tool"):
        utcp_toolbox.call_tool("ghost", {})


def test_utcp_missing_package_returns_empty(monkeypatch):
    class _FailRunner(_FakeRunner):
        def run(self, coro, timeout=30):
            raise ImportError("utcp not installed")

    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FailRunner)
    tb = UTCPToolBox(config={"utcp_config": {}})
    assert tb.tools == {}
