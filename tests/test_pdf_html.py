"""Tests for HTML-to-PDF rendering and input-type detection in generate_pdf."""

import io

import pytest
from fastmcp import Client
from pypdf import PdfReader

from assistant_mcp.toolsets.pdf import mcp

HTML_DOC = """<!DOCTYPE html>
<html><head><style>
h1 { color: #4472C4; }
@page { size: A4; margin: 2cm; }
</style></head>
<body><h1>HTML Titel</h1><p>Ein Absatz mit <b>fett</b>.</p></body></html>"""

HTML_FRAGMENT = "<h1>Fragment Titel</h1><p>Absatz im Fragment &ndash; Gr&#252;&#223;e.</p>"


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


def _pdf_bytes(result) -> bytes:
    import base64

    block = result.content[0]
    assert block.type == "resource"
    return base64.b64decode(block.resource.blob)


def _pdf_text(result) -> str:
    reader = PdfReader(io.BytesIO(_pdf_bytes(result)))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# --- detection (format="auto") ----------------------------------------------


async def test_html_document_is_detected_and_rendered():
    result = await call_generate_pdf(HTML_DOC)
    assert not result.is_error
    assert _pdf_bytes(result).startswith(b"%PDF-")
    text = _pdf_text(result)
    assert "HTML Titel" in text
    assert "Absatz" in text


async def test_html_fragment_is_detected_and_rendered():
    result = await call_generate_pdf(HTML_FRAGMENT)
    assert not result.is_error
    assert _pdf_bytes(result).startswith(b"%PDF-")
    text = _pdf_text(result)
    assert "Fragment Titel" in text


async def test_markdown_input_stays_on_markdown_path():
    md = "# Titel\n\nPunkt **fett** und *kursiv*.\n"
    result = await call_generate_pdf(md)
    text = _pdf_text(result)
    assert "Titel" in text


async def test_markdown_with_embedded_html_snippet_stays_markdown():
    md = "# Bericht\n\nEin Absatz.\n\n<p>html snippet</p>\n\nNoch ein Absatz.\n"
    result = await call_generate_pdf(md)
    assert not result.is_error
    text = _pdf_text(result)
    assert "Bericht" in text
    assert "Noch ein Absatz" in text


async def test_plain_text_stays_markdown_path():
    result = await call_generate_pdf("Erster Absatz.\n\nZweiter Absatz.")
    assert not result.is_error
    text = _pdf_text(result)
    assert "Erster Absatz." in text


# --- HTML rendering ----------------------------------------------------------


async def test_html_embedded_style_is_applied():
    html = (
        "<style>h1 { color: #4472C4; font-size: 24px; }"
        " @page { size: A4; margin: 2cm; }</style>"
        "<h1>Gestylt</h1><p>Inhalt</p>"
    )
    result = await call_generate_pdf(html)
    assert not result.is_error
    assert _pdf_bytes(result).startswith(b"%PDF-")
    text = _pdf_text(result)
    assert "Gestylt" in text


async def test_html_umlauts_and_entities_render():
    result = await call_generate_pdf("<p>Gr&uuml;&szlig;e aus M&uuml;nchen</p>")
    text = _pdf_text(result)
    assert "Grüße aus München" in text


async def test_html_external_resources_do_not_load():
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
    assert not result.is_error
    assert _pdf_bytes(result).startswith(b"%PDF-")
    text = _pdf_text(result)
    assert "before" in text
    assert "after" in text


async def test_html_data_uri_image_renders():
    html = (
        '<p>mit Bild</p><img src="data:image/gif;base64,'
        "R0lGODlhAQABAIAAAAAAAP///yH5BAAAAAAALAAAAAABAAEAAAIBRAA7\">"
    )
    result = await call_generate_pdf(html)
    assert not result.is_error
    assert _pdf_bytes(result).startswith(b"%PDF-")


# --- format parameter --------------------------------------------------------


async def test_format_html_overrides_detection():
    result = await call_generate_pdf("# Kein HTML", format="html")
    assert not result.is_error
    assert _pdf_bytes(result).startswith(b"%PDF-")


async def test_format_markdown_overrides_detection():
    result = await call_generate_pdf("<h1>HTML</h1><p>inhalt</p>", format="markdown")
    assert not result.is_error
    text = _pdf_text(result)
    assert "inhalt" in text


async def test_format_html_case_insensitive():
    result = await call_generate_pdf(HTML_FRAGMENT, format="HTML")
    assert not result.is_error


async def test_format_invalid_returns_error():
    result = await call_generate_pdf_error("irrelevant", format="rtf")
    assert "format" in result.content[0].text


async def test_empty_text_errors_for_html_format():
    result = await call_generate_pdf_error("", format="html")
    assert "text" in result.content[0].text
