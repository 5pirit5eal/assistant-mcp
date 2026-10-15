"""Time toolset: current time utilities."""

from datetime import UTC, datetime

from fastmcp import FastMCP

mcp = FastMCP("time")


@mcp.tool
def now_utc() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(UTC).isoformat()
