"""Tests for the docx toolset theme asset and converter behavior."""

import base64
import functools
import http.server
import importlib.resources
import io
import os
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path

import pytest
from docx import Document
from fastmcp import Client

from assistant_mcp.toolsets.docx import (
    _PANDOC_BINARY,
    _REFERENCE_DOCX_NAME,
    _SUPPORTED_FORMATS,
    mcp,
)
from assistant_mcp.toolsets.storage import GCS_BUCKET_ENV, PUBLIC_URL_TEMPLATE

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MARKDOWN_FORMAT = _SUPPORTED_FORMATS[0]
HTML_FORMAT = _SUPPORTED_FORMATS[1]
PANDOC = shutil.which(_PANDOC_BINARY)
TEST_BUCKET = "test-bucket"

_UPLOADS: dict[str, tuple[str, bytes]] = {}


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """Capture uploads and return public URLs instead of hitting GCS."""
    _UPLOADS.clear()
    monkeypatch.setenv(GCS_BUCKET_ENV, TEST_BUCKET)

    def fake_upload(data: bytes, object_name: str, content_type: str) -> str:
        _UPLOADS[object_name] = (content_type, bytes(data))
        return PUBLIC_URL_TEMPLATE.format(bucket=TEST_BUCKET, object=object_name)

    monkeypatch.setattr("assistant_mcp.toolsets.docx.upload_document", fake_upload)
    yield
    _UPLOADS.clear()


def _object_name(url: str) -> str:
    prefix = PUBLIC_URL_TEMPLATE.format(bucket=TEST_BUCKET, object="")
    assert url.startswith(prefix), url
    return url[len(prefix):]

# Known-good 1x1 transparent PNG, verified against pandoc 3.12.1.
PIXEL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhK/mAAAAAElFTkSuQmCC"
)
PIXEL_PNG_DATA_URI = f"data:image/png;base64,{PIXEL_PNG_B64}"


def _reference_resource() -> importlib.resources.abc.Traversable:
    return importlib.resources.files("assistant_mcp.toolsets").joinpath(_REFERENCE_DOCX_NAME)


def _reference_bytes() -> bytes:
    resource = _reference_resource()
    assert resource.is_file(), f"missing theme asset: {_REFERENCE_DOCX_NAME}"
    return resource.read_bytes()


def _reference_document() -> Document:
    return Document(io.BytesIO(_reference_bytes()))


def _style_element(document: Document, name: str):
    for style in document.styles:
        if style.name == name:
            return style.element
    return None


def test_theme_asset_ships_and_is_valid_ooxml_container():
    data = _reference_bytes()
    assert data, "theme asset is empty"
    assert zipfile.is_zipfile(io.BytesIO(data)), "theme asset is not a valid zip/DOTX container"


def test_theme_asset_defines_heading_1_style():
    document = _reference_document()
    element = _style_element(document, "Heading 1")
    assert element is not None, "theme asset must define a 'Heading 1' style"


def test_theme_asset_table_style_has_header_shading_and_borders():
    document = _reference_document()
    element = _style_element(document, "Table")
    assert element is not None, "theme asset must define a 'Table' style"

    by_type = {
        pr.get(f"{{{W_NS}}}type"): pr
        for pr in element.findall(f"{{{W_NS}}}tblStylePr")
    }
    header = by_type.get("firstRow")
    assert header is not None, "Table style must carry firstRow conditional formatting"

    shading = header.findall(f"{{{W_NS}}}rPr/{{{W_NS}}}shd")
    assert shading, "firstRow conditional formatting must shade the header row"
    assert shading[0].get(f"{{{W_NS}}}fill") == "4472C4"

    color = header.findall(f"{{{W_NS}}}rPr/{{{W_NS}}}color")
    assert color, "firstRow conditional formatting must set header text color"
    assert color[0].get(f"{{{W_NS}}}val") == "FFFFFF"
    bold = header.findall(f"{{{W_NS}}}rPr/{{{W_NS}}}b")
    assert bold, "firstRow conditional formatting must bold the header text"

    borders = header.findall(f"{{{W_NS}}}tcPr/{{{W_NS}}}tcBorders")
    assert borders, "firstRow conditional formatting must set header cell borders"

    style_borders = element.findall(f"{{{W_NS}}}tblPr/{{{W_NS}}}tblBorders")
    assert style_borders, "Table style must define table-wide cell borders"


