"""Nextcloud toolset: per-user image access on a Nextcloud via WebDAV."""

import asyncio
import io
import os
import xml.etree.ElementTree as ET
from collections.abc import Hashable, Mapping
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import unquote, urlparse

from cryptography.fernet import Fernet
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from key_value.aio.protocols import AsyncKeyValue
from mcp.types import ImageContent
from pydantic import BaseModel, ConfigDict, Field
from requests.exceptions import RequestException
from webdav3.client import Client as WebDavClient
from webdav3.exceptions import RemoteResourceNotFound, ResponseErrorCode, WebDavException
from webdav3.urn import Urn

from ..auth import MCP_OAUTH_STORAGE_KEY, build_client_storage

mcp = FastMCP("nextcloud")

NEXTCLOUD_WEBDAV_URL = "NEXTCLOUD_WEBDAV_URL"
NEXTCLOUD_USERNAME = "NEXTCLOUD_USERNAME"
NEXTCLOUD_APP_PASSWORD = "NEXTCLOUD_APP_PASSWORD"

NEXTCLOUD_ENV_VARS = (
    NEXTCLOUD_WEBDAV_URL,
    NEXTCLOUD_USERNAME,
    NEXTCLOUD_APP_PASSWORD,
)

NEXTCLOUD_CREDENTIALS_COLLECTION = "nextcloud-credentials"

NEXTCLOUD_DAV_SUFFIX = "/remote.php/dav"


class NextcloudCredentials(Hashable, BaseModel):
    """Nextcloud WebDAV credentials for one account.

    Hashable (frozen), so instances can serve as the cache key of the
    lru_cache-wrapped WebDAV client; ``build_webdav_client`` requires this.
    """

    model_config = ConfigDict(frozen=True)

    webdav_url: str
    username: str
    app_password: str

    def __hash__(self) -> int:
        return hash((type(self), self.webdav_url, self.username, self.app_password))


def build_credential_storage(
    fernet: Fernet,
    backend: AsyncKeyValue | None = None,
    cache: AsyncKeyValue | None = None,
) -> AsyncKeyValue:
    """Build the encrypted, cached storage for Nextcloud credentials.

    Credentials reuse the same storage stack as the OAuth state
    (``build_client_storage``): values are Fernet-encrypted before they reach
    the cache or the backend, reads are served from an in-process cache, and
    decryption failures are treated as absent entries. ``backend`` and
    ``cache`` override the persistence backend and in-process cache for tests.
    """
    return build_client_storage(fernet, backend, cache)


async def save_credentials(
    storage: AsyncKeyValue, identity_key: str, credentials: NextcloudCredentials
) -> None:
    """Persist ``credentials`` encrypted under ``identity_key``."""
    await storage.put(
        identity_key,
        credentials.model_dump(),
        collection=NEXTCLOUD_CREDENTIALS_COLLECTION,
    )


async def load_credentials(
    storage: AsyncKeyValue, identity_key: str
) -> NextcloudCredentials | None:
    """Load the credentials stored under ``identity_key``, if any."""
    raw = await storage.get(identity_key, collection=NEXTCLOUD_CREDENTIALS_COLLECTION)
    if raw is None:
        return None
    return NextcloudCredentials.model_validate(raw)


async def resolve_credentials(
    *,
    backend: AsyncKeyValue | None = None,
    env: Mapping[str, str] | None = None,
) -> NextcloudCredentials:
    """Resolve the caller's Nextcloud credentials.

    When the caller is authenticated, the credentials stored under the
    token's lowercased ``email`` claim are used and environment credentials
    are ignored. Otherwise the single-account credentials from the
    environment variables apply. No tool exposes a parameter that selects
    the storage key, so a caller can only ever reach their own credentials.
    ``backend`` and ``env`` override the persistence backend and the
    environment for tests.
    """
    env_map = os.environ if env is None else env
    identity = _caller_identity_key()
    if identity is not None:
        storage = build_credential_storage(_fernet_from_env(env_map), backend)
        stored = await load_credentials(storage, identity)
        if stored is None:
            raise ToolError(
                "no Nextcloud credentials are stored for your account; "
                "save them with the register_nextcloud_credentials tool first"
            )
        return stored
    present = [name for name in NEXTCLOUD_ENV_VARS if env_map.get(name, "").strip()]
    if not present:
        raise ToolError(
            "no Nextcloud credentials are available: authenticate and save them "
            "with the register_nextcloud_credentials tool, or configure the "
            f"single-account environment variables {', '.join(NEXTCLOUD_ENV_VARS)}"
        )
    missing = [name for name in NEXTCLOUD_ENV_VARS if not env_map.get(name, "").strip()]
    if missing:
        raise ToolError(
            f"incomplete Nextcloud configuration, missing: {', '.join(missing)}. "
            f"Set all of {', '.join(NEXTCLOUD_ENV_VARS)} or none of them."
        )
    return NextcloudCredentials(
        webdav_url=env_map[NEXTCLOUD_WEBDAV_URL].strip(),
        username=env_map[NEXTCLOUD_USERNAME].strip(),
        app_password=env_map[NEXTCLOUD_APP_PASSWORD].strip(),
    )


