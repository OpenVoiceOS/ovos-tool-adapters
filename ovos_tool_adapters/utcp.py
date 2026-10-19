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

import importlib.util
import inspect
import sys
from typing import Any, Dict, List, Optional, Union

from ovos_bus_client import MessageBusClient
from ovos_plugin_manager.templates.agent_tools import AgentTool, ToolArguments, ToolBox
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from pydantic import ValidationError

from ovos_tool_adapters._async_runner import _AsyncRunner
from ovos_tool_adapters._schema import AdapterToolOutput, _schema_to_pydantic

UTCP_DOCS_URL = "https://github.com/OpenVoiceOS/ovos-tool-adapters/blob/dev/docs/utcp.md"


def _config_error(utcp_config: Any) -> Optional[str]:
    """
    Check the ``utcp_config`` shape before it reaches the UTCP client.

    Args:
        utcp_config: The ``utcp_config`` value from the plugin configuration.

    Returns:
        An error message naming the problem, or ``None`` if the shape is valid.
    """
    if not isinstance(utcp_config, dict):
        return f"'utcp_config' must be an object, not {type(utcp_config).__name__}"
    for key in ("tool_providers", "providers"):
        if key in utcp_config:
            return (f"'utcp_config.{key}' is not a UTCP 1.x key; "
                    f"list each manual in 'manual_call_templates' instead, see {UTCP_DOCS_URL}")
    templates = utcp_config.get("manual_call_templates", [])
    if not isinstance(templates, list):
        return f"'utcp_config.manual_call_templates' must be a list, not {type(templates).__name__}"
    for index, template in enumerate(templates):
        if not isinstance(template, dict):
            return f"manual_call_templates[{index}] must be an object, not {type(template).__name__}"
        label = _template_label(index, template)
        required = ["call_template_type"]
        if template.get("call_template_type") == "http":
            required.append("url")
        for key in required:
            if key not in template:
                return f"{label} is missing the required key {key!r}, see {UTCP_DOCS_URL}"
    return None


def _template_label(index: int, template: Dict[str, Any]) -> str:
    """Name a manual call template for log messages."""
    return f"manual_call_templates[{index}] ({template.get('name', 'unnamed')!r})"


def _template_rejection(exc: BaseException) -> str:
    """
    Reduce a UTCP template validation error to one line.

    utcp wraps the real error in messages that hold only a traceback. The
    first pydantic error names the field; otherwise the outermost exception
    with its own message names the cause.
    """
    chain = []
    cause: Optional[BaseException] = exc
    while cause is not None:
        chain.append(cause)
        cause = cause.__cause__ or cause.__context__
    for cause in chain:
        if isinstance(cause, ValidationError):
            error = cause.errors()[0]
            return f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
    for cause in chain:
        first_line = (str(cause).strip().splitlines() or [""])[0]
        if first_line and not first_line.endswith("Traceback (most recent call last):"):
            return first_line if cause is exc else f"{type(cause).__name__}: {first_line}"
    return f"{type(chain[-1]).__name__}: {chain[-1]}"


def _utcp_http_installed() -> bool:
    """Return ``True`` if the ``utcp-http`` plugin, which handles ``http`` call templates, is importable."""
    return importlib.util.find_spec("utcp_http") is not None


class UTCPToolBox(ToolBox):
    """
    A ``ToolBox`` plugin that bridges any UTCP server into the OVOS agentic loop.

    UTCP (Universal Tool Calling Protocol) is transport-agnostic and wraps HTTP,
    SSE, CLI, WebSocket, MCP, and more under a single ``UtcpClient`` API.

    Config keys:

    - ``utcp_config`` *(required)*: dict passed to ``UtcpClientConfig(**utcp_config)``,
      with one ``manual_call_templates`` entry per UTCP manual
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
        from utcp.data.call_template import CallTemplateSerializer
        from utcp.data.utcp_client_config import UtcpClientConfig
        from utcp.utcp_client import UtcpClient

        utcp_config = dict(self.config.get("utcp_config", {}))
        templates = []
        for index, template in enumerate(utcp_config.pop("manual_call_templates", [])):
            try:
                templates.append(CallTemplateSerializer().validate_dict(template))
            except Exception as exc:
                hint = ""
                if template.get("call_template_type") == "http" and not _utcp_http_installed():
                    hint = " The utcp-http plugin is not installed: pip install 'ovos-tool-adapters[utcp]'."
                LOG.error(f"UTCPToolBox: {_template_label(index, template)} skipped: "
                          f"{_template_rejection(exc)}.{hint}")

        # Register on a new client before swapping it in, so tool calls made
        # during a refresh keep using the previous client and its manuals.
        client = await UtcpClient.create(config=UtcpClientConfig(**utcp_config))
        try:
            results = await client.register_manuals(templates)
        except BaseException:
            try:
                await client.close()
            except Exception as exc:
                LOG.debug(f"UTCPToolBox: error closing the UTCP client after a failed registration: {exc}")
            raise
        for result in results:
            if not result.success:
                reasons = "; ".join(error.strip().splitlines()[-1] for error in result.errors if error.strip())
                LOG.error(f"UTCPToolBox: manual {result.manual_call_template.name!r} "
                          f"loaded no tools: {reasons or 'no reason given'}")
        previous, self._client = self._client, client
        if previous is not None:
            try:
                await previous.close()
            except Exception as exc:
                LOG.debug(f"UTCPToolBox: error closing the previous UTCP client: {exc}")
        return await client.config.tool_repository.get_tools()

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

        error = _config_error(self.config.get("utcp_config", {}))
        if error:
            LOG.error(f"UTCPToolBox: {error} — no tools loaded.")
            return []

        try:
            utcp_tools = self._runner.run(self._connect_and_list(), timeout=self._timeout)
        except Exception as exc:
            LOG.warning(f"UTCPToolBox: failed to connect to UTCP server: {exc}")
            return []

        agent_tools: List[AgentTool] = []
        for utcp_tool in utcp_tools:
            schema = utcp_tool.inputs.model_dump(by_alias=True, exclude_none=True)
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
        """Close the UTCP client and stop the async runner."""
        # At interpreter shutdown the runner loop can no longer run the close
        # coroutine, so waiting for it would block exit for the full timeout.
        if self._client is not None and not sys.is_finalizing():
            closing = self._client.close()
            try:
                self._runner.run(closing, timeout=self._timeout)
            except Exception as exc:
                # a coroutine the runner never started must be closed here,
                # or asyncio warns that it was never awaited
                if inspect.getcoroutinestate(closing) == inspect.CORO_CREATED:
                    closing.close()
                LOG.debug(f"UTCPToolBox: error closing UTCP client: {exc}")
            self._client = None
        self._runner.close()

    def __del__(self) -> None:
        """Attempt cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
