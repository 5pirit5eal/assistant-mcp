"""PDF toolset: generate PDFs from text/Markdown and convert Office files."""

import base64
import binascii
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import File
from markdown_it import MarkdownIt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

mcp = FastMCP("pdf")

_MD = MarkdownIt("commonmark").enable("table")
_STYLES = getSampleStyleSheet()
_HEADING_STYLES = {
    1: _STYLES["Heading1"],
    2: _STYLES["Heading2"],
    3: _STYLES["Heading3"],
    4: _STYLES["Heading4"],
}
_CODE_STYLE = ParagraphStyle(
    "Code",
    parent=_STYLES["Code"],
    fontName="Courier",
    fontSize=9,
    leading=12,
    backColor=colors.whitesmoke,
    borderPadding=6,
)
_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#E7EDF7")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B0B0B0")),
    ]
)
_SUPPORTED_FORMATS = ("docx", "xlsx", "pptx")


def _build_pdf(story: list) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Generated PDF",
    )
    doc.build(story)
    return buffer.getvalue()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_inline(tokens) -> str:
    parts: list[str] = []
    for tok in tokens:
        if tok.type == "text":
            parts.append(_escape(tok.content))
        elif tok.type == "code_inline":
            parts.append(f"<font face='Courier'>{_escape(tok.content)}</font>")
        elif tok.type == "strong_open":
            parts.append("<b>")
        elif tok.type == "strong_close":
            parts.append("</b>")
        elif tok.type == "em_open":
            parts.append("<i>")
        elif tok.type == "em_close":
            parts.append("</i>")
        elif tok.type == "link_open":
            href = _escape(tok.attrs.get("href", "")).replace('"', "&quot;")
            parts.append(f'<link href="{href}" color="#4472C4"><u>')
        elif tok.type == "link_close":
            parts.append("</u></link>")
        elif tok.type == "softbreak":
            parts.append(" ")
        elif tok.type == "image":
            pass
        else:
            parts.append(_escape(tok.content) if tok.content else "")
    return "".join(parts)


def _token_text(token) -> str:
    parts = []
    for tok in token.children or []:
        parts.append(tok.content if tok.type == "text" else "")
    return "".join(parts)


def _render_list_item(inline_token) -> Paragraph:
    content = _render_inline(inline_token.children or [])
    return Paragraph(f"&bull; {content}", _STYLES["BodyText"])


def _render_table(header_cells: list[str], rows: list[list[str]]) -> Table:
    data = [[Paragraph(cell, _STYLES["BodyText"]) for cell in header_cells]]
    for row in rows:
        data.append([Paragraph(cell, _STYLES["BodyText"]) for cell in row])
    table = Table(data, hAlign="LEFT")
    table.setStyle(_TABLE_STYLE)
    return table


def _markdown_to_story(markdown: str) -> list:
    story: list = []
    tokens = _MD.parse(markdown)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type in ("heading_open",):
            level = int(tok.tag[1])
            inline = tokens[i + 1]
            style = _HEADING_STYLES.get(level, _HEADING_STYLES[4])
            story.append(Paragraph(_render_inline(inline.children), style))
            story.append(Spacer(1, 6))
            i += 3
        elif tok.type == "paragraph_open":
            inline = tokens[i + 1]
            story.append(Paragraph(_render_inline(inline.children), _STYLES["BodyText"]))
            story.append(Spacer(1, 8))
            i += 3
        elif tok.type == "bullet_list_open":
            i += 1
            while i < len(tokens) and tokens[i].type != "bullet_list_close":
                if tokens[i].type == "list_item_open":
                    j = i + 1
                    while tokens[j].type != "inline":
                        j += 1
                    story.append(_render_list_item(tokens[j]))
                    story.append(Spacer(1, 2))
                    i += 1
                else:
                    i += 1
            i += 1
        elif tok.type == "fence":
            story.append(Preformatted(_escape(tok.content), _CODE_STYLE))
            story.append(Spacer(1, 8))
            i += 1
        elif tok.type == "table_open":
            header_cells: list[str] = []
            rows: list[list[str]] = []
            i += 1
            current_row: list[str] = []
            in_header = False
            while i < len(tokens) and tokens[i].type != "table_close":
                t = tokens[i]
                if t.type == "thead_open":
                    in_header = True
                elif t.type == "thead_close":
                    in_header = False
                elif t.type == "tr_open":
                    current_row = []
                elif t.type == "tr_close":
                    if in_header:
                        header_cells = current_row
                    else:
                        rows.append(current_row)
                elif t.type in ("th_open", "td_open"):
                    inline = tokens[i + 1]
                    current_row.append(_render_inline(inline.children))
                    i += 2
                i += 1
            if header_cells or rows:
                story.append(_render_table(header_cells, rows))
                story.append(Spacer(1, 8))
            i += 1
        else:
            i += 1
    return story


@mcp.tool
def generate_pdf(text: str) -> File:
    """Generate a PDF from Markdown or plain text and return it as a file.

    Supports Markdown: headings, paragraphs, bullet lists, tables, code
    blocks, links, bold and italic. German umlauts render correctly.

    Args:
        text: Markdown or plain text content of the PDF.

    Returns:
        The generated PDF as a downloadable file.
    """
    if not text.strip():
        raise ToolError("text must not be empty")
    return File(data=_build_pdf(_markdown_to_story(text)), name="output.pdf", format="pdf")


@mcp.tool
def convert_to_pdf(content: str, format: str) -> File:
    """Convert a Microsoft Office file (DOCX, XLSX, PPTX) to PDF.

    The file content is passed as base64 so the tool works remotely
    without a shared filesystem. Note: very large files are limited
    by the request size of the transport (about 32 MB on Cloud Run).

    Args:
        content: Base64-encoded file content of the Office document.
        format: Source format: "docx", "xlsx" or "pptx".

    Returns:
        The converted PDF as a downloadable file.
    """
    fmt = format.lower().strip(".")
    if fmt not in _SUPPORTED_FORMATS:
        raise ToolError(f"unsupported format: {format}. Use one of: docx, xlsx, pptx")
    try:
        data = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ToolError(f"invalid base64 input: {exc}") from exc
    if not data:
        raise ToolError("decoded file content is empty")

    if shutil.which("soffice") is None:
        raise ToolError("LibreOffice (soffice) is not available on the server")

    with tempfile.TemporaryDirectory(prefix="convert_to_pdf_") as tmpdir:
        source = Path(tmpdir) / f"input.{fmt}"
        source.write_bytes(data)
        profile = Path(tmpdir) / "lo-profile"
        profile.mkdir()
        result_file = Path(tmpdir) / "input.pdf"
        cmd = [
            "soffice",
            "--headless",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to",
            "pdf",
            "--outdir",
            tmpdir,
            str(source),
        ]
        process = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        if process.returncode != 0 or not result_file.exists():
            detail = process.stderr.decode(errors="replace").strip()
            raise ToolError(f"conversion failed for {fmt}: {detail or 'unknown error'}")
        return File(data=result_file.read_bytes(), name="input.pdf", format="pdf")