class SaveCredentialsResult(BaseModel):
    """Outcome of a register_nextcloud_credentials call."""

    saved: bool
    message: str


def credential_backend() -> AsyncKeyValue | None:
    """Persistence backend override for tests; production uses Firestore."""
    return None


def _dav_hostname(credentials: NextcloudCredentials) -> str:
    """Scheme and host of the Nextcloud, without any path."""
    parsed = urlparse(credentials.webdav_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _dav_root(credentials: NextcloudCredentials) -> str:
    """Path of the account's file root on the Nextcloud.

    A Nextcloud WebDAV URL ending in ``/remote.php/dav`` addresses the raw
    DAV namespace (which lists collections like ``files/`` and ``avatars/``,
    not the account's files), so the client root is remapped to
    ``/remote.php/dav/files/<username>``. Any other path is used verbatim,
    assuming it already addresses the account's file root.
    """
    parsed = urlparse(credentials.webdav_url)
    path = parsed.path.rstrip("/")
    if path.endswith(NEXTCLOUD_DAV_SUFFIX):
        path = f"{path}/files/{credentials.username}"
    return path


WEBDAV_CLIENT_CACHE_SIZE = 128


@lru_cache(maxsize=WEBDAV_CLIENT_CACHE_SIZE)
def build_webdav_client(credentials: NextcloudCredentials) -> WebDavClient:
    """Build a synchronous webdavclient3 client for the given credentials.

    ``credentials`` must be hashable — it is the lru_cache key — which the
    frozen ``NextcloudCredentials`` model guarantees by implementing
    ``Hashable``. Clients are cached with ``functools.lru_cache``
    (``WEBDAV_CLIENT_CACHE_SIZE`` entries), so the connection pool of the
    underlying requests session is reused instead of building a fresh
    client on every tool call; least-recently-used clients are evicted.
    The cache is keyed by the complete credentials, so a caller can never
    hit another account's client. Calls made with the client are still
    wrapped in ``asyncio.to_thread`` by the tools because webdavclient3 is
    synchronous and must not block the event loop. The client root is the
    account's file root, so '/' in a tool path means the account's own
    storage.
    """
    return WebDavClient(
        options={
            "webdav_hostname": _dav_hostname(credentials),
            "root": _dav_root(credentials),
            "webdav_login": credentials.username,
            "webdav_password": credentials.app_password,
        }
    )


def _fernet_from_env(env_map: Mapping[str, str]) -> Fernet:
    fernet_key = env_map.get(MCP_OAUTH_STORAGE_KEY, "").strip()
    if not fernet_key:
        raise ToolError(
            f"{MCP_OAUTH_STORAGE_KEY} is not configured, "
            "so stored Nextcloud credentials cannot be used"
        )
    try:
        return Fernet(fernet_key.encode())
    except (TypeError, ValueError) as error:
        raise ToolError(f"{MCP_OAUTH_STORAGE_KEY} is not a valid Fernet key") from error


def _caller_identity_key() -> str | None:
    """Identity key derived from the authenticated caller, or ``None``."""
    token = get_access_token()
    if token is None:
        return None
    email = str(token.claims.get("email") or "").strip().lower()
    if not email:
        raise ToolError(
            "the authenticated token carries no email claim, "
            "so Nextcloud credentials cannot be keyed to the account"
        )
    return email


@mcp.tool
async def register_nextcloud_credentials(
    webdav_url: Annotated[
        str,
        Field(
            description="WebDAV URL of the Nextcloud instance, "
            "e.g. the Hetzner Storage Share endpoint ending in /remote.php/dav.",
            examples=["https://nx123.your-storageshare.de/remote.php/dav"],
        ),
    ],
    username: Annotated[
        str,
        Field(
            description="Nextcloud username (or user ID) of the account.",
            examples=["ruben"],
        ),
    ],
    app_password: Annotated[
        str,
        Field(
            description="Nextcloud app password created under "
            "Settings → Security (or Personal → Security).",
            examples=["aBcDeFgHiJkLmNoPqRsTuV"],
        ),
    ],
) -> SaveCredentialsResult:
    """Validate Nextcloud WebDAV credentials and store them for the caller.

    The credentials are checked against the Nextcloud with a cheap WebDAV
    operation before anything is persisted: rejected credentials are not
    stored. Credentials are stored encrypted, keyed to the authenticated
    caller, so each user only ever reaches their own Nextcloud account. Only
    usable with an authenticated identity; the single-account environment
    credentials of the stdio transport need no saving.

    Returns:
        Whether the credentials were validated and saved, with a message.
    """
    identity = _caller_identity_key()
    if identity is None:
        raise ToolError(
            "register_nextcloud_credentials requires an authenticated identity; "
            "the single-account environment credentials need no saving"
        )
    credentials = NextcloudCredentials(
        webdav_url=webdav_url.strip(),
        username=username.strip(),
        app_password=app_password,
    )
    try:
        dav_client = build_webdav_client(credentials)
        await asyncio.to_thread(dav_client.check, "/")
    except (WebDavException, RequestException) as error:
        return SaveCredentialsResult(
            saved=False,
            message=f"credentials rejected by the Nextcloud at {credentials.webdav_url}: {error}",
        )
    storage = build_credential_storage(_fernet_from_env(os.environ), credential_backend())
    await save_credentials(storage, identity, credentials)
    return SaveCredentialsResult(
        saved=True,
        message=f"credentials validated and stored for {identity}",
    )


IMAGE_EXTENSIONS = (
    ".bmp",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
)


class FileEntry(BaseModel):
    """One entry of a Nextcloud folder listing with its WebDAV metadata."""

    name: str
    path: str
    is_folder: bool
    content_type: str | None = None
    size: int | None = None
    file_id: str | None = None
    last_modified: str | None = None
    permissions: str | None = None
    owner: str | None = None
    has_preview: bool = False


DAV_NS = "DAV:"
OWNCLOUD_NS = "http://owncloud.org/ns"
NEXTCLOUD_NS = "http://nextcloud.org/ns"

PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:" '
    'xmlns:oc="http://owncloud.org/ns" '
    'xmlns:nc="http://nextcloud.org/ns">'
    "<d:prop>"
    "<d:resourcetype/>"
    "<d:getcontentlength/>"
    "<d:getcontenttype/>"
    "<d:getlastmodified/>"
    "<oc:fileid/>"
    "<oc:size/>"
    "<oc:permissions/>"
    "<oc:owner-id/>"
    "<oc:owner-display-name/>"
    "<nc:has-preview/>"
    "</d:prop>"
    "</d:propfind>"
)


