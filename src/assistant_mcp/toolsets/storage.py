"""GCS upload helper shared by the file-producing toolsets.

Uploads generated documents to a public read bucket (objects are deleted
by a bucket-level lifecycle rule one month after creation) and returns
the public resource URL of the uploaded object. Mirrors the upload
mechanics of swim-gen's backend (`internal/pdf/pdf.go`, `UploadPDF`).

The official google-cloud-storage client is synchronous, so the blocking
upload runs in a worker thread via `asyncio.to_thread`; the tool-facing
function is async and never blocks the event loop.
"""

import asyncio
import os
from functools import lru_cache

from fastmcp.exceptions import ToolError
from google.cloud.storage import Client as StorageClient

GCS_BUCKET_ENV = "GCS_BUCKET_NAME"
PUBLIC_URL_TEMPLATE = "https://storage.googleapis.com/{bucket}/{object}"
_UPLOAD_TIMEOUT_SECONDS = 10.0


def _new_client() -> StorageClient:
    return StorageClient()


@lru_cache(maxsize=1)
def get_storage_client() -> StorageClient:
    return _new_client()


def _bucket_name() -> str:
    name = os.environ.get(GCS_BUCKET_ENV, "").strip()
    if not name:
        raise ToolError(
            f"storage bucket is not configured: set {GCS_BUCKET_ENV}"
        )
    return name


def _upload_blocking(
    data: bytes, object_name: str, content_type: str, bucket_name: str
) -> None:
    try:
        bucket = get_storage_client().bucket(bucket_name)
        bucket.blob(object_name).upload_from_string(
            data, content_type=content_type, timeout=_UPLOAD_TIMEOUT_SECONDS
        )
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"upload to storage bucket failed: {exc}") from exc


async def upload_document(data: bytes, object_name: str, content_type: str) -> str:
    """Upload ``data`` as ``object_name`` and return its public URL."""
    bucket_name = _bucket_name()
    await asyncio.to_thread(
        _upload_blocking, data, object_name, content_type, bucket_name
    )
    return PUBLIC_URL_TEMPLATE.format(bucket=bucket_name, object=object_name)
