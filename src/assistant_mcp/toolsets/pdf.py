"""PDF toolset: generate PDFs from text/Markdown and convert Office files."""

import base64
import binascii
import io
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field
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
from weasyprint import HTML as WeasyprintHTML
from weasyprint.urls import URLFetcher

from assistant_mcp.toolsets.storage import upload_document

mcp = FastMCP("pdf")


class GenerationResult(BaseModel):
    """Public resource URL of a generated document in the storage bucket."""

    url: str = Field(
        description="Public resource URL of the generated document in the "
        "storage bucket. Bucket objects are deleted one month after creation.",
        examples=["https://storage.googleapis.com/bucket/pdf/object.pdf"],
    )


_PDF_CONTENT_TYPE = "application/pdf"

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
_FORMATS_DESC = ", ".join(f'"{item}"' for item in _SUPPORTED_FORMATS)

_GENERATE_FORMATS = ("auto", "markdown", "html")
_GENERATE_FORMATS_DESC = ", ".join(f'"{item}"' for item in _GENERATE_FORMATS)
_DATA_ONLY_FETCHER = URLFetcher(allowed_protocols={"data"})

_HTML_DOC_PREFIXES = (
    "<!doctype",
    "<html",
    "<head",
    "<body",
    "<title",
    "<meta",
    "<style",
    "<script",
)
_HTML_BLOCK_PREFIXES = (
    "<p>",
    "<p ",
    "<div",
    "<table",
    "<ul>",
    "<ul ",
    "<ol>",
    "<ol ",
    "<br",
    "<hr",
    "<h1",
    "<h2",
    "<h3",
    "<h4",
    "<h5",
    "<h6",
)
_MD_LINE_RE = re.compile(
    r"^(?:#{1,6} |- |\* |1\. |```|===|---\s*$|> |\|.*)"
)


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


def _detect_input_format(text: str) -> str:
    """Return ""html"" when HTML markup appears before any Markdown token.

    Scans stripped lines; the first line that carries an HTML indicator or
    a Markdown indicator decides. Plain text without any indicator stays
    Markdown. An HTML snippet embedded in leading Markdown content is
    therefore rendered by the Markdown pipeline, while HTML documents and
    fragments route to the HTML renderer.
    """
    for line in text.splitlines():
        stripped = line.strip().lower()
        if not stripped:
            continue
        if stripped.startswith(_HTML_DOC_PREFIXES + _HTML_BLOCK_PREFIXES):
            return "html"
        if _MD_LINE_RE.match(stripped):
            return "markdown"
    return "markdown"


def _render_html_to_pdf(html: str) -> bytes:
    try:
        return WeasyprintHTML(
            string=html, base_url=None, url_fetcher=_DATA_ONLY_FETCHER
        ).write_pdf()
    except Exception as exc:
        raise ToolError(f"HTML rendering failed: {exc}") from exc


_SUPERSCRIPT_RE = re.compile(r"\^(\{([^{}]+)\}|[A-Za-z0-9]+)")


def _render_text(text: str) -> str:
    """Escape plain text and turn ``^`` markers into superscript markup.

    ``x^2`` superscripts the following run of ASCII alphanumerics,
    ``x^{n+1}`` the braced group. A caret followed by anything else -
    empty, nested, or unclosed braces, non-ASCII characters,
    punctuation - stays a literal caret.
    """
    parts: list[str] = []
    pos = 0
    for match in _SUPERSCRIPT_RE.finditer(text):
        start, end = match.span()
        parts.append(_escape(text[pos:start]))
        content = match.group(2) if match.group(1).startswith("{") else match.group(1)
        parts.append(f"<super>{_escape(content)}</super>")
        pos = end
    parts.append(_escape(text[pos:]))
    return "".join(parts)


