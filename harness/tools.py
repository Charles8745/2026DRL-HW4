from data.store import DataStore

def _ok(data):  return {"ok": True, "data": data, "error": None}
def _err(msg):  return {"ok": False, "data": None, "error": msg}

def _enrich(store: DataStore, listing: dict) -> dict:
    cat = store.catalog_for(listing["model"]) or {}
    return {**listing, "brand": cat.get("brand"), "usage": cat.get("usage"),
            "specs": cat.get("specs", {})}

def search_listings(store, brand_pref=None, max_price=None, year_from=None, usage=None):
    rows = [_enrich(store, l) for l in store.listings if l["status"] == "在售"]
    if brand_pref: rows = [r for r in rows if r["brand"] == brand_pref]
    if usage:      rows = [r for r in rows if r["usage"] == usage]
    if max_price:  rows = [r for r in rows if r["asking_price"] <= int(max_price)]
    if year_from:  rows = [r for r in rows if r["year"] >= int(year_from)]
    return _ok(rows)

def recommend(store, budget, usage=None, brand_pref=None):
    r = search_listings(store, brand_pref=brand_pref, max_price=budget, usage=usage)
    rows = sorted(r["data"], key=lambda x: x["asking_price"])
    return _ok(rows)
