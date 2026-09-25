import hashlib
import statistics
from config import settings
from ebay_api import EbayAPI

def make_sku(title):
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:10].upper()
    return f"EB-{digest}"

def opportunity_score(item, median_price):
    price = float(item.get("price", {}).get("value", 0) or 0)
    if price <= 0:
        return 0
    spread = abs(price - median_price) / median_price if median_price else 0
    # Transparent proxy score: match to search + reasonable price + shipping signal.
    score = 50 + min(30, spread * 100) + (10 if item.get("shippingOptions") else 0)
    return round(min(100, score), 1)

def research_products(query, limit=20):
    api = EbayAPI()
    data = api.browse_search(query, limit=limit)
    items = data.get("itemSummaries", [])
    prices = [
        float(x.get("price", {}).get("value", 0))
        for x in items if x.get("price", {}).get("value")
    ]
    median_price = statistics.median(prices) if prices else 0
    results = []
    for item in items:
        title = item.get("title", "").strip()
        price = float(item.get("price", {}).get("value", 0) or 0)
        if not title or price <= 0:
            continue
        cost = round(price * settings.SUPPLIER_COST_FACTOR, 2)
        sell_price = round(max(price, cost + settings.MIN_PROFIT + price * settings.EBAY_FEE_RATE), 2)
        profit = round(sell_price - cost - sell_price * settings.EBAY_FEE_RATE, 2)
        margin = profit / sell_price if sell_price else 0
        score = opportunity_score(item, median_price)
        if profit >= settings.MIN_PROFIT and margin >= settings.MIN_MARGIN:
            results.append({
                "sku": make_sku(title),
                "query": query,
                "title": title,
                "source_url": item.get("itemWebUrl", ""),
                "source_price": price,
                "estimated_cost": cost,
                "sell_price": sell_price,
                "estimated_profit": profit,
                "score": score,
                "image_url": (item.get("image", {}) or {}).get("imageUrl") or settings.EBAY_IMAGE_URL,
                "category_id": item.get("leafCategoryIds", [""])[0] if item.get("leafCategoryIds") else settings.EBAY_CATEGORY_ID,
            })
    return sorted(results, key=lambda x: (x["score"], x["estimated_profit"]), reverse=True)
