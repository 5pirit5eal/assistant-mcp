"""OAuth 2.1 authentication layer: environment-driven provider factory."""

import hashlib
import os
from collections.abc import Iterable, Mapping
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.utilities.auth import parse_scopes
from google.cloud.firestore_v1.base_client import DEFAULT_DATABASE as FIRESTORE_DEFAULT_DATABASE
from key_value.aio.adapters.pydantic import PydanticAdapter
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.firestore import FirestoreStore
from key_value.aio.stores.memory import MemoryStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from key_value.aio.wrappers.passthrough_cache import PassthroughCacheWrapper
from mcp.server.auth.provider import RefreshToken, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, BaseModel, ValidationError

GOOGLE_CLIENT_ID = "GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET = "GOOGLE_CLIENT_SECRET"
MCP_BASE_URL = "MCP_BASE_URL"
MCP_ALLOWED_EMAILS = "MCP_ALLOWED_EMAILS"
MCP_OAUTH_STORAGE_KEY = "MCP_OAUTH_STORAGE_KEY"
MCP_ACCESS_TOKEN_TTL_SECONDS = "MCP_ACCESS_TOKEN_TTL_SECONDS"
MCP_REFRESH_GRACE_SECONDS = "MCP_REFRESH_GRACE_SECONDS"

REFRESH_GRACE_COLLECTION = "mcp-refresh-grace"

OAUTH_CACHE_TTL_SECONDS = 300

DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 43200
DEFAULT_REFRESH_GRACE_SECONDS = 60

OAUTH_ENV_VARS = (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    MCP_BASE_URL,
    MCP_ALLOWED_EMAILS,
    MCP_OAUTH_STORAGE_KEY,
)


class AuthConfigError(RuntimeError):
    """Raised at startup when the OAuth configuration is incomplete or invalid."""


def _optional_positive_int_seconds(
    env_map: Mapping[str, str], name: str, default: int
) -> int:
    """Read an optional positive-integer-seconds environment variable.

    Returns ``default`` when the variable is absent or blank; present but
    non-integer or non-positive values raise an :class:`AuthConfigError`
    naming the variable, mirroring the fail-fast style of the required
    configuration.
    """
    value = env_map.get(name, "").strip()
    if not value:
        return default
    try:
        seconds = int(value)
    except ValueError as error:
        raise AuthConfigError(
            f"{name} must be a positive integer number of seconds, got {value!r}."
        ) from error
    if seconds <= 0:
        raise AuthConfigError(
            f"{name} must be a positive integer number of seconds, got {value!r}."
        )
    return seconds


def build_client_storage(
    fernet: Fernet,
    backend: AsyncKeyValue | None = None,
    cache: AsyncKeyValue | None = None,
) -> AsyncKeyValue:
    """Build the encrypted, cached storage for the OAuth state.

    Values are encrypted with the given Fernet key before they reach the
    cache or the backend, so neither ever holds plaintext token material.
    Reads are served from an in-process cache while a cached entry has not
    expired (up to ``OAUTH_CACHE_TTL_SECONDS``), to minimize database
    operations; writes invalidate the cached entry and persist to the
    backend. Decryption failures are treated as absent entries, so key
    rotation forces re-registration instead of failing hard. The default
    backend is Google Firestore's ``(default)`` database — its free tier
    does not apply to named databases — resolved through Application
    Default Credentials. ``backend`` and ``cache`` override the
    persistence backend and the in-process cache store for tests.
    """
    if backend is None:
        backend = FirestoreStore(database=FIRESTORE_DEFAULT_DATABASE)
    if cache is None:
        cache = MemoryStore(max_entries_per_collection=1000)
    return FernetEncryptionWrapper(
        key_value=PassthroughCacheWrapper(
            primary_key_value=backend,
            cache_key_value=cache,
            maximum_ttl=OAUTH_CACHE_TTL_SECONDS,
            missing_ttl=OAUTH_CACHE_TTL_SECONDS,
        ),
        fernet=fernet,
        raise_on_decryption_error=False,
    )


