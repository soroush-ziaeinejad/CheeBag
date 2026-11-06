"""Stream Amazon Reviews 2023 Home_and_Kitchen metadata and keep a furniture/decor subset.

Run:  python fetch_amazon.py
Output: raw/amazon_candidates.jsonl
"""
import gzip
import http.client
import json
import os
import time
import urllib.request

URL = "https://datarepo.eng.ucsd.edu/mcauley_group/data/amazon_2023/raw/meta_categories/meta_Home_and_Kitchen.jsonl.gz"
OUT_PATH = os.path.join(os.path.dirname(__file__), "raw", "amazon_candidates.jsonl")
PER_CATEGORY = 30  # keep extra candidates; we curate ~60 later
MAX_RETRIES = 5

# our category -> phrases to look for in the title / Amazon category path
TARGETS = {
    "coffee_table": ["coffee table"],
    "sofa": ["sofa", "couch", "loveseat"],
    "chair": ["accent chair", "armchair", "dining chair", "office chair", "recliner"],
    "bed_frame": ["bed frame", "platform bed"],
    "bookshelf": ["bookshelf", "bookcase"],
    "dresser": ["dresser", "chest of drawers"],
    "rug": ["area rug", "runner rug"],
    "wall_art": ["wall art", "canvas print"],
    "lamp": ["table lamp", "floor lamp", "desk lamp"],
    "plant_stand": ["plant stand"],
}
# accessories that match the phrases above but are not the product itself
EXCLUDE = ["cover", "cushion", "pad", "shade", "replacement", "decal", "sticker", "toy", "doll", "miniature"]


class ResumableStream:
    """File-like download that reconnects and continues from the last byte (HTTP Range) on errors."""

    def __init__(self, url):
        self.url = url
        self.pos = 0
        self.total = None
        self.resp = None

    def _open(self):
        headers = {"Range": f"bytes={self.pos}-"} if self.pos else {}
        self.resp = urllib.request.urlopen(urllib.request.Request(self.url, headers=headers), timeout=60)
        if self.pos and self.resp.status != 206:
            raise RuntimeError("server does not support resuming (no HTTP 206)")
        length = self.resp.headers.get("Content-Length")
        if length:
            self.total = self.pos + int(length)

    def read(self, size=-1):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if self.resp is None:
                    self._open()
                data = self.resp.read(size)
                if not data and self.total and self.pos < self.total:
                    raise ConnectionError("connection closed early")
                self.pos += len(data)
                return data
            except (OSError, http.client.HTTPException) as e:
                print(f"download error at byte {self.pos:,}: {e} | retry {attempt}/{MAX_RETRIES}")
                self.resp = None
                time.sleep(5 * attempt)
        raise RuntimeError(f"download failed after {MAX_RETRIES} retries")


def match_category(item):
    text = (item.get("title") or "").lower() + " " + " ".join(item.get("categories") or []).lower()
    if any(word in text for word in EXCLUDE):
        return None
    for category, phrases in TARGETS.items():
        if any(p in text for p in phrases):
            return category
    return None


def first_image(item):
    for img in item.get("images") or []:
        url = img.get("hi_res") or img.get("large")
        if url:
            return url
    return None


def main():
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    counts = {c: 0 for c in TARGETS}
    seen = set()

    with gzip.open(ResumableStream(URL), "rt") as lines, open(OUT_PATH, "w") as out:
        for i, line in enumerate(lines):
            if i % 100_000 == 0:
                print(f"read {i:,} lines | kept {counts}")

            item = json.loads(line)
            category = match_category(item)
            if category is None or counts[category] >= PER_CATEGORY:
                continue

            asin = item.get("parent_asin")
            price = item.get("price")
            image = first_image(item)
            if not asin or asin in seen or not item.get("title") or not isinstance(price, (int, float)) or not image:
                continue

            record = {
                "source_asin": asin,
                "category": category,
                "title": item["title"],
                "original_price": price,
                "original_currency": "USD",
                "image_url": image,
                "store": item.get("store"),
                "average_rating": item.get("average_rating"),
                "rating_number": item.get("rating_number"),
                "features": item.get("features"),
                "description": item.get("description"),
                "details": item.get("details"),  # raw color/material/dimensions, parsed later
                "amazon_categories": item.get("categories"),
            }
            out.write(json.dumps(record) + "\n")
            seen.add(asin)
            counts[category] += 1

            if all(n >= PER_CATEGORY for n in counts.values()):
                break

    print(f"done | kept {sum(counts.values())} products -> {OUT_PATH}")
    print(counts)


if __name__ == "__main__":
    main()
