from be.harness.memory import SessionStore

def test_new_session_has_uuid_and_empty_state():
    store = SessionStore()
    sid = store.new_session()
    s = store.get(sid)
    assert s["history"] == [] and s["slots"]["viewed_listings"] == []

def test_update_slots_and_history():
    store = SessionStore(); sid = store.new_session()
    store.append_message(sid, "user", "hi")
    store.update_slots(sid, budget=300000, brand_pref="Yamaha")
    s = store.get(sid)
    assert s["slots"]["budget"] == 300000 and s["history"][0]["content"] == "hi"

def test_set_viewed_preserves_order_and_resolves_ordinal():
    store = SessionStore(); sid = store.new_session()
    store.set_viewed(sid, [{"listing_id": "L001"}, {"listing_id": "L007"}])
    assert store.resolve_reference(sid, "第一台") == "L001"
    assert store.resolve_reference(sid, "第二台") == "L007"

def test_out_of_range_reference_returns_none():
    store = SessionStore(); sid = store.new_session()
    store.set_viewed(sid, [{"listing_id": "L001"}])
    assert store.resolve_reference(sid, "第三台") is None
