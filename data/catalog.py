import os
import pandas as pd
from data.spec_parser import parse_specs

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "product_dataset.csv")

USAGE_BY_TITLE = {
    "YZF-R9": "sport", "YZF-R3": "sport", "MT-09 Y-AMT": "naked",
    "MT-07 Y-AMT": "naked", "MT-07": "naked", "MT-15": "naked",
    "Ténéré 700": "adventure", "TMAX": "scooter", "XMAX": "scooter",
    "Ninja ZX-4RR (ZX400-S)": "sport", "Ninja ZX-6R (ZX636-J)": "sport",
    "Ninja ZX-10R (ZX-1002L)": "sport", "Ninja 500 SE (EX500-J)": "sport",
    "Ninja 500 (EX500-G)": "sport", "Ninja H2SX SE (ZX1002-R)": "touring",
    "Z 500 (ER500-E)": "naked", "Z 650 (ER650-S)": "naked", "Z 900 (ZR900-F)": "naked",
    "Z 650RS (ER650-R)": "naked", "ELIMINATOR 500 SE (EL450-B)": "cruiser",
    "FORZA350": "scooter", "ADV350": "scooter", "CB1000F": "naked",
    "CB1000 Hornet SP": "naked", "CB650R E-Clutch": "naked", "CB300R": "naked",
    "CBR650R E-Clutch": "sport", "CBR500R": "sport",
    "AFRICA TWIN ADVENTURE SPORTS ES DCT": "adventure", "AFRICA TWIN ES": "adventure",
    "X-ADV": "scooter", "CRF300L": "adventure", "CB1000GT": "touring",
}

def _brand(categories: str) -> str:
    parts = [p.strip() for p in str(categories).split(",")]
    return parts[-1] if parts else ""

def load_catalog() -> list[dict]:
    df = pd.read_csv(CSV_PATH)
    items = []
    for _, r in df.iterrows():
        title = str(r["Title"]).strip()
        items.append({
            "title": title,
            "brand": _brand(r["Categories"]),
            "usage": USAGE_BY_TITLE.get(title, "naked"),
            "price": int(r["Price"]),
            "specs": parse_specs(str(r["Description"])),
            "description": str(r["Description"]),
            "media_url": str(r["Media_url"]),
            "uri": str(r["Uri"]),
        })
    return items
