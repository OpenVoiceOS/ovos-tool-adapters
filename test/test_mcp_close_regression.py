"""Regression tests for MCPToolBox's async teardown (close()).

Reproduces two symptoms observed against a live mcp>=2 http server on
2026-08-13 (see the fix's commit message / PR description for the original
reproduction transcript):

1. ``RuntimeError: Attempted to exit cancel scope in a different task than it
   was entered in`` -- the transport/session async context managers used to
   be entered on one ``_AsyncRunner.run()`` task (during ``discover_tools()``)
   and exited on a *different* one (during ``close()``); anyio's cancel
   scopes require the same task for both. The error was swallowed by a bare
   ``except Exception: pass``, so it never surfaced -- these tests catch the
   underlying condition directly (same-task identity) rather than relying on
   an exception that was, by design of the bug, invisible.

2. ``RuntimeWarning: coroutine 'MCPToolBox._close_async' was never awaited``
   -- ``close()`` built a fresh coroutine and handed it to the runner inside
   a bare ``try/except Exception: pass``, with no guard against being called
   again after the runner had already been stopped (which is exactly what
   ``__del__`` risks doing if a caller already closed explicitly).

Both tests use a fully mocked ``mcp`` module (same pattern as test_mcp.py) so
they are hermetic: no subprocess, no network, deterministic.
"""
import asyncio
import gc
import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ovos_tool_adapters.mcp import MCPToolBox


class _TaskRecordingTransport:
    """Fake transport context manager that records which asyncio Task
    entered and exited it -- exactly the identity anyio's cancel scopes
    check and enforce for real."""

    def __init__(self) -> None:
        self.enter_task = None
        self.exit_task = None

    async def __aenter__(self):
        self.enter_task = asyncio.current_task()
        return (None, None)  # (read, write)

    async def __aexit__(self, *exc_info):
        self.exit_task = asyncio.current_task()


class _TaskRecordingSession:
    """Fake session context manager with the same task-recording behaviour."""

    def __init__(self) -> None:
        self.enter_task = None
        self.exit_task = None

    async def __aenter__(self):
        self.enter_task = asyncio.current_task()
        return self

    async def __aexit__(self, *exc_info):
        self.exit_task = asyncio.current_task()

    async def initialize(self):
        pass

    async def list_tools(self):
        return SimpleNamespace(
            tools=[SimpleNamespace(name="echo", description="Echo", inputSchema={})]
        )

    async def call_tool(self, name, args):
        return SimpleNamespace(content=[], isError=False)


def _build_toolbox_with_fake_mcp(transport, session):
    fake_mcp_mod = MagicMock()
    fake_mcp_mod.ClientSession.return_value = session
    fake_mcp_mod.client.stdio.StdioServerParameters = SimpleNamespace
    fake_mcp_mod.client.stdio.stdio_client = lambda params: transport

    with patch.dict("sys.modules", {
        "mcp": fake_mcp_mod,
        "mcp.client": fake_mcp_mod.client,
        "mcp.client.stdio": fake_mcp_mod.client.stdio,
    }):
        return MCPToolBox(config={"transport": "stdio", "command": "x", "args": []})


def test_transport_and_session_are_entered_and_exited_on_the_same_task():
    """The bug, made observable without depending on a swallowed exception.

    anyio (used by the real mcp client transports) requires a cancel scope's
    ``__aenter__`` and ``__aexit__`` to run on the same ``asyncio.Task``.
    Before the fix, ``discover_tools()`` entered the transport/session
    context managers on one task (created by one ``_AsyncRunner.run()``
    call) and ``close()`` exited them on another task (created by a second,
    independent ``_AsyncRunner.run()`` call) -- this is exactly the
    condition that made the real ``mcp`` SDK raise
    ``RuntimeError: Attempted to exit cancel scope in a different task than
    it was entered in``.
    """
    transport = _TaskRecordingTransport()
    session = _TaskRecordingSession()
    tb = _build_toolbox_with_fake_mcp(transport, session)
    try:
        tools = list(tb.tools.values())
        assert len(tools) == 1
    finally:
        tb.close()

    assert transport.enter_task is not None, "transport was never entered"
    assert transport.exit_task is not None, "transport was never exited"
    assert transport.enter_task is transport.exit_task, (
        "transport context manager entered and exited on DIFFERENT asyncio "
        "Tasks -- this reproduces the anyio 'cancel scope in a different "
        "task' RuntimeError"
    )

    assert session.enter_task is not None, "session was never entered"
    assert session.exit_task is not None, "session was never exited"
    assert session.enter_task is session.exit_task, (
        "session context manager entered and exited on DIFFERENT asyncio "
        "Tasks -- this reproduces the anyio 'cancel scope in a different "
        "task' RuntimeError"
    )


def test_close_called_twice_never_leaves_a_coroutine_unawaited():
    """close() must be idempotent and never construct-then-drop a coroutine.

    __del__ always calls close() again, so any caller that already closed
    explicitly relies on the second call being a safe, cheap no-op. Before
    the fix, a second close() built a brand-new ``_close_async()`` coroutine
    and tried to schedule it on a runner whose event-loop thread had already
    been stopped by the first close() -- the coroutine was created but never
    actually awaited, which is exactly
    ``RuntimeWarning: coroutine '_close_async' was never awaited``.
    """
    transport = _TaskRecordingTransport()
    session = _TaskRecordingSession()
    tb = _build_toolbox_with_fake_mcp(transport, session)
    list(tb.tools.values())

    tb.close()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tb.close()  # second call -- must be a no-op, not a fresh teardown attempt
        gc.collect()

    unawaited = [
        w for w in caught
        if issubclass(w.category, RuntimeWarning) and "was never awaited" in str(w.message)
    ]
    assert not unawaited, f"a second close() left a coroutine unawaited: {unawaited}"


def test_del_after_explicit_close_never_leaves_a_coroutine_unawaited():
    """__del__ is close()'s real second caller in production -- exercise it directly."""
    transport = _TaskRecordingTransport()
    session = _TaskRecordingSession()
    tb = _build_toolbox_with_fake_mcp(transport, session)
    list(tb.tools.values())

    tb.close()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tb.__del__()
        gc.collect()

    unawaited = [
        w for w in caught
        if issubclass(w.category, RuntimeWarning) and "was never awaited" in str(w.message)
    ]
    assert not unawaited, f"__del__ after close() left a coroutine unawaited: {unawaited}"