def test_theme_asset_table_style_has_zebra_striping():
    document = _reference_document()
    element = _style_element(document, "Table")
    assert element is not None, "theme asset must define a 'Table' style"

    by_type = {
        pr.get(f"{{{W_NS}}}type"): pr
        for pr in element.findall(f"{{{W_NS}}}tblStylePr")
    }
    for band_type in ("band2Horz", "band1Horz"):
        if band_type in by_type:
            band = by_type[band_type]
            shading = band.findall(f"{{{W_NS}}}tcPr/{{{W_NS}}}shd")
            assert shading, f"{band_type} conditional formatting must shade the row"
            assert shading[0].get(f"{{{W_NS}}}fill") in ("E7EDF7", "FFFFFF")
            return
    pytest.fail("Table style must carry zebra striping (band1Horz or band2Horz)")


# --- convert_to_docx: Markdown core ------------------------------------------


def _docx_bytes(result) -> bytes:
    return _UPLOADS[_object_name(_url(result))][1]


def _url(result) -> str:
    assert not result.is_error
    return result.structured_content["url"]


def _assert_public_url(result) -> None:
    url = _url(result)
    assert url.startswith(
        f"https://storage.googleapis.com/{TEST_BUCKET}/docx/"
    ) and url.endswith(".docx")
    assert all(block.type != "resource" for block in result.content)


def _read_docx(result) -> Document:
    return Document(io.BytesIO(_docx_bytes(result)))


def _paragraph_texts_with_numbering(document: Document) -> list[str]:
    body = document.element.body
    texts = []
    for paragraph in body.findall(f".//{{{W_NS}}}p"):
        if paragraph.find(f".//{{{W_NS}}}numPr") is None:
            continue
        texts.append("".join(node.text or "" for node in paragraph.findall(f".//{{{W_NS}}}t")))
    return texts


async def _call_convert(content: str, format: str, title: str | None = None):
    arguments = {"content": content, "format": format}
    if title is not None:
        arguments["title"] = title
    async with Client(mcp) as client:
        return await client.call_tool("convert_to_docx", arguments)


MARKDOWN_COMMON_ELEMENTS = (
    "# Quarterly Report\n\n"
    "## Details\n\n"
    "### Notes\n\n"
    "Revenue is **up** and costs are *down*.\n\n"
    "- Alpha\n"
    "  - Alpha nested\n"
    "- Beta\n\n"
    "1. First step\n"
    "2. Second step\n\n"
    "| Name | Wert |\n"
    "|---|---|\n"
    "| Alpha | 1 |\n"
    "| Beta | 2 |\n"
)


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_convert_markdown_common_elements():
    result = await _call_convert(MARKDOWN_COMMON_ELEMENTS, MARKDOWN_FORMAT)
    assert not result.is_error
    _assert_public_url(result)
    document = _read_docx(result)

    headings = [p for p in document.paragraphs if p.style.name == "Heading 1"]
    assert headings and headings[0].text == "Quarterly Report"

    runs = [run for p in document.paragraphs for run in p.runs]
    assert any(run.bold for run in runs), "bold span must survive conversion"
    assert any(run.italic for run in runs), "italic span must survive conversion"

    numbered_texts = _paragraph_texts_with_numbering(document)
    for item in ("Alpha", "Alpha nested", "Beta", "First step", "Second step"):
        assert item in numbered_texts, f"list item {item!r} must carry Word numbering"

    tables = document.tables
    assert tables, "pipe table must become a Word table"
    assert tables[0].style.name == "Table"
    assert tables[0].rows[0].cells[0].text == "Name"
    assert tables[0].rows[1].cells[1].text == "1"


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_convert_markdown_link_is_preserved():
    md = "See the [Mistral docs](https://mistral.ai/docs) for details.\n"
    result = await _call_convert(md, MARKDOWN_FORMAT)
    assert not result.is_error
    document = _read_docx(result)
    hyperlinks = [link for p in document.paragraphs for link in p.hyperlinks]
    assert any(link.address == "https://mistral.ai/docs" for link in hyperlinks), (
        "markdown links must survive conversion as hyperlinks"
    )


# --- convert_to_docx: extended Markdown and temp hygiene ---------------------


