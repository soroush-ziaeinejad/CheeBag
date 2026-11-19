"""Products from online shops, for Room studio's "Online shops" mode.

Results come from Google Shopping through SerpApi, and only listings from the shops in SHOPS are kept.
We use SerpApi's free plan (250 searches a month), so:
  - results are cached for a few hours (asking for the same thing again doesn't use a search),
  - searches are counted per calendar month in a small file that survives restarts, and stop at
    SHOP_SEARCHES_PER_MONTH (if SerpApi's own count runs out first, its refusal gets the same friendly message),
  - main.py also limits each visitor per day (spend() raises ShopLimit when that's used up).

CheeBag doesn't sell these items. A listing's link goes to its Google Shopping page, and its price is what
the listing showed when it was searched.
"""
import hashlib
import json
import os
import time
from datetime import date
from pathlib import Path

import httpx

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
KEEP_SECONDS = 6 * 3600
SHOP_SEARCHES_PER_MONTH = int(os.environ.get("STUDIO_SHOP_SEARCHES_PER_MONTH", "250"))   # SerpApi's free plan
USAGE_FILE = Path(os.environ.get("STUDIO_DATA_DIR", "/data")) / "shop_searches.json"
MONTH_USED_UP = "This month's free shop searches are used up. They come back next month; CheeBag's own products still work."

# the shops we search, and words that identify them in Google Shopping's "source" field
SHOPS = {
    "IKEA": ["ikea"], "Wayfair": ["wayfair"], "Structube": ["structube"], "Article": ["article.com"],
    "EQ3": ["eq3"], "Walmart": ["walmart"], "Best Buy": ["best buy", "bestbuy"], "Amazon.ca": ["amazon"],
    "Canadian Tire": ["canadian tire"], "The Home Depot": ["home depot"], "HomeSense": ["homesense"],
    "CB2": ["cb2"], "West Elm": ["west elm"], "Crate & Barrel": ["crate & barrel", "crate and barrel"],
}
_searches = {}   # (query, max_price) -> (time, listings)
_listings = {}   # listing id -> (time, listing): so a preview or a plan can refer to a listing by its id


class ShopError(Exception):
    pass


class ShopLimit(ShopError):
    """Today's search limit is used up (raised by spend())."""


def ready():
    return bool(SERPAPI_KEY)


def used_this_month():
    """How many SerpApi searches this calendar month (0 if the file is missing, unreadable or from another month)."""
    try:
        saved = json.loads(USAGE_FILE.read_text())
        return saved["count"] if saved.get("month") == date.today().strftime("%Y-%m") else 0
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def _count_search():
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps({"month": date.today().strftime("%Y-%m"), "count": used_this_month() + 1}))


def shop_name(source):
    """Which of our shops a Google Shopping source is, or None if it isn't one of them."""
    s = (source or "").lower().strip()
    if s == "article":                     # "article" alone is too common a word to match inside other names
        return "Article"
    return next((shop for shop, words in SHOPS.items() if any(w in s for w in words)), None)


def search(query, max_price=None, spend=lambda: None):
    """Up to 12 listings from our shops. spend() is called before a paid (not cached) search."""
    query = " ".join(str(query or "").split())[:80]
    if not query:
        raise ShopError("Say what to look for, for example 'floor lamp'.")
    key = (query.lower(), max_price)
    cached = _searches.get(key)
    if cached and time.time() - cached[0] < KEEP_SECONDS:
        return cached[1]
    if not ready():
        raise ShopError("Online shops aren't set up yet.")
    if used_this_month() >= SHOP_SEARCHES_PER_MONTH:
        raise ShopLimit(MONTH_USED_UP)
    spend()
    params = {"engine": "google_shopping", "q": query, "gl": "ca", "hl": "en", "api_key": SERPAPI_KEY}
    if max_price:
        params["max_price"] = int(max_price)
    try:
        response = httpx.get("https://serpapi.com/search.json", params=params, timeout=25)
        if "run out of searches" in response.text.lower():      # SerpApi's own monthly count ran out
            raise ShopLimit(MONTH_USED_UP)
        response.raise_for_status()
        results = response.json().get("shopping_results", [])
        _count_search()                                           # failed searches aren't billed, so not counted
    except (httpx.HTTPError, ValueError) as e:
        print(f"SerpApi error: {e!r}")     # details for us (the key is never printed: it isn't in the error)
        raise ShopError("The shop search isn't working right now. Please try again.")

    listings = []
    for r in results:
        shop, price = shop_name(r.get("source")), r.get("extracted_price")
        image, link = r.get("serpapi_thumbnail") or r.get("thumbnail"), r.get("product_link")
        if not (shop and isinstance(price, (int, float)) and image and link and r.get("title")):
            continue
        listing_id = "s" + hashlib.sha1(f"{r.get('product_id')}|{link}".encode()).hexdigest()[:12]
        listing = {"id": listing_id, "name": r["title"][:160], "price": f"{price:.2f}", "store": shop,
                   "image_url": image, "link": link, "rating": r.get("rating"), "snippet": (r.get("snippet") or "")[:200]}
        _listings[listing_id] = (time.time(), listing)
        listings.append(listing)
        if len(listings) == 12:
            break
    _searches[key] = (time.time(), listings)
    return listings


def get(listing_id):
    """A listing seen in a recent search, or None (it was never seen, or it's older than a few hours)."""
    found = _listings.get(str(listing_id))
    if not found or time.time() - found[0] > KEEP_SECONDS:
        return None
    return found[1]
