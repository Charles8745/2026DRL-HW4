import uuid, re

_ORDINALS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}

def _empty_slots():
    return {"budget": None, "brand_pref": None, "usage": None,
            "viewed_listings": [], "pending_intent": None, "pending_action": None}

class SessionStore:
    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def new_session(self) -> str:
        sid = uuid.uuid4().hex
        self._sessions[sid] = {"history": [], "slots": _empty_slots()}
        return sid

    def get(self, sid: str) -> dict:
        if sid not in self._sessions:
            self._sessions[sid] = {"history": [], "slots": _empty_slots()}
        return self._sessions[sid]

    def append_message(self, sid, role, content):
        self.get(sid)["history"].append({"role": role, "content": content})

    def update_slots(self, sid, **kw):
        self.get(sid)["slots"].update({k: v for k, v in kw.items() if v is not None})

    def set_viewed(self, sid, listings: list[dict]):
        self.get(sid)["slots"]["viewed_listings"] = listings   # order preserved

    def resolve_reference(self, sid, text: str) -> str | None:
        viewed = self.get(sid)["slots"]["viewed_listings"]
        m = re.search(r"第\s*([一二三四五12345])\s*台", text)
        if m:
            idx = _ORDINALS[m.group(1)] - 1
            return viewed[idx]["listing_id"] if 0 <= idx < len(viewed) else None
        if ("那台" in text or "上一台" in text) and viewed:
            return viewed[-1]["listing_id"]
        return None
