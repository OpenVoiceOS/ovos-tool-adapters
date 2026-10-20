# ovos-tool-adapters

[![PyPI](https://img.shields.io/pypi/v/ovos-tool-adapters)](https://pypi.org/project/ovos-tool-adapters/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Tests](https://github.com/OpenVoiceOS/ovos-tool-adapters/actions/workflows/build-tests.yml/badge.svg)](https://github.com/OpenVoiceOS/ovos-tool-adapters/actions/workflows/build-tests.yml)

Bridges **MCP** (Model Context Protocol) and **UTCP** (Universal Tool Calling Protocol) servers into the [OVOS agentic loop](https://github.com/OpenVoiceOS/ovos-agentic-loop) as standard `ToolBox` plugins.

Configure an MCP or UTCP server in your persona JSON. The agent loop then consumes it like any other toolbox, with no protocol awareness required.

## Install

```bash
pip install --pre ovos-tool-adapters[mcp]    # MCP support
pip install --pre ovos-tool-adapters[utcp]   # UTCP support
pip install --pre ovos-tool-adapters[mcp,utcp]
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

The agent then has access to every tool the MCP server exposes, with the real JSON Schema forwarded to the LLM.

## Supported transports

### MCP (`ovos-mcp-toolbox`)

| Transport | Config |
|---|---|
| stdio (subprocess) | `"transport": "stdio", "command": "uvx", "args": [...]` |
| SSE | `"transport": "sse", "url": "http://..."` |
| Streamable HTTP | `"transport": "http", "url": "http://..."` |

### UTCP (`ovos-utcp-toolbox`)

The `utcp` extra installs the UTCP 1.x client and its HTTP plugin (`utcp-http`). Each entry in `manual_call_templates` points at a UTCP manual. This example loads the manual of a local [ovos-translate-server](https://github.com/OpenVoiceOS/ovos-translate-server):

```json
{
  "toolboxes": ["ovos-utcp-toolbox"],
  "ovos-utcp-toolbox": {
    "utcp_config": {
      "manual_call_templates": [
        {
          "name": "ovos_translate",
          "call_template_type": "http",
          "url": "http://localhost:9686/utcp",
          "http_method": "GET"
        }
      ]
    }
  }
}
```

The agent then gets tools such as `ovos_translate_translate_with_source`: the UTCP name `ovos_translate.translate_with_source` with the dot replaced, because function-calling providers reject a dot in a tool name. Other call template types (CLI, SSE, WebSocket, MCP) need their own UTCP plugin package, for example `utcp-cli`.

## How it works

- A daemon-thread asyncio event loop keeps MCP/UTCP sessions alive between calls, so there is no reconnect per tool call.
- Each server's JSON Schema is translated to a Pydantic model at discovery time, so the LLM sees the **actual** input schema.
- Missing `mcp`/`utcp` packages degrade gracefully: the toolbox returns an empty tool list and logs a warning, and the agent loop is not affected.
- A config with a `tool_providers` or `providers` key loads no tools. These keys are not UTCP 1.x keys. The toolbox logs an error that names `manual_call_templates` and links [docs/utcp.md](docs/utcp.md).

Full documentation: [docs/](docs/index.md)

---

## Credits

Developed by [TigreGótico](https://tigregotico.pt) for
[OpenVoiceOS](https://openvoiceos.org).

[![NGI0 Commons Fund](./ngi.png)](https://nlnet.nl/project/OpenVoiceOS)

This project was funded through the [NGI0 Commons Fund](https://nlnet.nl/commonsfund),
a fund established by [NLnet](https://nlnet.nl) with financial support from the
European Commission's [Next Generation Internet](https://ngi.eu) programme, under
the aegis of [DG Communications Networks, Content and Technology](https://commission.europa.eu/about-european-commission/departments-and-executive-agencies/communications-networks-content-and-technology_en)
under grant agreement No [101135429](https://cordis.europa.eu/project/id/101135429).

---

## License

Apache 2.0. See [LICENSE](LICENSE).
