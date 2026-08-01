# Architecture

## The sync/async problem

`ToolBox.discover_tools()` and `ToolBox.call_tool()` are **synchronous**. The OVOS agentic loop calls them from normal sync code. MCP's `ClientSession` and UTCP's `UtcpClient` are **async-only** and require a running event loop.

The naive solution, `asyncio.run(coro)` per call, destroys the loop after each call and closes the underlying transport. MCP's `ClientSession` would then need to reconnect on every `call_tool`, which is expensive and breaks server-side state.

## `_AsyncRunner` (`ovos_tool_adapters/_async_runner.py`)

```
┌─────────────────────────────────┐
│  Main thread (sync OVOS loop)   │
│                                 │
│  runner.run(coro, timeout=30)   │──── asyncio.run_coroutine_threadsafe ──→ ┐
│  blocks on future.result()      │ ←── future resolves ────────────────────  │
└─────────────────────────────────┘                                           │
                                                                              ▼
                                           ┌──────────────────────────────────┐
                                           │  Daemon thread                   │
                                           │  asyncio event loop (run_forever) │
                                           │  MCP/UTCP session lives here     │
                                           └──────────────────────────────────┘
```

One `_AsyncRunner` per toolbox instance. The loop runs forever in a daemon thread. `run(coro)` submits via `run_coroutine_threadsafe` and blocks with `.result(timeout)`. The MCP `ClientSession` and transport context managers live inside the loop thread and are never torn down between calls.

Key methods in `_async_runner.py`:
- `__init__` (line 17): starts the daemon thread and calls `loop.run_forever()`.
- `run(coro, timeout)` (line 37): submits the coroutine and blocks.
- `close()` (line 51): calls `loop.stop()` then `thread.join()`.

## Schema bridge (`ovos_tool_adapters/_schema.py`)

MCP and UTCP servers describe tool inputs as JSON Schema. OVOS `ToolBox` expects a Pydantic `ToolArguments` subclass. `_schema_to_pydantic` (`_schema.py:30`) builds a dynamic model at runtime using Pydantic's `create_model`:

```
MCP Tool.inputSchema (JSON Schema)
  ↓ _schema_to_pydantic("fetch_args", schema)
  ↓ maps "string"→str, "integer"→int, "boolean"→bool, etc.
  ↓ required fields → Field(...), optional → Field(None)
  → dynamic Pydantic class: fetch_args(ToolArguments)
```

This means `tool_json_list` (`agent_tools.py:291`) calls `.model_json_schema()` on the generated class, so the LLM receives the **actual schema** from the server.

## `AdapterToolOutput` (`_schema.py:53`)

Both adapters return this shared output type:

| Field | Source |
|---|---|
| `content` | All MCP `"text"` blocks joined, or the UTCP `text`/`content` field |
| `is_error` | MCP `CallToolResult.isError`, or the UTCP `is_error` key |
| `raw` | Original content blocks preserved for downstream inspection |

## MCPToolBox lifecycle (`mcp.py`)

```
__init__()
  self.config, self._timeout, self._runner = ...
  super().__init__()                    # triggers discover_tools()

discover_tools()                        # line 160
  _runner.run(_connect_and_list())      # blocks
    → opens transport CM
    → creates ClientSession
    → initialize()
    → list_tools()
    → stores session + CMs as instance attrs
  for each tool:
    args_model = _schema_to_pydantic(...)
    AgentTool(tool_call=_call_mcp_tool(name, ...))

call_tool("fetch", {"url":"..."})       # inherited from ToolBox
  → validate_input → fetch_args(url="...")
  → _call_mcp_tool("fetch", args)       # line 134
      _runner.run(session.call_tool(...))
      → AdapterToolOutput

close()                                 # line 200
  _runner.run(_close_async())
  _runner.close()
```

## UTCPToolBox lifecycle (`utcp.py`)

Mirrors MCPToolBox. The main difference is that `UtcpClient.create()` accepts a `UtcpClientConfig` and manages provider registration internally. Tools come from `client.get_tools()` (`utcp.py:73`).

## OPM integration

Both classes are registered as entry points under `opm.agents.toolbox` (`pyproject.toml:24`). OPM instantiates them with `MyToolBox(config={...})`, with no bus argument at construction. `bind(bus)` is called separately if the toolbox needs messagebus access.

---
[← Configuration](configuration.md) · [Home](index.md) · [Maintainers Guide →](MAINTAINERS_GUIDE.md)
