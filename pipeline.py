from config import settings
from db import get_product, upsert_product, save_listing, update_product_listing_fields, get_product_aspects
from ebay_api import EbayAPI
from optimizer import ai_optimize_title, optimize_description
from research import research_products
from datetime import datetime, timezone


def run_research(query):
    results = research_products(query)
    for p in results:
        p["title"] = ai_optimize_title(p["title"])
        upsert_product(p)
    return results


def _aspects_for_product(p):
    aspects = {}
    if p.get("brand"):
        aspects["Brand"] = [p["brand"].strip()]
    if p.get("item_type"):
        aspects["Type"] = [p["item_type"].strip()]

    model = (p.get("model") or "").strip()
    if model:
        aspects["Model"] = [model]

    return aspects


def _allowed_values(aspect_meta):
    return [
        v.get("localizedValue", "").strip()
        for v in aspect_meta.get("aspectValues", [])
        if v.get("localizedValue")
    ]


def _best_title_match(title, allowed_values):
    """Use an eBay-approved value only when it is explicitly present in the title."""
    title_lower = (title or "").lower()
    matches = [
        value for value in allowed_values
        if value and value.lower() in title_lower
    ]
    if not matches:
        return None
    return max(matches, key=len)


def _category_aware_aspects(api, p, category_id):
    """
    Build item specifics from eBay's live category metadata.
    Never invent arbitrary required values. Exact eBay-approved values may be
    selected when they are explicitly present in the researched product title.
    """
    aspects = _aspects_for_product(p)

    # Reviewed dashboard values override/increase the basic product fields.
    for name, value in get_product_aspects(p["sku"]).items():
        if value:
            aspects[name] = [value]

    metadata = api.get_item_aspects_for_category(category_id)
    missing = []

    for meta in metadata.get("aspects", []):
        name = (meta.get("localizedAspectName") or "").strip()
        if not name:
            continue

        constraint = meta.get("aspectConstraint") or {}
        required = constraint.get("aspectRequired") is True
        allowed = _allowed_values(meta)

        # Keep reviewed values already supplied by the product record.
        if name in aspects and aspects[name]:
            continue

        # Model has no DB field in this build. Use eBay's standard fallback only
        # when eBay explicitly offers it as a valid value for this category.
        if name == "Model":
            dne = next((v for v in allowed if v.lower() == "does not apply"), None)
            if dne:
                aspects[name] = [dne]
                continue

        # For values such as Connectivity=Bluetooth, use the eBay-approved value
        # only when that exact phrase is present in the researched title.
        matched = _best_title_match(p.get("title", ""), allowed)
        if matched:
            aspects[name] = [matched]
            continue

        if required:
            preview = ", ".join(allowed[:12])
            if preview:
                missing.append(f"{name} (eBay values include: {preview})")
            else:
                missing.append(name)

    return aspects, missing




def get_category_suggestions_for_product(sku):
    """Ask eBay for category suggestions based on the researched product title."""
    p = get_product(sku)
    if not p:
        raise ValueError("Product not found.")
    title = (p.get("title") or "").strip()
    if not title:
        raise ValueError("Product title is required for category discovery.")

    data = EbayAPI().get_category_suggestions(title)
    suggestions = []
    seen = set()

    for item in data.get("categorySuggestions", []):
        category = item.get("category") or {}
        category_id = str(category.get("categoryId") or "").strip()
        category_name = (category.get("categoryName") or "").strip()
        if not category_id or category_id in seen:
            continue
        seen.add(category_id)

        ancestors = []
        for ancestor in item.get("categoryTreeNodeAncestors", []) or []:
            ac = ancestor.get("category") or {}
            name = (ac.get("categoryName") or "").strip()
            if name:
                ancestors.append(name)

        suggestions.append({
            "category_id": category_id,
            "category_name": category_name,
            "path": " > ".join(ancestors + ([category_name] if category_name else [])),
        })

    return {
        "query": title,
        "current_category_id": str(p.get("category_id") or ""),
        "suggestions": suggestions[:10],
    }

