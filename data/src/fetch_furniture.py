"""Download furniture, decor, lamp and TV listings, and their reviews, from Amazon Reviews 2023 (Hugging Face).

The files are large (up to 31 GB), so they are streamed and only what we need is kept.

Run:  python fetch_furniture.py products home          (also: tools, electronics)
          -> storage/furniture/candidates_<source>.jsonl   the most-rated listings of each category in TARGETS
      python fetch_furniture.py reviews home           (once PICKS in add_furniture.py lists the chosen products)
          -> storage/furniture/reviews_<source>.jsonl      up to REVIEWS_PER_PRODUCT reviews of each picked product
Then: python add_furniture.py
"""
import heapq
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the data/ folder
OUT_DIR = os.path.join(HERE, "storage", "furniture")
BASE = "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw"
FILES = {  # source -> (product metadata, reviews)
    "home": ("meta_categories/meta_Home_and_Kitchen.jsonl", "review_categories/Home_and_Kitchen.jsonl"),
    "tools": ("meta_categories/meta_Tools_and_Home_Improvement.jsonl", "review_categories/Tools_and_Home_Improvement.jsonl"),
    "electronics": ("meta_categories/meta_Electronics.jsonl", "review_categories/Electronics.jsonl"),
}
KEEP_PER_CATEGORY = 40      # candidates kept per category; add_furniture.py picks from them
REVIEWS_PER_PRODUCT = 30

# our category -> (source, Amazon category names that must all appear in the listing's category path)
TARGETS = {
    "Sofas & Couches": ("home", [{"Sofas & Couches"}]),
    "Accent Chairs": ("home", [{"Living Room Furniture", "Chairs"}]),
    "Coffee & Side Tables": ("home", [{"Living Room Furniture", "Tables"}]),
    "TV Stands": ("home", [{"TV & Media Furniture"}]),
    "Beds & Bed Frames": ("home", [{"Beds, Frames & Bases", "Beds"}, {"Beds, Frames & Bases", "Bed Frames"}]),
    "Nightstands": ("home", [{"Nightstands"}]),
    "Dressers": ("home", [{"Bedroom Furniture", "Dressers"}]),
    "Dining Tables & Chairs": ("home", [{"Dining Room Furniture", "Tables"}, {"Dining Room Furniture", "Table & Chair Sets"},
                                         {"Dining Room Furniture", "Chairs"}]),
    "Bookcases & Shelves": ("home", [{"Home Office Furniture", "Bookcases"}]),
    "Desks": ("home", [{"Home Office Desks"}]),
    "Area Rugs": ("home", [{"Rugs, Pads & Protectors", "Area Rugs"}]),
    "Wall Art": ("home", [{"Wall Art"}]),
    "Artificial Plants": ("home", [{"Artificial Plants & Greenery"}, {"Artificial Trees"}]),
    "Mirrors": ("home", [{"Home Décor Products", "Mirrors"}]),
    "Lamps": ("tools", [{"Lamps & Shades", "Table Lamps"}, {"Lamps & Shades", "Floor Lamps"}]),
    "Televisions": ("electronics", [{"Television & Video", "Televisions"}]),
}
# listings that match a category but aren't the thing itself
EXCLUDE = ["cover", "slipcover", "cushion", "replacement", "decal", "sticker", "toy", "doll", "miniature", "bulb only",
           "lamp shade", "rug pad", "mount", "remote", "antenna", "kids", "toddler", "crib", "bunkie", "box spring"]


def lines(path):
    """The lines of a remote file, read in 8 MB pieces; reconnects and continues where it stopped (HTTP Range)."""
    url, pos, rest = f"{BASE}/{path}", 0, b""
    while True:
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={pos}-"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                while chunk := resp.read(8 << 20):
                    pos += len(chunk)
                    *done, rest = (rest + chunk).split(b"\n")
                    yield from done
            if rest:
                yield rest
            return
        except OSError as e:
            print(f"download error at {pos:,} bytes: {e!r}; retrying")
            time.sleep(5)


def category_of(item, source):
    path = set(item.get("categories") or [])
    text = (item.get("title") or "").lower()
    if any(word in text for word in EXCLUDE):
        return None
    return next((cat for cat, (src, options) in TARGETS.items()
                 if src == source and any(option <= path for option in options)), None)


def main_image(item):
    for img in item.get("images") or []:
        if img.get("variant") == "MAIN" and (img.get("hi_res") or img.get("large")):
            return img.get("hi_res") or img.get("large")
    return None


def products(source):
    best = {cat: [] for cat, (src, _) in TARGETS.items() if src == source}   # min-heaps of (rating_number, asin, item)
    for i, line in enumerate(lines(FILES[source][0])):
        if i % 500_000 == 0:
            print(f"{source}: {i:,} lines | {[len(h) for h in best.values()]}", flush=True)
        item = json.loads(line)
        cat = category_of(item, source)
        if (cat is None or not item.get("title") or not item.get("parent_asin") or not main_image(item)
                or not isinstance(item.get("price"), (int, float)) or (item.get("average_rating") or 0) < 4.0
                or (item.get("rating_number") or 0) < 300):
            continue
        item["our_category"], item["image_url"] = cat, main_image(item)
        entry = (item["rating_number"], item["parent_asin"], item)
        heap = best[cat]
        if any(e[1] == item["parent_asin"] for e in heap):
            continue
        if len(heap) < KEEP_PER_CATEGORY:
            heapq.heappush(heap, entry)
        elif entry[0] > heap[0][0]:
            heapq.heapreplace(heap, entry)
    out = os.path.join(OUT_DIR, f"candidates_{source}.jsonl")
    with open(out, "w") as f:
        for heap in best.values():
            for _, _, item in sorted(heap, key=lambda e: e[:2], reverse=True):
                f.write(json.dumps(item) + "\n")
    print(f"{source}: done -> {out}")


def reviews(source):
    from add_furniture import PICKS
    wanted = {asin: 0 for cat, asins in PICKS.items() if TARGETS[cat][0] == source for asin in asins}
    out = os.path.join(OUT_DIR, f"reviews_{source}.jsonl")
    with open(out, "w") as f:
        for i, line in enumerate(lines(FILES[source][1])):
            if i % 2_000_000 == 0:
                print(f"{source}: {i:,} reviews read | {sum(wanted.values())} kept", flush=True)
            if b'"parent_asin"' not in line:
                continue
            r = json.loads(line)
            asin = r.get("parent_asin")
            if asin in wanted and wanted[asin] < REVIEWS_PER_PRODUCT and (r.get("text") or "").strip():
                f.write(json.dumps(r) + "\n")
                wanted[asin] += 1
                if all(n >= REVIEWS_PER_PRODUCT for n in wanted.values()):
                    break
    print(f"{source}: done, {sum(wanted.values())} reviews -> {out}")


if __name__ == "__main__":
    step, source = sys.argv[1], sys.argv[2]
    os.makedirs(OUT_DIR, exist_ok=True)
    {"products": products, "reviews": reviews}[step](source)
