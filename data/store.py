from data.catalog import load_catalog
from data.listings import synth_listings
from data.orders import synth_orders

class DataStore:
    def __init__(self, seed: int = 42):
        self.catalog = load_catalog()
        self.listings = synth_listings(self.catalog, seed=seed)
        self.orders = synth_orders(self.listings, seed=seed)
        self.tickets: list[dict] = []
        self._catalog_by_title = {c["title"]: c for c in self.catalog}

    def catalog_for(self, title: str) -> dict | None:
        return self._catalog_by_title.get(title)

    def listing(self, listing_id: str) -> dict | None:
        return next((l for l in self.listings if l["listing_id"] == listing_id), None)

    def add_ticket(self, category: str, description: str) -> dict:
        t = {"ticket_id": f"T{len(self.tickets)+1:03d}", "category": category,
             "description": description, "status": "open"}
        self.tickets.append(t)
        return t