def _zip_member(result, member: str) -> str:
    with zipfile.ZipFile(io.BytesIO(_docx_bytes(result))) as archive:
        return archive.read(member).decode()


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_convert_markdown_extended_elements():
    md = (
        "~~struck out~~ text\n\n"
        "- [ ] open task\n"
        "- [x] done task\n\n"
        "```\nprint('hello')\n```\n"
    )
    result = await _call_convert(md, MARKDOWN_FORMAT)
    assert not result.is_error
    document = _read_docx(result)

    struck = [
        run
        for p in document.paragraphs
        for run in p.runs
        if run.element.find(f".//{{{W_NS}}}rPr/{{{W_NS}}}strike") is not None
    ]
    assert struck and struck[0].text == "struck out"

    numbering = _zip_member(result, "word/numbering.xml")
    assert "☐" in numbering, "open task items must carry an unchecked box marker"
    assert "☒" in numbering, "done task items must carry a checked box marker"

    code = [p for p in document.paragraphs if p.style.name == "Source Code"]
    assert code and "print('hello')" in code[0].text


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_convert_markdown_leaves_no_file_residue():
    import tempfile

    before_cwd = {entry.name for entry in Path.cwd().iterdir()}
    before_tmp = {entry.name for entry in Path(tempfile.gettempdir()).iterdir()}
    result = await _call_convert(MARKDOWN_COMMON_ELEMENTS, MARKDOWN_FORMAT)
    assert not result.is_error
    assert _read_docx(result) is not None
    after_cwd = {entry.name for entry in Path.cwd().iterdir()}
    after_tmp = {entry.name for entry in Path(tempfile.gettempdir()).iterdir()}
    assert not after_cwd - before_cwd, "conversion must not leave files in the working directory"
    assert not {
        name for name in after_tmp - before_tmp if name.startswith("convert_to_docx_")
    }, "conversion must not leave temp directories behind"


# --- convert_to_docx: error handling ------------------------------------------


async def _call_convert_error(content: str, format: str, title: str | None = None):
    arguments = {"content": content, "format": format}
    if title is not None:
        arguments["title"] = title
    async with Client(mcp) as client:
        result = await client.call_tool("convert_to_docx", arguments, raise_on_error=False)
        assert result.is_error
        return result


def _error_text(result) -> str:
    return result.content[0].text


async def test_convert_empty_content_returns_error():
    for content in ("", "   \n\t  "):
        result = await _call_convert_error(content, MARKDOWN_FORMAT)
        assert "content" in _error_text(result)
        assert "empty" in _error_text(result)


async def test_convert_unsupported_format_returns_error():
    result = await _call_convert_error("# Heading\n", "rtf")
    message = _error_text(result)
    assert "rtf" in message
    for fmt in _SUPPORTED_FORMATS:
        assert fmt in message


async def test_convert_pandoc_missing_returns_error(monkeypatch):
    missing_binary = "pandoc-not-installed-simulation"
    monkeypatch.setattr(
        "assistant_mcp.toolsets.docx._PANDOC_BINARY", missing_binary
    )
    result = await _call_convert_error("# Heading\n", MARKDOWN_FORMAT)
    assert missing_binary in _error_text(result)
    assert "not available" in _error_text(result)


# --- convert_to_docx: HTML ----------------------------------------------------


HTML_COMMON_ELEMENTS = (
    "<h1>Quarterly Report</h1>"
    "<h2>Details</h2>"
    "<h3>Notes</h3>"
    "<p>Revenue is <strong>up</strong> and costs are <em>down</em>.</p>"
    "<ul><li>Alpha<ul><li>Alpha nested</li></ul></li><li>Beta</li></ul>"
    "<ol><li>First step</li><li>Second step</li></ol>"
    "<table><tr><th>Name</th><th>Wert</th></tr>"
    "<tr><td>Alpha</td><td>1</td></tr>"
    "<tr><td>Beta</td><td>2</td></tr></table>"
)


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_convert_html_common_elements():
    result = await _call_convert(HTML_COMMON_ELEMENTS, HTML_FORMAT)
    assert not result.is_error
    _assert_public_url(result)
    document = _read_docx(result)

    heading_styles = {
        p.style.name for p in document.paragraphs if p.style.name.startswith("Heading")
    }
    assert {"Heading 1", "Heading 2", "Heading 3"} <= heading_styles

    runs = [run for p in document.paragraphs for run in p.runs]
    assert any(run.bold for run in runs)
    assert any(run.italic for run in runs)

    numbered_texts = _paragraph_texts_with_numbering(document)
    for item in ("Alpha", "Alpha nested", "Beta", "First step", "Second step"):
        assert item in numbered_texts

    tables = document.tables
    assert tables
    assert tables[0].style.name == "Table"
    assert tables[0].rows[0].cells[0].text == "Name"


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_styling_is_identical_across_formats():
    md_result = await _call_convert(MARKDOWN_COMMON_ELEMENTS, MARKDOWN_FORMAT)
    html_result = await _call_convert(HTML_COMMON_ELEMENTS, HTML_FORMAT)
    assert not md_result.is_error
    assert not html_result.is_error
    md_document = _read_docx(md_result)
    html_document = _read_docx(html_result)

    md_headings = {
        p.style.name for p in md_document.paragraphs if p.style.name.startswith("Heading")
    }
    html_headings = {
        p.style.name for p in html_document.paragraphs if p.style.name.startswith("Heading")
    }
    assert md_headings == html_headings
    assert md_headings

    md_table_styles = {t.style.name for t in md_document.tables}
    html_table_styles = {t.style.name for t in html_document.tables}
    assert md_table_styles == html_table_styles == {"Table"}

    md_styles_xml = _zip_member(md_result, "word/styles.xml")
    html_styles_xml = _zip_member(html_result, "word/styles.xml")
    assert md_styles_xml == html_styles_xml, "both formats must use the same shipped styles"


