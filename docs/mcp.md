# MCPToolBox

`MCPToolBox` — `ovos_tool_adapters/mcp.py`

Bridges any MCP (Model Context Protocol) server into the OVOS agentic loop. On construction it connects to the server, calls `list_tools`, and registers one `AgentTool` per MCP tool. The session is kept alive for the lifetime of the toolbox — no reconnection per call.

## Supported transports

| `transport` value | Protocol | Required config keys |
|---|---|---|
| `"stdio"` | Subprocess (stdin/stdout) | `command`, optionally `args`, `env` |
| `"sse"` | Server-Sent Events | `url` |
| `"http"` | Streamable HTTP | `url` |

## Config reference

| Key | Type | Default | Description |
|---|---|---|---|
| `transport` | str | — | **Required.** `"stdio"` \| `"sse"` \| `"http"` |
| `command` | str | — | stdio: executable, e.g. `"uvx"`, `"python"`, `"npx"` |
| `args` | list[str] | `[]` | stdio: argument list, e.g. `["mcp-server-fetch"]` |
| `env` | dict[str,str] | `None` | stdio: extra environment variables merged into the subprocess env |
| `url` | str | — | sse/http: full server URL including scheme and port |
| `timeout` | int | `30` | Seconds to wait per tool call or connection attempt |

## Persona config examples

### stdio — run an MCP server as a subprocess

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

### stdio — Python MCP server with env vars

```json
{
  "ovos-mcp-toolbox": {
    "transport": "stdio",
    "command": "python",
    "args": ["-m", "my_mcp_server"],
    "env": {"API_KEY": "secret"},
    "timeout": 60
  }
}
```

### SSE — remote MCP server

```json
{
  "ovos-mcp-toolbox": {
    "transport": "sse",
    "url": "http://localhost:8080/sse",
    "timeout": 30
  }
}
```

### HTTP — streamable HTTP MCP server

```json
{
  "ovos-mcp-toolbox": {
    "transport": "http",
    "url": "http://localhost:8080/mcp",
    "timeout": 30
  }
}
```

## How tools are exposed

Each MCP `Tool` object has a `name`, `description`, and `inputSchema` (JSON Schema). `MCPToolBox.discover_tools` — `mcp.py:160`:

1. Calls `_schema_to_pydantic(tool.name + "_args", tool.inputSchema)` to build a dynamic Pydantic `ToolArguments` subclass with the correct field types and required/optional markers.
2. Wraps `session.call_tool(name, args)` in `_call_mcp_tool` — `mcp.py:134`.
3. Returns `AdapterToolOutput(content=..., is_error=..., raw=...)` — `_schema.py:53`.

The LLM receives the **real JSON Schema** from the MCP server via `tool_json_list`, not a generic passthrough.

## Tool output

All MCP tool calls return `AdapterToolOutput`:

| Field | Type | Description |
|---|---|---|
| `content` | str | All `"text"` content blocks joined with `\n` |
| `is_error` | bool | `True` if the server set `isError=True` |
| `raw` | list[dict] | Original content blocks (image, resource, etc.) |

## Lifecycle

```
MCPToolBox.__init__()
  → _AsyncRunner started (daemon thread + event loop)
  → super().__init__() → discover_tools()
      → _runner.run(_connect_and_list())
          → transport context manager opened
          → ClientSession created and initialized
          → list_tools() called
      → AgentTools registered

call_tool("fetch", {"url": "..."})
  → _call_mcp_tool("fetch", args)
      → _runner.run(session.call_tool(...))
      → AdapterToolOutput returned

MCPToolBox.close() / __del__()
  → _runner.run(_close_async())   # closes session + transport
  → _runner.close()               # stops daemon thread
```

## Shutdown

Call `toolbox.close()` explicitly when done, or rely on `__del__`. For long-running OVOS processes, clean shutdown is automatic when the agentic loop shuts down its toolboxes.

## Popular MCP servers

| Server | Install | `command` | `args` |
|---|---|---|---|
| mcp-server-fetch | `uvx mcp-server-fetch` | `"uvx"` | `["mcp-server-fetch"]` |
| mcp-server-brave-search | `uvx mcp-server-brave-search` | `"uvx"` | `["mcp-server-brave-search"]` |
| mcp-server-filesystem | `uvx mcp-server-filesystem` | `"uvx"` | `["mcp-server-filesystem", "/path"]` |

See the [MCP server registry](https://github.com/modelcontextprotocol/servers) for a full list.
