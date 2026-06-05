from data.store import DataStore
from harness.tools import check_order, book_viewing

def test_check_order_by_id():
    S = DataStore(seed=42)
    oid = S.orders[0]["order_id"]
    r = check_order(S, order_id=oid)
    assert r["ok"] and r["data"]["order_id"] == oid

def test_check_order_unknown():
    S = DataStore(seed=42)
    r = check_order(S, order_id="O999")
    assert not r["ok"]

def test_book_viewing_creates_order():
    S = DataStore(seed=42)
    lid = S.listings[0]["listing_id"]
    n = len(S.orders)
    r = book_viewing(S, listing_id=lid, datetime="2026-06-13", contact="0912000000")
    assert r["ok"] and r["data"]["status"] == "預約看車"
    assert len(S.orders) == n + 1

def test_book_viewing_unknown_listing():
    S = DataStore(seed=42)
    r = book_viewing(S, listing_id="L999", datetime="2026-06-13", contact="x")
    assert not r["ok"]
