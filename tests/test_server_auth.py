"""HTTP shared-secret enforcement tests for the assembled server."""

import asyncio
import io
import socket
import threading
import time
from datetime import UTC, datetime

import httpx2
import pytest
import uvicorn
from fastmcp import Client
from key_value.aio.stores.memory import MemoryStore
from mcp.shared.exceptions import MCPError
from pypdf import PdfReader

from assistant_mcp.auth import (
    MCP_SHARED_SECRET_AUTH,
    AuthConfigError,
    SharedSecretTokenVerifier,
    UserRecord,
    build_user_record_store,
    secret_hash,
)
from assistant_mcp.server import build_server
from assistant_mcp.toolsets.storage import GCS_BUCKET_ENV, PUBLIC_URL_TEMPLATE

_UPLOADS: dict[str, tuple[str, bytes]] = {}

SOME_SECRET = "alice-test-secret"


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """Capture uploads so URL outputs can be verified without hitting GCS."""
    _UPLOADS.clear()
    monkeypatch.setenv(GCS_BUCKET_ENV, "test-bucket")

    async def fake_upload(data: bytes, object_name: str, content_type: str) -> str:
        _UPLOADS[object_name] = (content_type, bytes(data))
        return PUBLIC_URL_TEMPLATE.format(bucket="test-bucket", object=object_name)

    monkeypatch.setattr("assistant_mcp.toolsets.pdf.upload_document", fake_upload)
    yield
    _UPLOADS.clear()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _serve(server, app, port=None):
    if port is None:
        port = _free_port()
    uvicorn_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
        )
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


@pytest.fixture
async def secret_server():
    """Serve the assembled server over HTTP with one registered secret."""
    store = build_user_record_store(backend=MemoryStore())
    await store.put(
        key=secret_hash(SOME_SECRET),
        value=UserRecord(
            user_id="alice", label="Alice", created_at=datetime.now(UTC)
        ),
    )
    server = build_server(auth=SharedSecretTokenVerifier(records=store))
    base_url, uvicorn_server, thread = await _serve(server, server.http_app())
    yield base_url
    _stop(uvicorn_server, thread)


async def test_http_request_without_token_is_rejected(secret_server):
    with pytest.raises(MCPError):
        async with Client(f"{secret_server}/mcp") as client:
            await client.list_tools()


async def test_http_request_with_unknown_secret_is_rejected(secret_server):
    with pytest.raises(MCPError):
        async with Client(
            f"{secret_server}/mcp", auth="never-registered-secret"
        ) as client:
            await client.list_tools()


async def test_registered_secret_lists_tools(secret_server):
    async with Client(f"{secret_server}/mcp", auth=SOME_SECRET) as client:
        tools = await client.list_tools()
    assert "pdf_generate_pdf" in {tool.name for tool in tools}


async def test_registered_secret_calls_tool(secret_server):
    async with Client(f"{secret_server}/mcp", auth=SOME_SECRET) as client:
        result = await client.call_tool(
            "pdf_generate_pdf",
            {"text": "Erster Absatz.\n\nZweiter Absatz mit mehr Text."},
        )
    assert not result.is_error
    url = result.structured_content["url"]
    assert url.startswith("https://storage.googleapis.com/") and url.endswith(".pdf")
    object_name = url.removeprefix("https://storage.googleapis.com/test-bucket/")
    content_type, pdf = _UPLOADS[object_name]
    assert content_type == "application/pdf"
    assert pdf.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Erster Absatz." in text
    assert "Zweiter Absatz" in text


async def test_healthz_answers_without_authentication(secret_server):
    async with httpx2.AsyncClient() as client:
        response = await client.get(f"{secret_server}/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_stdio_transport_serves_without_authentication(monkeypatch):
    monkeypatch.delenv(MCP_SHARED_SECRET_AUTH, raising=False)
    server = build_server()
    async with Client(server) as client:
        tools = await client.list_tools()
    assert "pdf_generate_pdf" in {tool.name for tool in tools}


async def test_unconfigured_server_serves_without_authentication(monkeypatch):
    monkeypatch.delenv(MCP_SHARED_SECRET_AUTH, raising=False)
    server = build_server()
    async with Client(server) as client:
        tools = await client.list_tools()
    assert "pdf_generate_pdf" in {tool.name for tool in tools}


async def test_invalid_auth_flag_fails_fast_at_build(monkeypatch):
    monkeypatch.setenv(MCP_SHARED_SECRET_AUTH, "banana")
    with pytest.raises(AuthConfigError, match=MCP_SHARED_SECRET_AUTH):
        build_server()