def _render_inline(tokens) -> str:
    parts: list[str] = []
    for tok in tokens:
        match tok.type:
            case "text":
                parts.append(_render_text(tok.content))
            case "code_inline":
                parts.append(f"<font face='Courier'>{_escape(tok.content)}</font>")
            case "strong_open":
                parts.append("<b>")
            case "strong_close":
                parts.append("</b>")
            case "em_open":
                parts.append("<i>")
            case "em_close":
                parts.append("</i>")
            case "link_open":
                href = _escape(tok.attrs.get("href", "")).replace('"', "&quot;")
                parts.append(f'<link href="{href}" color="#4472C4"><u>')
            case "link_close":
                parts.append("</u></link>")
            case "softbreak":
                parts.append(" ")
            case "image":
                pass
            case _:
                parts.append(_escape(tok.content) if tok.content else "")
    return "".join(parts)


def _render_list_item(inline_token) -> Paragraph:
    content = _render_inline(inline_token.children or [])
    return Paragraph(f"&bull; {content}", _STYLES["BodyText"])


def _consume_list(tokens, i: int, ordered: bool) -> tuple[list, int]:
    """Consume a bullet or ordered list (including nested lists) from tokens[i]."""
    flowables: list = []
    depth = 1
    number = 0
    i += 1
    while i < len(tokens) and depth > 0:
        tok = tokens[i]
        match (ordered, tok.type):
            case (True, "ordered_list_open") | (False, "bullet_list_open"):
                depth += 1
            case (True, "ordered_list_close") | (False, "bullet_list_close"):
                depth -= 1
            case (_, "list_item_open"):
                number += 1
            case (_, "inline"):
                if ordered:
                    flowables.append(
                        Paragraph(
                            f"{number}. {_render_inline(tok.children)}", _STYLES["BodyText"]
                        )
                    )
                else:
                    flowables.append(_render_list_item(tok))
                flowables.append(Spacer(1, 2))
        i += 1
    return flowables, i


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
        match tok.type:
            case "heading_open":
                level = int(tok.tag[1])
                inline = tokens[i + 1]
                style = _HEADING_STYLES.get(level, _HEADING_STYLES[4])
                story.append(Paragraph(_render_inline(inline.children), style))
                story.append(Spacer(1, 6))
                i += 3
            case "paragraph_open":
                inline = tokens[i + 1]
                story.append(Paragraph(_render_inline(inline.children), _STYLES["BodyText"]))
                story.append(Spacer(1, 8))
                i += 3
            case "bullet_list_open" | "ordered_list_open":
                items, i = _consume_list(tokens, i, ordered=tok.type == "ordered_list_open")
                story.extend(items)
            case "fence" | "code_block":
                story.append(Preformatted(_escape(tok.content), _CODE_STYLE))
                story.append(Spacer(1, 8))
                i += 1
            case "table_open":
                header_cells: list[str] = []
                rows: list[list[str]] = []
                i += 1
                current_row: list[str] = []
                in_header = False
                while i < len(tokens) and tokens[i].type != "table_close":
                    t = tokens[i]
                    match t.type:
                        case "thead_open":
                            in_header = True
                        case "thead_close":
                            in_header = False
                        case "tr_open":
                            current_row = []
                        case "tr_close":
                            if in_header:
                                header_cells = current_row
                            else:
                                rows.append(current_row)
                        case "th_open" | "td_open":
                            inline = tokens[i + 1]
                            current_row.append(_render_inline(inline.children))
                            i += 2
                    i += 1
                if header_cells or rows:
                    story.append(_render_table(header_cells, rows))
                    story.append(Spacer(1, 8))
                i += 1
            case _:
                if tok.content:
                    story.append(Paragraph(_escape(tok.content), _STYLES["BodyText"]))
                i += 1
    return story


