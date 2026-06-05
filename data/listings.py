import random

_COND_FACTOR = {"A": 0.92, "B": 0.80, "C": 0.65}
_SELLERS = ["阿明車業", "重機達人", "個人賣家-Wang", "南區二手重車", "極速車庫"]
_LOCATIONS = ["台北", "台中", "高雄", "桃園", "台南"]
_FLOOR = 30000

def synth_listings(catalog: list[dict], seed: int = 42, per_model_range=(2, 3)) -> list[dict]:
    rng = random.Random(seed)
    out, n = [], 1
    for item in catalog:
        for _ in range(rng.randint(*per_model_range)):
            year = rng.randint(2018, 2024)
            mileage = rng.choice([3000, 8000, 15000, 24000, 38000])
            cond = rng.choice(["A", "B", "C"])
            year_factor = 1 - (2025 - year) * 0.04
            mileage_factor = max(0.6, 1 - mileage / 100000)
            price = int(item["price"] * year_factor * mileage_factor * _COND_FACTOR[cond])
            price = max(_FLOOR, min(price, item["price"]))
            out.append({
                "listing_id": f"L{n:03d}", "model": item["title"],
                "year": year, "mileage_km": mileage, "condition": cond,
                "asking_price": price, "seller": rng.choice(_SELLERS),
                "location": rng.choice(_LOCATIONS),
                "status": rng.choice(["在售", "在售", "在售", "保留中", "已售出"]),
            })
            n += 1
    return out
