from de.data.store import DataStore
from be.harness.tools import create_ticket, escalate_to_human

def test_create_ticket():
    S = DataStore(seed=42)
    r = create_ticket(S, category="退款", description="車況不符")
    assert r["ok"] and r["data"]["ticket_id"] == "T001"

def test_escalate_returns_handoff():
    S = DataStore(seed=42)
    r = escalate_to_human(S, reason="買賣糾紛")
    assert r["ok"] and r["data"]["handoff"] is True
