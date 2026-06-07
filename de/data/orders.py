import random

_STATUSES = ["預約看車", "出價中", "已成交", "已出貨", "退款中"]
_BUYERS = ["user_001", "user_002", "user_003", "user_004"]

def synth_orders(listings: list[dict], seed: int = 42, count: int = 12) -> list[dict]:
    rng = random.Random(seed + 1)
    sample = rng.sample(listings, min(count, len(listings)))
    out = []
    for i, l in enumerate(sample, 1):
        y, m = 2025, rng.randint(1, 5)
        out.append({
            "order_id": f"O{i:03d}", "listing_id": l["listing_id"],
            "buyer": rng.choice(_BUYERS), "status": rng.choice(_STATUSES),
            "created_at": f"{y}-{m:02d}-05", "updated_at": f"{y}-{m:02d}-12",
        })
    return out
