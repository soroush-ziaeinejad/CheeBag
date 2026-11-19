"""Where Room studio's products come from: CheeBag's own catalogue ("store") or online shops ("shops").

Every item has the same shape, whichever source it came from:
    {"id", "name", "price" (CAD, as text), "image_url", "store", "link"}
Ids are text: "123" for our own products, "s" + 12 hex characters for shop listings, so one preview,
plan or selection can mix both and still tell them apart.
"""
from . import shops, store

SOURCES = ("store", "shops")


def item(item_id):
    """One item by id, or None if it doesn't exist (or a shop listing has expired)."""
    item_id = str(item_id)
    if item_id.startswith("s"):
        return shops.get(item_id)
    product = store.get_product(item_id)
    if product is None:
        return None
    return {"id": str(product["id"]), "name": product["name"], "price": f"{float(product['price']):.2f}",
            "image_url": product["image_url"], "store": "CheeBag", "link": f"/products/{product['id']}/",
            "product": product}   # the full details, for Claude's get_product


def search(source, query=None, category=None, max_price=None, spend=lambda: None):
    """Search results for Claude, with ids as text."""
    if source == "shops":
        return [{k: v for k, v in s.items() if k != "image_url"} for s in shops.search(query, max_price, spend)]
    return [{**p, "product_id": str(p["product_id"]), "store": "CheeBag"}
            for p in store.search_products(query, category, max_price)]


def photo(it):
    """The item's photo as JPEG bytes, for the image model."""
    return store.product_photo(it)