def _prop_text(prop: ET.Element, namespace: str, tag: str) -> str | None:
    """Text of a namespaced child element, or ``None`` when absent/empty."""
    element = prop.find(f"{{{namespace}}}{tag}")
    if element is None or element.text is None or not element.text.strip():
        return None
    return element.text.strip()


def parse_propfind_multistatus(
    xml: str | bytes, *, dav_root: str, listed_path: str
) -> list[FileEntry]:
    """Parse a multistatus PROPFIND response into metadata entries.

    Reads the extended Nextcloud properties (file id, size, permissions,
    owner, preview availability) that webdavclient3's ``list(get_info=True)``
    does not expose. The response for the listed collection itself is
    dropped; hrefs are URL-decoded and mapped to account-relative paths,
    and names come from path basenames (the live instance returns no
    ``displayname``). Unfound properties (404 propstat blocks) yield their
    model defaults.
    """
    root = ET.fromstring(xml)
    listed = _account_relative(listed_path, dav_root)
    entries: list[FileEntry] = []
    for response in root.findall(f"{{{DAV_NS}}}response"):
        href = unquote(_prop_text(response, DAV_NS, "href") or "")
        if not href:
            continue
        entry_path = _account_relative(href, dav_root)
        if entry_path == listed:
            continue
        props = response.findall(f"{{{DAV_NS}}}propstat/{{{DAV_NS}}}prop")

        def find(namespace: str, tag: str) -> str | None:
            for prop in props:
                value = _prop_text(prop, namespace, tag)
                if value is not None:
                    return value
            return None

        is_folder = any(
            prop.find(f"{{{DAV_NS}}}resourcetype/{{{DAV_NS}}}collection") is not None
            for prop in props
        )
        size_text = find(DAV_NS, "getcontentlength") or find(OWNCLOUD_NS, "size")
        entries.append(
            FileEntry(
                name=PurePosixPath(entry_path.rstrip("/")).name,
                path=entry_path,
                is_folder=is_folder,
                content_type=find(DAV_NS, "getcontenttype"),
                size=int(size_text) if size_text and size_text.isdigit() else None,
                file_id=find(OWNCLOUD_NS, "fileid"),
                last_modified=find(DAV_NS, "getlastmodified"),
                permissions=find(OWNCLOUD_NS, "permissions"),
                owner=find(OWNCLOUD_NS, "owner-display-name")
                or find(OWNCLOUD_NS, "owner-id"),
                has_preview=find(NEXTCLOUD_NS, "has-preview") in ("true", "1"),
            )
        )
    return entries


