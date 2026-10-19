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

MCP and UTCP servers describe tool inputs as JSON Schema. OVOS `ToolBox` expects a Pydantic `ToolArguments` subclass. `_schema_to_pydantic` (`_schema.py:158`) builds that class at runtime with Pydantic's `create_model`:

```
MCP Tool.inputSchema or UTCP Tool.inputs (JSON Schema)
  ↓ _schema_to_pydantic("fetch_args", schema)
  ↓ "string"→str, "integer"→int, "boolean"→bool, "enum"→Literal
  ↓ an object with properties → a nested model, an array → List[item type]
  ↓ local $ref and anyOf/oneOf with null → the referenced type, Optional
  ↓ required fields → Field(...), optional → Field(None)
  → dynamic Pydantic class: fetch_args(ToolArguments)
```

The class validates every call the way the server does, nested objects included. A nested object keeps keys the schema does not list, unless the schema sets `additionalProperties: false`. Pydantic cannot make a field with some names, such as `_id` or `model_dump`. A nested object that has one is validated as a plain object, and the server still checks its fields.

If the schema of one tool cannot be built at all, for example a top-level `_id` or a nesting too deep to follow, the toolbox logs an ERROR that names the tool and the reason, skips that tool, and loads the others.

A call sends the arguments the caller gave, at every level of nesting. An argument the caller left out is not sent, so the server applies its own default. A `null` is sent only where the field's schema allows `null`: a `null` type, `nullable`, a `null` enum value, a `null` branch of `anyOf` or `oneOf`, or no type at all. Where the schema does not allow it, the `null` is left out, the same as an argument the caller did not give.

`.model_json_schema()` on the class returns the server's own JSON Schema, unchanged. `tool_json_list` (`agent_tools.py:311`) reads it, so the LLM sees each nested field, enum and description exactly as the server declared them.

## `AdapterToolOutput` (`_schema.py:206`)

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

Mirrors MCPToolBox. The main difference is the manual registration. The toolbox validates each template in `manual_call_templates` and skips one that the UTCP client rejects. It creates a `UtcpClient` without the templates, then registers the valid ones with `client.register_manuals()`, so it can log each failed manual with its reason. Tools come from the client's tool repository (`client.config.tool_repository.get_tools()`), and each tool's JSON Schema comes from `Tool.inputs`. `close()` closes the UTCP client before it stops the runner, except at interpreter shutdown, where the runner loop can no longer run the close. A new discovery registers the manuals on a new client first. Only then does it replace the previous client and close it, so tool calls made during the discovery keep working.

## OPM integration

Both classes are registered as entry points under `opm.agents.toolbox` (`pyproject.toml:24`). OPM instantiates them with `MyToolBox(config={...})`, with no bus argument at construction. `bind(bus)` is called separately if the toolbox needs messagebus access.

---
[← Configuration](configuration.md) · [Home](index.md) · [Maintainers Guide →](MAINTAINERS_GUIDE.md)
