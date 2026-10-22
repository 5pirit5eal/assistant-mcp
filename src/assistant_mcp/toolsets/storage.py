"""GCS upload helper shared by the file-producing toolsets.

Uploads generated documents to a public read bucket (objects are deleted
by a bucket-level lifecycle rule one month after creation) and returns
the public resource URL of the uploaded object. Mirrors the upload
mechanics of swim-gen's backend (`internal/pdf/pdf.go`, `UploadPDF`).
"""

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


def upload_document(data: bytes, object_name: str, content_type: str) -> str:
    """Upload ``data`` as ``object_name`` and return its public URL."""
    bucket_name = _bucket_name()
    try:
        bucket = get_storage_client().bucket(bucket_name)
        writer = bucket.object(object_name).new_writer(timeout=_UPLOAD_TIMEOUT_SECONDS)
        writer.content_type = content_type
        writer.write(data)
        writer.close()
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"upload to storage bucket failed: {exc}") from exc
    return PUBLIC_URL_TEMPLATE.format(bucket=bucket_name, object=object_name)
