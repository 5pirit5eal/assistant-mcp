"""Toolset registry: hier werden neue Toolsets registriert."""

from fastmcp import FastMCP

from . import echo, time_

TOOLSETS: dict[str, FastMCP] = {
    "echo": echo.mcp,
    "time": time_.mcp,
}

__all__ = ["TOOLSETS"]
