"""Tests for the pdf toolset, driven through the public MCP tool interface."""

import base64
import io
import shutil
from pathlib import Path

import pytest
from fastmcp import Client
from pypdf import PdfReader

from assistant_mcp.toolsets.pdf import mcp

SOFFICE = shutil.which("soffice")
FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_b64(name: str) -> str:
    return base64.b64encode((FIXTURES / name).read_bytes()).decode()


def _pdf_bytes(result) -> bytes:
    block = result.content[0]
    assert block.type == "resource"
    return base64.b64decode(block.resource.blob)


def _read_pdf(result) -> PdfReader:
    return PdfReader(io.BytesIO(_pdf_bytes(result)))


def _pdf_text(result) -> str:
    reader = _read_pdf(result)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


async def call_generate_pdf(text: str):
    async with Client(mcp) as client:
        return await client.call_tool("generate_pdf", {"text": text})


async def call_generate_pdf_error(text: str):
    async with Client(mcp) as client:
        result = await client.call_tool("generate_pdf", {"text": text}, raise_on_error=False)
        assert result.is_error
        return result


async def test_generate_pdf_plain_text_returns_pdf_bytes():
    result = await call_generate_pdf("Erster Absatz.\n\nZweiter Absatz mit mehr Text.")
    assert not result.is_error
    pdf = _pdf_bytes(result)
    assert pdf.startswith(b"%PDF-")
    text = _pdf_text(result)
    assert "Erster Absatz." in text
    assert "Zweiter Absatz" in text


async def test_generate_pdf_umlauts_render_correctly():
    result = await call_generate_pdf("Käse, schön, größer, Maße – Gewürzt.")
    pdf = _pdf_bytes(result)
    assert pdf.startswith(b"%PDF-")
    text = _pdf_text(result)
    assert "Käse, schön, größer, Maße – Gewürzt." in text


async def test_generate_pdf_empty_text_returns_error():
    result = await call_generate_pdf_error("")
    assert "text" in result.content[0].text


async def test_generate_pdf_markdown_headings_and_inline():
    md = "# Titel\n\n## Untertitel\n\n### Abschnitt\n\nPunkt **fett** und *kursiv*.\n"
    result = await call_generate_pdf(md)
    text = _pdf_text(result)
    assert "Titel" in text
    assert "Untertitel" in text
    assert "Abschnitt" in text
    assert "fett" in text
    assert "kursiv" in text
    assert "#" not in text
    assert "*" not in text
    assert "**" not in text


async def test_generate_pdf_markdown_bullet_list():
    md = "- Erster Punkt\n- Zweiter Punkt\n"
    result = await call_generate_pdf(md)
    text = _pdf_text(result)
    assert "Erster Punkt" in text
    assert "Zweiter Punkt" in text


async def test_generate_pdf_markdown_table():
    md = "| Name | Wert |\n|---|---|\n| Alpha | 1 |\n| Beta | 2 |\n"
    result = await call_generate_pdf(md)
    text = _pdf_text(result)
    for cell in ("Name", "Wert", "Alpha", "Beta"):
        assert cell in text
    assert "|" not in text
    assert "---" not in text


async def test_generate_pdf_markdown_code_block():
    md = "```\nprint('hello')\n```\n"
    result = await call_generate_pdf(md)
    text = _pdf_text(result)
    assert "print('hello')" in text
    assert "```" not in text


async def test_generate_pdf_markdown_multipage():
    paragraph = "Absatz mit etwas Text. " * 20
    md = "\n\n".join([f"## Abschnitt {i}\n\n{paragraph}" for i in range(15)])
    result = await call_generate_pdf(md)
    reader = _read_pdf(result)
    assert len(reader.pages) > 1
    text = _pdf_text(result)
    assert "Abschnitt 14" in text


async def test_generate_pdf_markdown_link_url_present():
    md = "[Mistral](https://mistral.ai)\n"
    result = await call_generate_pdf(md)
    pdf = _pdf_bytes(result)
    assert b"https://mistral.ai" in pdf
    text = _pdf_text(result)
    assert "Mistral" in text
    assert "[" not in text


# --- convert_to_pdf ---------------------------------------------------------


async def call_convert_to_pdf(content_b64: str, format: str):
    async with Client(mcp) as client:
        return await client.call_tool(
            "convert_to_pdf", {"content": content_b64, "format": format}, raise_on_error=False
        )


async def test_convert_to_pdf_invalid_base64_returns_error():
    result = await call_convert_to_pdf("!!!nicht-base64!!!", "docx")
    assert result.is_error
    assert "base64" in result.content[0].text


async def test_convert_to_pdf_unsupported_format_returns_error():
    result = await call_convert_to_pdf(base64.b64encode(b"datei").decode(), "txt")
    assert result.is_error
    assert "txt" in result.content[0].text


@pytest.mark.skipif(SOFFICE is None, reason="soffice not available in this environment")
async def test_convert_to_pdf_docx_returns_pdf():
    result = await call_convert_to_pdf(_fixture_b64("sample.docx"), "docx")
    assert not result.is_error, result.content[0].text
    pdf = _pdf_bytes(result)
    assert pdf.startswith(b"%PDF-")


@pytest.mark.skipif(SOFFICE is None, reason="soffice not available in this environment")
async def test_convert_to_pdf_xlsx_returns_pdf():
    result = await call_convert_to_pdf(_fixture_b64("sample.xlsx"), "xlsx")
    assert not result.is_error, result.content[0].text
    pdf = _pdf_bytes(result)
    assert pdf.startswith(b"%PDF-")


@pytest.mark.skipif(SOFFICE is None, reason="soffice not available in this environment")
async def test_convert_to_pdf_pptx_returns_pdf():
    result = await call_convert_to_pdf(_fixture_b64("sample.pptx"), "pptx")
    assert not result.is_error, result.content[0].text
    pdf = _pdf_bytes(result)
    assert pdf.startswith(b"%PDF-")


@pytest.mark.skipif(SOFFICE is None, reason="soffice not available in this environment")
async def test_convert_to_pdf_leaves_no_temp_files():
    import tempfile

    before = set(Path(tempfile.gettempdir()).iterdir())
    result = await call_convert_to_pdf(_fixture_b64("sample.docx"), "docx")
    assert not result.is_error, result.content[0].text
    after = set(Path(tempfile.gettempdir()).iterdir())
    assert not {p for p in after - before if p.name.startswith("convert_to_pdf_")}


@pytest.mark.skipif(SOFFICE is None, reason="soffice not available in this environment")
async def test_convert_to_pdf_corrupt_file_returns_error():
    result = await call_convert_to_pdf(_fixture_b64("corrupt.docx"), "docx")
    assert result.is_error
    assert "docx" in result.content[0].text or "conversion" in result.content[0].text
