# ovos-tool-adapters

Bridges **MCP** (Model Context Protocol) and **UTCP** (Universal Tool Calling Protocol) servers into the OVOS agentic loop as standard `ToolBox` plugins. Agents consuming these toolboxes need no protocol awareness — the adapter handles connection, schema translation, and sync/async bridging transparently.

## When to use this

| Use case | Plugin |
|---|---|
| Connect to any MCP server (stdio subprocess, SSE, HTTP) | `ovos-mcp-toolbox` |
| Connect to any UTCP server (HTTP, SSE, CLI, WebSocket, MCP, …) | `ovos-utcp-toolbox` |

## Navigation

| Doc | Contents |
|---|---|
| [installation.md](installation.md) | Prerequisites, pip extras, editable install |
| [mcp.md](mcp.md) | `MCPToolBox` — transports, config reference, persona example |
| [utcp.md](utcp.md) | `UTCPToolBox` — config reference, persona example |
| [configuration.md](configuration.md) | Full config key table for both plugins |
| [architecture.md](architecture.md) | `_AsyncRunner`, schema bridge, lifecycle |
| [MAINTAINERS_GUIDE.md](MAINTAINERS_GUIDE.md) | Release process, CI/CD, contribution workflow |

## Quick start

```bash
pip install ovos-tool-adapters[mcp]
```

Persona JSON:

```json
{
  "name": "researcher",
  "chat_module": "ovos-react-loop",
  "toolboxes": ["ovos-mcp-toolbox"],
  "ovos-mcp-toolbox": {
    "transport": "stdio",
    "command": "uvx",
    "args": ["mcp-server-fetch"],
    "timeout": 30
  }
}
```

## Key classes

| Class | File |
|---|---|
| `MCPToolBox` — MCP adapter | `ovos_tool_adapters/mcp.py` |
| `UTCPToolBox` — UTCP adapter | `ovos_tool_adapters/utcp.py` |
| `_AsyncRunner` — sync/async bridge | `ovos_tool_adapters/_async_runner.py` |
| `AdapterToolOutput` — shared output model | `ovos_tool_adapters/_schema.py` |
| `_schema_to_pydantic` — JSON Schema → Pydantic | `ovos_tool_adapters/_schema.py` |
