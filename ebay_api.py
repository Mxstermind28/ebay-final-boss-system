import base64
import time
import requests
from urllib.parse import urlencode
from config import settings

class EbayAPIError(RuntimeError):
    pass

class EbayAPI:
    def __init__(self):
        if settings.EBAY_ENV == "production":
            self.api_base = "https://api.ebay.com"
            self.auth_base = "https://auth.ebay.com"
        else:
            self.api_base = "https://api.sandbox.ebay.com"
            self.auth_base = "https://auth.sandbox.ebay.com"
        self._app_token = None
        self._user_token = None
        self._user_token_expiry = 0

    def _check_client(self):
        if not settings.EBAY_CLIENT_ID or not settings.EBAY_CLIENT_SECRET:
            raise EbayAPIError("Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in .env.")

    def app_token(self):
        self._check_client()
        if self._app_token:
            return self._app_token
        raw = f"{settings.EBAY_CLIENT_ID}:{settings.EBAY_CLIENT_SECRET}".encode()
        basic = base64.b64encode(raw).decode()
        r = requests.post(
            f"{self.api_base}/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"App token failed: {r.status_code} {r.text}")
        self._app_token = r.json()["access_token"]
        return self._app_token

    def user_token(self):
        self._check_client()
        if self._user_token and time.time() < self._user_token_expiry - 60:
            return self._user_token
        if not settings.EBAY_REFRESH_TOKEN:
            raise EbayAPIError("Set EBAY_REFRESH_TOKEN after completing eBay OAuth consent.")
        raw = f"{settings.EBAY_CLIENT_ID}:{settings.EBAY_CLIENT_SECRET}".encode()
        basic = base64.b64encode(raw).decode()
        scopes = "https://api.ebay.com/oauth/api_scope/sell.account https://api.ebay.com/oauth/api_scope/sell.inventory"
        r = requests.post(
            f"{self.api_base}/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": settings.EBAY_REFRESH_TOKEN,
                "scope": scopes,
            },
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"User token refresh failed: {r.status_code} {r.text}")
        body = r.json()
        self._user_token = body["access_token"]
        self._user_token_expiry = time.time() + body.get("expires_in", 7200)
        return self._user_token

    def oauth_authorize_url(self, state="setup"):
        scopes = "https://api.ebay.com/oauth/api_scope/sell.account https://api.ebay.com/oauth/api_scope/sell.inventory"
        params = {
            "client_id": settings.EBAY_CLIENT_ID,
            "redirect_uri": settings.EBAY_RUNAME,
            "response_type": "code",
            "scope": scopes,
            "state": state,
        }
        return f"{self.auth_base}/oauth2/authorize?{urlencode(params)}"

    def exchange_code(self, code):
        self._check_client()
        raw = f"{settings.EBAY_CLIENT_ID}:{settings.EBAY_CLIENT_SECRET}".encode()
        basic = base64.b64encode(raw).decode()
        r = requests.post(
            f"{self.api_base}/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.EBAY_RUNAME,
            },
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"OAuth exchange failed: {r.status_code} {r.text}")
        return r.json()

    def browse_search(self, query, limit=20):
        r = requests.get(
            f"{self.api_base}/buy/browse/v1/item_summary/search",
            params={"q": query, "limit": min(limit, 200), "filter": "buyingOptions:{FIXED_PRICE}"},
            headers={
                "Authorization": f"Bearer {self.app_token()}",
                "X-EBAY-C-MARKETPLACE-ID": settings.EBAY_MARKETPLACE_ID,
            },
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"Browse search failed: {r.status_code} {r.text}")
        return r.json()

    def get_policies(self):
        token = self.user_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": settings.EBAY_MARKETPLACE_ID,
        }
        out = {}
        for name, path in {
            "fulfillment": "/sell/account/v1/fulfillment_policy",
            "payment": "/sell/account/v1/payment_policy",
            "return": "/sell/account/v1/return_policy",
        }.items():
            r = requests.get(
                self.api_base + path,
                params={"marketplace_id": settings.EBAY_MARKETPLACE_ID},
                headers=headers,
                timeout=30,
            )
            if not r.ok:
                out[name] = {"error": f"{r.status_code} {r.text}"}
            else:
                out[name] = r.json()
        return out

    def get_default_category_tree_id(self):
        """Return the default eBay category tree ID for the configured marketplace."""
        r = requests.get(
            f"{self.api_base}/commerce/taxonomy/v1/get_default_category_tree_id",
            params={"marketplace_id": settings.EBAY_MARKETPLACE_ID},
            headers={"Authorization": f"Bearer {self.app_token()}"},
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"Category tree lookup failed: {r.status_code} {r.text}")
        tree_id = r.json().get("categoryTreeId")
        if tree_id is None:
            raise EbayAPIError(f"eBay did not return a categoryTreeId: {r.text}")
        return str(tree_id)

    def get_category_suggestions(self, query):
        """Return eBay Taxonomy category suggestions for a product/title query."""
        tree_id = self.get_default_category_tree_id()
        r = requests.get(
            f"{self.api_base}/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_suggestions",
            params={"q": (query or "").strip()},
            headers={
                "Authorization": f"Bearer {self.app_token()}",
                "Accept-Language": "en-US",
            },
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"Category suggestions failed: {r.status_code} {r.text}")
        return r.json()

    def get_item_aspects_for_category(self, category_id):
        """Return eBay aspect metadata for one leaf category."""
        tree_id = self.get_default_category_tree_id()
        r = requests.get(
            f"{self.api_base}/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_aspects_for_category",
            params={"category_id": str(category_id)},
            headers={
                "Authorization": f"Bearer {self.app_token()}",
                "Accept-Language": "en-US",
            },
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"Category aspects lookup failed: {r.status_code} {r.text}")
        return r.json()

    def create_inventory_item(self, sku, title, description, image_urls, quantity=1, aspects=None):
        token = self.user_token()
        url = f"{self.api_base}/sell/inventory/v1/inventory_item/{sku}"
        body = {
            "product": {
                "title": title[:80],
                "description": description,
                "imageUrls": image_urls[:12],
            },
            "condition": "NEW",
            "availability": {
                "shipToLocationAvailability": {"quantity": int(quantity)}
            },
        }
        if aspects:
            body["product"]["aspects"] = aspects

        r = requests.put(
            url, json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Content-Language": "en-US",
            },
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"Inventory item failed: {r.status_code} {r.text}")
        return r

    def create_offer(self, sku, price, category_id):
        token = self.user_token()
        url = f"{self.api_base}/sell/inventory/v1/offer"
        missing = [
            name for name, value in {
                "category": category_id,
                "fulfillment policy": settings.EBAY_FULFILLMENT_POLICY_ID,
                "payment policy": settings.EBAY_PAYMENT_POLICY_ID,
                "return policy": settings.EBAY_RETURN_POLICY_ID,
            }.items() if not value
        ]
        if missing:
            raise EbayAPIError("Missing: " + ", ".join(missing))
        body = {
            "sku": sku,
            "marketplaceId": settings.EBAY_MARKETPLACE_ID,
            "format": "FIXED_PRICE",
            "availableQuantity": 1,
            "categoryId": str(category_id),
            "merchantLocationKey": getattr(
                settings, "EBAY_MERCHANT_LOCATION_KEY", ""
            ) or "FINAL-BOSS-LOC",
            "listingDuration": "GTC",
            "listingPolicies": {
                "fulfillmentPolicyId": settings.EBAY_FULFILLMENT_POLICY_ID,
                "paymentPolicyId": settings.EBAY_PAYMENT_POLICY_ID,
                "returnPolicyId": settings.EBAY_RETURN_POLICY_ID,
            },
            "pricingSummary": {
                "price": {"value": f"{price:.2f}", "currency": "USD"}
            },
        }
        r = requests.post(
            url, json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Content-Language": "en-US",
            },
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"Offer failed: {r.status_code} {r.text}")
        return r.json()

    def publish_offer(self, offer_id):
        token = self.user_token()
        r = requests.post(
            f"{self.api_base}/sell/inventory/v1/offer/{offer_id}/publish",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
        if not r.ok:
            raise EbayAPIError(f"Publish failed: {r.status_code} {r.text}")
        return r.json()
