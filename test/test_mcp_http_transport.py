"""The http transport must resolve a client factory on the installed mcp SDK.

mcp 1.x exports `streamablehttp_client`; mcp 2.x renamed it to
`streamable_http_client`. Importing only the 1.x spelling raises ImportError on
2.x, and `discover_tools()` swallows that into a warning -- so the toolbox
reports zero tools instead of failing, which reads like "the server has no
tools" rather than "the transport never connected".
"""
import pytest

mcp_http = pytest.importorskip("mcp.client.streamable_http")


def test_installed_mcp_exposes_a_streamable_http_client():
    """Whichever spelling the installed SDK uses, one of them must exist."""
    names = [n for n in ("streamable_http_client", "streamablehttp_client")
             if hasattr(mcp_http, n)]
    assert names, (
        "neither streamable_http_client nor streamablehttp_client is exported "
        f"by {mcp_http.__name__}; the http transport cannot work"
    )


def test_http_transport_resolves_without_importerror():
    """Exercise the adapter's own import path, not just the SDK's exports."""
    from ovos_tool_adapters.mcp import MCPToolBox  # noqa: F401
    import inspect

    from ovos_tool_adapters import mcp as adapter

    src = inspect.getsource(adapter)
    assert "streamable_http_client" in src, (
        "the adapter only knows the mcp 1.x spelling; it will raise ImportError "
        "on mcp 2.x and silently load no tools"
    )
