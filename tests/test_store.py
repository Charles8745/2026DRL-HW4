from de.data.store import DataStore

def test_store_builds_all_tables():
    s = DataStore(seed=42)
    assert len(s.catalog) == 33
    assert len(s.listings) >= 33
    assert len(s.orders) >= 1
    assert s.tickets == []

def test_orders_reference_real_listings():
    s = DataStore(seed=42)
    ids = {l["listing_id"] for l in s.listings}
    for o in s.orders:
        assert o["listing_id"] in ids
        assert o["status"] in {"預約看車","出價中","已成交","已出貨","退款中"}

def test_add_ticket_appends():
    s = DataStore(seed=42)
    t = s.add_ticket("退款", "車況不符")
    assert t["ticket_id"] == "T001" and t["status"] == "open"
    assert s.tickets[-1]["category"] == "退款"
