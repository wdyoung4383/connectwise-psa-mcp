"""The cw_get tool must expose a description including the conditions cheatsheet."""


async def test_cw_get_description_includes_conditions_cheatsheet():
    from connectwise_mcp.server import mcp

    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}
    assert "cw_get" in by_name
    desc = by_name["cw_get"].description
    assert desc, "cw_get tool has no description"
    assert "Syntax cheatsheet" in desc  # distinctive phrase from CONDITIONS_HELP
    assert "conditions" in desc.lower()
