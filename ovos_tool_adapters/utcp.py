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
"""UTCPToolBox — exposes a UTCP server as an OVOS ToolBox plugin."""

from typing import Any, Dict, List, Optional, Union

from ovos_bus_client import MessageBusClient
from ovos_plugin_manager.templates.agent_tools import AgentTool, ToolArguments, ToolBox
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG

from ovos_tool_adapters._async_runner import _AsyncRunner
from ovos_tool_adapters._schema import AdapterToolOutput, _schema_to_pydantic


class UTCPToolBox(ToolBox):
    """
    A ``ToolBox`` plugin that bridges any UTCP server into the OVOS agentic loop.

    UTCP (Universal Tool Calling Protocol) is transport-agnostic and wraps HTTP,
    SSE, CLI, WebSocket, MCP, and more under a single ``UtcpClient`` API.

    Config keys:

    - ``utcp_config`` *(required)*: dict passed to ``UtcpClientConfig(**utcp_config)``
    - ``timeout`` *(optional)*: seconds per call, default ``30``

    Entry point group: ``opm.agents.toolbox``
    """

    def __init__(self,
                 config: Optional[Dict[str, Any]] = None,
                 bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 toolbox_id: str = "ovos-utcp-toolbox") -> None:
        """
        Initialise the toolbox and start the async runner.

        Args:
            config: Plugin configuration dict; see class docstring for keys.
            bus: The OVOS Messagebus client instance.
            toolbox_id: Per-instance identifier, so multiple UTCP servers can
                be fronted at once. Defaults to ``"ovos-utcp-toolbox"``.
        """
        self.config: Dict[str, Any] = config or {}
        self._timeout: int = int(self.config.get("timeout", 30))
        self._runner: _AsyncRunner = _AsyncRunner()
        self._client: Optional[Any] = None
        super().__init__(toolbox_id=toolbox_id, config=config, bus=bus)

    # ------------------------------------------------------------------
    # Internal async helpers
    # ------------------------------------------------------------------

    async def _connect_and_list(self) -> List[Any]:
        """
        Create a ``UtcpClient``, register configured providers, and list tools.

        Callers must only invoke this once the ``utcp`` package is known to be
        importable (see :meth:`discover_tools`) — creating this coroutine and
        then failing to hand it to the runner before raising would leave it
        dangling and trigger a "coroutine was never awaited" warning.

        Returns:
            List of UTCP ``Tool`` objects.
        """
        from utcp.client import UtcpClient
        from utcp.client.utcp_client_config import UtcpClientConfig

        utcp_config_dict: Dict[str, Any] = self.config.get("utcp_config", {})
        utcp_cfg = UtcpClientConfig(**utcp_config_dict)
        self._client = await UtcpClient.create(config=utcp_cfg)
        tools = await self._client.get_tools()
        return tools

    async def _call_tool_async(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Call a tool on the live UTCP client.

        Args:
            name: Tool name.
            arguments: Dict of arguments to pass.

        Returns:
            Raw UTCP response object.
        """
        return await self._client.call_tool(name, arguments)

    # ------------------------------------------------------------------
    # ToolBox interface
    # ------------------------------------------------------------------

    def _call_utcp_tool(self, name: str, args: ToolArguments) -> AdapterToolOutput:
        """
        Synchronous wrapper around the async UTCP tool call.

        Args:
            name: Tool name.
            args: Validated ``ToolArguments`` instance.

        Returns:
            ``AdapterToolOutput`` with text content and raw response.
        """
        result = self._runner.run(
            self._call_tool_async(name, args.model_dump(exclude_none=True)),
            timeout=self._timeout,
        )
        # UTCP responses vary by transport; normalise to text + raw.
        if isinstance(result, str):
            return AdapterToolOutput(content=result, raw=[{"type": "text", "text": result}])
        if isinstance(result, dict):
            text = result.get("text") or result.get("content") or str(result)
            return AdapterToolOutput(
                content=text,
                is_error=bool(result.get("is_error", False)),
                raw=[result],
            )
        # Fallback: stringify whatever came back.
        return AdapterToolOutput(content=str(result), raw=[{"type": "raw", "value": str(result)}])

    def discover_tools(self) -> List[AgentTool]:
        """
        Connect to the UTCP server and return one ``AgentTool`` per UTCP tool.

        Returns ``[]`` with a warning if the ``utcp`` package is not installed.

        The ``utcp`` package is checked for *before* :meth:`_connect_and_list`
        is ever called, so on the missing-package path no coroutine is created
        at all — there is nothing left dangling for asyncio to warn about. When
        the package is present, the coroutine is created and handed to the
        runner in the same expression, so it is always scheduled and awaited.

        Returns:
            List of ``AgentTool`` objects matching the server's tool list.
        """
        try:
            import utcp  # noqa: F401
        except ImportError as exc:
            LOG.warning(
                f"UTCPToolBox: utcp package is required: pip install 'ovos-tool-adapters[utcp]' ({exc}) "
                "— no tools loaded."
            )
            return []

        try:
            utcp_tools = self._runner.run(self._connect_and_list(), timeout=self._timeout)
        except Exception as exc:
            LOG.warning(f"UTCPToolBox: failed to connect to UTCP server: {exc}")
            return []

        agent_tools: List[AgentTool] = []
        for utcp_tool in utcp_tools:
            schema = getattr(utcp_tool, "input_schema", None) or {}
            args_model = _schema_to_pydantic(f"{utcp_tool.name}_args", schema)
            name_copy = utcp_tool.name

            def _make_call(tool_name: str) -> Any:
                def _call(args: ToolArguments) -> AdapterToolOutput:
                    return self._call_utcp_tool(tool_name, args)
                return _call

            agent_tools.append(AgentTool(
                name=utcp_tool.name,
                description=getattr(utcp_tool, "description", "") or "",
                argument_schema=args_model,
                output_schema=AdapterToolOutput,
                tool_call=_make_call(name_copy),
            ))
        return agent_tools

    def close(self) -> None:
        """Stop the async runner."""
        self._runner.close()

    def __del__(self) -> None:
        """Attempt cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
