from harness.prompts import REWRITER_SYS, ROUTER_SYS, FALLBACK_SYS, handler_sys

def test_router_lists_all_five_labels():
    for label in ["找車推薦","規格比較","交易訂單","售後轉真人","閒聊範圍外"]:
        assert label in ROUTER_SYS

def test_handler_sys_mentions_groundedness_rule():
    s = handler_sys("找車推薦")
    assert "工具" in s and ("不可捏造" in s or "groundedness" in s.lower())
