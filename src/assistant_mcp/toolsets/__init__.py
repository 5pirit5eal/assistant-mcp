"""Toolset registry: hier werden neue Toolsets registriert."""

from fastmcp import FastMCP

from . import echo, pdf, time_

TOOLSETS: dict[str, FastMCP] = {
    "echo": echo.mcp,
    "pdf": pdf.mcp,
    "time": time_.mcp,
}

__all__ = ["TOOLSETS"]
