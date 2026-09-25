import os
import requests

def optimize_title(title):
    # Safe fallback: preserve factual product information; do not add fake claims.
    cleaned = " ".join(title.split())
    return cleaned[:80]

def optimize_description(title):
    return (
        f"{title}\n\n"
        "Please review the photos and item specifics before purchase. "
        "Product details are based on the source information available to the seller. "
        "Shipping and returns follow the eBay listing policies configured for this store."
    )

def ai_optimize_title(title):
    """
    Optional OpenAI enhancement. If OPENAI_API_KEY is not configured,
    the deterministic optimizer is used. Keep claims factual.
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return optimize_title(title)
    try:
        # Uses the Responses API over HTTPS to avoid hard-coding a model SDK version.
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
                "input": (
                    "Rewrite this e-commerce title for search clarity. "
                    "Maximum 80 characters. Keep only factual attributes present "
                    "in the original. Do not add claims such as best seller, top rated, "
                    "guaranteed, limited stock, or free shipping unless present.\n\n"
                    f"Original: {title}"
                ),
            },
            timeout=30,
        )
        if not r.ok:
            return optimize_title(title)
        data = r.json()
        text = data.get("output_text", "").strip()
        return (text or optimize_title(title))[:80]
    except Exception:
        return optimize_title(title)
