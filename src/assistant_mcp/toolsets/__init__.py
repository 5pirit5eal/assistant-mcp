"""Toolset registry: hier werden neue Toolsets registriert."""

from fastmcp import FastMCP

from . import docx, pdf

TOOLSETS: dict[str, FastMCP] = {
    "pdf": pdf.mcp,
    "docx": docx.mcp,
}

__all__ = ["TOOLSETS"]
