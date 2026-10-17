"""Tests for the nextcloud toolset: storage, resolution, and tools."""

import asyncio
import base64
import json
import socket
import threading
import time
from collections.abc import Hashable
from types import SimpleNamespace

import pytest
import uvicorn
from cryptography.fernet import Fernet
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.utilities.types import Image
from key_value.aio.stores.memory import MemoryStore
from requests.exceptions import RequestException
from webdav3.exceptions import RemoteResourceNotFound, ResponseErrorCode

from assistant_mcp.auth import MCP_OAUTH_STORAGE_KEY
from assistant_mcp.server import build_server
from assistant_mcp.toolsets import ToolsetConfigError, nextcloud, validate_env_config
from assistant_mcp.toolsets.nextcloud import (
    NEXTCLOUD_APP_PASSWORD,
    NEXTCLOUD_CREDENTIALS_COLLECTION,
    NEXTCLOUD_USERNAME,
    NEXTCLOUD_WEBDAV_URL,
    NextcloudCredentials,
    build_credential_storage,
    build_webdav_client,
    load_credentials,
    resolve_credentials,
    save_credentials,
)

FERNET_KEY = Fernet.generate_key().decode()
WEBDAV_URL = "https://nx.example.com/remote.php/dav"
ENV_USERNAME = "env-user"
ENV_APP_PASSWORD = "env-app-password"


def _env_credentials() -> dict[str, str]:
    return {
        NEXTCLOUD_WEBDAV_URL: WEBDAV_URL,
        NEXTCLOUD_USERNAME: ENV_USERNAME,
        NEXTCLOUD_APP_PASSWORD: ENV_APP_PASSWORD,
    }


def _token(email: str) -> AccessToken:
    return AccessToken(
        token="token", client_id="client-id", scopes=["openid"], claims={"email": email}
    )


class _FixedTokenProvider:
    """Sync stand-in for get_access_token returning a fixed token."""

    def __init__(self, token: AccessToken | None) -> None:
        self.token = token

    def __call__(self) -> AccessToken | None:
        return self.token


def _authenticate_as(monkeypatch: pytest.MonkeyPatch, email: str) -> None:
    monkeypatch.setattr(nextcloud, "get_access_token", _FixedTokenProvider(_token(email)))


def _unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nextcloud, "get_access_token", _FixedTokenProvider(None))


def _storage_env() -> dict[str, str]:
    return {MCP_OAUTH_STORAGE_KEY: FERNET_KEY}


def _fernet() -> Fernet:
    return Fernet(FERNET_KEY.encode())


def _credentials(username: str) -> NextcloudCredentials:
    return NextcloudCredentials(
        webdav_url=WEBDAV_URL,
        username=username,
        app_password=f"app-password-{username}",
    )


async def test_credentials_are_stored_encrypted():
    backend = MemoryStore()
    storage = build_credential_storage(_fernet(), backend=backend)
    await save_credentials(storage, "user@example.com", _credentials("nextcloud-user"))
    raw = await backend.get(
        "user@example.com", collection=NEXTCLOUD_CREDENTIALS_COLLECTION
    )
    assert raw is not None
    payload = json.dumps(raw)
    assert "app-password-nextcloud-user" not in payload
    assert "nextcloud-user" not in payload
    assert "__encrypted_data__" in raw


async def test_stored_credentials_round_trip():
    backend = MemoryStore()
    storage = build_credential_storage(_fernet(), backend=backend)
    credentials = _credentials("nextcloud-user")
    await save_credentials(storage, "user@example.com", credentials)
    loaded = await load_credentials(storage, "user@example.com")
    assert loaded == credentials


async def test_no_credentials_stored_returns_none():
    storage = build_credential_storage(_fernet(), backend=MemoryStore())
    assert await load_credentials(storage, "user@example.com") is None


async def test_other_users_credentials_not_readable():
    backend = MemoryStore()
    storage = build_credential_storage(_fernet(), backend=backend)
    await save_credentials(storage, "alice@example.com", _credentials("alice-user"))
    await save_credentials(storage, "bob@example.com", _credentials("bob-user"))
    alice = await load_credentials(storage, "alice@example.com")
    bob = await load_credentials(storage, "bob@example.com")
    assert alice is not None and bob is not None
    assert alice.username == "alice-user"
    assert bob.username == "bob-user"


async def test_user_can_overwrite_own_credentials():
    backend = MemoryStore()
    storage = build_credential_storage(_fernet(), backend=backend)
    await save_credentials(storage, "user@example.com", _credentials("first-user"))
    await save_credentials(storage, "user@example.com", _credentials("second-user"))
    loaded = await load_credentials(storage, "user@example.com")
    assert loaded is not None
    assert loaded.username == "second-user"


