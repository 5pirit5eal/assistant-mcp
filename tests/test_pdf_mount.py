"""Tests for the pdf toolset mounted through the toolset registry."""

from fastmcp import Client

from assistant_mcp.toolsets import TOOLSETS


async def test_pdf_toolset_mountable():
    async with Client(TOOLSETS["pdf"]) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        assert "generate_pdf" in tool_names
        assert "convert_to_pdf" in tool_names
