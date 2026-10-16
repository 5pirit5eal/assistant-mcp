from fastmcp import Client

from assistant_mcp.toolsets import TOOLSETS


async def test_no_bootstrap_tools_offered():
    assert TOOLSETS, "toolset registry is empty"
    for name, toolset in TOOLSETS.items():
        async with Client(toolset) as client:
            tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        assert "echo" not in tool_names, f"toolset {name} offers bootstrap tool 'echo'"
        assert "now_utc" not in tool_names, f"toolset {name} offers bootstrap tool 'now_utc'"


async def test_registry_compliance_tool_parameters_and_outputs():
    assert TOOLSETS, "toolset registry is empty"
    for name, toolset in TOOLSETS.items():
        async with Client(toolset) as client:
            tools = await client.list_tools()
        for tool in tools:
            properties = tool.input_schema.get("properties", {})
            for param_name, schema in properties.items():
                description = (schema or {}).get("description", "")
                assert description and description.strip(), (
                    f"parameter {param_name!r} of tool {tool.name!r} "
                    f"in toolset {name!r} lacks a non-empty description"
                )
                examples = (schema or {}).get("examples", [])
                assert isinstance(examples, list) and examples, (
                    f"parameter {param_name!r} of tool {tool.name!r} "
                    f"in toolset {name!r} lacks at least one example"
                )
            output_schema = tool.output_schema
            plain_string_output = output_schema is not None and (
                output_schema.get("type") == "string"
                or output_schema.get("x-fastmcp-wrap-result", False)
            )
            assert not plain_string_output, (
                f"tool {tool.name!r} in toolset {name!r} "
                f"returns a plain unstructured string"
            )