async def test_credentials_survive_storage_rebuild_on_shared_backend():
    backend = MemoryStore()
    first = build_credential_storage(_fernet(), backend=backend)
    await save_credentials(first, "user@example.com", _credentials("nextcloud-user"))
    second = build_credential_storage(_fernet(), backend=backend)
    loaded = await load_credentials(second, "user@example.com")
    assert loaded == _credentials("nextcloud-user")


async def test_credentials_use_a_collection_separate_from_oauth_state():
    assert NEXTCLOUD_CREDENTIALS_COLLECTION != "mcp-oauth-proxy-clients"


async def test_authenticated_identity_keys_stored_credentials(monkeypatch):
    backend = MemoryStore()
    storage = build_credential_storage(_fernet(), backend=backend)
    await save_credentials(storage, "user@example.com", _credentials("nextcloud-user"))
    _authenticate_as(monkeypatch, "user@example.com")
    resolved = await resolve_credentials(env=_storage_env(), backend=backend)
    assert resolved == _credentials("nextcloud-user")


async def test_token_email_claim_is_lowercased_for_the_key(monkeypatch):
    backend = MemoryStore()
    storage = build_credential_storage(_fernet(), backend=backend)
    await save_credentials(storage, "user@example.com", _credentials("nextcloud-user"))
    _authenticate_as(monkeypatch, "USER@Example.com")
    resolved = await resolve_credentials(env=_storage_env(), backend=backend)
    assert resolved == _credentials("nextcloud-user")


async def test_unauthenticated_uses_environment_credentials(monkeypatch):
    _unauthenticated(monkeypatch)
    resolved = await resolve_credentials(env=_env_credentials(), backend=MemoryStore())
    assert resolved == NextcloudCredentials(
        webdav_url=WEBDAV_URL, username=ENV_USERNAME, app_password=ENV_APP_PASSWORD
    )


async def test_environment_credentials_are_ignored_when_authenticated(monkeypatch):
    backend = MemoryStore()
    storage = build_credential_storage(_fernet(), backend=backend)
    await save_credentials(storage, "user@example.com", _credentials("stored-user"))
    _authenticate_as(monkeypatch, "user@example.com")
    resolved = await resolve_credentials(
        env=_storage_env() | _env_credentials(), backend=backend
    )
    assert resolved == _credentials("stored-user")


async def test_partial_environment_configuration_yields_clear_error(monkeypatch):
    _unauthenticated(monkeypatch)
    partial = {NEXTCLOUD_WEBDAV_URL: WEBDAV_URL}
    with pytest.raises(ToolError) as excinfo:
        await resolve_credentials(env=partial, backend=MemoryStore())
    message = str(excinfo.value)
    assert NEXTCLOUD_USERNAME in message
    assert NEXTCLOUD_APP_PASSWORD in message


async def test_unauthenticated_without_env_credentials_yields_clear_error(monkeypatch):
    _unauthenticated(monkeypatch)
    with pytest.raises(ToolError) as excinfo:
        await resolve_credentials(env={}, backend=MemoryStore())
    message = str(excinfo.value)
    assert "credentials" in message.lower()
    assert NEXTCLOUD_WEBDAV_URL in message
    assert NEXTCLOUD_USERNAME in message
    assert NEXTCLOUD_APP_PASSWORD in message


async def test_authenticated_without_stored_credentials_yields_clear_error(monkeypatch):
    _authenticate_as(monkeypatch, "user@example.com")
    with pytest.raises(ToolError) as excinfo:
        await resolve_credentials(env=_storage_env(), backend=MemoryStore())
    assert "save" in str(excinfo.value).lower()


async def test_authenticated_without_storage_key_yields_clear_error(monkeypatch):
    _authenticate_as(monkeypatch, "user@example.com")
    with pytest.raises(ToolError, match=MCP_OAUTH_STORAGE_KEY):
        await resolve_credentials(env={}, backend=MemoryStore())


