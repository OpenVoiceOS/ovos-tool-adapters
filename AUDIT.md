# AUDIT — ovos-tool-adapters

## Known Issues / Technical Debt

| ID | Severity | File:Line | Description |
|---|---|---|---|
| AUDIT-001 | Low | `mcp.py:173` | `discover_tools()` failure path leaves an unawaited coroutine when `_runner.run()` raises before the coroutine is awaited. Benign at runtime; produces a `RuntimeWarning` in tests. |
| AUDIT-002 | Medium | `mcp.py:138` | stdio transport `__aenter__` returns `(read, write)` but streamable-http may return a 3-tuple `(read, write, session)`. The extra element is currently discarded; verify against `mcp>=1.4` API. |
| AUDIT-003 | Low | `utcp.py:100` | UTCP response normalisation is heuristic (`dict.get("text")`). The UTCP spec may define a richer content model; revisit when UTCP hits stable 1.x. |
| AUDIT-004 | Low | `_async_runner.py:50` | `_thread.join(timeout=5)` may silently fail to join if the loop is blocked. No hard guarantee of clean shutdown. |

## Security

- `MCPToolBox` can spawn subprocesses via `stdio` transport. Config must be controlled by operators, not untrusted end-users.
- No input sanitisation beyond Pydantic validation; downstream MCP/UTCP servers are responsible for their own security.