def get_required_item_specifics(sku):
    """Return eBay-required aspects, allowed values, current values and completion state."""
    p = get_product(sku)
    if not p:
        raise ValueError("Product not found.")
    category_id = p.get("category_id") or settings.EBAY_CATEGORY_ID
    if not category_id:
        raise ValueError("Save an eBay category ID first.")

    api = EbayAPI()
    metadata = api.get_item_aspects_for_category(category_id)
    current = _aspects_for_product(p)
    for name, value in get_product_aspects(sku).items():
        if value:
            current[name] = [value]

    rows = []
    for meta in metadata.get("aspects", []):
        constraint = meta.get("aspectConstraint") or {}
        if constraint.get("aspectRequired") is not True:
            continue
        name = (meta.get("localizedAspectName") or "").strip()
        allowed = _allowed_values(meta)
        current_value = (current.get(name) or [""])[0]
        if not current_value:
            matched = _best_title_match(p.get("title", ""), allowed)
            if matched:
                current_value = matched
        rows.append({
            "name": name,
            "required": True,
            "allowed_values": allowed,
            "value": current_value,
            "complete": bool(current_value),
        })
    return {"category_id": str(category_id), "aspects": rows}

def _validate_product(p):
    problems = []
    category_id = p.get("category_id") or settings.EBAY_CATEGORY_ID
    if not p.get("image_url"):
        problems.append("Image URL is required")
    if not category_id:
        problems.append("eBay leaf category ID is required")
    if not p.get("brand"):
        problems.append("Brand is required")
    if not p.get("item_type"):
        problems.append("Type is required")
    if p.get("sell_price") is None or float(p["sell_price"]) <= 0:
        problems.append("Sell price must be greater than zero")
    return category_id, problems


def publish_product(sku):
    p = get_product(sku)
    if not p:
        raise ValueError("Product not found.")

    # Record every button press first so dry-run/errors can never disappear silently.
    save_listing(
        sku, title=p["title"], price=p.get("sell_price"),
        status="VALIDATING", error=None
    )

    category_id, problems = _validate_product(p)
    if problems:
        message = "; ".join(problems)
        save_listing(sku, title=p["title"], price=p.get("sell_price"), status="VALIDATION_ERROR", error=message)
        raise ValueError(message)

    aspects = _aspects_for_product(p)
    if settings.DRY_RUN:
        save_listing(
            sku, title=p["title"], price=p["sell_price"],
            status="DRY_RUN_VALIDATED", error=None
        )
        return f"DRY RUN VALIDATED: {p['title']}. No request was sent to eBay."

    # Normal product publishing is intentionally locked in this build.
    # Use the dedicated Sandbox API Test for controlled Sandbox writes.
    save_listing(
        sku, title=p["title"], price=p.get("sell_price"),
        status="PUBLISH_LOCKED", error="Normal publishing is disabled in this build."
    )
    raise RuntimeError("Normal publishing is disabled. Use Sandbox API Test while EBAY_ENV=sandbox.")

    api = EbayAPI()
    try:
        api.create_inventory_item(
            sku=p["sku"],
            title=p["title"],
            description=optimize_description(p["title"]),
            image_urls=[p["image_url"]],
            quantity=1,
            aspects=aspects,
        )
        save_listing(sku, title=p["title"], price=p["sell_price"], status="INVENTORY_CREATED", error=None)

        offer = api.create_offer(p["sku"], p["sell_price"], category_id)
        offer_id = offer.get("offerId")
        if not offer_id:
            raise ValueError(f"eBay did not return an offerId: {offer}")
        save_listing(sku, offer_id=offer_id, title=p["title"], price=p["sell_price"], status="OFFER_CREATED", error=None)

        published = api.publish_offer(offer_id)
        listing_id = published.get("listingId", "")
        save_listing(
            p["sku"], offer_id=offer_id, listing_id=listing_id,
            title=p["title"], price=p["sell_price"], status="LIVE", error=None
        )
        return f"Published: {p['title']} (listing {listing_id or 'created'})"
    except Exception as exc:
        save_listing(
            sku, title=p["title"], price=p.get("sell_price"),
            status="ERROR", error=str(exc)
        )
        raise


def save_listing_fields(sku, category_id="", brand="", item_type=""):
    if not get_product(sku):
        raise ValueError("Product not found.")
    update_product_listing_fields(sku, category_id, brand, item_type)