class FakeWebDavClient:
    """In-memory WebDAV client stand-in covering the used surface."""

    def __init__(
        self,
        *,
        files: dict[str, bytes] | None = None,
        error: Exception | None = None,
        propfind_xml: str | None = None,
    ) -> None:
        self.files = files or {}
        self.error = error
        self.propfind_xml = propfind_xml
        self.checked_paths: list[str] = []
        self.listed_paths: list[str] = []
        self.downloaded_paths: list[str] = []
        self.last_credentials: NextcloudCredentials | None = None

    def check(self, remote_path: str = "/") -> bool:
        self.checked_paths.append(remote_path)
        if self.error is not None:
            raise self.error
        return True

    def execute_request(self, action, path, data=None, headers_ext=None):
        self.listed_paths.append(path)
        if self.error is not None:
            raise self.error
        if self.propfind_xml is None:
            raise AssertionError("no PROPFIND XML configured on the fake client")
        return SimpleNamespace(content=self.propfind_xml)

    def download_from(self, buff, remote_path: str) -> None:
        self.downloaded_paths.append(remote_path)
        if self.error is not None:
            raise self.error
        buff.write(self.files[remote_path])

    def record(self, credentials: NextcloudCredentials) -> FakeWebDavClient:
        self.last_credentials = credentials
        return self


def _mount_tool_seams(monkeypatch, backend, *, email=None, dav=None):
    """Point the toolset's identity, storage, and WebDAV seams at fakes."""
    monkeypatch.setattr(nextcloud, "credential_backend", lambda: backend)
    monkeypatch.setenv(MCP_OAUTH_STORAGE_KEY, FERNET_KEY)
    if email is None:
        _unauthenticated(monkeypatch)
    else:
        _authenticate_as(monkeypatch, email)
    if dav is not None:
        monkeypatch.setattr(nextcloud, "build_webdav_client", dav.record)

SAVE_ARGS = {
    "webdav_url": WEBDAV_URL,
    "username": "nextcloud-user",
    "app_password": "app-password-nextcloud-user",
}


