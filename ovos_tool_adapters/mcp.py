# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""MCPToolBox — exposes an MCP server as an OVOS ToolBox plugin."""

import asyncio
import concurrent.futures
import threading
from typing import Any, Dict, List, Optional, Union

from ovos_bus_client import MessageBusClient
from ovos_plugin_manager.templates.agent_tools import AgentTool, ToolArguments, ToolBox
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG

from ovos_tool_adapters._async_runner import _AsyncRunner
from ovos_tool_adapters._schema import AdapterToolOutput, _schema_to_pydantic


class MCPToolBox(ToolBox):
    """
    A ``ToolBox`` plugin that bridges any MCP server into the OVOS agentic loop.

    Connects to an MCP server on construction and keeps the session alive across
    all ``call_tool`` invocations. Supports ``stdio``, ``sse``, and ``http``
    transports.

    Config keys:

    - ``transport`` *(required)*: ``"stdio"`` | ``"sse"`` | ``"http"``
    - ``command`` *(stdio only)*: executable path, e.g. ``"uvx"``
    - ``args`` *(stdio only)*: list of arguments, e.g. ``["mcp-server-fetch"]``
    - ``env`` *(stdio only)*: optional dict of extra environment variables
    - ``url`` *(sse/http only)*: server URL
    - ``timeout`` *(optional)*: seconds per call, default ``30``

    Entry point group: ``opm.agents.toolbox``
    """

    def __init__(self,
                 config: Optional[Dict[str, Any]] = None,
                 bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 toolbox_id: str = "ovos-mcp-toolbox") -> None:
        """
        Initialise the toolbox, start the async runner, and connect to the MCP server.

        Args:
            config: Plugin configuration dict; see class docstring for keys.
            bus: The OVOS Messagebus client instance.
            toolbox_id: Per-instance identifier, so multiple MCP servers can be
                fronted at once. Defaults to ``"ovos-mcp-toolbox"``.
        """
        self.config: Dict[str, Any] = config or {}
        self._timeout: int = int(self.config.get("timeout", 30))
        self._runner: _AsyncRunner = _AsyncRunner()
        # Session — populated once the driver task has connected.
        self._session: Optional[Any] = None
        # Signalled (thread-safely, via _runner.call_soon) from close() to tell
        # the driver task it is time to exit the transport/session context
        # managers. Created eagerly so close() never races discover_tools().
        self._close_event: "asyncio.Event" = asyncio.Event()
        # The single, long-lived task started by discover_tools() that owns
        # the transport/session context managers for the toolbox's lifetime.
        self._driver_future: Optional["concurrent.futures.Future"] = None
        self._closed: bool = False
        self._close_lock: threading.Lock = threading.Lock()
        super().__init__(toolbox_id=toolbox_id, config=config, bus=bus)

    # ------------------------------------------------------------------
    # Internal async helpers
    # ------------------------------------------------------------------

    async def _driver(self, ready: "concurrent.futures.Future") -> None:
        """
        Own the MCP transport/session context managers for the whole life of
        the toolbox, as a single ``asyncio.Task``.

        anyio (used by the ``mcp`` client transports) requires cancel scopes
        to be exited from the same task that entered them. Running this
        coroutine once via ``_AsyncRunner.submit`` — rather than issuing
        separate ``_AsyncRunner.run`` calls for "connect" and "close", which
        each create their own task — guarantees ``__aenter__`` and
        ``__aexit__`` happen in the same task.

        On success, resolves *ready* with the discovered tool list and then
        blocks on ``self._close_event`` until :meth:`close` signals shutdown,
        at which point the context managers are exited before this task ends.
        On failure, resolves *ready* with the exception and returns — nothing
        was left open, so there is nothing to tear down.

        Args:
            ready: Thread-safe future used to hand the tool list (or a
                connection error) back to the synchronous caller of
                :meth:`discover_tools`.
        """
        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters
        except ImportError as exc:
            ready.set_exception(
                ImportError("mcp package is required: pip install 'ovos-tool-adapters[mcp]'").with_traceback(
                    exc.__traceback__
                )
            )
            return

        transport = self.config.get("transport", "stdio")
        try:
            if transport == "stdio":
                from mcp.client.stdio import stdio_client
                params = StdioServerParameters(
                    command=self.config["command"],
                    args=self.config.get("args", []),
                    env=self.config.get("env"),
                )
                transport_cm = stdio_client(params)
            elif transport == "sse":
                from mcp.client.sse import sse_client
                transport_cm = sse_client(url=self.config["url"])
            elif transport == "http":
                # mcp 2.x renamed this to `streamable_http_client`; 1.x
                # spells it `streamablehttp_client`. Both are tried so the
                # http transport works across the split -- without this the
                # import fails, the error is swallowed by discover_tools()
                # and the toolbox silently reports zero tools instead of
                # failing loudly.
                try:
                    from mcp.client.streamable_http import streamable_http_client as _http_client
                except ImportError:
                    from mcp.client.streamable_http import streamablehttp_client as _http_client
                transport_cm = _http_client(url=self.config["url"])
            else:
                raise ValueError(f"Unknown MCP transport: {transport!r}")

            read, write = await transport_cm.__aenter__()
        except Exception as exc:
            ready.set_exception(exc)
            return

        try:
            session_cm = ClientSession(read, write)
            session = await session_cm.__aenter__()
            await session.initialize()
            result = await session.list_tools()
        except Exception as exc:
            try:
                await transport_cm.__aexit__(type(exc), exc, exc.__traceback__)
            except Exception:
                LOG.warning("MCPToolBox: error closing transport after connect failure", exc_info=True)
            ready.set_exception(exc)
            return

        self._session = session
        ready.set_result(result.tools)

        # Keep running — on this same task — until close() asks us to stop,
        # so the context managers below are exited by the task that entered
        # them above.
        await self._close_event.wait()

        try:
            await session_cm.__aexit__(None, None, None)
        except Exception:
            LOG.warning("MCPToolBox: error closing MCP session", exc_info=True)
        try:
            await transport_cm.__aexit__(None, None, None)
        except Exception:
            LOG.warning("MCPToolBox: error closing MCP transport", exc_info=True)

    async def _call_tool_async(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Call a tool on the live MCP session.

        Args:
            name: Tool name.
            arguments: Dict of arguments to pass.

        Returns:
            Raw MCP ``CallToolResult``.
        """
        return await self._session.call_tool(name, arguments)

    # ------------------------------------------------------------------
    # ToolBox interface
    # ------------------------------------------------------------------

    def _call_mcp_tool(self, name: str, args: ToolArguments) -> AdapterToolOutput:
        """
        Synchronous wrapper around the async MCP tool call.

        Args:
            name: Tool name.
            args: Validated ``ToolArguments`` instance.

        Returns:
            ``AdapterToolOutput`` with concatenated text and raw blocks.
        """
        result = self._runner.run(
            self._call_tool_async(name, args.model_dump(exclude_none=True)),
            timeout=self._timeout,
        )
        raw_blocks = [block.model_dump() if hasattr(block, "model_dump") else dict(block)
                      for block in (result.content or [])]
        text_parts = [
            b.get("text", "") for b in raw_blocks if b.get("type") == "text"
        ]
        # mcp>=2.0 renamed ``CallToolResult.isError`` to ``is_error``.
        is_error = getattr(result, "is_error", None)
        if is_error is None:
            is_error = getattr(result, "isError", False)
        return AdapterToolOutput(
            content="\n".join(text_parts),
            is_error=bool(is_error),
            raw=raw_blocks,
        )

    def discover_tools(self) -> List[AgentTool]:
        """
        Connect to the MCP server and return one ``AgentTool`` per MCP tool.

        Returns ``[]`` with a warning if the ``mcp`` package is not installed.

        Returns:
            List of ``AgentTool`` objects matching the server's tool list.
        """
        ready: "concurrent.futures.Future" = concurrent.futures.Future()
        self._driver_future = self._runner.submit(self._driver(ready))
        try:
            mcp_tools = ready.result(timeout=self._timeout)
        except ImportError as exc:
            LOG.warning(f"MCPToolBox: {exc} — no tools loaded.")
            return []
        except Exception as exc:
            LOG.warning(f"MCPToolBox: failed to connect to MCP server: {exc}")
            return []

        agent_tools: List[AgentTool] = []
        for mcp_tool in mcp_tools:
            # mcp>=2.0 renamed ``Tool.inputSchema`` to ``Tool.input_schema``.
            input_schema = getattr(mcp_tool, "input_schema", None)
            if input_schema is None:
                input_schema = getattr(mcp_tool, "inputSchema", None)
            args_model = _schema_to_pydantic(
                f"{mcp_tool.name}_args",
                input_schema or {},
            )
            name_copy = mcp_tool.name  # capture for closure

            def _make_call(tool_name: str) -> Any:
                def _call(args: ToolArguments) -> AdapterToolOutput:
                    return self._call_mcp_tool(tool_name, args)
                return _call

            agent_tools.append(AgentTool(
                name=mcp_tool.name,
                description=mcp_tool.description or "",
                argument_schema=args_model,
                output_schema=AdapterToolOutput,
                tool_call=_make_call(name_copy),
            ))
        return agent_tools

    def close(self) -> None:
        """
        Close the MCP session and stop the async runner.

        Idempotent and safe to call more than once (including once from
        :meth:`__del__` after an earlier explicit call) — the second call is
        a no-op. Never leaves ``self._driver(...)`` uncreated-but-unawaited:
        the coroutine object is created exactly once, inside
        ``discover_tools()``, and handed straight to ``_runner.submit`` in
        the same expression, so there is never a coroutine sitting around
        that might be dropped without being awaited.
        """
        with self._close_lock:
            if self._closed:
                return
            self._closed = True

        if self._driver_future is not None:
            try:
                # Wake the driver task so it exits the transport/session
                # context managers on the same task that entered them.
                self._runner.call_soon(self._close_event.set)
            except Exception:
                LOG.warning("MCPToolBox: failed to signal MCP session shutdown", exc_info=True)
            else:
                try:
                    self._driver_future.result(timeout=10)
                except Exception:
                    LOG.warning("MCPToolBox: error while tearing down MCP session", exc_info=True)

        try:
            self._runner.close()
        except Exception:
            LOG.warning("MCPToolBox: error stopping async runner", exc_info=True)

    def __del__(self) -> None:
        """Attempt cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            LOG.warning("MCPToolBox: error during __del__ cleanup", exc_info=True)
