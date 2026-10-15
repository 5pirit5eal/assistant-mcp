from fastmcp import Client

from assistant_mcp.toolsets import TOOLSETS


async def test_all_toolsets_mountable():
    async with Client(TOOLSETS["echo"]) as client:
        result = await client.call_tool("echo", {"text": "hello"})
        assert result.content[0].text == "hello"


async def test_now_utc():
    async with Client(TOOLSETS["time"]) as client:
        result = await client.call_tool("now_utc", {})
        assert result.content[0].text  # non-empty ISO timestamp
