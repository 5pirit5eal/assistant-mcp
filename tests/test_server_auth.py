"""HTTP token enforcement tests for the assembled server."""

import asyncio
import base64
import contextlib
import dataclasses
import datetime
import hashlib
import io
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
import uvicorn
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastmcp import Client
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.oauth_proxy.upstream import AsyncOAuth2Client
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.utilities.auth import parse_scopes
from key_value.aio.stores.memory import MemoryStore
from mcp.server.auth.provider import RefreshToken, TokenError
from mcp.shared.auth import OAuthToken
from mcp.shared.exceptions import MCPError
from pypdf import PdfReader

from assistant_mcp.auth import (
    DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
    DEFAULT_REFRESH_GRACE_SECONDS,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    MCP_ACCESS_TOKEN_TTL_SECONDS,
    MCP_ALLOWED_EMAILS,
    MCP_BASE_URL,
    MCP_OAUTH_STORAGE_KEY,
    MCP_REFRESH_GRACE_SECONDS,
    OAUTH_ENV_VARS,
    REFRESH_GRACE_COLLECTION,
    RefreshGraceEntry,
    _presented_token_key,
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


async def _serve(server, app, port=None, ssl_certfile=None, ssl_keyfile=None):
    if port is None:
        port = _free_port()
    uvicorn_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
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


# ---------------------------------------------------------------------------
# Full OAuth code-flow harness
# ---------------------------------------------------------------------------

_GOOGLE_SCOPE = "openid https://www.googleapis.com/auth/userinfo.email"
HARNESS_REDIRECT_URI = "http://127.0.0.1:9/cb"


def _write_self_signed_cert(tmp_path):
    """Create a self-signed TLS certificate for the 127.0.0.1 test server."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "test-cert.pem"
    key_path = tmp_path / "test-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


def _form_value(html, name):
    match = re.search(rf'name="{name}"\s+value="([^"]+)"', html)
    assert match, f"form field {name!r} not found in consent page"
    return match.group(1)


def _stub_google_upstream(monkeypatch):
    """Replace Google's token endpoint at the upstream client boundary.

    The stub returns canned Google token responses; every other part of the
    proxy flow (consent, callback, PKCE, storage, JWT issuance) runs real.
    """

    async def fake_fetch_token(self, url, **kwargs):
        return {
            "access_token": f"google-access-{secrets.token_hex(8)}",
            "refresh_token": "google-refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": _GOOGLE_SCOPE,
        }

    async def fake_refresh_token(self, url, refresh_token=None, **kwargs):
        return {
            "access_token": f"google-access-{secrets.token_hex(8)}",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": _GOOGLE_SCOPE,
        }

    monkeypatch.setattr(AsyncOAuth2Client, "fetch_token", fake_fetch_token)
    monkeypatch.setattr(AsyncOAuth2Client, "refresh_token", fake_refresh_token)


@dataclasses.dataclass
class FlowContext:
    base_url: str
    client_id: str
    redirect_uri: str
    code_verifier: str
    tokens: dict
    backend: MemoryStore
    provider: object


@contextlib.asynccontextmanager
async def _oauth_server_on(
    backend, monkeypatch, tmp_path, env_overrides=None
):
    """Serve the assembled server over TLS with the given storage backend.

    The provider's public base URL is the test server's own
    https://127.0.0.1:<port> address (the authorize redirect and OAuth
    metadata are issuer-based). Yields the public base URL.
    """
    port = _free_port()
    base_url = f"https://127.0.0.1:{port}"
    env = {**OAUTH_ENV, MCP_BASE_URL: base_url, **(env_overrides or {})}
    provider = create_auth_provider(env=env, storage_backend=backend)
    assert provider is not None
    server = build_server(auth=provider)
    cert_path, key_path = _write_self_signed_cert(tmp_path)
    _, uvicorn_server, thread = await _serve(
        server,
        server.http_app(),
        port=port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
    )
    _stub_google_upstream(monkeypatch)
    try:
        yield base_url, provider
    finally:
        _stop(uvicorn_server, thread)


async def _login(base_url):
    """Drive the full OAuth authorization-code flow as one MCP client."""
    async with httpx2.AsyncClient(verify=False, follow_redirects=False) as http:
        register = await http.post(
            f"{base_url}/register",
            json={
                "client_name": "full-flow-harness",
                "redirect_uris": [HARNESS_REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": _GOOGLE_SCOPE,
            },
        )
        assert register.status_code == 201, register.text
        client_id = register.json()["client_id"]
        verifier, challenge = _pkce_pair()
        authorize = await http.get(
            f"{base_url}/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": HARNESS_REDIRECT_URI,
                "scope": _GOOGLE_SCOPE,
                "state": "harness-state",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert authorize.status_code == 302, authorize.text
        consent_page = await http.get(authorize.headers["location"])
        assert consent_page.status_code == 200, consent_page.text
        approve = await http.post(
            f"{base_url}/consent",
            data={
                "txn_id": _form_value(consent_page.text, "txn_id"),
                "csrf_token": _form_value(consent_page.text, "csrf_token"),
                "action": "approve",
            },
        )
        assert approve.status_code == 302, approve.text
        txn_id = parse_qs(urlparse(authorize.headers["location"]).query)[
            "txn_id"
        ][0]
        callback = await http.get(
            f"{base_url}/auth/callback",
            params={"code": "google-code-1", "state": txn_id},
        )
        assert callback.status_code == 302, callback.text
        client_redirect = callback.headers["location"]
        proxy_code = parse_qs(urlparse(client_redirect).query)["code"][0]
        token_response = await http.post(
            f"{base_url}/token",
            data={
                "grant_type": "authorization_code",
                "code": proxy_code,
                "client_id": client_id,
                "redirect_uri": HARNESS_REDIRECT_URI,
                "code_verifier": verifier,
            },
        )
        assert token_response.status_code == 200, token_response.text
        return client_id, verifier, token_response.json()


@pytest.fixture
def oauth_flow(monkeypatch, tmp_path):
    """Factory that completes a full OAuth authorization-code flow.

    Starts the assembled server over TLS, logs in once, and yields the flow
    context with the issued token response. Pass ``backend`` to share the
    OAuth state storage across servers (restart simulation) and
    ``env_overrides`` for optional configuration values.
    """

    @contextlib.asynccontextmanager
    async def run(env_overrides=None, backend=None):
        if backend is None:
            backend = MemoryStore()
        async with _oauth_server_on(
            backend, monkeypatch, tmp_path, env_overrides
        ) as (base_url, provider):
            client_id, verifier, tokens = await _login(base_url)
            yield FlowContext(
                base_url=base_url,
                client_id=client_id,
                redirect_uri=HARNESS_REDIRECT_URI,
                code_verifier=verifier,
                tokens=tokens,
                backend=backend,
                provider=provider,
            )

    return run


async def _post_token(base_url, data):
    async with httpx2.AsyncClient(verify=False) as http:
        return await http.post(f"{base_url}/token", data=data)


async def _post_refresh(base_url, client_id, refresh_token):
    return await _post_token(
        base_url,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
    )


async def test_issued_access_token_uses_default_ttl(oauth_flow):
    async with oauth_flow() as flow:
        assert flow.tokens["expires_in"] == DEFAULT_ACCESS_TOKEN_TTL_SECONDS


async def test_issued_access_token_uses_configured_ttl(oauth_flow):
    async with oauth_flow(
        env_overrides={MCP_ACCESS_TOKEN_TTL_SECONDS: "7200"}
    ) as flow:
        assert flow.tokens["expires_in"] == 7200


async def test_grace_entry_is_encrypted_in_backend(oauth_flow):
    async with oauth_flow() as flow:
        refresh = await _post_refresh(
            flow.base_url, flow.client_id, flow.tokens["refresh_token"]
        )
        assert refresh.status_code == 200, refresh.text
        rotated = refresh.json()
        keys = await flow.backend.keys(collection=REFRESH_GRACE_COLLECTION)
        assert keys, "no grace entry persisted after refresh rotation"
        for key in keys:
            raw = await flow.backend.get(key, collection=REFRESH_GRACE_COLLECTION)
            assert raw is not None
            serialized = json.dumps(raw)
            assert "__encrypted_data__" in serialized
            assert flow.tokens["refresh_token"] not in serialized
            assert rotated["refresh_token"] not in serialized
            assert rotated["access_token"] not in serialized


async def test_grace_entry_expires_with_the_grace_period(oauth_flow):
    async with oauth_flow() as flow:
        refresh = await _post_refresh(
            flow.base_url, flow.client_id, flow.tokens["refresh_token"]
        )
        assert refresh.status_code == 200, refresh.text
        keys = await flow.backend.keys(collection=REFRESH_GRACE_COLLECTION)
        assert len(keys) == 1
        _, remaining_ttl = await flow.backend.ttl(
            keys[0], collection=REFRESH_GRACE_COLLECTION
        )
        assert remaining_ttl is not None
        assert 0 < remaining_ttl <= DEFAULT_REFRESH_GRACE_SECONDS


async def test_grace_replay_survives_restart(oauth_flow):
    backend = MemoryStore()
    async with oauth_flow(backend=backend) as flow:
        consumed = flow.tokens["refresh_token"]
        first = await _post_refresh(flow.base_url, flow.client_id, consumed)
        assert first.status_code == 200, first.text
    async with oauth_flow(backend=backend) as restarted:
        replay = await _post_refresh(
            restarted.base_url, flow.client_id, consumed
        )
        assert replay.status_code == 200, replay.text
        assert replay.json() == first.json()


async def test_concurrent_refreshes_converge_on_one_token_set(oauth_flow):
    async with oauth_flow() as flow:
        consumed = flow.tokens["refresh_token"]
        first = await _post_refresh(flow.base_url, flow.client_id, consumed)
        assert first.status_code == 200, first.text
        second = await _post_refresh(flow.base_url, flow.client_id, consumed)
        assert second.status_code == 200, second.text
        assert second.json() == first.json()


async def test_late_refresh_beyond_grace_window_is_rejected(oauth_flow):
    async with oauth_flow(
        env_overrides={MCP_REFRESH_GRACE_SECONDS: "1"}
    ) as flow:
        consumed = flow.tokens["refresh_token"]
        first = await _post_refresh(flow.base_url, flow.client_id, consumed)
        assert first.status_code == 200, first.text
        await asyncio.sleep(1.2)
        late = await _post_refresh(flow.base_url, flow.client_id, consumed)
        assert late.status_code == 401, late.text
        assert late.json()["error"] == "invalid_grant"


async def test_unknown_refresh_token_is_rejected(oauth_flow):
    async with oauth_flow() as flow:
        response = await _post_refresh(
            flow.base_url, flow.client_id, "never-issued-token"
        )
        assert response.status_code == 401, response.text
        assert response.json()["error"] == "invalid_grant"


async def test_refresh_racing_past_grace_check_replays(oauth_flow, monkeypatch):
    async with oauth_flow() as flow:
        client = await flow.provider.get_client(flow.client_id)
        assert client is not None
        winner = OAuthToken(
            access_token="winner-access-token",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="winner-refresh-token",
            scope=_GOOGLE_SCOPE,
        )

        async def lost_race(self, client, refresh_token, scopes):
            await self._grace_store.put(
                key=_presented_token_key(refresh_token.token),
                value=RefreshGraceEntry(
                    client_id=client.client_id or "",
                    access_token=winner.access_token,
                    expires_in=winner.expires_in,
                    refresh_token=winner.refresh_token,
                    scope=winner.scope,
                ),
                ttl=DEFAULT_REFRESH_GRACE_SECONDS,
            )
            raise TokenError("invalid_grant", "Refresh token mapping not found")

        monkeypatch.setattr(GoogleProvider, "exchange_refresh_token", lost_race)
        result = await flow.provider.exchange_refresh_token(
            client,
            RefreshToken(
                token=flow.tokens["refresh_token"],
                client_id=flow.client_id,
                scopes=parse_scopes(_GOOGLE_SCOPE),
            ),
            parse_scopes(_GOOGLE_SCOPE),
        )
        assert result.access_token == "winner-access-token"
        assert result.refresh_token == "winner-refresh-token"


async def test_load_returns_refresh_token_within_grace_window(oauth_flow):
    async with oauth_flow() as flow:
        client = await flow.provider.get_client(flow.client_id)
        assert client is not None
        consumed = flow.tokens["refresh_token"]
        first = await _post_refresh(flow.base_url, flow.client_id, consumed)
        assert first.status_code == 200, first.text
        loaded = await flow.provider.load_refresh_token(client, consumed)
        assert loaded is not None
        assert loaded.token == consumed
        assert loaded.client_id == flow.client_id


async def test_load_rejects_consumed_token_beyond_grace_window(oauth_flow):
    async with oauth_flow(
        env_overrides={MCP_REFRESH_GRACE_SECONDS: "1"}
    ) as flow:
        client = await flow.provider.get_client(flow.client_id)
        assert client is not None
        consumed = flow.tokens["refresh_token"]
        first = await _post_refresh(flow.base_url, flow.client_id, consumed)
        assert first.status_code == 200, first.text
        await asyncio.sleep(1.2)
        assert await flow.provider.load_refresh_token(client, consumed) is None


async def test_load_rejects_unknown_token(oauth_flow):
    async with oauth_flow() as flow:
        client = await flow.provider.get_client(flow.client_id)
        assert client is not None
        loaded = await flow.provider.load_refresh_token(
            client, "never-issued-token"
        )
        assert loaded is None
