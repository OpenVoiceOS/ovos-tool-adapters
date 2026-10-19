"""Tests for UTCPToolBox — all UTCP I/O is mocked."""
import asyncio
import gc
import sys
import warnings
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from ovos_tool_adapters.utcp import UTCP_DOCS_URL, UTCPToolBox, _config_error, _utcp_http_installed
from ovos_tool_adapters._schema import AdapterToolOutput


def _make_utcp_tool(name: str, description: str, schema: Dict[str, Any]) -> SimpleNamespace:
    inputs = SimpleNamespace(model_dump=lambda **_: schema)
    return SimpleNamespace(name=name, description=description, inputs=inputs)


class _FakeRunner:
    def run(self, coro: Any, timeout: int = 30) -> Any:
        return asyncio.run(coro)

    def close(self) -> None:
        pass


class _Clients:
    """Counts the fake UTCP clients a toolbox creates and closes."""

    def __init__(self):
        self.created = 0
        self.closed = 0


def _fake_utcp_modules(tools_list, clients=None, create_error=None, registered_types=("http",),
                       register_error=None, close_error=None):
    """Stand-ins for the utcp 1.x module layout the toolbox imports."""
    clients = clients or _Clients()

    class _FakeRepository:
        async def get_tools(self):
            return tools_list

    class _FakeClient:
        config = SimpleNamespace(tool_repository=_FakeRepository())

        async def register_manuals(self, templates):
            if register_error is not None:
                raise register_error
            return []

        async def call_tool(self, name, args):
            return {"text": f"result for {args.get('query', '')}", "is_error": False}

        async def close(self):
            clients.closed += 1
            if close_error is not None:
                raise close_error

    class _FakeUtcpClient:
        @staticmethod
        async def create(config):
            if create_error is not None:
                raise create_error
            clients.created += 1
            return _FakeClient()

    class _FakeConfig:
        def __init__(self, **kwargs):
            self.manual_call_templates = kwargs.get("manual_call_templates", [])

    class _FakeSerializer:
        def validate_dict(self, template):
            if template["call_template_type"] not in registered_types:
                raise ValueError(f"Invalid call template type: {template['call_template_type']}")
            return SimpleNamespace(**template)

    fake_utcp_mod = MagicMock()
    fake_utcp_mod.data.call_template.CallTemplateSerializer = _FakeSerializer
    fake_utcp_mod.utcp_client.UtcpClient = _FakeUtcpClient
    fake_utcp_mod.data.utcp_client_config.UtcpClientConfig = _FakeConfig
    return {
        "utcp": fake_utcp_mod,
        "utcp.utcp_client": fake_utcp_mod.utcp_client,
        "utcp.data": fake_utcp_mod.data,
        "utcp.data.utcp_client_config": fake_utcp_mod.data.utcp_client_config,
        "utcp.data.call_template": fake_utcp_mod.data.call_template,
    }


_SEARCH_TOOL = _make_utcp_tool(
    "search",
    "Search the web",
    {"properties": {"query": {"type": "string"}}, "required": ["query"]},
)


@pytest.fixture()
def utcp_toolbox(monkeypatch):
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)
    with patch.dict("sys.modules", _fake_utcp_modules([_SEARCH_TOOL])):
        tb = UTCPToolBox(config={"utcp_config": {}})
    return tb


def _captured(monkeypatch, level):
    """Collect the messages the toolbox logs at *level*."""
    messages = []
    monkeypatch.setattr(f"ovos_tool_adapters.utcp.LOG.{level}", lambda msg, *a, **kw: messages.append(msg))
    return messages


def test_utcp_toolbox_id_default(utcp_toolbox):
    assert utcp_toolbox.toolbox_id == "ovos-utcp-toolbox"


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
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)
    # Setting the module to None in sys.modules is the standard way to make
    # `import utcp` raise ImportError regardless of what is actually installed.
    monkeypatch.setitem(sys.modules, "utcp", None)
    tb = UTCPToolBox(config={"utcp_config": {}})
    assert tb.tools == {}


def test_utcp_missing_package_does_not_leave_coroutine_unawaited(monkeypatch):
    """
    Regression test: discover_tools() used to unconditionally create the
    ``_connect_and_list`` coroutine and hand it to ``self._runner.run(...)``.
    If the runner failed to schedule it — anything raised on the way to, or
    inside, ``run()`` before it reaches ``asyncio.run_coroutine_threadsafe`` —
    the coroutine was silently garbage collected without ever running,
    producing a "coroutine '_connect_and_list' was never awaited"
    RuntimeWarning. That is exactly the shape of problem fixed for
    MCPToolBox's session teardown.

    The fix checks that ``utcp`` is importable *before* ``_connect_and_list``
    is ever called, so on the missing-package path no coroutine is created at
    all, regardless of what the runner would have done with it.
    """

    class _LeakyRunner:
        """A runner that never touches the coroutine it is handed."""

        def run(self, coro, timeout=30):
            raise RuntimeError("runner unavailable")

        def close(self) -> None:
            pass

    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _LeakyRunner)
    monkeypatch.setitem(sys.modules, "utcp", None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tb = UTCPToolBox(config={"utcp_config": {}})
        gc.collect()

    unawaited = [w for w in caught
                 if issubclass(w.category, RuntimeWarning) and "was never awaited" in str(w.message)]
    assert not unawaited, f"unawaited coroutine leaked: {unawaited}"
    assert tb.tools == {}


def test_utcp_argument_schema_comes_from_tool_inputs(utcp_toolbox):
    """utcp 1.x tools carry their JSON Schema in ``inputs``, not ``input_schema``."""
    args_model = utcp_toolbox.tools["search"].argument_schema
    assert list(args_model.model_fields) == ["query"]
    assert args_model.model_fields["query"].is_required()


@pytest.mark.parametrize("key", ["tool_providers", "providers"])
def test_utcp_pre_1x_provider_keys_are_refused(monkeypatch, key):
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)
    errors = _captured(monkeypatch, "error")
    clients = _Clients()
    legacy = {key: [{"name": "tx", "provider_type": "http", "url": "http://localhost:9686/utcp"}]}
    with patch.dict("sys.modules", _fake_utcp_modules([_SEARCH_TOOL], clients)):
        tb = UTCPToolBox(config={"utcp_config": legacy})
    assert tb.tools == {}
    assert clients.created == 0
    assert errors == [
        f"UTCPToolBox: 'utcp_config.{key}' is not a UTCP 1.x key; list each manual in "
        f"'manual_call_templates' instead, see {UTCP_DOCS_URL} — no tools loaded."
    ]


