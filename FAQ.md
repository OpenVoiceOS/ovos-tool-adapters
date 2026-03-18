# FAQ — ovos-tool-adapters

**Q: Why is there a daemon thread? Can't I just use `asyncio.run()`?**
`asyncio.run()` creates a new event loop per call and destroys it on exit. MCP's `ClientSession` and transport context managers must remain open across calls. `_AsyncRunner` keeps one loop alive for the lifetime of the toolbox. — `_async_runner.py:17`

**Q: What happens if `mcp` or `utcp` is not installed?**
`discover_tools()` catches the `ImportError`, logs a `LOG.warning`, and returns `[]`. OPM loads the entry point without crashing; the toolbox simply provides no tools. — `mcp.py:171`, `utcp.py:130`

**Q: How are MCP tool schemas exposed to the LLM?**
`_schema_to_pydantic` converts `Tool.inputSchema` into a dynamic Pydantic `ToolArguments` subclass. `ToolBox.tool_json_list` calls `.model_json_schema()` on it, so the LLM receives the real schema. — `_schema.py:30`

**Q: Is the MCP session reconnected on every `call_tool`?**
No. The session is established once in `discover_tools()` via `_connect_and_list()` and reused for all subsequent calls. — `mcp.py:99`

**Q: Which MCP transports are supported?**
`stdio` (subprocess), `sse` (Server-Sent Events), `http` (Streamable HTTP). Set via the `transport` config key. — `mcp.py:78`

**Q: How does UTCP normalise varied response types?**
`_call_utcp_tool` handles `str`, `dict`, and fallback `str()` responses, always returning `AdapterToolOutput`. — `utcp.py:108`

**Q: Can I use both MCP and UTCP toolboxes at the same time?**
Yes. List both in `toolboxes` and configure each separately. — `docs/configuration.md`

**Q: How do I run tests without a live MCP or UTCP server?**
All tests use mocks — no server needed. Run: `uv run pytest test/ -v --cov=ovos_tool_adapters`

**Q: The toolbox connected but returned no tools. Why?**
The MCP/UTCP server started but exposed zero tools, or `list_tools()` returned an empty list. Check the server logs and verify it started correctly.

**Q: Does the adapter support MCP tools that return images or resources?**
Yes. Non-text content blocks are preserved in `AdapterToolOutput.raw`. Only text blocks are concatenated into `AdapterToolOutput.content`. The agent can inspect `raw` for other content types.
