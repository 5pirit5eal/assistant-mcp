"""Tests for the OAuth 2.1 auth factory in assistant_mcp.auth."""

import json

import pytest
from cryptography.fernet import Fernet
from fastmcp.server.auth import AccessToken, TokenVerifier
from key_value.aio.stores.memory import MemoryStore

from assistant_mcp.auth import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    MCP_ALLOWED_EMAILS,
    MCP_BASE_URL,
    MCP_OAUTH_STORAGE_KEY,
    OAUTH_CACHE_TTL_SECONDS,
    OAUTH_ENV_VARS,
    AllowlistGoogleProvider,
    AllowlistTokenVerifier,
    AuthConfigError,
    build_client_storage,
    create_auth_provider,
)

FERNET_KEY = Fernet.generate_key().decode()
CLIENT_ID = "123456789.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-test-secret"
BASE_URL = "https://assistant-mcp.example.com"
ALLOWED_EMAILS = "user@example.com,other@example.com"


def complete_env() -> dict[str, str]:
    return {
        GOOGLE_CLIENT_ID: CLIENT_ID,
        GOOGLE_CLIENT_SECRET: CLIENT_SECRET,
        MCP_BASE_URL: BASE_URL,
        MCP_ALLOWED_EMAILS: ALLOWED_EMAILS,
        MCP_OAUTH_STORAGE_KEY: FERNET_KEY,
    }


def test_env_var_constants_cover_the_activation_contract():
    assert OAUTH_ENV_VARS == (
        GOOGLE_CLIENT_ID,
        GOOGLE_CLIENT_SECRET,
        MCP_BASE_URL,
        MCP_ALLOWED_EMAILS,
        MCP_OAUTH_STORAGE_KEY,
    )


def test_unconfigured_environment_returns_no_auth():
    provider = create_auth_provider(env={}, storage_backend=MemoryStore())
    assert provider is None


def test_partial_configuration_raises_naming_missing_variables():
    env = {GOOGLE_CLIENT_ID: CLIENT_ID}
    with pytest.raises(AuthConfigError) as excinfo:
        create_auth_provider(env=env, storage_backend=MemoryStore())
    message = str(excinfo.value)
    for missing in OAUTH_ENV_VARS:
        if missing == GOOGLE_CLIENT_ID:
            continue
        assert missing in message, f"{missing} not named in error: {message}"


@pytest.mark.parametrize(
    "base_url",
    ["http://assistant-mcp.example.com", "https://", "https:///foo", "assistant-mcp.example.com"],
)
def test_non_absolute_https_base_url_is_rejected(base_url):
    with pytest.raises(AuthConfigError, match=MCP_BASE_URL):
        create_auth_provider(
            env=complete_env() | {MCP_BASE_URL: base_url},
            storage_backend=MemoryStore(),
        )


def test_invalid_storage_key_fails_fast():
    env = complete_env() | {MCP_OAUTH_STORAGE_KEY: "not-a-fernet-key"}
    with pytest.raises(AuthConfigError, match=MCP_OAUTH_STORAGE_KEY):
        create_auth_provider(env=env, storage_backend=MemoryStore())


def test_complete_configuration_returns_google_provider():
    provider = create_auth_provider(env=complete_env(), storage_backend=MemoryStore())
    assert provider is not None
    assert str(provider.base_url).rstrip("/") == BASE_URL
    assert provider.required_scopes == [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
    ]


def test_factory_wires_allowlist_into_provider():
    provider = create_auth_provider(env=complete_env(), storage_backend=MemoryStore())
    assert isinstance(provider, AllowlistGoogleProvider)
    assert provider.allowed_emails == {
        "user@example.com",
        "other@example.com",
    }


class StubInnerVerifier(TokenVerifier):
    """Inner token verifier returning a fixed access token, no network."""

    def __init__(self, claims: dict[str, object]) -> None:
        super().__init__()
        self.claims = claims

    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(
            token=token,
            client_id="google-sub",
            scopes=["openid"],
            claims=dict(self.claims),
        )


class RejectingInnerVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        return None


async def test_allowlist_verifier_passes_allowlisted_email():
    inner = StubInnerVerifier({"email": "user@example.com"})
    verifier = AllowlistTokenVerifier(inner=inner, allowed_emails={"user@example.com"})
    result = await verifier.verify_token("token")
    assert result is not None
    assert result.claims["email"] == "user@example.com"


async def test_allowlist_verifier_rejects_other_email():
    inner = StubInnerVerifier({"email": "stranger@example.com"})
    verifier = AllowlistTokenVerifier(inner=inner, allowed_emails={"user@example.com"})
    assert await verifier.verify_token("token") is None


async def test_allowlist_verifier_matches_case_insensitively():
    inner = StubInnerVerifier({"email": "USER@Example.com"})
    verifier = AllowlistTokenVerifier(inner=inner, allowed_emails={"user@example.com"})
    assert await verifier.verify_token("token") is not None


async def test_allowlist_verifier_rejects_missing_email():
    inner = StubInnerVerifier({})
    verifier = AllowlistTokenVerifier(inner=inner, allowed_emails={"user@example.com"})
    assert await verifier.verify_token("token") is None


