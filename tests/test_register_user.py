"""Tests for the shared-secret user registration script."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from key_value.aio.stores.memory import MemoryStore

from assistant_mcp.auth import (
    USER_COLLECTION,
    SharedSecretTokenVerifier,
    UserIndexEntry,
    build_user_index_store,
    build_user_record_store,
    secret_hash,
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "register_user.py"


def load_script() -> ModuleType:
    """Import scripts/register_user.py from its repo-rooted path."""
    spec = importlib.util.spec_from_file_location("register_user_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_new_registration_persists_record_and_prints_secret_once(capsys):
    script = load_script()
    backend = MemoryStore()
    secret = await script.main(["--user-id", "alice"], backend=backend)
    assert secret

    output = capsys.readouterr().out
    assert output.count(secret) == 1
    assert "cannot be displayed again" in output.lower()

    records = build_user_record_store(backend=backend)
    record = await records.get(key=secret_hash(secret))
    assert record is not None
    assert record.user_id == "alice"
    assert record.label == "alice"

    index = build_user_index_store(backend=backend)
    assert await index.get(key="alice") == UserIndexEntry(secret_hash=secret_hash(secret))

    verifier = SharedSecretTokenVerifier(records=build_user_record_store(backend=backend))
    token = await verifier.verify_token(secret)
    assert token is not None
    assert token.claims["user_id"] == "alice"


async def test_new_registration_with_label_persists_the_label(capsys):
    script = load_script()
    backend = MemoryStore()
    await script.main(
        ["--user-id", "alice", "--label", "Alice Doe"], backend=backend
    )
    capsys.readouterr()
    records = build_user_record_store(backend=backend)
    record = await records.get(key=await _current_hash(backend, "alice"))
    assert record is not None
    assert record.label == "Alice Doe"


async def _current_hash(backend: MemoryStore, user_id: str) -> str:
    index = build_user_index_store(backend=backend)
    entry = await index.get(key=user_id)
    assert entry is not None
    return entry.secret_hash


async def test_registration_persists_no_recoverable_secret_material(capsys):
    script = load_script()
    backend = MemoryStore()
    secret = await script.main(["--user-id", "alice"], backend=backend)
    capsys.readouterr()

    raw = await backend.get(secret_hash(secret), collection=USER_COLLECTION)
    assert raw is not None
    serialized = json.dumps(raw)
    assert secret not in serialized
    assert set(raw) == {"user_id", "label", "created_at"}
    assert all(secret not in str(value) for value in raw.values())


async def test_re_registration_replaces_the_previous_secret(capsys):
    script = load_script()
    backend = MemoryStore()
    old_secret = await script.main(["--user-id", "alice"], backend=backend)
    capsys.readouterr()
    new_secret = await script.main(
        ["--user-id", "alice", "--label", "Alice 2"], backend=backend
    )
    output = capsys.readouterr().out
    assert new_secret != old_secret
    assert output.count(new_secret) == 1
    assert old_secret not in output

    assert await backend.get(secret_hash(old_secret), collection=USER_COLLECTION) is None
    assert await backend.get(secret_hash(new_secret), collection=USER_COLLECTION) is not None

    index = build_user_index_store(backend=backend)
    assert await index.get(key="alice") == UserIndexEntry(
        secret_hash=secret_hash(new_secret)
    )

    fresh_records = build_user_record_store(backend=backend)
    verifier = SharedSecretTokenVerifier(records=fresh_records)
    assert await verifier.verify_token(old_secret) is None
    token = await verifier.verify_token(new_secret)
    assert token is not None
    assert token.claims["user_id"] == "alice"
