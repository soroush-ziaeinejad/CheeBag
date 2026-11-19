"""Reading products from the Store API (the same door the agent uses; this service never touches the database)."""
import io
import os

import httpx
from PIL import Image

STORE_API_URL = os.environ.get("STORE_API_URL", "http://store-api:8000")


class StoreError(Exception):
    pass


def _get(path, params=None):
    try:
        response = httpx.get(f"{STORE_API_URL}{path}", params=params, timeout=10)
    except httpx.HTTPError:
        raise StoreError("The store system is not reachable right now.")
    if response.status_code == 404:
        raise StoreError("not_found")
    if response.status_code != 200:
        raise StoreError("The store system returned an error.")
    return response.json()


def search_products(query=None, category=None, max_price=None, limit=10):
    params = {"q": query, "category": category, "max_price": max_price, "limit": limit}
    products = _get("/products", {k: v for k, v in params.items() if v is not None})
    return [{"product_id": p["id"], "name": p["name"], "category": p["category"], "price": p["price"],
             "rating": p["rating"], "in_stock": p["stock_quantity"] > 0} for p in products]


def get_product(product_id):
    """Full product details, or None if there's no such (active) product."""
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return None
    try:
        return _get(f"/products/{product_id}")
    except StoreError as e:
        if str(e) == "not_found":
            return None
        raise


def product_photo(product):
    """The product's catalogue photo as JPEG bytes (the image model needs to see the real item)."""
    url = product.get("image_url") or ""
    if not url.startswith("https://"):
        raise StoreError("This product has no photo to place in the room.")
    try:
        response = httpx.get(url, timeout=15, follow_redirects=True)
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception:
        raise StoreError("The product photo couldn't be downloaded right now.")
    image.thumbnail((1024, 1024))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()
