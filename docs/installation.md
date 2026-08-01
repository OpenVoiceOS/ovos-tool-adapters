# Installation

## Requirements

- Python 3.10+
- An OVOS installation with `ovos-plugin-manager>=0.7.0`
- An MCP or UTCP server to connect to (not bundled)

## Pip extras

```bash
# MCP support only
pip install ovos-tool-adapters[mcp]

# UTCP support only
pip install ovos-tool-adapters[utcp]

# Both
pip install ovos-tool-adapters[mcp,utcp]
```

`mcp` and `utcp` are **optional**. The package installs and OPM loads without them. A toolbox configured for a missing protocol returns an empty tool list and logs a warning, and it does not crash the agent loop.

## Editable install (development)

```bash
git clone https://github.com/OpenVoiceOS/ovos-tool-adapters
cd ovos-tool-adapters
pip install -e ".[mcp,utcp,dev]"
```

## Verify OPM discovery

After installation, OPM should discover both entry points:

```bash
python -c "
from ovos_plugin_manager.agents import find_plugins
print(find_plugins('opm.agents.toolbox'))
"
# Expected: {'ovos-mcp-toolbox': ..., 'ovos-utcp-toolbox': ...}
```

---
[Home](index.md) · [MCPToolBox →](mcp.md)
