"""Tests for the shared-secret auth layer in assistant_mcp.auth."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

import pytest
from fastmcp.server.auth import TokenVerifier
from key_value.aio.stores.memory import MemoryStore

from assistant_mcp.auth import (
    AUTH_CACHE_TTL_SECONDS,
    MCP_SHARED_SECRET_AUTH,
    USER_COLLECTION,
    AuthConfigError,
    SharedSecretTokenVerifier,
    UserIndexEntry,
    UserRecord,
    build_user_index_store,
    build_user_record_store,
    create_token_verifier,
    secret_hash,
)


def test_activation_flag_absent_returns_no_verifier():
    assert create_token_verifier(env={}, backend=MemoryStore()) is None


@pytest.mark.parametrize("value", ["", "   "])
def test_activation_flag_blank_returns_no_verifier(value):
    env = {MCP_SHARED_SECRET_AUTH: value}
    assert create_token_verifier(env=env, backend=MemoryStore()) is None


@pytest.mark.parametrize("value", ["true", "TRUE", "True"])
def test_activation_flag_true_returns_verifier(value):
    env = {MCP_SHARED_SECRET_AUTH: value}
    verifier = create_token_verifier(env=env, backend=MemoryStore())
    assert isinstance(verifier, TokenVerifier)


@pytest.mark.parametrize("value", ["false", "yes", "1", "on"])
def test_activation_flag_invalid_value_fails_fast(value):
    env = {MCP_SHARED_SECRET_AUTH: value}
    with pytest.raises(AuthConfigError, match=MCP_SHARED_SECRET_AUTH):
        create_token_verifier(env=env, backend=MemoryStore())


async def test_activated_factory_returns_shared_secret_verifier():
    env = {MCP_SHARED_SECRET_AUTH: "true"}
    verifier = create_token_verifier(env=env, backend=MemoryStore())
    assert isinstance(verifier, SharedSecretTokenVerifier)


def test_auth_cache_ttl_is_bounded_short():
    assert AUTH_CACHE_TTL_SECONDS == 60


def _user_record() -> UserRecord:
    return UserRecord(
        user_id="alice",
        label="Alice",
        created_at=datetime.now(UTC),
    )


async def test_user_record_persists_identity_fields():
    backend = MemoryStore()
    store = build_user_record_store(backend=backend)
    record = _user_record()
    secret = "a-registered-test-secret"
    await store.put(key=secret_hash(secret), value=record)
    loaded = await store.get(key=secret_hash(secret))
    assert loaded == record
    assert loaded is not None and loaded.user_id == "alice"
    assert loaded.label == "Alice"
    assert loaded.created_at == record.created_at


async def test_document_key_is_sha256_of_the_secret():
    backend = MemoryStore()
    store = build_user_record_store(backend=backend)
    secret = "a-registered-test-secret"
    await store.put(key=secret_hash(secret), value=_user_record())
    keys = await backend.keys(collection=USER_COLLECTION)
    assert keys == [hashlib.sha256(secret.encode()).hexdigest()]
    assert secret not in keys


async def test_stored_record_holds_no_recoverable_secret_material():
    backend = MemoryStore()
    store = build_user_record_store(backend=backend)
    secret = "a-registered-test-secret"
    await store.put(key=secret_hash(secret), value=_user_record())
    raw = await backend.get(secret_hash(secret), collection=USER_COLLECTION)
    assert raw is not None
    serialized = json.dumps(raw)
    assert secret not in serialized
    assert set(raw) == {"user_id", "label", "created_at"}


async def test_cache_entries_expire_within_auth_cache_ttl():
    backend = MemoryStore()
    cache = MemoryStore()
    store = build_user_record_store(backend=backend, cache=cache)
    secret = "a-registered-test-secret"
    await store.put(key=secret_hash(secret), value=_user_record())
    await store.get(key=secret_hash(secret))
    _, ttl = await cache.ttl(secret_hash(secret), collection=USER_COLLECTION)
    assert ttl is not None
    assert 0 < ttl <= AUTH_CACHE_TTL_SECONDS


async def test_user_index_persists_current_secret_hash():
    backend = MemoryStore()
    store = build_user_index_store(backend=backend)
    digest = secret_hash("alice-secret")
    await store.put(key="alice", value=UserIndexEntry(secret_hash=digest))
    loaded = await store.get(key="alice")
    assert loaded == UserIndexEntry(secret_hash=digest)


async def test_registered_secret_is_accepted_with_user_identity():
    backend = MemoryStore()
    store = build_user_record_store(backend=backend)
    secret = "alice-secret"
    await store.put(
        key=secret_hash(secret),
        value=UserRecord(
            user_id="alice", label="Alice", created_at=datetime.now(UTC)
        ),
    )
    verifier = SharedSecretTokenVerifier(records=store)
    token = await verifier.verify_token(secret)
    assert token is not None
    assert token.client_id == "alice"
    assert token.claims["user_id"] == "alice"
    assert token.claims["label"] == "Alice"


async def test_unknown_secret_is_rejected():
    backend = MemoryStore()
    store = build_user_record_store(backend=backend)
    await store.put(
        key=secret_hash("alice-secret"),
        value=UserRecord(
            user_id="alice", label="Alice", created_at=datetime.now(UTC)
        ),
    )
    verifier = SharedSecretTokenVerifier(records=store)
    assert await verifier.verify_token("never-registered-secret") is None


async def test_empty_token_is_rejected():
    backend = MemoryStore()
    verifier = SharedSecretTokenVerifier(records=build_user_record_store(backend))
    assert await verifier.verify_token("") is None


async def test_deleted_record_stops_authorizing_after_cache_expiry():
    backend = MemoryStore()
    store = build_user_record_store(backend=backend, cache_ttl_seconds=1)
    secret = "alice-secret"
    await store.put(
        key=secret_hash(secret),
        value=UserRecord(
            user_id="alice", label="Alice", created_at=datetime.now(UTC)
        ),
    )
    verifier = SharedSecretTokenVerifier(records=store)
    assert await verifier.verify_token(secret) is not None
    await backend.delete(secret_hash(secret), collection=USER_COLLECTION)
    assert await verifier.verify_token(secret) is not None
    await asyncio.sleep(1.2)
    assert await verifier.verify_token(secret) is None
