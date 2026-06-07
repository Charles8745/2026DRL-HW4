import re

_INJECTION = ["忽略前述", "ignore previous", "ignore all previous", "system prompt",
              "系統提示", "系統指令", "洩漏", "reveal your", "開發者模式", "developer mode",
              "印出上面", "印出你的", "repeat the above", "隱藏指令", "無視所有", "無視先前"]
_AFFIRM = ["好", "確認", "對", "是的", "ok", "yes", "沒問題", "可以"]
_NEGATE = ["不要", "先不", "取消", "no", "不用"]

def check_input(text: str) -> dict:
    low = text.lower()
    blocked = any(k.lower() in low for k in _INJECTION)
    return {"blocked": blocked, "reason": "疑似 prompt-injection" if blocked else None}

def is_affirmative(text: str) -> bool:
    if any(n in text.lower() for n in _NEGATE):
        return False
    return any(a in text.lower() for a in _AFFIRM)

def groundedness_violations(answer: str, facts: dict) -> list[str]:
    """Return price-like numbers in the answer not present in tool facts."""
    allowed = {str(p) for p in facts.get("prices", [])}
    # not \b: CJK are word chars in Python's Unicode regex, so "250000元" would be missed.
    nums = re.findall(r"(?<!\d)\d{5,7}(?!\d)", answer.replace(",", ""))
    return [n for n in nums if n not in allowed]

class TurnBudget:
    def __init__(self, max_calls: int):
        self.max_calls, self.used = max_calls, 0
    def allow(self) -> bool:
        if self.used >= self.max_calls:
            return False
        self.used += 1
        return True