@pytest.mark.parametrize("template, missing", [
    ({"name": "tx", "url": "http://localhost:9686/utcp"}, "call_template_type"),
    ({"name": "tx", "call_template_type": "http", "http_method": "GET"}, "url"),
])
def test_utcp_template_missing_key_names_key_and_template(template, missing):
    error = _config_error({"manual_call_templates": [{"name": "ok", "call_template_type": "http",
                                                      "url": "http://a/utcp"}, template]})
    assert error == (f"manual_call_templates[1] ('tx') is missing the required key {missing!r}, "
                     f"see {UTCP_DOCS_URL}")


@pytest.mark.parametrize("utcp_config, error", [
    ("http://localhost:9686/utcp", "'utcp_config' must be an object, not str"),
    ({"manual_call_templates": "http://localhost:9686/utcp"},
     "'utcp_config.manual_call_templates' must be a list, not str"),
    ({"manual_call_templates": ["http://localhost:9686/utcp"]},
     "manual_call_templates[0] must be an object, not str"),
])
def test_utcp_malformed_config_shape_is_named(utcp_config, error):
    assert _config_error(utcp_config) == error


def test_utcp_close_closes_the_client(monkeypatch):
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)
    clients = _Clients()
    with patch.dict("sys.modules", _fake_utcp_modules([_SEARCH_TOOL], clients)):
        tb = UTCPToolBox(config={"utcp_config": {}})
    tb.close()
    assert (clients.created, clients.closed) == (1, 1)
    tb.close()
    assert clients.closed == 1


def test_utcp_close_skips_the_client_at_interpreter_shutdown(monkeypatch):
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)
    clients = _Clients()
    with patch.dict("sys.modules", _fake_utcp_modules([_SEARCH_TOOL], clients)):
        tb = UTCPToolBox(config={"utcp_config": {}})
    monkeypatch.setattr("ovos_tool_adapters.utcp.sys.is_finalizing", lambda: True)
    tb.close()
    assert clients.closed == 0


def test_utcp_refresh_closes_the_previous_client(monkeypatch):
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)
    clients = _Clients()
    with patch.dict("sys.modules", _fake_utcp_modules([_SEARCH_TOOL], clients)):
        tb = UTCPToolBox(config={"utcp_config": {}})
        for _ in range(5):
            tb.refresh_tools()
        assert (clients.created, clients.closed) == (6, 5)
        tb.close()
    assert (clients.created, clients.closed) == (6, 6)


@pytest.mark.parametrize("installed", [True, False])
def test_utcp_http_hint_only_when_utcp_http_is_missing(monkeypatch, installed):
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)
    monkeypatch.setattr("ovos_tool_adapters.utcp._utcp_http_installed", lambda: installed)
    errors = _captured(monkeypatch, "error")
    template = {"name": "tx", "call_template_type": "http", "url": "http://localhost:9686/utcp"}
    with patch.dict("sys.modules", _fake_utcp_modules([], registered_types=())):
        tb = UTCPToolBox(config={"utcp_config": {"manual_call_templates": [template]}})
    assert tb.tools == {}
    hint = " The utcp-http plugin is not installed: pip install 'ovos-tool-adapters[utcp]'."
    assert errors == ["UTCPToolBox: manual_call_templates[0] ('tx') skipped: "
                      "Invalid call template type: http." + ("" if installed else hint)]


def test_utcp_http_installed_reads_the_real_import_state(monkeypatch):
    import importlib.util
    real_find_spec = importlib.util.find_spec
    assert _utcp_http_installed() is (real_find_spec("utcp_http") is not None)
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: None if name == "utcp_http" else real_find_spec(name, *a))
    assert _utcp_http_installed() is False


def test_utcp_client_is_closed_when_registration_raises(monkeypatch):
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)
    clients = _Clients()
    modules = _fake_utcp_modules([_SEARCH_TOOL], clients, register_error=LookupError("API_KEY not set"))
    with patch.dict("sys.modules", modules):
        tb = UTCPToolBox(config={"utcp_config": {}})
        tb.refresh_tools()
    assert tb.tools == {}
    assert (clients.created, clients.closed) == (2, 2)


def test_utcp_registration_error_survives_a_failing_close(monkeypatch):
    monkeypatch.setattr("ovos_tool_adapters.utcp._AsyncRunner", _FakeRunner)
    warnings_logged = _captured(monkeypatch, "warning")
    clients = _Clients()
    registration_error = LookupError("API_KEY not set")
    modules = _fake_utcp_modules([_SEARCH_TOOL], clients, register_error=registration_error,
                                 close_error=RuntimeError("close boom"))
    with patch.dict("sys.modules", modules):
        tb = UTCPToolBox(config={"utcp_config": {}})
    assert tb.tools == {}
    assert (clients.created, clients.closed) == (1, 1)
    assert warnings_logged == [f"UTCPToolBox: failed to connect to UTCP server: {registration_error}"]
