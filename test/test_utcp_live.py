"""Live round-trip test for UTCPToolBox against a real UTCP HTTP manual.

Unlike test_utcp.py (which mocks all UTCP I/O), this serves a UTCP 1.0 manual
and an HTTP endpoint from a local server and drives them through the installed
``utcp`` and ``utcp-http`` packages.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from ovos_tool_adapters._schema import AdapterToolOutput
from ovos_tool_adapters.utcp import UTCPToolBox


class _ManualGate:
    """Holds the manual response while a test calls tools during a refresh."""

    def __init__(self):
        self.hold = False
        self.requested = threading.Event()
        self.release = threading.Event()


_gate = _ManualGate()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/utcp" and _gate.hold:
            _gate.requested.set()
            _gate.release.wait(timeout=10)
        if url.path == "/utcp":
            base = f"http://{self.headers['Host']}"
            body = {
                "utcp_version": "1.0.0",
                "manual_version": "1.0.0",
                "tools": [{
                    "name": "echo",
                    "description": "Echo the text back with an 'echo:' prefix.",
                    "inputs": {"type": "object",
                               "properties": {"text": {"type": "string"}},
                               "required": ["text"]},
                    "outputs": {"type": "string"},
                    "tool_call_template": {"call_template_type": "http",
                                           "url": f"{base}/echo",
                                           "http_method": "GET"},
                }],
            }
        elif url.path == "/locked/utcp":
            self.send_error(401, "Unauthorized")
            return
        elif url.path == "/echo":
            body = "echo:" + parse_qs(url.query)["text"][0]
        else:
            self.send_error(404)
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def manual_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/utcp"
    server.shutdown()


def _toolbox(utcp_config):
    return UTCPToolBox(config={"utcp_config": utcp_config, "timeout": 30})


def test_live_call_tool_round_trip(manual_url):
    tb = _toolbox({"manual_call_templates": [{
        "name": "local", "call_template_type": "http",
        "url": manual_url, "http_method": "GET"}]})
    try:
        assert list(tb.tools) == ["local.echo"]
        result = tb.call_tool("local.echo", {"text": "hello-utcp"})
        assert isinstance(result, AdapterToolOutput)
        assert result.is_error is False
        assert result.content == "echo:hello-utcp"
    finally:
        tb.close()


def test_live_failed_manual_reports_the_reason(manual_url, monkeypatch):
    errors = []
    monkeypatch.setattr("ovos_tool_adapters.utcp.LOG.error", lambda msg, *a, **kw: errors.append(msg))
    locked_url = manual_url.replace("/utcp", "/locked/utcp")
    tb = _toolbox({"manual_call_templates": [
        {"name": "locked", "call_template_type": "http", "url": locked_url, "http_method": "GET"},
        {"name": "local", "call_template_type": "http", "url": manual_url, "http_method": "GET"},
    ]})
    try:
        assert list(tb.tools) == ["local.echo"]
        assert len(errors) == 1
        assert errors[0].startswith("UTCPToolBox: manual 'locked' loaded no tools: ")
        assert "401" in errors[0]
    finally:
        tb.close()


def test_live_tool_calls_keep_working_during_a_refresh(manual_url):
    tb = _toolbox({"manual_call_templates": [{
        "name": "local", "call_template_type": "http",
        "url": manual_url, "http_method": "GET"}]})
    _gate.hold = True
    refresh = threading.Thread(target=tb.refresh_tools)
    try:
        refresh.start()
        assert _gate.requested.wait(timeout=10)
        result = tb.call_tool("local.echo", {"text": "during-refresh"})
        assert result.content == "echo:during-refresh"
    finally:
        _gate.hold = False
        _gate.release.set()
        refresh.join(timeout=10)
        tb.close()
    assert list(tb.tools) == ["local.echo"]


@pytest.mark.parametrize("bad_template, reason", [
    ({"name": "cli-tools", "call_template_type": "cli", "command": "my-cli-tool"},
     "Invalid call template type: cli"),
    ({"name": "bad-method", "call_template_type": "http", "url": "http://127.0.0.1:1/utcp",
      "http_method": "FOO"},
     "http_method: Input should be 'GET', 'POST', 'PUT', 'DELETE' or 'PATCH'"),
])
def test_live_invalid_template_is_skipped_and_named(manual_url, monkeypatch, bad_template, reason):
    errors = []
    monkeypatch.setattr("ovos_tool_adapters.utcp.LOG.error", lambda msg, *a, **kw: errors.append(msg))
    tb = _toolbox({"manual_call_templates": [
        bad_template,
        {"name": "local", "call_template_type": "http", "url": manual_url, "http_method": "GET"},
    ]})
    try:
        assert list(tb.tools) == ["local.echo"]
        assert tb.call_tool("local.echo", {"text": "still-here"}).content == "echo:still-here"
        assert errors == [f"UTCPToolBox: manual_call_templates[0] ({bad_template['name']!r}) skipped: {reason}."]
    finally:
        tb.close()


def _type_error(operation):
    try:
        operation()
    except TypeError as exc:
        return f"TypeError: {exc}"


@pytest.mark.parametrize("bad_template, reason", [
    ({"name": "auth-str", "call_template_type": "http", "url": "http://127.0.0.1:1/utcp", "auth": "token"},
     _type_error(lambda: "token"["auth_type"])),
    ({"name": "type-list", "call_template_type": ["http"], "url": "http://127.0.0.1:1/utcp"},
     _type_error(lambda: {}[["http"]])),
])
def test_live_rejection_without_pydantic_error_names_the_cause(manual_url, monkeypatch, bad_template, reason):
    errors = []
    monkeypatch.setattr("ovos_tool_adapters.utcp.LOG.error", lambda msg, *a, **kw: errors.append(msg))
    tb = _toolbox({"manual_call_templates": [
        bad_template,
        {"name": "local", "call_template_type": "http", "url": manual_url, "http_method": "GET"},
    ]})
    try:
        assert list(tb.tools) == ["local.echo"]
        assert errors == [f"UTCPToolBox: manual_call_templates[0] ({bad_template['name']!r}) skipped: {reason}."]
    finally:
        tb.close()
