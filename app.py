from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from config import settings
from db import init_db, get_products, get_listings, get_product, get_product_aspects, save_product_aspects
from ebay_api import EbayAPI
from pipeline import run_research, publish_product, save_listing_fields, run_sandbox_api_test, publish_researched_product_to_sandbox, get_required_item_specifics, get_category_suggestions_for_product
from dotenv import load_dotenv
import hashlib
import os

load_dotenv()
init_db()

app = Flask(__name__)
app.secret_key = settings.FLASK_SECRET_KEY


@app.get("/")
def dashboard():
    return render_template(
        "index.html",
        products=get_products(100),
        listings=get_listings(100),
        dry_run=settings.DRY_RUN,
        ebay_env=settings.EBAY_ENV,
    )


@app.post("/research")
def research():
    query = request.form.get("query", "").strip()
    if not query:
        flash("Enter a product keyword.", "error")
        return redirect(url_for("dashboard"))
    try:
        results = run_research(query)
        flash(f"Research complete: {len(results)} opportunities saved.", "success")
    except Exception as exc:
        flash(f"Research error: {exc}", "error")
    return redirect(url_for("dashboard"))


@app.post("/product/<sku>/listing-details")
def listing_details(sku):
    try:
        save_listing_fields(
            sku,
            request.form.get("category_id", "").strip(),
            request.form.get("brand", "").strip(),
            request.form.get("item_type", "").strip(),
        )
        flash("Listing details saved.", "success")
    except Exception as exc:
        flash(f"Save error: {exc}", "error")
    return redirect(url_for("dashboard"))


@app.post("/publish/<sku>")
def publish(sku):
    try:
        result = publish_product(sku)
        flash(result, "success")
    except Exception as exc:
        flash(f"Validation/Publish error: {exc}", "error")
    return redirect(url_for("dashboard"))



@app.get("/api/product/<sku>/category-suggestions")
def category_suggestions(sku):
    try:
        return jsonify(get_category_suggestions_for_product(sku))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/product/<sku>/required-aspects")
def required_aspects(sku):
    try:
        return jsonify(get_required_item_specifics(sku))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/product/<sku>/item-specifics")
def item_specifics(sku):
    try:
        if not get_product(sku):
            raise ValueError("Product not found.")
        names = request.form.getlist("aspect_name")
        values = request.form.getlist("aspect_value")
        save_product_aspects(sku, dict(zip(names, values)))
        flash("Required item specifics saved.", "success")
    except Exception as exc:
        flash(f"Item specifics error: {exc}", "error")
    return redirect(url_for("dashboard"))


@app.post("/sandbox-publish/<sku>")
def sandbox_publish_researched(sku):
    try:
        flash(publish_researched_product_to_sandbox(sku), "success")
    except Exception as exc:
        flash(f"Researched-product Sandbox error: {exc}", "error")
    return redirect(url_for("dashboard"))


@app.post("/sandbox-api-test")
def sandbox_api_test():
    try:
        result = run_sandbox_api_test()
        flash(result, "success")
    except Exception as exc:
        flash(f"Sandbox API Test error: {exc}", "error")
    return redirect(url_for("dashboard"))


@app.route("/ebay/account-deletion", methods=["GET", "POST"])
def ebay_account_deletion():
    """eBay Marketplace Account Deletion callback.

    GET: answers eBay's endpoint-verification challenge.
    POST: acknowledges account-deletion notifications. The current app does not
    persist buyer/user records; if order/buyer storage is added later, deletion
    processing and signature verification must be added before that data is used.
    """
    verification_token = os.getenv("EBAY_DELETION_VERIFICATION_TOKEN", "").strip()
    endpoint = os.getenv("EBAY_DELETION_ENDPOINT", "").strip()

    if not verification_token or not endpoint:
        return jsonify({"error": "eBay deletion callback is not configured"}), 503

    if request.method == "GET":
        challenge_code = request.args.get("challenge_code", "").strip()
        if not challenge_code:
            return jsonify({"error": "missing challenge_code"}), 400

        digest_input = f"{challenge_code}{verification_token}{endpoint}"
        challenge_response = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
        return jsonify({"challengeResponse": challenge_response}), 200

    payload = request.get_json(silent=True) or {}
    topic = (payload.get("metadata") or {}).get("topic")
    if topic != "MARKETPLACE_ACCOUNT_DELETION":
        return jsonify({"error": "unsupported notification topic"}), 400

    # Do not log the payload: it can contain eBay user identifiers.
    return "", 204


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "dry_run": settings.DRY_RUN})


@app.get("/api/policies")
def policies():
    try:
        api = EbayAPI()
        return jsonify(api.get_policies())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.PORT, debug=settings.FLASK_DEBUG)
