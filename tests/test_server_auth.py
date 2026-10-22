"""HTTP token enforcement tests for the assembled server."""

import asyncio
import io
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from cryptography.fernet import Fernet
from fastmcp import Client
from fastmcp.server.auth import AccessToken, TokenVerifier
from key_value.aio.stores.memory import MemoryStore
from mcp.shared.exceptions import MCPError
from pypdf import PdfReader

from assistant_mcp.auth import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    MCP_ALLOWED_EMAILS,
    MCP_BASE_URL,
    MCP_OAUTH_STORAGE_KEY,
    OAUTH_ENV_VARS,
    create_auth_provider,
)
from assistant_mcp.server import build_server
from assistant_mcp.toolsets.storage import GCS_BUCKET_ENV, PUBLIC_URL_TEMPLATE

_UPLOADS: dict[str, tuple[str, bytes]] = {}


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

STUB_TOKEN = "stub-valid-token"
OAUTH_ENV = {
    GOOGLE_CLIENT_ID: "123456789.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET: "GOCSPX-test-secret",
    MCP_BASE_URL: "https://assistant-mcp.example.com",
    MCP_ALLOWED_EMAILS: "user@example.com",
    MCP_OAUTH_STORAGE_KEY: Fernet.generate_key().decode(),
}


class StubTokenVerifier(TokenVerifier):
    """Accepts exactly one known token; everything else is rejected."""

    def __init__(self, valid_token: str = STUB_TOKEN) -> None:
        super().__init__()
        self.valid_token = valid_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != self.valid_token:
            return None
        return AccessToken(
            token=token,
            client_id="stub-client",
            scopes=["openid", "email"],
            claims={"email": "user@example.com"},
        )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _serve(server, app):
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


@pytest.fixture
async def stub_auth_server():
    server = build_server(auth=StubTokenVerifier())
    base_url, uvicorn_server, thread = await _serve(server, server.http_app())
    yield base_url
    _stop(uvicorn_server, thread)


async def test_http_request_without_token_is_rejected(stub_auth_server):
    with pytest.raises(MCPError):
        async with Client(f"{stub_auth_server}/mcp") as client:
            await client.list_tools()


async def test_http_request_with_malformed_token_is_rejected(stub_auth_server):
    with pytest.raises(MCPError):
        async with Client(f"{stub_auth_server}/mcp", auth="malformed-token") as client:
            await client.list_tools()


async def test_authenticated_client_lists_tools(stub_auth_server):
    async with Client(f"{stub_auth_server}/mcp", auth=STUB_TOKEN) as client:
        tools = await client.list_tools()
    assert "pdf_generate_pdf" in {tool.name for tool in tools}


async def test_authenticated_client_calls_generate_pdf(stub_auth_server):
    async with Client(f"{stub_auth_server}/mcp", auth=STUB_TOKEN) as client:
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


@pytest.fixture
async def oauth_server():
    provider = create_auth_provider(env=OAUTH_ENV, storage_backend=MemoryStore())
    assert provider is not None
    server = build_server(auth=provider)
    base_url, uvicorn_server, thread = await _serve(server, server.http_app())
    yield base_url
    _stop(uvicorn_server, thread)


async def test_oauth_metadata_is_discoverable(oauth_server):
    async with httpx2.AsyncClient() as client:
        response = await client.get(
            f"{oauth_server}/.well-known/oauth-protected-resource/mcp"
        )
    assert response.status_code == 200
    metadata = response.json()
    assert metadata["authorization_servers"], "no authorization server advertised"

    async with httpx2.AsyncClient() as client:
        response = await client.get(
            f"{oauth_server}/.well-known/oauth-authorization-server"
        )
    assert response.status_code == 200
    authorization_metadata = response.json()
    for endpoint in (
        "authorization_endpoint",
        "token_endpoint",
        "registration_endpoint",
    ):
        assert authorization_metadata[endpoint], f"{endpoint} not advertised"


async def test_unconfigured_server_serves_without_authentication(monkeypatch):
    for name in OAUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    server = build_server()
    async with Client(server) as client:
        tools = await client.list_tools()
    assert "pdf_generate_pdf" in {tool.name for tool in tools}
