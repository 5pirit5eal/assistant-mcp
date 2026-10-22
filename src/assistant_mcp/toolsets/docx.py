"""DOCX toolset: convert Markdown or HTML content to a styled Word document."""

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from assistant_mcp.toolsets.storage import upload_document

mcp = FastMCP("docx")

_PANDOC_BINARY = "pandoc"
_SUPPORTED_FORMATS = ("markdown", "html")
_FORMATS_DESC = ", ".join(f'"{item}"' for item in _SUPPORTED_FORMATS)
_SUBPROCESS_TIMEOUT_SECONDS = 120
_OUTPUT_FILENAME = "output.docx"
_REFERENCE_DOCX_NAME = "docx_reference.docx"
_STDERR_DETAIL_LIMIT = 2000
_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GenerationResult(BaseModel):
    """Public resource URL of a generated document in the storage bucket."""

    url: str = Field(
        description="Public resource URL of the generated document in the "
        "storage bucket. Bucket objects are deleted one month after creation.",
        examples=["https://storage.googleapis.com/bucket/docx/object.docx"],
    )


@mcp.tool
def convert_to_docx(
    content: Annotated[
        str,
        Field(
            description="Markdown or HTML content of the document.",
            examples=["# Quarterly Report\nRevenue is up."],
        ),
    ],
    format: Annotated[
        str,
        Field(
            description=f"Input format: one of {_FORMATS_DESC}.",
            examples=["markdown"],
        ),
    ],
    title: Annotated[
        str | None,
        Field(
            description="Optional document title; stored as the file's title "
            "property and rendered as the document's title block.",
            examples=["Quarterly Report"],
        ),
    ] = None,
) -> GenerationResult:
    """Convert Markdown or HTML content to a styled Word document.

    Styling comes from a fixed shipped theme, identical for both input
    formats: heading styles, body text, and tables with a shaded header
    row. Images passed as base64 data URIs are embedded; remote http(s)
    image URLs are fetched by the server during conversion (an image
    that cannot be fetched is replaced by its description). An optional
    title is stored as the file's title property and rendered as the
    document's title block.

    Returns:
        Public resource URL of the uploaded DOCX in the storage bucket
        (bucket objects are deleted one month after creation).
    """
    if not content.strip():
        raise ToolError("content must not be empty")
    fmt = format.lower().strip()
    if fmt not in _SUPPORTED_FORMATS:
        raise ToolError(f"unsupported format: {format}. Use one of: {_FORMATS_DESC}")
    if shutil.which(_PANDOC_BINARY) is None:
        raise ToolError(f"{_PANDOC_BINARY} is not available on the server")

    reference_doc = Path(__file__).parent / _REFERENCE_DOCX_NAME
    with tempfile.TemporaryDirectory(prefix="convert_to_docx_") as tmpdir:
        output = Path(tmpdir) / _OUTPUT_FILENAME
        cmd = [
            _PANDOC_BINARY,
            "-f",
            fmt,
            "-t",
            "docx",
            f"--reference-doc={reference_doc}",
            "-o",
            str(output),
        ]
        if title is not None:
            cmd.extend(["--metadata", f"title={title}"])
        try:
            process = subprocess.run(
                cmd,
                input=content.encode(),
                capture_output=True,
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError("docx conversion timed out") from exc
        detail = process.stderr.decode(errors="replace").strip()[-_STDERR_DETAIL_LIMIT:]
        if process.returncode != 0 or not output.exists():
            raise ToolError(f"docx conversion failed: {detail or 'unknown error'}")
        object_name = f"docx/{uuid.uuid4()}.docx"
        return GenerationResult(
            url=upload_document(output.read_bytes(), object_name, _DOCX_CONTENT_TYPE)
        )
