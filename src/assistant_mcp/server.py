"""Entry point: assembles the FastMCP server from all registered toolsets."""

import os

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider

from .auth import create_auth_provider
from .toolsets import TOOLSETS


def build_server(auth: AuthProvider | None = None) -> FastMCP:
    """Assemble the FastMCP server from all registered toolsets.

    ``auth`` supplies the auth provider directly (test seam); by default it
    comes from the OAuth environment configuration, which yields no
    authentication when unconfigured.
    """
    if auth is None:
        auth = create_auth_provider()
    server = FastMCP(
        "assistant-mcp",
        instructions="Modular assistant MCP server.",
        auth=auth,
    )
    for _prefix, _toolset in TOOLSETS.items():
        server.mount(_toolset, namespace=_prefix)
    return server


server = build_server()


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        server.run(transport="http", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
