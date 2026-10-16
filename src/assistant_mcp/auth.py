"""OAuth 2.1 authentication layer: environment-driven provider factory."""

import os
from collections.abc import Iterable, Mapping
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.providers.google import GoogleProvider
from google.cloud.firestore_v1.base_client import DEFAULT_DATABASE as FIRESTORE_DEFAULT_DATABASE
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.firestore import FirestoreStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from pydantic import AnyHttpUrl, ValidationError

GOOGLE_CLIENT_ID = "GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET = "GOOGLE_CLIENT_SECRET"
MCP_BASE_URL = "MCP_BASE_URL"
MCP_ALLOWED_EMAILS = "MCP_ALLOWED_EMAILS"
MCP_OAUTH_STORAGE_KEY = "MCP_OAUTH_STORAGE_KEY"

OAUTH_ENV_VARS = (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    MCP_BASE_URL,
    MCP_ALLOWED_EMAILS,
    MCP_OAUTH_STORAGE_KEY,
)


class AuthConfigError(RuntimeError):
    """Raised at startup when the OAuth configuration is incomplete or invalid."""


def build_client_storage(fernet: Fernet, backend: AsyncKeyValue | None = None) -> AsyncKeyValue:
    """Build the encrypted storage for the OAuth state.

    Values are encrypted with the given Fernet key before they reach the
    backend, so no plaintext token material is persisted. Decryption failures
    are treated as absent entries, so key rotation forces re-registration
    instead of failing hard. The default backend is Google Firestore's
    ``(default)`` database — its free tier does not apply to named databases —
    resolved through Application Default Credentials.
    """
    if backend is None:
        backend = FirestoreStore(database=FIRESTORE_DEFAULT_DATABASE)
    return FernetEncryptionWrapper(
        key_value=backend,
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


class AllowlistGoogleProvider(GoogleProvider):
    """Google provider whose internal token validator enforces the allowlist.

    ``GoogleProvider`` constructs its ``GoogleTokenVerifier`` internally with no
    injection point, so the verifier is wrapped after construction through the
    proxy's ``_token_validator`` attribute. Every path that validates an
    upstream Google token goes through that single validator.
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
    ) -> None:
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            required_scopes=required_scopes,
            client_storage=client_storage,
        )
        self.allowed_emails = frozenset(
            email.strip().lower() for email in allowed_emails if email.strip()
        )
        self._token_validator = AllowlistTokenVerifier(
            inner=self._token_validator, allowed_emails=self.allowed_emails
        )


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
    return AllowlistGoogleProvider(
        client_id=env_map[GOOGLE_CLIENT_ID].strip(),
        client_secret=env_map[GOOGLE_CLIENT_SECRET].strip(),
        base_url=base_url,
        required_scopes=["openid", "email"],
        client_storage=build_client_storage(fernet, storage_backend),
        allowed_emails=allowed_emails,
    )
