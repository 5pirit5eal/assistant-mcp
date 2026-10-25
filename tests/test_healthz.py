"""Tests for the /healthz platform probe endpoint on the assembled server."""

import fastmcp
import httpx2
import pytest

from assistant_mcp.server import build_server

MCP_PATH = fastmcp.settings.streamable_http_path
INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "healthz-test", "version": "0"},
    },
}


def _asgi_client(app) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
    )


@pytest.mark.parametrize("stateless_http", [True, False], ids=["stateless", "stateful"])
async def test_healthz_returns_ok_when_unconfigured(cleared_auth_env, stateless_http):
    server = build_server()
    async with _asgi_client(server.http_app(stateless_http=stateless_http)) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("stateless_http", [True, False], ids=["stateless", "stateful"])
async def test_healthz_is_exempt_from_auth_while_mcp_rejects(
    rejecting_token_verifier, stateless_http
):
    server = build_server(auth=rejecting_token_verifier)
    async with _asgi_client(server.http_app(stateless_http=stateless_http)) as client:
        health = await client.get("/healthz")
        mcp = await client.post(MCP_PATH, json=INITIALIZE_REQUEST)
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert mcp.status_code == 401
