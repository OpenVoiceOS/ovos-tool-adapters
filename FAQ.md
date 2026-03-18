# FAQ — ovos-tool-adapters

**Q: Why is there a daemon thread? Can't I use `asyncio.run()`?**
`asyncio.run()` creates a new event loop per call and destroys it on exit. MCP's `ClientSession` and transport context managers must remain open across calls. `_AsyncRunner` keeps one loop alive for the lifetime of the toolbox. — `_async_runner.py:21`

**Q: What happens if `mcp` or `utcp` is not installed?**
`discover_tools()` catches the `ImportError`, logs a `LOG.warning`, and returns `[]`. OPM loads the entry point without crashing; the toolbox simply provides no tools. — `mcp.py:148`, `utcp.py:115`

**Q: How are MCP tool input schemas exposed to the LLM?**
`_schema_to_pydantic` converts the JSON Schema from `mcp.types.Tool.inputSchema` into a dynamic Pydantic model. `ToolBox.tool_json_list` calls `.model_json_schema()` on that model, so the LLM sees the real schema. — `_schema.py:30`

**Q: Is the MCP session reconnected on every `call_tool`?**
No. The session is established once in `discover_tools()` and reused for all subsequent calls via `MCPToolBox._call_mcp_tool`. — `mcp.py:110`

**Q: Which MCP transports are supported?**
`stdio` (subprocess), `sse` (Server-Sent Events), `http` (Streamable HTTP). Configured via the `transport` key in the persona config. — `mcp.py:67`

**Q: How does UTCP normalise varied response types?**
`UTCPToolBox._call_utcp_tool` handles `str`, `dict`, and fallback `str()` responses, always returning `AdapterToolOutput`. — `utcp.py:100`
