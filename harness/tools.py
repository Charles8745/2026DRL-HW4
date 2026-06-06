from data.store import DataStore
from harness.retrieval.retriever import FINAL_K

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

def semantic_search(store, query, budget=None, usage=None):
    """Hybrid retrieval (BM25 + dense RAG + rerank) over catalog models, expanded
    to in-sale listings. Returns a FLAT list of enriched listing dicts (same shape
    as search_listings, plus match_snippet / retrieval_rank) so groundedness and
    ordinal reference work unchanged."""
    models = store.retriever.retrieve(query, k=FINAL_K)
    rows = []
    for m in models:
        if usage and m["usage"] != usage:
            continue
        for l in store.listings:
            if l["model"] != m["title"] or l["status"] != "在售":
                continue
            if budget and l["asking_price"] > int(budget):
                continue
            rows.append({**_enrich(store, l),
                         "match_snippet": m["snippet"],
                         "retrieval_rank": m["retrieval_rank"]})
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

def check_order(store, order_id=None, buyer=None):
    if order_id:
        o = next((o for o in store.orders if o["order_id"] == order_id), None)
        return _ok(o) if o else _err(f"查無訂單 {order_id}")
    if buyer:
        rows = [o for o in store.orders if o["buyer"] == buyer]
        return _ok(rows) if rows else _err(f"查無買家 {buyer} 的訂單")
    return _err("請提供 order_id 或 buyer")

def book_viewing(store, listing_id, datetime, contact):
    l = store.listing(listing_id)
    if not l:
        return _err(f"找不到刊登 {listing_id}")
    oid = f"O{len(store.orders)+1:03d}"
    order = {"order_id": oid, "listing_id": listing_id, "buyer": contact,
             "status": "預約看車", "created_at": datetime, "updated_at": datetime}
    store.orders.append(order)
    return _ok(order)

def create_ticket(store, category, description):
    return _ok(store.add_ticket(category, description))

def escalate_to_human(store, reason):
    return _ok({"handoff": True, "reason": reason,
                "message": "已為您轉接真人客服，稍後將有專人聯繫。"})

TOOL_FUNCS = {
    "search_listings": search_listings, "recommend": recommend,
    "semantic_search": semantic_search,
    "get_listing_detail": get_listing_detail, "compare_models": compare_models,
    "check_order": check_order, "book_viewing": book_viewing,
    "create_ticket": create_ticket, "escalate_to_human": escalate_to_human,
}
TOOL_GROUPS = {
    "找車推薦": ["search_listings", "recommend", "semantic_search"],
    "規格比較": ["get_listing_detail", "compare_models"],
    "交易訂單": ["check_order", "book_viewing"],
    "售後轉真人": ["create_ticket", "escalate_to_human"],
}
CONFIRM_REQUIRED = {"book_viewing", "create_ticket", "escalate_to_human"}

def _p(props, required):  # build a JSON-schema object
    return {"type": "object", "properties": props, "required": required}

TOOL_SCHEMAS = {
    "search_listings": {"name": "search_listings",
        "description": "依品牌/價格上限/年份/車種篩選在售二手刊登",
        "parameters": _p({"brand_pref": {"type": "string"}, "max_price": {"type": "integer"},
                          "year_from": {"type": "integer"},
                          "usage": {"type": "string",
                                    "enum": ["sport","naked","touring","adventure","scooter","cruiser"]}}, [])},
    "recommend": {"name": "recommend", "description": "依預算/車種推薦並由低到高排序",
        "parameters": _p({"budget": {"type": "integer"}, "usage": {"type": "string"},
                          "brand_pref": {"type": "string"}}, ["budget"])},
    "semantic_search": {"name": "semantic_search",
        "description": "以自然語言語意檢索車款（用途/情境/模糊偏好，如『新手通勤省油好停』），回傳相關在售刈登。查詢若已含明確品牌/車種/價格條件，請改用 search_listings 或 recommend。",
        "parameters": _p({"query": {"type": "string"}, "budget": {"type": "integer"},
                          "usage": {"type": "string"}}, ["query"])},
    "get_listing_detail": {"name": "get_listing_detail", "description": "取得單一刊登完整規格與車況",
        "parameters": _p({"listing_id": {"type": "string"}}, ["listing_id"])},
    "compare_models": {"name": "compare_models", "description": "並排比較兩車款規格與價格",
        "parameters": _p({"model_a": {"type": "string"}, "model_b": {"type": "string"}}, ["model_a","model_b"])},
    "check_order": {"name": "check_order", "description": "以訂單編號或買家查交易/出貨/退款狀態",
        "parameters": _p({"order_id": {"type": "string"}, "buyer": {"type": "string"}}, [])},
    "book_viewing": {"name": "book_viewing", "description": "為指定刊登建立預約看車（狀態變更）",
        "parameters": _p({"listing_id": {"type": "string"}, "datetime": {"type": "string"},
                          "contact": {"type": "string"}}, ["listing_id","datetime","contact"])},
    "create_ticket": {"name": "create_ticket", "description": "建立客訴/退款工單（狀態變更）",
        "parameters": _p({"category": {"type": "string"}, "description": {"type": "string"}}, ["category","description"])},
    "escalate_to_human": {"name": "escalate_to_human", "description": "轉接真人客服（狀態變更）",
        "parameters": _p({"reason": {"type": "string"}}, ["reason"])},
}

def schemas_for(domain: str) -> list[dict]:
    return [TOOL_SCHEMAS[n] for n in TOOL_GROUPS[domain]]
