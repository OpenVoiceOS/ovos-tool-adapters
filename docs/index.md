# ovos-tool-adapters

Bridges **MCP** (Model Context Protocol) and **UTCP** (Universal Tool Calling Protocol) servers into the OVOS agentic loop as standard `ToolBox` plugins. Agents consuming these toolboxes need no protocol awareness.

## Architecture

| Module | Role |
|---|---|
| `_async_runner.py` — `_AsyncRunner` | Daemon-thread event loop; synchronous `run(coro)` bridge |
| `_schema.py` — `_schema_to_pydantic` | JSON Schema → dynamic Pydantic `ToolArguments` class |
| `_schema.py` — `AdapterToolOutput` | Shared output model (`content`, `is_error`, `raw`) |
| `mcp.py` — `MCPToolBox` | MCP adapter; stdio / SSE / HTTP transports |
| `utcp.py` — `UTCPToolBox` | UTCP adapter; any UTCP-supported transport |

`_AsyncRunner` owns one `asyncio` loop in a daemon thread. All async MCP/UTCP calls are submitted via `asyncio.run_coroutine_threadsafe` and waited on synchronously, satisfying the `ToolBox.discover_tools()` / `call_tool()` synchronous contract while keeping the client session alive between calls.

## Installation

```bash
pip install ovos-tool-adapters[mcp]   # MCP support
pip install ovos-tool-adapters[utcp]  # UTCP support
pip install ovos-tool-adapters[mcp,utcp]
```

## Persona Configuration

```json
{
  "toolboxes": ["ovos-mcp-toolbox"],
  "ovos-mcp-toolbox": {
    "transport": "stdio",
    "command": "uvx",
    "args": ["mcp-server-fetch"],
    "timeout": 30
  }
}
```

## Config Reference

### MCPToolBox (`ovos-mcp-toolbox`)

| Key | Required | Description |
|---|---|---|
| `transport` | yes | `"stdio"` \| `"sse"` \| `"http"` |
| `command` | stdio | Executable, e.g. `"uvx"` |
| `args` | stdio | Argument list |
| `env` | stdio | Extra env vars dict |
| `url` | sse/http | Server URL |
| `timeout` | no | Seconds per call (default 30) |

### UTCPToolBox (`ovos-utcp-toolbox`)

| Key | Required | Description |
|---|---|---|
| `utcp_config` | yes | Dict passed to `UtcpClientConfig(**...)` |
| `timeout` | no | Seconds per call (default 30) |
