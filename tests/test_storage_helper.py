"""Tests for the GCS storage helper, driven through its public functions."""

import pytest
from fastmcp.exceptions import ToolError

from assistant_mcp.toolsets.storage import (
    GCS_BUCKET_ENV,
    PUBLIC_URL_TEMPLATE,
    get_storage_client,
    upload_document,
)


class _FakeBlob:
    def __init__(self, bucket: _FakeBucket, name: str) -> None:
        self._bucket = bucket
        self._name = name

    def upload_from_string(
        self, data, content_type: str = "text/plain", timeout: float = 60
    ) -> None:
        self._bucket.timeouts.append(timeout)
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("upload payload must be bytes")
        self._bucket.objects[self._name] = (content_type, bytes(data))


class _FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[str, bytes]] = {}
        self.timeouts: list[float] = []

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self, name)


class _FakeClient:
    def __init__(self) -> None:
        self.fake_bucket = _FakeBucket()
        self.bucket_name: str | None = None

    def bucket(self, name: str) -> _FakeBucket:  # noqa: A003 - mirrors SDK API
        self.bucket_name = name
        return self.fake_bucket


class _FailingClient:
    def bucket(self, name: str) -> None:
        raise RuntimeError("storage backend unavailable")


def _install_fake_client(monkeypatch, client) -> _FakeClient:
    monkeypatch.setenv(GCS_BUCKET_ENV, "test-bucket")
    monkeypatch.setattr(
        "assistant_mcp.toolsets.storage.get_storage_client", lambda: client
    )
    return client


def test_public_url_template_matches_gcs_layout():
    assert PUBLIC_URL_TEMPLATE.format(
        bucket="my-bucket", object="pdf/abc.pdf"
    ) == "https://storage.googleapis.com/my-bucket/pdf/abc.pdf"


def test_bucket_env_constant_is_stable():
    assert GCS_BUCKET_ENV == "GCS_BUCKET_NAME"


async def test_upload_document_returns_public_url(monkeypatch):
    client = _install_fake_client(monkeypatch, _FakeClient())
    url = await upload_document(b"%PDF-1.7 fake", "pdf/abc.pdf", "application/pdf")
    assert url == "https://storage.googleapis.com/test-bucket/pdf/abc.pdf"
    assert client.bucket_name == "test-bucket"
    content_type, data = client.fake_bucket.objects["pdf/abc.pdf"]
    assert content_type == "application/pdf"
    assert data == b"%PDF-1.7 fake"


async def test_upload_document_uses_ten_second_deadline(monkeypatch):
    client = _install_fake_client(monkeypatch, _FakeClient())
    await upload_document(b"x", "pdf/a.pdf", "application/pdf")
    assert client.fake_bucket.timeouts == [10.0]


async def test_upload_document_missing_bucket_raises_tool_error(monkeypatch):
    monkeypatch.delenv(GCS_BUCKET_ENV, raising=False)
    with pytest.raises(ToolError, match="bucket"):
        await upload_document(b"x", "pdf/a.pdf", "application/pdf")


async def test_upload_document_empty_bucket_raises_tool_error(monkeypatch):
    monkeypatch.setenv(GCS_BUCKET_ENV, "   ")
    with pytest.raises(ToolError, match="bucket"):
        await upload_document(b"x", "pdf/a.pdf", "application/pdf")


async def test_upload_document_backend_failure_raises_tool_error(monkeypatch):
    _install_fake_client(monkeypatch, _FailingClient())
    with pytest.raises(ToolError, match="upload"):
        await upload_document(b"x", "pdf/a.pdf", "application/pdf")


def test_get_storage_client_is_cached(monkeypatch):
    calls = []

    class _CountingClient:
        def bucket(self, name):
            return _FakeBucket()

    def _build():
        calls.append(1)
        return _CountingClient()

    monkeypatch.setattr("assistant_mcp.toolsets.storage._new_client", _build)
    get_storage_client.cache_clear()
    first = get_storage_client()
    second = get_storage_client()
    assert first is second
    assert len(calls) == 1
    get_storage_client.cache_clear()