class ListImagesResult(BaseModel):
    """Structured part of a list_images call: the folder's metadata entries."""

    path: str
    entries: list[FileEntry]


def _is_image(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in IMAGE_EXTENSIONS


THUMBNAIL_SIZE = (256, 256)
NEXTCLOUD_PREVIEW_PATH = "/index.php/core/preview"


def fetch_thumbnail(dav_client: WebDavClient, file_id: str) -> Image | None:
    """Fetch the Nextcloud's server-side preview of a file as an ``Image``.

    Uses the core preview endpoint (the files-API thumbnail route is
    deprecated) over the cached client's requests session with the same
    basic auth, at the dimensions of ``THUMBNAIL_SIZE``. Returns ``None``
    when the preview is unavailable or the request fails, so a listing
    never breaks on a missing thumbnail; the caller then degrades the
    entry to one without a thumbnail.
    """
    url = f"{dav_client.webdav.hostname}{NEXTCLOUD_PREVIEW_PATH}"
    try:
        response = dav_client.session.request(
            method="GET",
            url=url,
            params={
                "fileId": file_id,
                "x": THUMBNAIL_SIZE[0],
                "y": THUMBNAIL_SIZE[1],
            },
            auth=(dav_client.webdav.login, dav_client.webdav.password),
            timeout=dav_client.timeout,
        )
    except RequestException:
        return None
    if response.status_code >= 400 or not response.content:
        return None
    content_type = (
        response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    )
    if not content_type.startswith("image/"):
        return None
    return Image(data=response.content, format=content_type.removeprefix("image/"))


def _webdav_error(error: Exception, path: str, kind: str) -> ToolError:
    if isinstance(error, RemoteResourceNotFound):
        return ToolError(f"{kind} not found on the Nextcloud: {path}")
    if isinstance(error, ResponseErrorCode) and error.code in (401, 403):
        return ToolError(
            f"the Nextcloud rejected the credentials for this request "
            f"(HTTP {error.code}); save them again with "
            f"register_nextcloud_credentials or update the single-account "
            f"environment configuration"
        )
    return ToolError(f"Nextcloud WebDAV error: {error}")


def _account_relative(raw_path: str, dav_root: str) -> str:
    """Map a raw server path to a path relative to the account's file root."""
    if raw_path.startswith(dav_root):
        raw_path = raw_path[len(dav_root) :]
    return "/" + raw_path.strip("/")


def _propfind_entries(
    dav_client: WebDavClient, path: str, dav_root: str
) -> list[FileEntry]:
    """List a folder via an extended PROPFIND on the cached client.

    webdavclient3's ``list(get_info=True)`` does not expose the Nextcloud
    properties the metadata listing needs, so the PROPFIND is issued
    directly through the client's ``execute_request``: same requests
    session, auth, and error mapping (404 raises ``RemoteResourceNotFound``,
    other 4xx raise ``ResponseErrorCode``). The default ``list`` header set
    already carries ``Depth: 1``.
    """
    urn = Urn(path, directory=True)
    response = dav_client.execute_request(
        action="list",
        path=urn.quote(),
        data=PROPFIND_BODY,
        headers_ext=["Content-Type: application/xml"],
    )
    return parse_propfind_multistatus(
        response.content, dav_root=dav_root, listed_path=path
    )


@mcp.tool
async def list_images(
    path: Annotated[
        str,
        Field(
            description="Absolute path of the Nextcloud folder to list; '/' lists the root.",
            examples=["/photos", "/"],
        ),
    ],
) -> ToolResult:
    """List the images of a folder on the caller's Nextcloud with metadata.

    Each entry carries the file's WebDAV metadata: name, path, content
    type, size, file id, last-modified date, permissions, and owner.
    For every image file whose preview can be fetched, a thumbnail is
    included as an image content block in the same result; the k-th
    thumbnail belongs to the k-th entry with ``has_preview`` true. An
    entry's ``has_preview`` reports the delivered result: it is false when
    the Nextcloud has no preview, the preview request fails, or the entry
    carries no file id — a missing or failed preview never fails the
    listing. Only image files are returned, plus every subfolder
    (subfolders may hold more images).
    Files reachable through shares mounted into the account are listed
    like files of the user's own storage. The caller's credentials are
    resolved from their authenticated identity (or the single-account
    environment configuration on stdio). Paths are relative to the
    account's own storage, so they can be passed straight to download_image.

    Returns:
        The folder's metadata entries and thumbnails for the images.
    """
    credentials = await resolve_credentials(backend=credential_backend())
    dav_client = build_webdav_client(credentials)
    try:
        entries = await asyncio.to_thread(
            _propfind_entries, dav_client, path, _dav_root(credentials)
        )
    except (WebDavException, RequestException) as error:
        raise _webdav_error(error, path, "path") from error
    entries = [
        entry for entry in entries if entry.is_folder or _is_image(entry.path)
    ]
    fetch_targets: list[tuple[FileEntry, str]] = []
    for entry in entries:
        file_id = entry.file_id
        if not entry.is_folder and file_id and entry.has_preview:
            fetch_targets.append((entry, file_id))
    images = await asyncio.gather(
        *(
            asyncio.to_thread(fetch_thumbnail, dav_client, file_id)
            for _entry, file_id in fetch_targets
        )
    )
    thumbnails_by_path = {
        entry.path: image
        for (entry, _file_id), image in zip(fetch_targets, images)
        if image is not None
    }
    thumbnails: list[ImageContent] = []
    for entry in entries:
        image = thumbnails_by_path.get(entry.path)
        if image is None:
            entry.has_preview = False
            continue
        thumbnails.append(image.to_image_content())
    return ToolResult(
        content=thumbnails,
        structured_content=ListImagesResult(path=path, entries=entries).model_dump(),
    )


@mcp.tool
async def download_image(
    path: Annotated[
        str,
        Field(
            description="Absolute path of the image file to download, as returned by list_images.",
            examples=["/photos/cat.jpg"],
        ),
    ],
) -> Image:
    """Download an image file from the caller's Nextcloud.

    The image is returned unmodified, as image content with the image's
    media type, so the caller can view it. The caller's credentials are
    resolved from their authenticated identity (or the single-account
    environment configuration on stdio).

    Returns:
        The downloaded image, unmodified.
    """
    credentials = await resolve_credentials(backend=credential_backend())
    dav_client = build_webdav_client(credentials)
    buffer = io.BytesIO()
    try:
        await asyncio.to_thread(dav_client.download_from, buffer, path)
    except (WebDavException, RequestException) as error:
        raise _webdav_error(error, path, "file") from error
    data = buffer.getvalue()
    if not data:
        raise ToolError(f"the Nextcloud returned no content for: {path}")
    format = PurePosixPath(path).suffix.lstrip(".").lower()
    if not format:
        raise ToolError(f"cannot determine the media type of: {path}")
    return Image(data=data, format=format)
