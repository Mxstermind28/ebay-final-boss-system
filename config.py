import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def as_bool(value, default=False):
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class Settings:
    EBAY_ENV: str = os.getenv("EBAY_ENV", "sandbox")
    EBAY_MARKETPLACE_ID: str = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
    EBAY_CLIENT_ID: str = os.getenv("EBAY_CLIENT_ID", "")
    EBAY_CLIENT_SECRET: str = os.getenv("EBAY_CLIENT_SECRET", "")
    EBAY_RUNAME: str = os.getenv("EBAY_RUNAME", "")
    EBAY_REFRESH_TOKEN: str = os.getenv("EBAY_REFRESH_TOKEN", "")
    EBAY_FULFILLMENT_POLICY_ID: str = os.getenv("EBAY_FULFILLMENT_POLICY_ID", "")
    EBAY_PAYMENT_POLICY_ID: str = os.getenv("EBAY_PAYMENT_POLICY_ID", "")
    EBAY_RETURN_POLICY_ID: str = os.getenv("EBAY_RETURN_POLICY_ID", "")
    EBAY_CATEGORY_ID: str = os.getenv("EBAY_CATEGORY_ID", "")
    EBAY_MERCHANT_LOCATION_KEY: str = os.getenv("EBAY_MERCHANT_LOCATION_KEY", "FINAL-BOSS-LOC")
    EBAY_IMAGE_URL: str = os.getenv("EBAY_IMAGE_URL", "")
    SUPPLIER_COST_FACTOR: float = float(os.getenv("SUPPLIER_COST_FACTOR", "0.55"))
    EBAY_FEE_RATE: float = float(os.getenv("EBAY_FEE_RATE", "0.135"))
    MIN_PROFIT: float = float(os.getenv("MIN_PROFIT", "7"))
    MIN_MARGIN: float = float(os.getenv("MIN_MARGIN", "0.20"))
    DRY_RUN: bool = as_bool(os.getenv("DRY_RUN", "true"), True)
    FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "change-me")
    FLASK_DEBUG: bool = as_bool(os.getenv("FLASK_DEBUG", "false"), False)
    PORT: int = int(os.getenv("PORT", "5000"))
    DB_PATH: str = os.getenv("DB_PATH", "data/app.db")

settings = Settings()
