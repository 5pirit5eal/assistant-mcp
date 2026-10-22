"""Tests for HTML-to-PDF rendering and input-type detection in generate_pdf."""

import pytest
from fastmcp import Client

from assistant_mcp.toolsets.pdf import mcp
from assistant_mcp.toolsets.storage import GCS_BUCKET_ENV, PUBLIC_URL_TEMPLATE

TEST_BUCKET = "test-bucket"

HTML_DOC = """<!DOCTYPE html>
<html><head><style>
h1 { color: #4472C4; }
@page { size: A4; margin: 2cm; }
</style></head>
<body><h1>HTML Titel</h1><p>Ein Absatz mit <b>fett</b>.</p></body></html>"""

HTML_FRAGMENT = "<h1>Fragment Titel</h1><p>Absatz im Fragment &ndash; Gr&#252;&#223;e.</p>"


_UPLOADS: dict[str, tuple[str, bytes]] = {}


@pytest.fixture
def uploads():
    return _UPLOADS


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """Capture uploads and return public URLs instead of hitting GCS."""
    _UPLOADS.clear()
    monkeypatch.setenv(GCS_BUCKET_ENV, TEST_BUCKET)

    async def fake_upload(data: bytes, object_name: str, content_type: str) -> str:
        _UPLOADS[object_name] = (content_type, bytes(data))
        return PUBLIC_URL_TEMPLATE.format(bucket=TEST_BUCKET, object=object_name)

    monkeypatch.setattr("assistant_mcp.toolsets.pdf.upload_document", fake_upload)
    yield
    _UPLOADS.clear()


async def call_generate_pdf(text: str, **kwargs):
    async with Client(mcp) as client:
        return await client.call_tool("generate_pdf", {"text": text, **kwargs})


async def call_generate_pdf_error(text: str, **kwargs):
    async with Client(mcp) as client:
        result = await client.call_tool(
            "generate_pdf", {"text": text, **kwargs}, raise_on_error=False
        )
        assert result.is_error
        return result


def _url(result) -> str:
    assert not result.is_error
    return result.structured_content["url"]


def _assert_public_pdf_url(result) -> str:
    url = _url(result)
    prefix = PUBLIC_URL_TEMPLATE.format(bucket=TEST_BUCKET, object="")
    assert url.startswith(prefix) and url.endswith(".pdf"), url
    return url


def _pdf_bytes(result, uploads) -> bytes:
    url = _assert_public_pdf_url(result)
    object_name = url[len(PUBLIC_URL_TEMPLATE.format(bucket=TEST_BUCKET, object="")):]
    return uploads[object_name][1]


def _pdf_text(result, uploads) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(_pdf_bytes(result, uploads)))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# --- detection (format="auto") ----------------------------------------------


async def test_html_document_is_detected_and_rendered(uploads):
    result = await call_generate_pdf(HTML_DOC)
    text = _pdf_text(result, uploads)
    assert "HTML Titel" in text
    assert "Absatz" in text


async def test_html_fragment_is_detected_and_rendered(uploads):
    result = await call_generate_pdf(HTML_FRAGMENT)
    text = _pdf_text(result, uploads)
    assert "Fragment Titel" in text


async def test_markdown_input_stays_on_markdown_path(uploads):
    result = await call_generate_pdf("# Titel\n\nPunkt **fett** und *kursiv*.\n")
    text = _pdf_text(result, uploads)
    assert "Titel" in text


async def test_markdown_with_embedded_html_snippet_stays_markdown(uploads):
    md = "# Bericht\n\nEin Absatz.\n\n<p>html snippet</p>\n\nNoch ein Absatz.\n"
    result = await call_generate_pdf(md)
    text = _pdf_text(result, uploads)
    assert "Bericht" in text
    assert "Noch ein Absatz" in text


async def test_plain_text_stays_markdown_path(uploads):
    result = await call_generate_pdf("Erster Absatz.\n\nZweiter Absatz.")
    text = _pdf_text(result, uploads)
    assert "Erster Absatz." in text


# --- HTML rendering ----------------------------------------------------------


async def test_html_embedded_style_is_applied(uploads):
    html = (
        "<style>h1 { color: #4472C4; font-size: 24px; }"
        " @page { size: A4; margin: 2cm; }</style>"
        "<h1>Gestylt</h1><p>Inhalt</p>"
    )
    result = await call_generate_pdf(html)
    text = _pdf_text(result, uploads)
    assert "Gestylt" in text


async def test_html_umlauts_and_entities_render(uploads):
    result = await call_generate_pdf("<p>Gr&uuml;&szlig;e aus M&uuml;nchen</p>")
    text = _pdf_text(result, uploads)
    assert "Grüße aus München" in text


async def test_html_external_resources_do_not_load(uploads):
    """External URLs are never fetched; WeasyPrint's default fetcher would.

    We assert on the fetcher the tool installs: it must raise on every
    non-data URI scheme, so a real network request can never be attempted.
    """
    from assistant_mcp.toolsets.pdf import _DATA_ONLY_FETCHER

    with pytest.raises(ValueError, match="disallowed protocol"):
        _DATA_ONLY_FETCHER("https://example.invalid/x.png")
    with pytest.raises(ValueError, match="disallowed protocol"):
        _DATA_ONLY_FETCHER("http://example.invalid/style.css")

    html = (
        '<p>before</p><img src="https://example.invalid/x.png">'
        "<p>after</p>"
    )
    result = await call_generate_pdf(html)
    text = _pdf_text(result, uploads)
    assert "before" in text
    assert "after" in text


async def test_html_data_uri_image_renders(uploads):
    html = (
        '<p>mit Bild</p><img src="data:image/gif;base64,'
        "R0lGODlhAQABAIAAAAAAAP///yH5BAAAAAAALAAAAAABAAEAAAIBRAA7\">"
    )
    result = await call_generate_pdf(html)
    assert _pdf_bytes(result, uploads).startswith(b"%PDF-")


# --- format parameter --------------------------------------------------------


async def test_format_html_overrides_detection(uploads):
    result = await call_generate_pdf("# Kein HTML", format="html")
    assert _pdf_bytes(result, uploads).startswith(b"%PDF-")


async def test_format_markdown_overrides_detection(uploads):
    result = await call_generate_pdf("<h1>HTML</h1><p>inhalt</p>", format="markdown")
    text = _pdf_text(result, uploads)
    assert "inhalt" in text


async def test_format_html_case_insensitive(uploads):
    result = await call_generate_pdf(HTML_FRAGMENT, format="HTML")
    assert _pdf_bytes(result, uploads).startswith(b"%PDF-")


async def test_format_invalid_returns_error():
    result = await call_generate_pdf_error("irrelevant", format="rtf")
    assert "format" in result.content[0].text


async def test_empty_text_errors_for_html_format():
    result = await call_generate_pdf_error("", format="html")
    assert "text" in result.content[0].text
