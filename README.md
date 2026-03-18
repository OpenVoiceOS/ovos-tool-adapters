# ovos-tool-adapters

MCP and UTCP ToolBox plugins for the [OVOS agentic loop](https://github.com/OpenVoiceOS/ovos-agentic-loop).

Transparently translates MCP (Model Context Protocol) and UTCP (Universal Tool Calling Protocol) servers into standard OVOS `ToolBox` plugins. No protocol awareness required from the agent.

## Install

```bash
pip install ovos-tool-adapters[mcp]    # MCP support
pip install ovos-tool-adapters[utcp]   # UTCP support
```

## Quick start

Add to your persona JSON:

```json
{
  "toolboxes": ["ovos-mcp-toolbox"],
  "ovos-mcp-toolbox": {
    "transport": "stdio",
    "command": "uvx",
    "args": ["mcp-server-fetch"]
  }
}
```

See [docs/index.md](docs/index.md) for full configuration reference.

## License

Apache 2.0