async def test_save_valid_credentials_are_stored_under_caller_identity(monkeypatch):
    backend = MemoryStore()
    dav = FakeWebDavClient()
    _mount_tool_seams(monkeypatch, backend, email="user@example.com", dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool("register_nextcloud_credentials", SAVE_ARGS)
    assert not result.is_error, result.content[0].text
    assert result.data.saved is True
    storage = build_credential_storage(_fernet(), backend=backend)
    stored = await load_credentials(storage, "user@example.com")
    assert stored == _credentials("nextcloud-user")


async def test_save_validates_with_the_given_credentials_first(monkeypatch):
    backend = MemoryStore()
    dav = FakeWebDavClient()
    _mount_tool_seams(monkeypatch, backend, email="user@example.com", dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool("register_nextcloud_credentials", SAVE_ARGS)
    assert not result.is_error
    assert dav.checked_paths == ["/"]
    assert dav.last_credentials == _credentials("nextcloud-user")


async def test_save_invalid_credentials_are_not_stored_and_report_failure(monkeypatch):
    backend = MemoryStore()
    rejecting = FakeWebDavClient(
        error=ResponseErrorCode(WEBDAV_URL, 401, "Unauthorized")
    )
    _mount_tool_seams(monkeypatch, backend, email="user@example.com", dav=rejecting)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool("register_nextcloud_credentials", SAVE_ARGS)
    assert not result.is_error
    assert result.data.saved is False
    storage = build_credential_storage(_fernet(), backend=backend)
    assert await load_credentials(storage, "user@example.com") is None


async def test_save_without_authenticated_identity_yields_clear_error(monkeypatch):
    backend = MemoryStore()
    dav = FakeWebDavClient()
    _mount_tool_seams(monkeypatch, backend, email=None, dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool(
            "register_nextcloud_credentials", SAVE_ARGS, raise_on_error=False
        )
    assert result.is_error
    assert "authenticate" in result.content[0].text.lower()
    storage = build_credential_storage(_fernet(), backend=backend)
    assert await load_credentials(storage, "user@example.com") is None


IMAGE_BYTES = b"\xff\xd8\xff\xe0 fake jpeg bytes"
def _thumbnail_bytes(file_id: str) -> bytes:
    return f"thumbnail-{file_id}".encode()


class _FakePreviewFetcher:
    """Stand-in for ``nextcloud.fetch_thumbnail``.

    Returns per-file-id data, so tests can assert which entry a thumbnail
    belongs to (the order-correlation invariant is falsifiable).
    """

    def __init__(self, *, fail_ids: tuple[str, ...] = ()) -> None:
        self.fail_ids = fail_ids
        self.fetched_ids: list[str] = []

    def __call__(self, dav_client, file_id: str) -> Image | None:
        self.fetched_ids.append(file_id)
        if file_id in self.fail_ids:
            return None
        return Image(data=_thumbnail_bytes(file_id), format="png")


DAV_ROOT = "/remote.php/dav/files/nextcloud-user"


async def _seed_and_mount(monkeypatch, *, email="user@example.com", dav=None):
    backend = MemoryStore()
    storage = build_credential_storage(_fernet(), backend=backend)
    await save_credentials(storage, email, _credentials("nextcloud-user"))
    _mount_tool_seams(monkeypatch, backend, email=email, dav=dav)
    return backend


async def test_list_images_returns_metadata_and_thumbnails(monkeypatch):
    dav = FakeWebDavClient(propfind_xml=_multistatus_xml())
    fetcher = _FakePreviewFetcher()
    monkeypatch.setattr(nextcloud, "fetch_thumbnail", fetcher)
    await _seed_and_mount(monkeypatch, dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool("list_images", {"path": "/photos"})
    assert not result.is_error, result.content[0].text
    entries = result.structured_content["entries"]
    by_name = {entry["name"]: entry for entry in entries}
    assert set(by_name) == {"subfolder", "cat.jpg", "süden.png", "beach.png", "noid.png"}
    cat = by_name["cat.jpg"]
    assert cat["is_folder"] is False
    assert cat["path"] == "/photos/cat.jpg"
    assert cat["file_id"] == "42"
    assert cat["size"] == 1234
    assert cat["content_type"] == "image/jpeg"
    assert cat["last_modified"] == "Sat, 04 Oct 2025 12:34:56 GMT"
    assert cat["permissions"] == "RGDNVW"
    assert cat["owner"] == "Nextcloud User"
    assert by_name["subfolder"]["is_folder"] is True
    assert by_name["beach.png"]["path"] == "/photos/mounted-share/beach.png"
    assert by_name["noid.png"]["file_id"] is None
    assert by_name["noid.png"]["has_preview"] is False
    with_preview = [entry for entry in entries if entry["has_preview"]]
    assert [entry["name"] for entry in with_preview] == ["cat.jpg", "beach.png"]
    image_blocks = [block for block in result.content if block.type == "image"]
    assert len(image_blocks) == len(with_preview)
    for block, entry in zip(image_blocks, with_preview):
        assert block.mime_type == "image/png"
        assert base64.b64decode(block.data) == _thumbnail_bytes(entry["file_id"])
    # fetches run concurrently; the delivered order is pinned by the zip above
    assert set(fetcher.fetched_ids) == {"42", "45"}


def test_thumbnail_size_is_256x256():
    assert nextcloud.THUMBNAIL_SIZE == (256, 256)


class _FakeSessionClient:
    """Minimal webdavclient3 client stand-in for ``fetch_thumbnail``."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = b"fake png bytes",
        content_type: str = "image/png",
        error: Exception | None = None,
    ) -> None:
        self.webdav = SimpleNamespace(
            hostname="https://nx.example.com",
            login="nextcloud-user",
            password="app-password-nextcloud-user",
        )
        self.timeout = 30
        self.error = error
        self.response = SimpleNamespace(
            status_code=status_code,
            content=content,
            headers={"Content-Type": content_type},
        )
        self.requests: list[dict] = []

    @property
    def session(self) -> object:
        client = self

        class _Session:
            def request(self, **kwargs):
                client.requests.append(kwargs)
                if client.error is not None:
                    raise client.error
                return client.response

        return _Session()


def test_fetch_thumbnail_requests_the_core_preview_endpoint():
    dav = _FakeSessionClient()
    image = nextcloud.fetch_thumbnail(dav, "42")
    assert image is not None
    request = dav.requests[0]
    assert request["method"] == "GET"
    assert request["url"] == "https://nx.example.com/index.php/core/preview"
    assert request["params"] == {"fileId": "42", "x": 256, "y": 256}
    assert request["auth"] == ("nextcloud-user", "app-password-nextcloud-user")
    content = image.to_image_content()
    assert content.mime_type == "image/png"
    assert base64.b64decode(content.data) == b"fake png bytes"


def test_fetch_thumbnail_degrades_on_request_error():
    dav = _FakeSessionClient(error=RequestException("boom"))
    assert nextcloud.fetch_thumbnail(dav, "42") is None


def test_fetch_thumbnail_degrades_on_http_error():
    dav = _FakeSessionClient(status_code=404, content=b"", content_type="")
    assert nextcloud.fetch_thumbnail(dav, "42") is None


def test_fetch_thumbnail_degrades_on_empty_content():
    dav = _FakeSessionClient(content=b"")
    assert nextcloud.fetch_thumbnail(dav, "42") is None


def test_fetch_thumbnail_degrades_on_non_image_content_type():
    dav = _FakeSessionClient(content=b"<html/>", content_type="text/html")
    assert nextcloud.fetch_thumbnail(dav, "42") is None


async def test_list_images_degrades_when_a_preview_fetch_fails(monkeypatch):
    dav = FakeWebDavClient(propfind_xml=_multistatus_xml())
    fetcher = _FakePreviewFetcher(fail_ids=("45",))
    monkeypatch.setattr(nextcloud, "fetch_thumbnail", fetcher)
    await _seed_and_mount(monkeypatch, dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool("list_images", {"path": "/photos"})
    assert not result.is_error, result.content[0].text
    entries = result.structured_content["entries"]
    by_name = {entry["name"]: entry for entry in entries}
    assert set(by_name) == {"subfolder", "cat.jpg", "süden.png", "beach.png", "noid.png"}
    assert by_name["cat.jpg"]["has_preview"] is True
    assert by_name["beach.png"]["has_preview"] is False
    assert by_name["noid.png"]["has_preview"] is False
    image_blocks = [block for block in result.content if block.type == "image"]
    assert len(image_blocks) == 1
    assert base64.b64decode(image_blocks[0].data) == _thumbnail_bytes("42")


async def test_list_images_skips_thumbnails_for_files_without_preview(monkeypatch):
    dav = FakeWebDavClient(propfind_xml=_multistatus_xml())
    fetcher = _FakePreviewFetcher(fail_ids=("42", "45"))
    monkeypatch.setattr(nextcloud, "fetch_thumbnail", fetcher)
    await _seed_and_mount(monkeypatch, dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool("list_images", {"path": "/photos"})
    assert not result.is_error, result.content[0].text
    entries = result.structured_content["entries"]
    assert {entry["name"] for entry in entries} == {
        "subfolder",
        "cat.jpg",
        "süden.png",
        "beach.png",
        "noid.png",
    }
    assert all(entry["has_preview"] is False for entry in entries)
    assert set(fetcher.fetched_ids) == {"42", "45"}


async def test_list_images_lists_the_requested_path(monkeypatch):
    dav = FakeWebDavClient(propfind_xml=_multistatus_xml())
    monkeypatch.setattr(nextcloud, "fetch_thumbnail", _FakePreviewFetcher())
    await _seed_and_mount(monkeypatch, dav=dav)
    async with Client(nextcloud.mcp) as client:
        await client.call_tool("list_images", {"path": "/photos"})
    assert dav.listed_paths == ["/photos/"]


async def test_list_images_missing_path_yields_clear_error(monkeypatch):
    dav = FakeWebDavClient(error=RemoteResourceNotFound("/missing"))
    monkeypatch.setattr(
        nextcloud, "fetch_thumbnail", _FakePreviewFetcher()
    )
    await _seed_and_mount(monkeypatch, dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool(
            "list_images", {"path": "/missing"}, raise_on_error=False
        )
    assert result.is_error
    assert "not found" in result.content[0].text.lower()


async def test_list_images_without_stored_credentials_yields_clear_error(monkeypatch):
    dav = FakeWebDavClient(propfind_xml=_multistatus_xml())
    monkeypatch.setattr(nextcloud, "fetch_thumbnail", _FakePreviewFetcher())
    backend = MemoryStore()
    _mount_tool_seams(monkeypatch, backend, email="user@example.com", dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool(
            "list_images", {"path": "/"}, raise_on_error=False
        )
    assert result.is_error
    assert "save" in result.content[0].text.lower()


async def test_list_images_stdio_uses_environment_credentials(monkeypatch):
    dav = FakeWebDavClient(propfind_xml=_multistatus_xml())
    monkeypatch.setattr(nextcloud, "fetch_thumbnail", _FakePreviewFetcher())
    backend = MemoryStore()
    _mount_tool_seams(monkeypatch, backend, email=None, dav=dav)
    for name, value in _env_credentials().items():
        monkeypatch.setenv(name, value)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool("list_images", {"path": "/photos"})
    assert not result.is_error, result.content[0].text
    assert dav.last_credentials == NextcloudCredentials(
        webdav_url=WEBDAV_URL, username=ENV_USERNAME, app_password=ENV_APP_PASSWORD
    )


async def test_list_images_rejected_credentials_yield_clear_error(monkeypatch):
    rejecting = FakeWebDavClient(error=ResponseErrorCode(WEBDAV_URL, 401, "Unauthorized"))
    monkeypatch.setattr(nextcloud, "fetch_thumbnail", _FakePreviewFetcher())
    await _seed_and_mount(monkeypatch, dav=rejecting)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool(
            "list_images", {"path": "/"}, raise_on_error=False
        )
    assert result.is_error
    message = result.content[0].text.lower()
    assert "credentials" in message
    assert "register_nextcloud_credentials" in message


async def test_download_image_returns_original_bytes_as_image_content(monkeypatch):
    dav = FakeWebDavClient(files={"/photos/cat.jpg": IMAGE_BYTES})
    await _seed_and_mount(monkeypatch, dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool("download_image", {"path": "/photos/cat.jpg"})
    assert not result.is_error, result.content[0].text
    block = result.content[0]
    assert block.type == "image"
    assert base64.b64decode(block.data) == IMAGE_BYTES
    assert block.mime_type == "image/jpeg"


async def test_download_image_missing_file_yields_clear_error(monkeypatch):
    dav = FakeWebDavClient(error=RemoteResourceNotFound("/photos/missing.jpg"))
    await _seed_and_mount(monkeypatch, dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool(
            "download_image", {"path": "/photos/missing.jpg"}, raise_on_error=False
        )
    assert result.is_error
    assert "not found" in result.content[0].text.lower()


async def test_download_image_without_stored_credentials_yields_clear_error(monkeypatch):
    dav = FakeWebDavClient(files={"/photos/cat.jpg": IMAGE_BYTES})
    backend = MemoryStore()
    _mount_tool_seams(monkeypatch, backend, email="user@example.com", dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool(
            "download_image", {"path": "/photos/cat.jpg"}, raise_on_error=False
        )
    assert result.is_error
    assert "save" in result.content[0].text.lower()


async def test_download_image_without_extension_yields_clear_error(monkeypatch):
    dav = FakeWebDavClient(files={"/justbytes": IMAGE_BYTES})
    await _seed_and_mount(monkeypatch, dav=dav)
    async with Client(nextcloud.mcp) as client:
        result = await client.call_tool(
            "download_image", {"path": "/justbytes"}, raise_on_error=False
        )
    assert result.is_error
    assert "media type" in result.content[0].text.lower()


def test_webdav_client_maps_dav_url_to_account_file_root():
    client = build_webdav_client(_credentials("nextcloud-user"))
    assert client.webdav.hostname == "https://nx.example.com"
    assert client.webdav.root == "/remote.php/dav/files/nextcloud-user"


def test_webdav_client_uses_files_url_verbatim():
    credentials = NextcloudCredentials(
        webdav_url="https://nx.example.com/remote.php/dav/files/nextcloud-user",
        username="nextcloud-user",
        app_password="app-password-nextcloud-user",
    )
    client = build_webdav_client(credentials)
    assert client.webdav.hostname == "https://nx.example.com"
    assert client.webdav.root == "/remote.php/dav/files/nextcloud-user"


async def test_authenticated_ignores_env_credentials_even_without_stored(monkeypatch):
    _authenticate_as(monkeypatch, "user@example.com")
    env = _storage_env() | _env_credentials()
    with pytest.raises(ToolError) as excinfo:
        await resolve_credentials(env=env, backend=MemoryStore())
    assert "save" in str(excinfo.value).lower()


def test_validate_env_config_all_or_nothing():
    validate_env_config(env={})
    validate_env_config(env=_env_credentials())
    with pytest.raises(ToolsetConfigError) as excinfo:
        validate_env_config(env={NEXTCLOUD_WEBDAV_URL: WEBDAV_URL})
    message = str(excinfo.value)
    assert NEXTCLOUD_USERNAME in message
    assert NEXTCLOUD_APP_PASSWORD in message


def test_partial_nextcloud_env_config_fails_at_server_startup(monkeypatch):
    monkeypatch.setenv(NEXTCLOUD_WEBDAV_URL, WEBDAV_URL)
    with pytest.raises(ToolsetConfigError) as excinfo:
        build_server()
    message = str(excinfo.value)
    assert NEXTCLOUD_USERNAME in message
    assert NEXTCLOUD_APP_PASSWORD in message


def test_complete_nextcloud_env_config_builds_server(monkeypatch):
    for name, value in _env_credentials().items():
        monkeypatch.setenv(name, value)
    assert build_server() is not None


STUB_TOKEN = "stub-valid-token"


class _EmailTokenVerifier(TokenVerifier):
    """Accepts exactly one known token with a fixed email claim."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != STUB_TOKEN:
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


async def _serve(server):
    port = _free_port()
    uvicorn_server = uvicorn.Server(
        uvicorn.Config(server.http_app(), host="127.0.0.1", port=port, log_level="critical")
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


async def test_authenticated_identity_reaches_tool_through_http_server(monkeypatch):
    """End-to-end: a real authenticated HTTP call keys the tool to the token identity."""
    backend = MemoryStore()
    storage = build_credential_storage(_fernet(), backend=backend)
    await save_credentials(storage, "user@example.com", _credentials("nextcloud-user"))
    dav = FakeWebDavClient(propfind_xml=_multistatus_xml())
    monkeypatch.setattr(nextcloud, "credential_backend", lambda: backend)
    monkeypatch.setenv(MCP_OAUTH_STORAGE_KEY, FERNET_KEY)
    monkeypatch.setattr(nextcloud, "build_webdav_client", dav.record)
    monkeypatch.setattr(nextcloud, "fetch_thumbnail", _FakePreviewFetcher())
    server = build_server(auth=_EmailTokenVerifier())
    base_url, uvicorn_server, thread = await _serve(server)
    try:
        async with Client(f"{base_url}/mcp", auth=STUB_TOKEN) as client:
            result = await client.call_tool("nextcloud_list_images", {"path": "/photos"})
        assert not result.is_error, result.content[0].text
        names = {entry["name"] for entry in result.structured_content["entries"]}
        assert "cat.jpg" in names
        assert dav.last_credentials == _credentials("nextcloud-user")
    finally:
        _stop(uvicorn_server, thread)


def _multistatus_xml() -> str:
    """An extended Nextcloud PROPFIND response for ``/photos``.

    Mirrors a live server: the listed collection itself is the first
    response, names come from hrefs (no displayname), unfound properties
    sit in a 404 propstat block.
    """
    return f"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns" xmlns:nc="http://nextcloud.org/ns">
  <d:response>
    <d:href>{DAV_ROOT}/photos/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><d:collection/></d:resourcetype>
        <oc:fileid>17</oc:fileid>
        <oc:size>71680</oc:size>
        <d:getlastmodified>Sat, 04 Oct 2025 10:00:00 GMT</d:getlastmodified>
        <oc:permissions>RDNVCK</oc:permissions>
        <oc:owner-id>nextcloud-user</oc:owner-id>
        <oc:owner-display-name>Nextcloud User</oc:owner-display-name>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>{DAV_ROOT}/photos/subfolder/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><d:collection/></d:resourcetype>
        <oc:fileid>18</oc:fileid>
        <oc:size>4096</oc:size>
        <d:getlastmodified>Sat, 04 Oct 2025 11:00:00 GMT</d:getlastmodified>
        <oc:permissions>RDNVCK</oc:permissions>
        <oc:owner-id>nextcloud-user</oc:owner-id>
        <oc:owner-display-name>Nextcloud User</oc:owner-display-name>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>{DAV_ROOT}/photos/cat.jpg</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype/>
        <d:getcontentlength>1234</d:getcontentlength>
        <d:getcontenttype>image/jpeg</d:getcontenttype>
        <d:getlastmodified>Sat, 04 Oct 2025 12:34:56 GMT</d:getlastmodified>
        <d:getetag>&quot;a1b2c3&quot;</d:getetag>
        <oc:fileid>42</oc:fileid>
        <oc:permissions>RGDNVW</oc:permissions>
        <oc:owner-id>nextcloud-user</oc:owner-id>
        <oc:owner-display-name>Nextcloud User</oc:owner-display-name>
        <nc:has-preview>true</nc:has-preview>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>{DAV_ROOT}/photos/notes.txt</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype/>
        <d:getcontentlength>100</d:getcontentlength>
        <d:getcontenttype>text/plain</d:getcontenttype>
        <d:getlastmodified>Sat, 04 Oct 2025 08:00:00 GMT</d:getlastmodified>
        <oc:fileid>43</oc:fileid>
        <oc:permissions>RGDNVW</oc:permissions>
        <oc:owner-id>nextcloud-user</oc:owner-id>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
    <d:propstat>
      <d:prop>
        <nc:has-preview/>
      </d:prop>
      <d:status>HTTP/1.1 404 Not Found</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>{DAV_ROOT}/photos/s%C3%BCden.png</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype/>
        <d:getcontentlength>2048</d:getcontentlength>
        <d:getcontenttype>image/png</d:getcontenttype>
        <d:getlastmodified>Sat, 04 Oct 2025 09:15:00 GMT</d:getlastmodified>
        <oc:fileid>44</oc:fileid>
        <oc:permissions>RGDNVW</oc:permissions>
        <oc:owner-display-name>Nextcloud User</oc:owner-display-name>
        <nc:has-preview>false</nc:has-preview>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>{DAV_ROOT}/photos/mounted-share/beach.png</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype/>
        <d:getcontentlength>2048</d:getcontentlength>
        <d:getcontenttype>image/png</d:getcontenttype>
        <d:getlastmodified>Fri, 03 Oct 2025 18:45:00 GMT</d:getlastmodified>
        <oc:fileid>45</oc:fileid>
        <oc:permissions>S</oc:permissions>
        <oc:owner-id>sharer</oc:owner-id>
        <oc:owner-display-name>Sharer Name</oc:owner-display-name>
        <nc:has-preview>true</nc:has-preview>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>{DAV_ROOT}/photos/noid.png</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype/>
        <d:getcontentlength>512</d:getcontentlength>
        <d:getcontenttype>image/png</d:getcontenttype>
        <d:getlastmodified>Sat, 04 Oct 2025 13:00:00 GMT</d:getlastmodified>
        <oc:permissions>RGDNVW</oc:permissions>
        <nc:has-preview>true</nc:has-preview>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
    <d:propstat>
      <d:prop>
        <oc:fileid/>
      </d:prop>
      <d:status>HTTP/1.1 404 Not Found</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>
"""


def test_parse_propfind_multistatus_returns_full_metadata():
    entries = nextcloud.parse_propfind_multistatus(
        _multistatus_xml(), dav_root=DAV_ROOT, listed_path="/photos"
    )
    assert entries, "the parsed listing must not be empty"
    cat = next(entry for entry in entries if entry.name == "cat.jpg")
    assert cat.is_folder is False
    assert cat.path == "/photos/cat.jpg"
    assert cat.content_type == "image/jpeg"
    assert cat.size == 1234
    assert cat.file_id == "42"
    assert cat.last_modified == "Sat, 04 Oct 2025 12:34:56 GMT"
    assert cat.permissions == "RGDNVW"
    assert cat.owner == "Nextcloud User"
    assert cat.has_preview is True


def test_parse_propfind_multistatus_excludes_the_listed_collection():
    entries = nextcloud.parse_propfind_multistatus(
        _multistatus_xml(), dav_root=DAV_ROOT, listed_path="/photos"
    )
    assert [entry.path for entry in entries if entry.path == "/photos"] == []
    paths = {entry.path for entry in entries}
    assert "/photos/subfolder" in paths


def test_parse_propfind_multistatus_maps_folders_via_resourcetype():
    entries = nextcloud.parse_propfind_multistatus(
        _multistatus_xml(), dav_root=DAV_ROOT, listed_path="/photos"
    )
    subfolder = next(entry for entry in entries if entry.name == "subfolder")
    assert subfolder.is_folder is True
    assert subfolder.path == "/photos/subfolder"
    assert subfolder.size == 4096
    assert subfolder.content_type is None
    assert subfolder.has_preview is False


def test_parse_propfind_multistatus_decodes_encoded_hrefs():
    entries = nextcloud.parse_propfind_multistatus(
        _multistatus_xml(), dav_root=DAV_ROOT, listed_path="/photos"
    )
    encoded = next(entry for entry in entries if entry.file_id == "44")
    assert encoded.name == "süden.png"
    assert encoded.path == "/photos/süden.png"


def test_parse_propfind_multistatus_defaults_missing_properties():
    entries = nextcloud.parse_propfind_multistatus(
        _multistatus_xml(), dav_root=DAV_ROOT, listed_path="/photos"
    )
    notes = next(entry for entry in entries if entry.name == "notes.txt")
    assert notes.file_id == "43"
    assert notes.owner == "nextcloud-user"
    assert notes.has_preview is False
    noid = next(entry for entry in entries if entry.name == "noid.png")
    assert noid.file_id is None
    assert noid.has_preview is True
    sueden = next(entry for entry in entries if entry.name == "süden.png")
    assert sueden.has_preview is False
    beach = next(entry for entry in entries if entry.name == "beach.png")
    assert beach.has_preview is True
    assert beach.owner == "Sharer Name"


def test_parse_propfind_multistatus_lists_the_root_collection():
    entries = nextcloud.parse_propfind_multistatus(
        _multistatus_xml(), dav_root=DAV_ROOT, listed_path="/"
    )
    paths = {entry.path for entry in entries}
    assert "/photos/subfolder" in paths
    assert "/" not in paths


async def test_webdav_client_is_reused_for_same_credentials():
    first = build_webdav_client(_credentials("cached-user"))
    second = build_webdav_client(_credentials("cached-user"))
    assert second is first


async def test_webdav_client_cache_isolates_credentials():
    alice_client = build_webdav_client(_credentials("alice-user"))
    bob_client = build_webdav_client(_credentials("bob-user"))
    assert alice_client is not bob_client


def test_webdav_client_cache_size_is_bounded():
    assert build_webdav_client.cache_info().maxsize == 128


def test_credentials_implement_hashable():
    first = _credentials("hash-user")
    same = _credentials("hash-user")
    other = _credentials("other-user")
    assert isinstance(first, Hashable)
    assert hash(first) == hash(same)
    assert first == same
    assert first != other
