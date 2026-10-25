"""Entry point: assembles the FastMCP server from all registered toolsets."""

import os

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import create_token_verifier
from .toolsets import TOOLSETS

MCP_STATELESS_HTTP = "MCP_STATELESS_HTTP"


def resolve_stateless_http() -> bool:
    """Resolve whether the HTTP transport serves requests statelessly.

    Unset or any value other than case-insensitive ``false`` means stateless;
    only ``MCP_STATELESS_HTTP=false`` restores stateful HTTP behavior. The
    stdio transport is unaffected by this setting.
    """
    return os.environ.get(MCP_STATELESS_HTTP, "").strip().lower() != "false"


def build_server(auth: AuthProvider | None = None) -> FastMCP:
    """Assemble the FastMCP server from all registered toolsets.

    ``auth`` supplies the auth provider directly (test seam); by default it
    comes from the shared-secret environment configuration, which yields no
    authentication when unconfigured.
    """
    if auth is None:
        auth = create_token_verifier()
    server = FastMCP(
        "assistant-mcp",
        instructions="Modular assistant MCP server.",
        auth=auth,
    )
    for _prefix, _toolset in TOOLSETS.items():
        server.mount(_toolset, namespace=_prefix)

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        """Unauthenticated health endpoint for platform startup probes."""
        return JSONResponse({"status": "ok"})

    return server


server = build_server()


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        server.run(
            transport="http",
            host="0.0.0.0",
            port=int(os.environ.get("PORT", "8080")),
            stateless_http=resolve_stateless_http(),
        )
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
