"""Regenerate the docx toolset's reference theme asset.

Fetches pandoc's default reference document and restyles it with python-docx
to match the pdf toolset's visual language (accent #4472C4, zebra rows
#E7EDF7, border gray #B0B0B0), then writes it to
src/assistant_mcp/toolsets/docx_reference.docx.

Dev script; not part of the shipped package. Requires pandoc on PATH.
Run from the repo root: uv run scripts/build_docx_reference.py
"""

import io
import subprocess
import sys
import zipfile
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor
from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "src" / "assistant_mcp" / "toolsets" / "docx_reference.docx"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}

ACCENT = "4472C4"
ZEBRA = "E7EDF7"
BORDER = "B0B0B0"
BORDER_SIZE = "4"  # eighths of a point; 4 = 0.5pt, matching the pdf grid

HEADING_SIZES = {1: 18, 2: 16, 3: 14, 4: 12}


def _qn(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _fetch_default_reference() -> bytes:
    process = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"],
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.decode(errors="replace").strip()
        sys.exit(f"pandoc failed: {detail or 'unknown error'}")
    return process.stdout


def _subelement(parent: etree._Element, tag: str, **attributes: str) -> etree._Element:
    element = etree.SubElement(parent, _qn(tag), nsmap=NSMAP)
    for name, value in attributes.items():
        element.set(_qn(name), value)
    return element


def _restyle_headings(document: Document) -> None:
    """Accent color on all heading styles; explicit sizes for the common levels."""
    for style in document.styles:
        if not style.name.startswith("Heading "):
            continue
        level_text = style.name.removeprefix("Heading ")
        if not level_text.isdigit():
            continue
        style.font.color.rgb = RGBColor.from_string(ACCENT)
        if int(level_text) in HEADING_SIZES:
            style.font.size = Pt(HEADING_SIZES[int(level_text)])


def _table_style_element(document: Document) -> etree._Element:
    for style in document.styles:
        if style.name == "Table":
            return style.element
    sys.exit("pandoc reference document has no 'Table' style")


def _set_border(tag: str, parent: etree._Element) -> None:
    _subelement(parent, tag, val="single", sz=BORDER_SIZE, space="0", color=BORDER)


def _restyle_table(element: etree._Element) -> None:
    # Table-wide visible cell borders (inside tblPr, before tblCellMar).
    tbl_pr = element.find(_qn("tblPr"))
    if tbl_pr is None:
        sys.exit("Table style has no tblPr")
    old_borders = tbl_pr.find(_qn("tblBorders"))
    if old_borders is not None:
        tbl_pr.remove(old_borders)
    tbl_borders = etree.Element(_qn("tblBorders"), nsmap=NSMAP)
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        _set_border(side, tbl_borders)
    cell_mar = tbl_pr.find(_qn("tblCellMar"))
    insert_at = list(tbl_pr).index(cell_mar) if cell_mar is not None else len(tbl_pr)
    tbl_pr.insert(insert_at, tbl_borders)

    # firstRow conditional formatting: shaded accent background, white bold text.
    first_row = element.find(f"{_qn('tblStylePr')}[@{_qn('type')}='firstRow']")
    if first_row is None:
        sys.exit("Table style has no firstRow conditional formatting")
    for child in list(first_row):
        first_row.remove(child)
    run_props = etree.Element(_qn("rPr"), nsmap=NSMAP)
    _subelement(run_props, "b")
    _subelement(run_props, "color", val="FFFFFF")
    _subelement(run_props, "shd", val="clear", color="auto", fill=ACCENT)
    first_row.insert(0, run_props)
    cell_props = _subelement(first_row, "tcPr")
    header_borders = _subelement(cell_props, "tcBorders")
    for side in ("top", "left", "bottom", "right"):
        _set_border(side, header_borders)
    _subelement(cell_props, "vAlign", val="bottom")

    # Zebra striping on even body rows.
    band = _subelement(element, "tblStylePr", type="band2Horz")
    band_cell_props = _subelement(band, "tcPr")
    _subelement(band_cell_props, "shd", val="clear", color="auto", fill=ZEBRA)


def _repack_deterministic(data: bytes) -> bytes:
    """Rewrite the zip with fixed timestamps so reruns are byte-identical."""
    source = zipfile.ZipFile(io.BytesIO(data))
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in source.namelist():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = source.getinfo(name).external_attr
            archive.writestr(info, source.read(name))
    return target.getvalue()


def main() -> None:
    document = Document(io.BytesIO(_fetch_default_reference()))
    _restyle_headings(document)
    _restyle_table(_table_style_element(document))
    buffer = io.BytesIO()
    document.save(buffer)
    OUTPUT_PATH.write_bytes(_repack_deterministic(buffer.getvalue()))
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({OUTPUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