def run_sandbox_api_test():
    """Create and publish a controlled listing in eBay Sandbox only."""
    if str(settings.EBAY_ENV).lower() != "sandbox":
        raise RuntimeError("Sandbox API Test is locked unless EBAY_ENV=sandbox.")

    # Use a fresh SKU each run so repeated tests cannot collide with an older offer.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    sku = f"SANDBOX-AUTO-{stamp}"
    title = "Lenovo ThinkPad Mini Dock Series 3 Docking Station"
    price = 19.99
    category_id = "3709"
    image_url = "http://i.ebayimg.sandbox.ebay.com/images/g/G3EAAeSwXxRqmQgf/s-l225.jpg"
    aspects = {
        "Brand": ["Lenovo"],
        "Type": ["Docking Station"],
    }

    save_listing(
        sku, title=title, price=price,
        status="SANDBOX_TEST_STARTING", error=None
    )

    api = EbayAPI()
    try:
        api.create_inventory_item(
            sku=sku,
            title=title,
            description="Controlled eBay Sandbox API test item. Not a real production product listing.",
            image_urls=[image_url],
            quantity=1,
            aspects=aspects,
        )
        save_listing(
            sku, title=title, price=price,
            status="SANDBOX_INVENTORY_CREATED", error=None
        )

        offer = api.create_offer(sku, price, category_id)
        offer_id = offer.get("offerId")
        if not offer_id:
            raise ValueError(f"eBay Sandbox did not return an offerId: {offer}")

        save_listing(
            sku, offer_id=offer_id, title=title, price=price,
            status="SANDBOX_OFFER_CREATED", error=None
        )

        published = api.publish_offer(offer_id)
        listing_id = published.get("listingId", "")
        if not listing_id:
            raise ValueError(f"eBay Sandbox did not return a listingId: {published}")

        save_listing(
            sku, offer_id=offer_id, listing_id=listing_id,
            title=title, price=price, status="SANDBOX_LIVE", error=None
        )
        return f"Sandbox API Test passed. Listing ID: {listing_id}"
    except Exception as exc:
        save_listing(
            sku, title=title, price=price,
            status="SANDBOX_ERROR", error=str(exc)
        )
        raise

def publish_researched_product_to_sandbox(sku):
    """Publish one reviewed research product to eBay Sandbox only."""
    if str(settings.EBAY_ENV).lower() != "sandbox":
        raise RuntimeError("Sandbox publishing is locked unless EBAY_ENV=sandbox.")
    p = get_product(sku)
    if not p:
        raise ValueError("Product not found.")
    missing = [label for label, value in [
        ("category ID", p.get("category_id")), ("Brand", p.get("brand")),
        ("Type", p.get("item_type")), ("sell price", p.get("sell_price"))
    ] if not value]
    if missing:
        raise ValueError("Missing required listing data: " + ", ".join(missing))
    image_url = (p.get("image_url") or "").strip() or "http://i.ebayimg.sandbox.ebay.com/images/g/G3EAAeSwXxRqmQgf/s-l225.jpg"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    test_sku = f"{sku[:28]}-SB-{stamp}"
    title = (p.get("title") or "Sandbox researched product")[:80]
    price = float(p["sell_price"])
    save_listing(test_sku, title=title, price=price, status="RESEARCH_SANDBOX_STARTING", error=None)
    api = EbayAPI()
    try:
        aspects, missing_aspects = _category_aware_aspects(api, p, str(p["category_id"]))
        if missing_aspects:
            message = "Missing required eBay item specifics: " + "; ".join(missing_aspects)
            save_listing(test_sku, title=title, price=price,
                         status="RESEARCH_SANDBOX_ASPECTS_REQUIRED", error=message)
            raise ValueError(message)

        api.create_inventory_item(test_sku, title,
            "Controlled eBay Sandbox listing generated from a reviewed research record. Development/testing only.",
            [image_url], 1, aspects=aspects)
        save_listing(test_sku, title=title, price=price, status="RESEARCH_SANDBOX_INVENTORY", error=None)
        offer = api.create_offer(test_sku, price, str(p["category_id"]))
        offer_id = offer.get("offerId")
        if not offer_id:
            raise ValueError(f"No offerId returned: {offer}")
        save_listing(test_sku, offer_id=offer_id, title=title, price=price, status="RESEARCH_SANDBOX_OFFER", error=None)
        published = api.publish_offer(offer_id)
        listing_id = published.get("listingId", "")
        if not listing_id:
            raise ValueError(f"No listingId returned: {published}")
        save_listing(test_sku, offer_id=offer_id, listing_id=listing_id, title=title, price=price, status="RESEARCH_SANDBOX_LIVE", error=None)
        return f"Researched product published to Sandbox. Listing ID: {listing_id}"
    except Exception as exc:
        save_listing(test_sku, title=title, price=price, status="RESEARCH_SANDBOX_ERROR", error=str(exc))
        raise
