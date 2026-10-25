"""Shared-secret bearer authentication: environment-driven verifier factory."""

import hashlib
import os
from collections.abc import Mapping
from datetime import datetime

from fastmcp.server.auth import AccessToken, TokenVerifier
from google.cloud.firestore_v1.base_client import DEFAULT_DATABASE as FIRESTORE_DEFAULT_DATABASE
from key_value.aio.adapters.pydantic import PydanticAdapter
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.firestore import FirestoreStore
from key_value.aio.stores.memory import MemoryStore
from key_value.aio.wrappers.passthrough_cache import PassthroughCacheWrapper
from pydantic import BaseModel

MCP_SHARED_SECRET_AUTH = "MCP_SHARED_SECRET_AUTH"

USER_COLLECTION = "mcp-users"
USER_INDEX_COLLECTION = "mcp-user-index"

AUTH_CACHE_TTL_SECONDS = 60


class AuthConfigError(RuntimeError):
    """Raised at startup when the auth configuration is invalid."""


def secret_hash(secret: str) -> str:
    """Return the hex SHA-256 digest used as the user record document key."""
    return hashlib.sha256(secret.encode()).hexdigest()


class UserRecord(BaseModel):
    """Registered user, stored keyed by the SHA-256 hash of their secret.

    Holds only the identity fields; the secret itself never reaches storage,
    so nothing in the record allows recovering usable credential material.
    """

    user_id: str
    label: str
    created_at: datetime


def build_user_record_store(
    backend: AsyncKeyValue | None = None,
    cache: AsyncKeyValue | None = None,
    cache_ttl_seconds: int = AUTH_CACHE_TTL_SECONDS,
) -> PydanticAdapter[UserRecord]:
    """Build the cached, hash-keyed store for the user records.

    Reads are served from an in-process passthrough cache while a cached
    entry has not expired (up to ``AUTH_CACHE_TTL_SECONDS``), bounding how
    long a deleted or replaced record keeps authorizing; writes invalidate
    the cached entry and persist to the backend. The default backend is
    Google Firestore's ``(default)`` database, resolved through Application
    Default Credentials. ``backend`` and ``cache`` override the persistence
    backend and the in-process cache store for tests;
    ``cache_ttl_seconds`` is a test seam for the cache expiry behavior.
    """
    if backend is None:
        backend = FirestoreStore(database=FIRESTORE_DEFAULT_DATABASE)
    if cache is None:
        cache = MemoryStore(max_entries_per_collection=1000)
    return PydanticAdapter[UserRecord](
        key_value=PassthroughCacheWrapper(
            primary_key_value=backend,
            cache_key_value=cache,
            maximum_ttl=cache_ttl_seconds,
            missing_ttl=cache_ttl_seconds,
        ),
        pydantic_model=UserRecord,
        default_collection=USER_COLLECTION,
        raise_on_validation_error=True,
    )


class UserIndexEntry(BaseModel):
    """Current secret hash for a user id, keyed by the user id.

    Lets the admin registration command find (and replace) a user's
    previous hash-keyed record, which keyed-only storage cannot enumerate.
    Written only by the registration command; verification never reads it.
    """

    secret_hash: str


def build_user_index_store(
    backend: AsyncKeyValue | None = None,
) -> PydanticAdapter[UserIndexEntry]:
    """Build the user-id-keyed index over the current secret hashes.

    The default backend is Google Firestore's ``(default)`` database,
    resolved through Application Default Credentials; ``backend`` overrides
    it for tests. No cache: the index is read and written only by the
    offline registration command, never on the request path.
    """
    if backend is None:
        backend = FirestoreStore(database=FIRESTORE_DEFAULT_DATABASE)
    return PydanticAdapter[UserIndexEntry](
        key_value=backend,
        pydantic_model=UserIndexEntry,
        default_collection=USER_INDEX_COLLECTION,
        raise_on_validation_error=True,
    )


class SharedSecretTokenVerifier(TokenVerifier):
    """Token verifier that grants access to holders of registered secrets.

    The presented bearer token is hashed; the hash is the document key of a
    registered user record, so a keyed lookup decides access. No secret
    material is ever compared or stored — only its one-way hash. A miss
    (unknown, revoked, or unregistered secret) yields ``None``, which the
    HTTP layer treats as an unauthenticated request.
    """

    def __init__(self, records: PydanticAdapter[UserRecord]) -> None:
        super().__init__()
        self.records = records

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return an access token for the user the presented secret belongs to."""
        if not token:
            return None
        record = await self.records.get(key=secret_hash(token))
        if record is None:
            return None
        return AccessToken(
            token=token,
            client_id=record.user_id,
            scopes=[],
            claims={"user_id": record.user_id, "label": record.label},
        )


def create_token_verifier(
    *,
    env: Mapping[str, str] | None = None,
    backend: AsyncKeyValue | None = None,
) -> TokenVerifier | None:
    """Build the shared-secret token verifier from the environment.

    Returns ``None`` when ``MCP_SHARED_SECRET_AUTH`` is unset or blank, in
    which case the service runs without authentication (the stdio transport
    never authenticates regardless). The value ``true`` (case-insensitive)
    activates shared-secret authentication; any other value raises an
    :class:`AuthConfigError` naming the variable. ``env`` overrides the
    environment and ``backend`` overrides the persistence backend for tests.
    """
    env_map = os.environ if env is None else env
    raw = env_map.get(MCP_SHARED_SECRET_AUTH, "").strip()
    if not raw:
        return None
    if raw.lower() != "true":
        raise AuthConfigError(
            f"{MCP_SHARED_SECRET_AUTH} must be 'true' to activate shared-secret "
            f"authentication, or absent to run without authentication; got {raw!r}."
        )
    return SharedSecretTokenVerifier(records=build_user_record_store(backend=backend))
