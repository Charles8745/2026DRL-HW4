from be.harness.prompts import handler_sys

def test_find_handler_asks_for_concise_summary():
    s = handler_sys("找車推薦")
    assert "1-2 句" in s or "1–2 句" in s
    assert "不要" in s and "重述" in s   # 不重述卡片規格
    assert "JSON" in s                  # 反原始資料傾印守門（real-browser 抓到的 JSON dump 失效模式）
    assert "價格可自然帶到" in s         # 刻意保留價格可述 → groundedness 仍可量測
