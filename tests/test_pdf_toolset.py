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


# --- Tool-Schema (Input-Modelle) ---------------------------------------------


async def test_tool_input_schema_has_documented_parameters():
    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    assert set(tools) >= {"generate_pdf", "convert_to_pdf"}

    generate = tools["generate_pdf"]
    assert set(generate.input_schema["properties"]) == {"text"}
    text_prop = generate.input_schema["properties"]["text"]
    assert text_prop["type"] == "string"
    assert text_prop["description"].strip()
    assert isinstance(text_prop.get("examples"), list) and text_prop["examples"], (
        "generate_pdf parameter 'text' must carry at least one example"
    )

    convert = tools["convert_to_pdf"]
    assert set(convert.input_schema["properties"]) == {"content", "format"}
    for name, prop in convert.input_schema["properties"].items():
        assert prop["type"] == "string", name
        assert prop["description"].strip(), name
        assert isinstance(prop.get("examples"), list) and prop["examples"], (
            f"convert_to_pdf parameter {name!r} must carry at least one example"
        )


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


async def test_convert_to_pdf_empty_content_returns_error():
    result = await call_convert_to_pdf(base64.b64encode(b"").decode(), "docx")
    assert result.is_error
    assert "empty" in result.content[0].text


async def test_convert_to_pdf_invalid_ooxml_container_returns_error():
    result = await call_convert_to_pdf(base64.b64encode(b"not a real office file").decode(), "docx")
    assert result.is_error
    assert "invalid" in result.content[0].text


async def test_convert_to_pdf_soffice_missing_returns_error(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = await call_convert_to_pdf(_fixture_b64("sample.docx"), "docx")
    assert result.is_error
    assert "LibreOffice" in result.content[0].text


# --- Markdown-Vollständigkeit und Stile ------------------------------------


def _fonts(result) -> set[str]:
    reader = _read_pdf(result)
    fonts = set()
    for page in reader.pages:
        for font in (page.get("/Resources") or {}).get("/Font", {}).values():
            fonts.add(str(font.get_object()["/BaseFont"]))
    return fonts


async def test_generate_pdf_indented_code_block_renders_content():
    md = "Vorher\n\n    print('eingerückt')\n\nNachher\n"
    result = await call_generate_pdf(md)
    text = _pdf_text(result)
    assert "print('eingerückt')" in text
    assert "Vorher" in text
    assert "Nachher" in text


async def test_generate_pdf_ordered_list_keeps_numbering():
    md = "1. Erster Schritt\n2. Zweiter Schritt\n"
    result = await call_generate_pdf(md)
    text = _pdf_text(result)
    assert "1. Erster Schritt" in text
    assert "2. Zweiter Schritt" in text


async def test_generate_pdf_nested_bullet_list_renders_all_items():
    md = "- A\n  - A1\n  - A2\n- B\n"
    result = await call_generate_pdf(md)
    text = _pdf_text(result)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for item in ("A", "A1", "A2", "B"):
        assert any(line.endswith(f" {item}") for line in lines), lines


async def test_generate_pdf_unknown_block_falls_back_to_text():
    md = '<div>Blockinhalt</div>\n\nAbsatz danach.\n'
    result = await call_generate_pdf(md)
    text = _pdf_text(result)
    assert "Blockinhalt" in text


async def test_generate_pdf_style_distinction_between_elements():
    md = "# Titel\n\nFließtext.\n\n```\nprint('code')\n```\n"
    result = await call_generate_pdf(md)
    fonts = _fonts(result)
    assert any("Helvetica-Bold" in font for font in fonts), fonts
    assert any("Courier" in font for font in fonts), fonts


async def test_generate_pdf_whitespace_only_returns_error():
    result = await call_generate_pdf_error("   \n\t  ")
    assert "text" in result.content[0].text
