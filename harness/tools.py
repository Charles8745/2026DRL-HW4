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

_SENTINEL = "資料未提供"

def get_listing_detail(store, listing_id):
    l = store.listing(listing_id)
    if not l:
        return _err(f"找不到刊登 {listing_id}")
    return _ok(_enrich(store, l))

def _spec_view(specs: dict) -> dict:
    fields = ["displacement_cc", "horsepower", "torque_nm", "seat_height_mm", "weight_kg"]
    return {f: (specs.get(f) if specs.get(f) is not None else _SENTINEL) for f in fields}

def compare_models(store, model_a, model_b):
    out = {}
    for m in (model_a, model_b):
        cat = store.catalog_for(m)
        if not cat:
            return _err(f"型錄查無車款：{m}")
        out[m] = {"brand": cat["brand"], "usage": cat["usage"],
                  "price": cat["price"], **_spec_view(cat["specs"])}
    return _ok(out)
