from config import settings
from db import get_listings
from ebay_api import EbayAPI

def competitor_snapshot(query, limit=20):
    api = EbayAPI()
    data = api.browse_search(query, limit)
    rows = []
    for item in data.get("itemSummaries", []):
        price = float(item.get("price", {}).get("value", 0) or 0)
        if price:
            rows.append({
                "title": item.get("title", ""),
                "price": price,
                "url": item.get("itemWebUrl", ""),
                "seller": (item.get("seller", {}) or {}).get("username", ""),
            })
    return rows

def run_monitor(query):
    competitors = competitor_snapshot(query)
    if not competitors:
        return {"query": query, "count": 0, "min_price": None, "avg_price": None, "items": []}
    prices = [x["price"] for x in competitors]
    return {
        "query": query,
        "count": len(competitors),
        "min_price": min(prices),
        "avg_price": round(sum(prices) / len(prices), 2),
        "items": competitors,
    }
