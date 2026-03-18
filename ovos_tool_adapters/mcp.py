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

from typing import Any, Dict, List, Optional

from ovos_plugin_manager.templates.agent_tools import AgentTool, ToolArguments, ToolBox
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

    toolbox_id = "ovos-mcp-toolbox"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialise the toolbox, start the async runner, and connect to the MCP server.

        Args:
            config: Plugin configuration dict; see class docstring for keys.
        """
        self.config: Dict[str, Any] = config or {}
        self._timeout: int = int(self.config.get("timeout", 30))
        self._runner: _AsyncRunner = _AsyncRunner()
        # Session and context managers — populated by discover_tools()
        self._session: Optional[Any] = None
        self._transport_cm: Optional[Any] = None
        self._session_cm: Optional[Any] = None
        super().__init__(toolbox_id=self.toolbox_id)

    # ------------------------------------------------------------------
    # Internal async helpers
    # ------------------------------------------------------------------

    async def _connect_and_list(self) -> List[Any]:
        """
        Open the MCP transport, initialise the session, and list available tools.

        Returns:
            List of ``mcp.types.Tool`` objects.
        """
        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters
        except ImportError as exc:
            raise ImportError("mcp package is required: pip install 'ovos-tool-adapters[mcp]'") from exc

        transport = self.config.get("transport", "stdio")

        if transport == "stdio":
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(
                command=self.config["command"],
                args=self.config.get("args", []),
                env=self.config.get("env"),
            )
            self._transport_cm = stdio_client(params)
        elif transport == "sse":
            from mcp.client.sse import sse_client
            self._transport_cm = sse_client(url=self.config["url"])
        elif transport == "http":
            from mcp.client.streamable_http import streamablehttp_client
            self._transport_cm = streamablehttp_client(url=self.config["url"])
        else:
            raise ValueError(f"Unknown MCP transport: {transport!r}")

        read, write = await self._transport_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        result = await self._session.list_tools()
        return result.tools

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

    async def _close_async(self) -> None:
        """Close the session and transport context managers."""
        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception:
                pass
        if self._transport_cm is not None:
            try:
                await self._transport_cm.__aexit__(None, None, None)
            except Exception:
                pass

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
        return AdapterToolOutput(
            content="\n".join(text_parts),
            is_error=bool(result.isError),
            raw=raw_blocks,
        )

    def discover_tools(self) -> List[AgentTool]:
        """
        Connect to the MCP server and return one ``AgentTool`` per MCP tool.

        Returns ``[]`` with a warning if the ``mcp`` package is not installed.

        Returns:
            List of ``AgentTool`` objects matching the server's tool list.
        """
        try:
            mcp_tools = self._runner.run(self._connect_and_list(), timeout=self._timeout)
        except ImportError as exc:
            LOG.warning(f"MCPToolBox: {exc} — no tools loaded.")
            return []
        except Exception as exc:
            LOG.warning(f"MCPToolBox: failed to connect to MCP server: {exc}")
            return []

        agent_tools: List[AgentTool] = []
        for mcp_tool in mcp_tools:
            args_model = _schema_to_pydantic(
                f"{mcp_tool.name}_args",
                mcp_tool.inputSchema or {},
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
        """Close the MCP session and stop the async runner."""
        try:
            self._runner.run(self._close_async(), timeout=10)
        except Exception:
            pass
        self._runner.close()

    def __del__(self) -> None:
        """Attempt cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
