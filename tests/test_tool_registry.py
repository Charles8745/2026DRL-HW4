from harness.tools import TOOL_GROUPS, TOOL_FUNCS, schemas_for

def test_four_groups_findcar_has_three_tools():
    assert set(TOOL_GROUPS) == {"找車推薦","規格比較","交易訂單","售後轉真人"}
    # 找車推薦 has 3 tools (incl. read-only semantic_search); the other groups have 2
    assert len(TOOL_GROUPS["找車推薦"]) == 3
    assert all(len(v) == 2 for k, v in TOOL_GROUPS.items() if k != "找車推薦")

def test_every_tool_has_callable_and_schema():
    for names in TOOL_GROUPS.values():
        for n in names:
            assert callable(TOOL_FUNCS[n])
    schemas = schemas_for("找車推薦")
    assert {s["name"] for s in schemas} == {"search_listings","recommend","semantic_search"}
    assert "parameters" in schemas[0]
