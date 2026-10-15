"""Echo toolset: minimal reference implementation for new toolsets."""

from fastmcp import FastMCP

mcp = FastMCP("echo")


@mcp.tool
def echo(text: str) -> str:
    """Return the input text unchanged."""
    return text
