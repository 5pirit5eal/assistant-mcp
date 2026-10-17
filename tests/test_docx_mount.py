"""Tests for the docx toolset mounted through the toolset registry."""

from fastmcp import Client

from assistant_mcp.toolsets import TOOLSETS


async def test_docx_toolset_mountable():
    async with Client(TOOLSETS["docx"]) as client:
        tools = await client.list_tools()
        tool_by_name = {tool.name: tool for tool in tools}
        assert "convert_to_docx" in tool_by_name
        properties = tool_by_name["convert_to_docx"].input_schema["properties"]
        assert set(properties) == {"content", "format", "title"}
