import sqlite3
from pathlib import Path
from config import settings


def conn():
    Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(settings.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            query TEXT,
            title TEXT NOT NULL,
            source_url TEXT,
            source_price REAL,
            estimated_cost REAL,
            sell_price REAL,
            estimated_profit REAL,
            score REAL,
            image_url TEXT,
            category_id TEXT,
            brand TEXT,
            item_type TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS product_aspects (
            sku TEXT NOT NULL,
            aspect_name TEXT NOT NULL,
            aspect_value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (sku, aspect_name)
        );
        CREATE TABLE IF NOT EXISTS listings (
            sku TEXT PRIMARY KEY,
            offer_id TEXT,
            listing_id TEXT,
            title TEXT,
            price REAL,
            status TEXT,
            error TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        columns = {row[1] for row in c.execute("PRAGMA table_info(products)").fetchall()}
        if "brand" not in columns:
            c.execute("ALTER TABLE products ADD COLUMN brand TEXT")
        if "item_type" not in columns:
            c.execute("ALTER TABLE products ADD COLUMN item_type TEXT")


def upsert_product(p):
    with conn() as c:
        c.execute("""
        INSERT INTO products
        (sku, query, title, source_url, source_price, estimated_cost, sell_price,
         estimated_profit, score, image_url, category_id, brand, item_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
          title=excluded.title, source_url=excluded.source_url,
          source_price=excluded.source_price, estimated_cost=excluded.estimated_cost,
          sell_price=excluded.sell_price, estimated_profit=excluded.estimated_profit,
          score=excluded.score, image_url=excluded.image_url,
          category_id=COALESCE(excluded.category_id, products.category_id),
          brand=COALESCE(excluded.brand, products.brand),
          item_type=COALESCE(excluded.item_type, products.item_type)
        """, (
            p["sku"], p.get("query"), p["title"], p.get("source_url"),
            p.get("source_price"), p.get("estimated_cost"), p.get("sell_price"),
            p.get("estimated_profit"), p.get("score"), p.get("image_url"),
            p.get("category_id"), p.get("brand"), p.get("item_type")
        ))


def get_products(limit=100):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM products ORDER BY score DESC, created_at DESC LIMIT ?", (limit,)
        ).fetchall()]


def get_product(sku):
    with conn() as c:
        r = c.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
        return dict(r) if r else None


def update_product_listing_fields(sku, category_id=None, brand=None, item_type=None):
    with conn() as c:
        c.execute("""
        UPDATE products
        SET category_id=COALESCE(?, category_id),
            brand=COALESCE(?, brand),
            item_type=COALESCE(?, item_type)
        WHERE sku=?
        """, (category_id or None, brand or None, item_type or None, sku))


def save_listing(sku, offer_id=None, listing_id=None, title=None, price=None, status=None, error=None):
    """Insert/update listing state without erasing IDs from earlier successful stages."""
    with conn() as c:
        c.execute("""
        INSERT INTO listings(sku, offer_id, listing_id, title, price, status, error)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
          offer_id=COALESCE(excluded.offer_id, listings.offer_id),
          listing_id=COALESCE(excluded.listing_id, listings.listing_id),
          title=COALESCE(excluded.title, listings.title),
          price=COALESCE(excluded.price, listings.price),
          status=COALESCE(excluded.status, listings.status),
          error=excluded.error,
          updated_at=CURRENT_TIMESTAMP
        """, (sku, offer_id, listing_id, title, price, status, error))


def get_listing(sku):
    with conn() as c:
        r = c.execute("SELECT * FROM listings WHERE sku=?", (sku,)).fetchone()
        return dict(r) if r else None


def get_listings(limit=100):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM listings ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()]


def get_product_aspects(sku):
    with conn() as c:
        rows = c.execute(
            "SELECT aspect_name, aspect_value FROM product_aspects WHERE sku=? ORDER BY aspect_name",
            (sku,)
        ).fetchall()
        return {r["aspect_name"]: r["aspect_value"] for r in rows}


def save_product_aspects(sku, aspects):
    """Save arbitrary reviewed eBay item specifics for a product."""
    with conn() as c:
        for name, value in (aspects or {}).items():
            name = (name or "").strip()
            value = (value or "").strip()
            if not name:
                continue
            if value:
                c.execute("""
                    INSERT INTO product_aspects(sku, aspect_name, aspect_value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(sku, aspect_name) DO UPDATE SET
                      aspect_value=excluded.aspect_value,
                      updated_at=CURRENT_TIMESTAMP
                """, (sku, name, value))
            else:
                c.execute(
                    "DELETE FROM product_aspects WHERE sku=? AND aspect_name=?",
                    (sku, name)
                )
