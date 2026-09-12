"""Tool registration: names, descriptions and MCP annotations."""


async def test_cw_get_description_includes_conditions_cheatsheet():
    from connectwise_mcp.server import mcp

    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}
    assert "cw_get" in by_name
    desc = by_name["cw_get"].description
    assert desc, "cw_get tool has no description"
    assert "Syntax cheatsheet" in desc  # distinctive phrase from CONDITIONS_HELP
    assert "conditions" in desc.lower()


async def test_all_gateway_tools_registered_and_no_delete_tool():
    from connectwise_mcp.server import mcp

    names = {t.name for t in await mcp.list_tools()}
    assert {
        "list_modules",
        "search_endpoints",
        "describe_endpoint",
        "cw_get",
        "cw_post",
        "cw_put",
        "cw_patch",
    } <= names
    assert not any("delete" in n.lower() for n in names)


async def test_read_tools_are_read_only_and_write_tools_are_not():
    from connectwise_mcp.server import mcp

    by_name = {t.name: t for t in await mcp.list_tools()}
    for name in ("list_modules", "search_endpoints", "describe_endpoint", "cw_get"):
        assert by_name[name].annotations.readOnlyHint is True, name
    for name in ("cw_post", "cw_put", "cw_patch"):
        assert by_name[name].annotations.readOnlyHint is False, name
    assert by_name["cw_put"].annotations.destructiveHint is True


async def test_patch_description_explains_json_patch():
    from connectwise_mcp.server import mcp

    by_name = {t.name: t for t in await mcp.list_tools()}
    desc = by_name["cw_patch"].description
    assert '"op": "replace"' in desc