async def test_allowlist_verifier_passes_through_rejected_tokens():
    verifier = AllowlistTokenVerifier(
        inner=RejectingInnerVerifier(), allowed_emails={"user@example.com"}
    )
    assert await verifier.verify_token("token") is None


def _fernet(key: str) -> Fernet:
    return Fernet(key.encode())


async def test_storage_writes_ciphertext_to_backend():
    backend = MemoryStore()
    storage = build_client_storage(_fernet(FERNET_KEY), backend)
    await storage.put(
        "client-1",
        {"client_secret_token": "top-secret-token-material"},
        collection="mcp-oauth-proxy-clients",
    )
    raw = await backend.get("client-1", collection="mcp-oauth-proxy-clients")
    assert raw is not None
    assert "top-secret-token-material" not in json.dumps(raw)
    assert "__encrypted_data__" in raw


async def test_storage_state_survives_restart_on_shared_backend():
    backend = MemoryStore()
    first = build_client_storage(_fernet(FERNET_KEY), backend)
    second = build_client_storage(_fernet(FERNET_KEY), backend)
    await first.put(
        "client-1",
        {"client_secret_token": "top-secret-token-material"},
        collection="mcp-oauth-proxy-clients",
    )
    value = await second.get("client-1", collection="mcp-oauth-proxy-clients")
    assert value == {"client_secret_token": "top-secret-token-material"}


async def test_state_without_storage_key_is_unusable():
    backend = MemoryStore()
    original = build_client_storage(_fernet(FERNET_KEY), backend)
    rotated = build_client_storage(_fernet(Fernet.generate_key().decode()), backend)
    await original.put(
        "client-1",
        {"client_secret_token": "top-secret-token-material"},
        collection="mcp-oauth-proxy-clients",
    )
    assert await rotated.get("client-1", collection="mcp-oauth-proxy-clients") is None


class CountingStore(MemoryStore):
    """In-memory store that counts backend read and write operations."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.writes = 0

    async def get(self, key, *, collection=None):
        self.reads += 1
        return await super().get(key, collection=collection)

    async def ttl(self, key, *, collection=None):
        self.reads += 1
        return await super().ttl(key, collection=collection)

    async def put(self, key, value, *, collection=None, ttl=None):
        self.writes += 1
        return await super().put(key, value, collection=collection, ttl=ttl)


async def test_cache_serves_repeated_reads_with_one_backend_read():
    backend = CountingStore()
    cache = MemoryStore()
    storage = build_client_storage(_fernet(FERNET_KEY), backend, cache=cache)
    await storage.put(
        "client-1",
        {"client_secret_token": "top-secret-token-material"},
        collection="mcp-oauth-proxy-clients",
    )
    first = await storage.get("client-1", collection="mcp-oauth-proxy-clients")
    second = await storage.get("client-1", collection="mcp-oauth-proxy-clients")
    assert first == {"client_secret_token": "top-secret-token-material"}
    assert second == {"client_secret_token": "top-secret-token-material"}
    assert backend.reads <= 1
    assert backend.writes == 1


async def test_cache_write_persists_and_invalidates():
    backend = CountingStore()
    cache = MemoryStore()
    storage = build_client_storage(_fernet(FERNET_KEY), backend, cache=cache)
    await storage.put(
        "client-1",
        {"client_secret_token": "first-value"},
        collection="mcp-oauth-proxy-clients",
    )
    assert await storage.get("client-1", collection="mcp-oauth-proxy-clients") == {
        "client_secret_token": "first-value"
    }
    await storage.put(
        "client-1",
        {"client_secret_token": "second-value"},
        collection="mcp-oauth-proxy-clients",
    )
    assert await storage.get("client-1", collection="mcp-oauth-proxy-clients") == {
        "client_secret_token": "second-value"
    }
    assert backend.writes == 2


async def test_cache_holds_no_plaintext_token_material():
    backend = CountingStore()
    cache = MemoryStore()
    storage = build_client_storage(_fernet(FERNET_KEY), backend, cache=cache)
    await storage.put(
        "client-1",
        {"client_secret_token": "top-secret-token-material"},
        collection="mcp-oauth-proxy-clients",
    )
    await storage.get("client-1", collection="mcp-oauth-proxy-clients")
    cached = await cache.get("client-1", collection="mcp-oauth-proxy-clients")
    assert cached is not None
    assert "top-secret-token-material" not in json.dumps(cached)
    assert "__encrypted_data__" in cached


async def test_cache_entries_expire_within_oauth_cache_ttl():
    backend = CountingStore()
    cache = MemoryStore()
    storage = build_client_storage(_fernet(FERNET_KEY), backend, cache=cache)
    await storage.put(
        "client-1",
        {"client_secret_token": "top-secret-token-material"},
        collection="mcp-oauth-proxy-clients",
    )
    await storage.get("client-1", collection="mcp-oauth-proxy-clients")
    _, ttl = await cache.ttl("client-1", collection="mcp-oauth-proxy-clients")
    assert ttl is not None
    assert 0 < ttl <= OAUTH_CACHE_TTL_SECONDS
