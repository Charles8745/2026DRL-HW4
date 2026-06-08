from be.harness.prompts import handler_sys

def test_find_handler_asks_for_concise_summary():
    s = handler_sys("找車推薦")
    assert "1-2 句" in s or "1–2 句" in s
    assert "不要" in s and "重述" in s   # 不重述卡片規格