# --- convert_to_docx: title metadata -----------------------------------------


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_title_is_set_as_core_property_and_title_block():
    result = await _call_convert(
        MARKDOWN_COMMON_ELEMENTS, MARKDOWN_FORMAT, title="Quarterly Report"
    )
    assert not result.is_error
    document = _read_docx(result)
    assert document.core_properties.title == "Quarterly Report"
    title_paragraphs = [p for p in document.paragraphs if p.style.name == "Title"]
    assert title_paragraphs and title_paragraphs[0].text == "Quarterly Report"


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_omitted_title_leaves_usable_default():
    result = await _call_convert(MARKDOWN_COMMON_ELEMENTS, MARKDOWN_FORMAT)
    assert not result.is_error
    document = _read_docx(result)
    title_paragraphs = [p for p in document.paragraphs if p.style.name == "Title"]
    assert not title_paragraphs
    headings = [p for p in document.paragraphs if p.style.name == "Heading 1"]
    assert headings and headings[0].text == "Quarterly Report"


# --- convert_to_docx: images -------------------------------------------------


def _media_members(result) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(_docx_bytes(result))) as archive:
        return [name for name in archive.namelist() if name.startswith("word/media/")]


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_data_uri_image_is_embedded():
    md = f"![pixel]({PIXEL_PNG_DATA_URI})\n\nBody text.\n"
    result = await _call_convert(md, MARKDOWN_FORMAT)
    assert not result.is_error
    media = _media_members(result)
    assert media, "data-URI image must be embedded in the document package"


def _pandoc_has_http_support() -> bool:
    """Probe whether the local pandoc build can fetch remote resources."""
    if PANDOC is None:
        return False
    probe = subprocess.run(
        [PANDOC, "-f", MARKDOWN_FORMAT, "-t", "docx", "-o", os.devnull],
        input=b"![x](http://127.0.0.1:1/x.png)\n",
        capture_output=True,
        check=False,
        timeout=30,
    )
    return b"compiled without HTTP support" not in probe.stderr


@pytest.fixture(scope="session")
def pandoc_http_support() -> bool:
    return _pandoc_has_http_support()


@pytest.fixture
def local_image_url(tmp_path):
    pixel = tmp_path / "pixel.png"
    pixel.write_bytes(base64.b64decode(PIXEL_PNG_B64))
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/pixel.png"
    finally:
        server.shutdown()
        thread.join(timeout=5)


async def test_remote_image_is_fetched_and_embedded(local_image_url, pandoc_http_support):
    if not pandoc_http_support:
        pytest.skip("pandoc not available or lacks HTTP support in this environment")
    md = f"![pixel]({local_image_url})\n\nBody text.\n"
    result = await _call_convert(md, MARKDOWN_FORMAT)
    assert not result.is_error
    media = _media_members(result)
    assert media, "remote image must be fetched and embedded in the document package"


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_unfetchable_remote_image_degrades_gracefully():
    md = "![missing pixel](http://127.0.0.1:1/pixel.png)\n\nBody text.\n"
    result = await _call_convert(md, MARKDOWN_FORMAT)
    assert not result.is_error
    assert not _media_members(result)
    document = _read_docx(result)
    paragraph_texts = [p.text for p in document.paragraphs]
    assert any("missing pixel" in text for text in paragraph_texts), (
        "unfetchable image must be replaced by its description"
    )


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_conversion_failure_returns_error_and_server_recovers():
    long_detail = b"x" * 4000 + b"pandoc: cannot parse input"

    def failing_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout=b"", stderr=long_detail
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("assistant_mcp.toolsets.docx.subprocess.run", failing_run)
        result = await _call_convert_error(MARKDOWN_COMMON_ELEMENTS, MARKDOWN_FORMAT)
    message = _error_text(result)
    assert "cannot parse input" in message
    assert "conversion failed" in message
    assert "x" * 4000 not in message, "error detail must be truncated"

    follow_up = await _call_convert("# Still alive\n", MARKDOWN_FORMAT)
    assert not follow_up.is_error


@pytest.mark.skipif(PANDOC is None, reason="pandoc not available in this environment")
async def test_conversion_timeout_returns_error(monkeypatch):
    def timing_out_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr("assistant_mcp.toolsets.docx.subprocess.run", timing_out_run)
    result = await _call_convert_error(MARKDOWN_COMMON_ELEMENTS, MARKDOWN_FORMAT)
    assert "timed out" in _error_text(result)
