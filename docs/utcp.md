# UTCPToolBox

`UTCPToolBox` — `ovos_tool_adapters/utcp.py`

Bridges any UTCP (Universal Tool Calling Protocol) server into the OVOS agentic loop. UTCP is transport-agnostic — it wraps HTTP, SSE, CLI, WebSocket, MCP, and more under a single `UtcpClient` API. Configuration is passed directly to `UtcpClientConfig`, so any transport supported by the installed UTCP version works without changes to the adapter.

## Config reference

| Key | Type | Default | Description |
|---|---|---|---|
| `utcp_config` | dict | `{}` | **Required.** Passed verbatim to `UtcpClientConfig(**utcp_config)` |
| `timeout` | int | `30` | Seconds to wait per tool call or connection attempt |

The contents of `utcp_config` depend on the UTCP version and transport. Refer to the [UTCP documentation](https://github.com/universal-tool-calling-protocol/python-utcp) for available keys.

## Persona config examples

### HTTP provider

```json
{
  "toolboxes": ["ovos-utcp-toolbox"],
  "ovos-utcp-toolbox": {
    "utcp_config": {
      "tool_providers": [
        {
          "name": "my-http-tools",
          "provider_type": "http",
          "url": "https://my-tool-server.example.com/tools"
        }
      ]
    },
    "timeout": 30
  }
}
```

### Multiple providers

```json
{
  "ovos-utcp-toolbox": {
    "utcp_config": {
      "tool_providers": [
        {
          "name": "web-tools",
          "provider_type": "http",
          "url": "http://localhost:8000/tools"
        },
        {
          "name": "cli-tools",
          "provider_type": "cli",
          "command": "my-cli-tool"
        }
      ]
    }
  }
}
```

## How tools are exposed

Each UTCP `Tool` has `name`, `description`, and `input_schema` (JSON Schema). `UTCPToolBox.discover_tools` — `utcp.py:121`:

1. Calls `UtcpClient.create(config=...)` and `client.get_tools()` to enumerate all tools from all configured providers.
2. Calls `_schema_to_pydantic(tool.name + "_args", tool.input_schema)` for each tool — `_schema.py:30`.
3. Wraps `client.call_tool(name, args)` in `_call_utcp_tool` — `utcp.py:93`.

## Tool output

All UTCP tool calls return `AdapterToolOutput`:

| Field | Type | Description |
|---|---|---|
| `content` | str | Normalised text from the response |
| `is_error` | bool | `True` if the response contained `is_error: true` |
| `raw` | list[dict] | Original response block(s) |

Response normalisation — `utcp.py:108`:
- `str` response → `content = str`, `raw = [{"type": "text", "text": str}]`
- `dict` response → `content = dict["text"] or dict["content"] or str(dict)`
- Other → `content = str(result)`, `raw = [{"type": "raw", ...}]`

## Lifecycle

```
UTCPToolBox.__init__()
  → _AsyncRunner started
  → super().__init__() → discover_tools()
      → _runner.run(_connect_and_list())
          → UtcpClient.create(config=UtcpClientConfig(**utcp_config))
          → client.get_tools()
      → AgentTools registered

call_tool("search", {"query": "..."})
  → _call_utcp_tool("search", args)
      → _runner.run(client.call_tool(...))
      → AdapterToolOutput returned
```