class AllowlistTokenVerifier(TokenVerifier):
    """Token verifier that grants access only to allowlisted Google accounts.

    Delegates verification to the wrapped inner verifier (Google's), then
    returns ``None`` unless the authenticated account's email is on the
    allowlist. Email matching is case-insensitive.
    """

    def __init__(self, *, inner: TokenVerifier, allowed_emails: Iterable[str]) -> None:
        super().__init__(required_scopes=inner.required_scopes)
        self.inner = inner
        self.allowed_emails = frozenset(
            email.strip().lower() for email in allowed_emails if email.strip()
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await self.inner.verify_token(token)
        if verified is None:
            return None
        email = str(verified.claims.get("email") or "").strip().lower()
        if email not in self.allowed_emails:
            return None
        return verified


class RefreshGraceEntry(BaseModel):
    """Token response a refresh issued, keyed by the consumed token's hash.

    Served idempotently to concurrent refreshes presenting the same consumed
    token within the grace period, so parallel client sessions converge on
    one token set instead of one of them being rejected.
    """

    client_id: str
    access_token: str
    expires_in: int
    refresh_token: str
    scope: str


def _presented_token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _grace_entry_to_token(entry: RefreshGraceEntry) -> OAuthToken:
    return OAuthToken(
        access_token=entry.access_token,
        token_type="Bearer",
        expires_in=entry.expires_in,
        refresh_token=entry.refresh_token,
        scope=entry.scope,
    )


class AllowlistGoogleProvider(GoogleProvider):
    """Google provider whose internal token validator enforces the allowlist.

    ``GoogleProvider`` constructs its ``GoogleTokenVerifier`` internally with no
    injection point, so the verifier is wrapped after construction through the
    proxy's ``_token_validator`` attribute. Every path that validates an
    upstream Google token goes through that single validator.

    Refresh-token rotation is one-time-use upstream: a concurrent refresh
    presenting an already-rotated token would be rejected with
    ``invalid_grant`` and force a browser re-authorization. To tolerate
    clients with parallel sessions, a consumed refresh token maps to the token
    response its rotation issued for a short grace period; further refreshes
    presenting that consumed token within the window receive the same
    response (idempotent replay). The mapping lives in the same encrypted
    OAuth state storage as the token records and expires with the grace
    period. Beyond the window, the upstream rejection is unchanged.
    """

    allowed_emails: frozenset[str]

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str | None,
        base_url: AnyHttpUrl | str,
        required_scopes: list[str] | None,
        client_storage: AsyncKeyValue | None,
        allowed_emails: Iterable[str],
        access_token_ttl_seconds: int,
        refresh_grace_seconds: int,
    ) -> None:
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            required_scopes=required_scopes,
            client_storage=client_storage,
            fastmcp_access_token_expiry_seconds=access_token_ttl_seconds,
        )
        self.allowed_emails = frozenset(
            email.strip().lower() for email in allowed_emails if email.strip()
        )
        self._token_validator = AllowlistTokenVerifier(
            inner=self._token_validator, allowed_emails=self.allowed_emails
        )
        self._refresh_grace_seconds = refresh_grace_seconds
        self._grace_store: PydanticAdapter[RefreshGraceEntry] = PydanticAdapter[
            RefreshGraceEntry
        ](
            key_value=self._client_storage,
            pydantic_model=RefreshGraceEntry,
            default_collection=REFRESH_GRACE_COLLECTION,
            raise_on_validation_error=True,
        )

    async def _grace_replay(
        self, client: OAuthClientInformationFull, token: str
    ) -> RefreshGraceEntry | None:
        """Return the grace entry for a consumed token of this client."""
        entry = await self._grace_store.get(key=_presented_token_key(token))
        if entry is not None and entry.client_id == client.client_id:
            return entry
        return None

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        """Load a refresh token, honoring the grace window for replay.

        A consumed token within its grace window is reconstructed from the
        grace entry so the token handler proceeds to the exchange, which
        replays the stored response. Beyond the window the upstream behavior
        (``None``, forcing re-authentication) is unchanged.
        """
        replay = await self._grace_replay(client, refresh_token)
        if replay is not None:
            return RefreshToken(
                token=refresh_token,
                client_id=replay.client_id,
                scopes=parse_scopes(replay.scope) or [],
                expires_at=None,
            )
        return await super().load_refresh_token(client, refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange a refresh token, replaying grace-window rotations.

        Within the grace window after a rotation, the same consumed token is
        answered with the stored token response instead of a second rotation,
        so concurrent refreshes converge on one token set. If the upstream
        exchange fails, the grace store is re-checked once before propagating
        the error: a refresh that raced past the grace check before the
        winning rotation wrote its entry still receives the replay. A grace
        entry is only written when the rotation issued a refresh token —
        without one there is nothing for concurrent refreshes to converge
        on, and persisting an incomplete response would replay it for the
        whole grace window.
        """
        replay = await self._grace_replay(client, refresh_token.token)
        if replay is not None:
            return _grace_entry_to_token(replay)
        try:
            issued = await super().exchange_refresh_token(
                client, refresh_token, scopes
            )
        except TokenError:
            replay = await self._grace_replay(client, refresh_token.token)
            if replay is not None:
                return _grace_entry_to_token(replay)
            raise
        if issued.refresh_token:
            await self._grace_store.put(
                key=_presented_token_key(refresh_token.token),
                value=RefreshGraceEntry(
                    client_id=client.client_id or "",
                    access_token=issued.access_token,
                    expires_in=issued.expires_in or 0,
                    refresh_token=issued.refresh_token,
                    scope=issued.scope or "",
                ),
                ttl=self._refresh_grace_seconds,
            )
        return issued


def create_auth_provider(
    *,
    env: Mapping[str, str] | None = None,
    storage_backend: AsyncKeyValue | None = None,
) -> GoogleProvider | None:
    """Build the OAuth 2.1 provider from the environment.

    Returns ``None`` when no OAuth configuration is present (the service runs
    without authentication). Any partial configuration raises an
    :class:`AuthConfigError` naming the missing variables.

    ``storage_backend`` overrides the persistence backend for tests; in
    production the OAuth state persists in Google Firestore.
    """
    env_map = os.environ if env is None else env
    present = [name for name in OAUTH_ENV_VARS if env_map.get(name, "").strip()]
    if not present:
        return None
    missing = [name for name in OAUTH_ENV_VARS if not env_map.get(name, "").strip()]
    if missing:
        raise AuthConfigError(
            f"Incomplete OAuth configuration, missing: {', '.join(missing)}. "
            f"Set all of {', '.join(OAUTH_ENV_VARS)} or none of them."
        )
    base_url = env_map[MCP_BASE_URL].strip()
    parsed = urlparse(base_url)
    try:
        AnyHttpUrl(base_url)
    except ValidationError as error:
        raise AuthConfigError(
            f"{MCP_BASE_URL} must be an absolute https:// URL, "
            f"got {base_url!r}: {error}"
        ) from error
    if parsed.scheme != "https" or not parsed.netloc:
        raise AuthConfigError(
            f"{MCP_BASE_URL} must be an absolute https:// URL, got {base_url!r}."
        )
    fernet_key = env_map[MCP_OAUTH_STORAGE_KEY].strip()
    try:
        fernet = Fernet(fernet_key.encode())
    except (TypeError, ValueError) as error:
        raise AuthConfigError(
            f"{MCP_OAUTH_STORAGE_KEY} is not a valid Fernet key: {error}"
        ) from error
    allowed_emails = env_map[MCP_ALLOWED_EMAILS].split(",")
    access_token_ttl_seconds = _optional_positive_int_seconds(
        env_map, MCP_ACCESS_TOKEN_TTL_SECONDS, DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    )
    refresh_grace_seconds = _optional_positive_int_seconds(
        env_map, MCP_REFRESH_GRACE_SECONDS, DEFAULT_REFRESH_GRACE_SECONDS
    )
    return AllowlistGoogleProvider(
        client_id=env_map[GOOGLE_CLIENT_ID].strip(),
        client_secret=env_map[GOOGLE_CLIENT_SECRET].strip(),
        base_url=base_url,
        required_scopes=["openid", "email"],
        client_storage=build_client_storage(fernet, storage_backend),
        allowed_emails=allowed_emails,
        access_token_ttl_seconds=access_token_ttl_seconds,
        refresh_grace_seconds=refresh_grace_seconds,
    )
