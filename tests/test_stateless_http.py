"""Tests for stateless-by-default HTTP transport configuration (MCP_STATELESS_HTTP)."""

import asyncio
import socket
import threading
import time

import fastmcp
import httpx2
import pytest
import uvicorn
from fastmcp import Client

from assistant_mcp import server as server_module
from assistant_mcp.server import MCP_STATELESS_HTTP, build_server, resolve_stateless_http
from assistant_mcp.toolsets.storage import GCS_BUCKET_ENV, PUBLIC_URL_TEMPLATE

MCP_PATH = fastmcp.settings.streamable_http_path
INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "stateless-http-test", "version": "0"},
    },
}
INITIALIZE_HEADERS = {"Accept": "application/json, text/event-stream"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _serve(app):
    # The initialize tests need a real uvicorn server, not the in-process
    # ASGI transport: the MCP session manager is started by the app's
    # lifespan, which httpx2's ASGITransport does not run.
    port = _free_port()
    uvicorn_server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    )
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10.0
    while not uvicorn_server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            uvicorn_server.should_exit = True
            raise RuntimeError("test server did not start")
        await asyncio.sleep(0.05)
    return f"http://127.0.0.1:{port}", uvicorn_server, thread


def _stop(uvicorn_server, thread):
    uvicorn_server.should_exit = True
    thread.join(timeout=10)


def _asgi_client(app) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
    )


def _fake_run_recorder(monkeypatch) -> dict:
    """Replace the assembled server's run() with a kwargs recorder."""
    recorded: dict = {}

    def fake_run(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(server_module.server, "run", fake_run)
    return recorded


async def test_resolution_defaults_to_stateless(monkeypatch):
    monkeypatch.delenv(MCP_STATELESS_HTTP, raising=False)
    assert resolve_stateless_http() is True


@pytest.mark.parametrize("value", ["false", "FALSE", "False"])
async def test_resolution_exact_false_disables_stateless(monkeypatch, value):
    monkeypatch.setenv(MCP_STATELESS_HTTP, value)
    assert resolve_stateless_http() is False


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
async def test_resolution_any_other_value_stays_stateless(monkeypatch, value):
    monkeypatch.setenv(MCP_STATELESS_HTTP, value)
    assert resolve_stateless_http() is True


async def test_stateless_default_serves_mcp_statelessly(
    monkeypatch, rejecting_token_verifier
):
    monkeypatch.delenv(MCP_STATELESS_HTTP, raising=False)
    stateless = resolve_stateless_http()
    assert stateless is True
    server = build_server(auth=rejecting_token_verifier)
    async with _asgi_client(server.http_app(stateless_http=stateless)) as client:
        get_response = await client.get(MCP_PATH)
        post_response = await client.post(MCP_PATH, json=INITIALIZE_REQUEST)
    assert get_response.status_code == 405
    assert post_response.status_code == 401


async def test_stateless_initialize_succeeds_without_session_header(
    cleared_oauth_env, monkeypatch
):
    monkeypatch.delenv(MCP_STATELESS_HTTP, raising=False)
    stateless = resolve_stateless_http()
    server = build_server()
    base_url, uvicorn_server, thread = await _serve(server.http_app(stateless_http=stateless))
    try:
        async with httpx2.AsyncClient(base_url=base_url) as client:
            response = await client.post(
                MCP_PATH, json=INITIALIZE_REQUEST, headers=INITIALIZE_HEADERS
            )
    finally:
        _stop(uvicorn_server, thread)
    assert response.status_code == 200
    assert '"serverInfo"' in response.text
    assert response.headers.get("mcp-session-id") is None


async def test_override_false_serves_get_with_auth_challenge(
    monkeypatch, rejecting_token_verifier
):
    monkeypatch.setenv(MCP_STATELESS_HTTP, "false")
    stateless = resolve_stateless_http()
    assert stateless is False
    server = build_server(auth=rejecting_token_verifier)
    async with _asgi_client(server.http_app(stateless_http=stateless)) as client:
        get_response = await client.get(MCP_PATH)
        post_response = await client.post(MCP_PATH, json=INITIALIZE_REQUEST)
    assert get_response.status_code == 401
    assert post_response.status_code == 401


async def test_override_false_initialize_returns_session_header(
    cleared_oauth_env, monkeypatch
):
    monkeypatch.setenv(MCP_STATELESS_HTTP, "false")
    stateless = resolve_stateless_http()
    server = build_server()
    base_url, uvicorn_server, thread = await _serve(server.http_app(stateless_http=stateless))
    try:
        async with httpx2.AsyncClient(base_url=base_url) as client:
            response = await client.post(
                MCP_PATH, json=INITIALIZE_REQUEST, headers=INITIALIZE_HEADERS
            )
    finally:
        _stop(uvicorn_server, thread)
    assert response.status_code == 200
    assert response.headers.get("mcp-session-id")


async def test_tools_remain_callable_in_memory_with_stateless_http_set(
    cleared_oauth_env, monkeypatch
):
    monkeypatch.setenv(MCP_STATELESS_HTTP, "true")
    monkeypatch.setenv(GCS_BUCKET_ENV, "test-bucket")
    async def fake_upload(data, object_name, content_type):
        return PUBLIC_URL_TEMPLATE.format(bucket="test-bucket", object=object_name)

    monkeypatch.setattr("assistant_mcp.toolsets.pdf.upload_document", fake_upload)
    server = build_server()
    async with Client(server) as client:
        result = await client.call_tool("pdf_generate_pdf", {"text": "Stateless probe text."})
    assert not result.is_error
    assert result.structured_content["url"].endswith(".pdf")


def test_main_wires_stateless_http_into_http_transport(monkeypatch):
    recorded = _fake_run_recorder(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.delenv(MCP_STATELESS_HTTP, raising=False)
    server_module.main()
    assert recorded["transport"] == "http"
    assert recorded["stateless_http"] is True


def test_main_wires_stateless_override_into_http_transport(monkeypatch):
    recorded = _fake_run_recorder(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv(MCP_STATELESS_HTTP, "false")
    server_module.main()
    assert recorded["stateless_http"] is False


def test_main_leaves_stdio_transport_without_stateless_http(monkeypatch):
    recorded = _fake_run_recorder(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv(MCP_STATELESS_HTTP, "true")
    server_module.main()
    assert recorded == {"transport": "stdio"}
