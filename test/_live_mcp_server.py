"""Standalone stdio MCP server used as a live test peer for MCPToolBox.

Not a pytest module — launched as a subprocess by test_mcp_live.py via
``StdioServerParameters(command=sys.executable, args=[this_file])``.
Exercises a real ``mcp`` server implementation so the client-side code in
``ovos_tool_adapters.mcp`` is validated against the installed ``mcp`` SDK
instead of mocks.
"""
try:
    # mcp>=2.0: FastMCP was renamed to MCPServer and moved module.
    from mcp.server.mcpserver import MCPServer as _ServerClass
except ImportError:
    # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _ServerClass

server = _ServerClass("echo-test")


@server.tool()
def echo(text: str) -> str:
    """Echo back the given text, prefixed with 'echo:'."""
    return f"echo:{text}"


if __name__ == "__main__":
    server.run("stdio")
