# ovos-tool-adapters

[![PyPI](https://img.shields.io/pypi/v/ovos-tool-adapters)](https://pypi.org/project/ovos-tool-adapters/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Tests](https://github.com/OpenVoiceOS/ovos-tool-adapters/actions/workflows/build-tests.yml/badge.svg)](https://github.com/OpenVoiceOS/ovos-tool-adapters/actions/workflows/build-tests.yml)

Bridges **MCP** (Model Context Protocol) and **UTCP** (Universal Tool Calling Protocol) servers into the [OVOS agentic loop](https://github.com/OpenVoiceOS/ovos-agentic-loop) as standard `ToolBox` plugins.

Configure an MCP or UTCP server in your persona JSON and the agent loop consumes it like any other toolbox — no protocol awareness required.

## Install

```bash
pip install ovos-tool-adapters[mcp]    # MCP support
pip install ovos-tool-adapters[utcp]   # UTCP support
pip install ovos-tool-adapters[mcp,utcp]
```

## Quick start

Add to your persona JSON:

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

The agent now has access to every tool the MCP server exposes, with the real JSON Schema forwarded to the LLM.

## Supported transports

### MCP (`ovos-mcp-toolbox`)

| Transport | Config |
|---|---|
| stdio (subprocess) | `"transport": "stdio", "command": "uvx", "args": [...]` |
| SSE | `"transport": "sse", "url": "http://..."` |
| Streamable HTTP | `"transport": "http", "url": "http://..."` |

### UTCP (`ovos-utcp-toolbox`)

Any transport supported by the installed UTCP version (HTTP, SSE, CLI, WebSocket, MCP, …):

```json
{
  "toolboxes": ["ovos-utcp-toolbox"],
  "ovos-utcp-toolbox": {
    "utcp_config": {
      "tool_providers": [
        {"name": "search", "provider_type": "http", "url": "http://localhost:8000/tools"}
      ]
    }
  }
}
```

## How it works

- A daemon-thread asyncio event loop keeps MCP/UTCP sessions alive between calls — no reconnect per tool call.
- Each server's JSON Schema is translated to a Pydantic model at discovery time, so the LLM sees the **actual** input schema.
- Missing `mcp`/`utcp` packages degrade gracefully: the toolbox returns an empty tool list and logs a warning — the agent loop is not affected.

Full documentation: [docs/](docs/index.md)

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Credits

Developed by [TigreGotico](https://tigregotico.pt) for [OpenVoiceOS](https://openvoiceos.org).

Funded by [NGI0 Commons Fund](https://nlnet.nl/project/OpenVoiceOS) / [NLnet](https://nlnet.nl)
under grant agreement No [101135429](https://cordis.europa.eu/project/id/101135429),
through the European Commission's [Next Generation Internet](https://ngi.eu) programme.
