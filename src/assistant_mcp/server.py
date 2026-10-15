"""Entry point: assembles the FastMCP server from all registered toolsets."""

import os

from fastmcp import FastMCP

from .toolsets import TOOLSETS

server = FastMCP("assistant-mcp", instructions="Modular assistant MCP server.")

for _prefix, _toolset in TOOLSETS.items():
    server.mount(_toolset, namespace=_prefix)


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        server.run(transport="http", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
