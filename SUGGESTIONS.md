# SUGGESTIONS — ovos-tool-adapters

- **SUGG-001**: Add `reconnect_on_failure` option to `MCPToolBox` — if `call_tool` fails with a broken-pipe or connection error, attempt one reconnect before raising.
- **SUGG-002**: Expose `MCPToolBox.refresh_session()` as a public method so operators can force reconnection without restarting OVOS.
- **SUGG-003**: Add a `UTCPToolBox` teardown `close_async()` that calls any UTCP client cleanup method when available.
- **SUGG-004**: Consider an `ovos-tool-adapters[all]` extra that installs both `mcp` and `utcp` for convenience.
- **SUGG-005**: Track open `_AsyncRunner` instances globally (weakref set) and shut them all down at process exit via `atexit`.
