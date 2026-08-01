# Configuration Reference

Both toolboxes are configured via the persona JSON. The top-level key is the `toolbox_id`.

## MCPToolBox (`ovos-mcp-toolbox`)

```json
{
  "toolboxes": ["ovos-mcp-toolbox"],
  "ovos-mcp-toolbox": { ... }
}
```

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `transport` | str | yes | n/a | `"stdio"` \| `"sse"` \| `"http"` |
| `command` | str | stdio | n/a | Executable to launch, e.g. `"uvx"`, `"python"` |
| `args` | list[str] | stdio | `[]` | Arguments passed to `command` |
| `env` | dict[str,str] | no | `None` | Extra env vars for the subprocess (merged with inherited env) |
| `url` | str | sse/http | n/a | Full URL including scheme, host, port, path |
| `timeout` | int | no | `30` | Seconds per operation (connection + each tool call) |

## UTCPToolBox (`ovos-utcp-toolbox`)

```json
{
  "toolboxes": ["ovos-utcp-toolbox"],
  "ovos-utcp-toolbox": { ... }
}
```

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `utcp_config` | dict | yes | `{}` | Passed as `UtcpClientConfig(**utcp_config)`; see the UTCP documentation for keys |
| `timeout` | int | no | `30` | Seconds per operation |

## Using both together

```json
{
  "toolboxes": ["ovos-mcp-toolbox", "ovos-utcp-toolbox"],
  "ovos-mcp-toolbox": {
    "transport": "stdio",
    "command": "uvx",
    "args": ["mcp-server-fetch"]
  },
  "ovos-utcp-toolbox": {
    "utcp_config": {
      "tool_providers": [
        {"name": "search", "provider_type": "http", "url": "http://localhost:8001/tools"}
      ]
    }
  }
}
```

## Graceful degradation

If the `mcp` or `utcp` package is not installed, the corresponding toolbox returns `[]` from `discover_tools()` and logs a `LOG.warning`. The OVOS agent loop continues with any other configured toolboxes. No exception is raised at import or OPM discovery time.

---
[← UTCPToolBox](utcp.md) · [Home](index.md) · [Architecture →](architecture.md)
