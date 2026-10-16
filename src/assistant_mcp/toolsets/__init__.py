"""Toolset registry: hier werden neue Toolsets registriert."""

from fastmcp import FastMCP

from . import pdf

TOOLSETS: dict[str, FastMCP] = {
    "pdf": pdf.mcp,
}

__all__ = ["TOOLSETS"]