@mcp.tool
async def generate_pdf(
    text: Annotated[
        str,
        Field(
            description="Content of the PDF: Markdown, plain text, or HTML.",
            examples=["# Quarterly Report\nRevenue is up."],
        ),
    ],
    format: Annotated[  # noqa: A002
        str,
        Field(
            description=(
                f"Input format: one of {_GENERATE_FORMATS_DESC}. "
                '"auto" (default) detects HTML vs. Markdown content; '
                '"markdown" and "html" force the respective renderer.'
            ),
            examples=["auto"],
        ),
    ] = "auto",
) -> GenerationResult:
    """Generate a PDF from Markdown, plain text, or HTML and return its
    public resource URL.

    Markdown supports headings, paragraphs, bullet and ordered lists,
    tables, code blocks, links, bold and italic. Math superscripts: a
    caret renders the following run of ASCII letters and digits as
    raised, smaller glyphs (``x^2``), and a braced group as a
    multi-character superscript (``x^{n+1}``); a caret followed by
    anything else (punctuation, non-ASCII, empty braces) stays
    literal (use code spans for literal carets in front of digits).
    German umlauts and quotes render correctly; characters outside
    the built-in Latin fonts (e.g. CJK) render as replacement glyphs.
    Image tokens in the Markdown input are not supported and are
    silently skipped (no error, no output).

    HTML input (fragments or full documents) is rendered with
    print-CSS fidelity: embedded ``<style>`` rules, inline styles, and
    ``@page`` geometry apply. External resources (images, stylesheets,
    fonts referenced by URL) are never fetched; data-URI resources
    embedded in the input are allowed.

    Args:
        text: Markdown, plain text, or HTML content of the PDF.
        format: "auto" detects the input type (HTML markup before any
            Markdown token routes to the HTML renderer); "markdown" and
            "html" override detection explicitly.

    Returns:
        Public resource URL of the uploaded PDF in the storage bucket
        (bucket objects are deleted one month after creation).
    """
    if not text.strip():
        raise ToolError("text must not be empty")
    fmt = (format or "auto").lower().strip()
    if fmt not in _GENERATE_FORMATS:
        supported = ", ".join(_GENERATE_FORMATS)
        raise ToolError(f"unsupported format: {format}. Use one of: {supported}")
    effective = fmt if fmt != "auto" else _detect_input_format(text)
    if effective == "html":
        data = _render_html_to_pdf(text)
    else:
        data = _build_pdf(_markdown_to_story(text))
    object_name = f"pdf/{uuid.uuid4()}.pdf"
    return GenerationResult(
        url=await upload_document(data, object_name, _PDF_CONTENT_TYPE)
    )


@mcp.tool
async def convert_to_pdf(
    content: Annotated[
        str,
        Field(
            description="Base64-encoded file content of the Office document.",
            examples=["UEsDBA=="],
        ),
    ],
    format: Annotated[
        str,
        Field(
            description=f"Source format: one of {_FORMATS_DESC}.",
            examples=["docx"],
        ),
    ],
) -> GenerationResult:
    """Convert a Microsoft Office file (DOCX, XLSX, PPTX) to PDF.

    The file content is passed as base64 so the tool works remotely
    without a shared filesystem. Note: very large files are limited
    by the request size of the transport (about 32 MB on Cloud Run).

    Returns:
        Public resource URL of the uploaded PDF in the storage bucket
        (bucket objects are deleted one month after creation).
    """
    fmt = format.lower().strip(".")
    if fmt not in _SUPPORTED_FORMATS:
        supported = ", ".join(_SUPPORTED_FORMATS)
        raise ToolError(f"unsupported format: {format}. Use one of: {supported}")
    try:
        data = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ToolError(f"invalid base64 input: {exc}") from exc
    if not data:
        raise ToolError("decoded file content is empty")

    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ToolError(f"invalid {fmt} file: not a valid OOXML container")

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
        try:
            process = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"conversion timed out for {fmt}") from exc
        if process.returncode != 0 or not result_file.exists():
            detail = process.stderr.decode(errors="replace").strip()
            raise ToolError(f"conversion failed for {fmt}: {detail or 'unknown error'}")
        object_name = f"pdf/{uuid.uuid4()}.pdf"
        return GenerationResult(
            url=await upload_document(
                result_file.read_bytes(), object_name, _PDF_CONTENT_TYPE
            )
        )
