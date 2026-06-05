from harness.tools import TOOL_GROUPS, TOOL_FUNCS, schemas_for

def test_four_groups_with_two_tools_each():
    assert set(TOOL_GROUPS) == {"找車推薦","規格比較","交易訂單","售後轉真人"}
    assert all(len(v) == 2 for v in TOOL_GROUPS.values())

def test_every_tool_has_callable_and_schema():
    for names in TOOL_GROUPS.values():
        for n in names:
            assert callable(TOOL_FUNCS[n])
    schemas = schemas_for("找車推薦")
    assert {s["name"] for s in schemas} == {"search_listings","recommend"}
    assert "parameters" in schemas[0]
