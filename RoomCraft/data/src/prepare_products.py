"""Turn home&kitchen.csv into a clean products table for the store.

Run:  python prepare_products.py
Output: products_clean.csv
"""
import json
import os
import random
import re

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the data/ folder (scripts live in data/src/)
IN_PATH = os.path.join(HERE, "storage", "home&kitchen.csv")
OUT_PATH = os.path.join(HERE, "products_clean.csv")
SEED = 42

# simulated price range (USD) per category, used when the description shows no price
PRICE_RANGES = {
    "Kitchen Utensils & Gadgets": (8, 35),
    "Coffee, Tea & Espresso": (15, 120),
    "Storage & Organization": (10, 45),
    "Dining & Entertaining": (12, 50),
    "Small Appliances": (40, 150),
    "Parts & Accessories": (15, 60),
    "Kitchen & Table Linens": (10, 30),
    "Bathroom Accessories": (10, 40),
    "Vacuum Parts & Accessories": (10, 35),
    "Wine Accessories": (10, 40),
    "Household Fans": (30, 100),
    "Vacuums": (80, 300),
    "Photo Albums, Frames & Accessories": (10, 35),
    "Kids' Bedding": (20, 50),
    "Sheets & Pillowcases": (20, 60),
    "Clothing & Closet Storage": (15, 40),
    "Mattress Protectors & Encasements": (20, 50),
    "Bath Rugs": (10, 30),
    "Decorative Pillows, Inserts & Covers": (15, 40),
    "Bed Pillows & Positioners": (20, 60),
    "Air Conditioners": (150, 400),
    "Laundry Storage & Organization": (15, 40),
    "Home Décor Accents": (15, 50),
    "Bakeware": (10, 35),
    "Favors": (8, 25),
}
DEFAULT_RANGE = (10, 40)


def flat_characteristics(text):
    """characteristics is {"0": {...}, "1": {...}}; merge groups into one dict."""
    merged = {}
    for group in json.loads(text).values():
        merged.update(group)
    return {k: str(v).replace("‎", "").strip() for k, v in merged.items()}


def short_name(title):
    return title.split(",")[0].strip()[:80]


def category(breadcrumbs):
    parts = breadcrumbs.split(" -> ")
    return parts[2] if len(parts) > 2 else parts[-1]


def about_section(description):
    m = re.search(r"About this item(.*?)(›|Product information|$)", description, flags=re.S)
    text = m.group(1) if m else description[:500]
    return " ".join(text.split())


def listed_price(description):
    """Some descriptions have a comparison table whose first 'Price $x' is this product."""
    m = re.search(r"Price \$(\d+\.\d\d)", description)
    return float(m.group(1)) if m else None


def simulated_price(cat):
    low, high = PRICE_RANGES.get(cat, DEFAULT_RANGE)
    return round(random.uniform(low, high)) - 0.01


def full_size_image(url):
    # ".../71Cfld2aMpL.__AC_SX300_SY300_QL70_ML2_.jpg" -> ".../71Cfld2aMpL.jpg"
    return re.sub(r"\._[^/]+_\.", ".", url)


def dimensions_cm(ch):
    """Parse '7.5"L x 6"W x 6"H' (inches) into width/depth/height in cm."""
    text = ch.get("Item Dimensions L x W x H") or ch.get("Item Dimensions W x H") or ""
    sides = {axis: round(float(num) * 2.54, 1) for num, axis in re.findall(r'([\d.]+)"([LWH])', text)}
    if "H" not in sides and ch.get("Item Height", "").endswith("inches"):
        sides["H"] = round(float(ch["Item Height"].split()[0]) * 2.54, 1)
    return sides.get("W"), sides.get("L"), sides.get("H")


def main():
    random.seed(SEED)
    df = pd.read_csv(IN_PATH)
    rows = []
    for i, r in enumerate(df.itertuples(), start=1):
        ch = flat_characteristics(r.characteristics)
        width, depth, height = dimensions_cm(ch)
        cat = category(r.breadcrumbs)
        original = listed_price(r.description)
        rows.append({
            "id": i,
            "source_asin": r.asin,
            "source_url": r.url,
            "name": short_name(r.title),
            "full_title": r.title,
            "category": cat,
            "description": about_section(r.description),
            "original_price": original,  # from Amazon description, empty if not shown
            "price": original or simulated_price(cat),  # storefront price
            "currency": "USD",
            "image_url": full_size_image(r.main_image),
            "brand": ch.get("Brand Name"),
            "color": ch.get("Color"),
            "material": ch.get("Material Type") or ch.get("Material"),
            "width_cm": width,
            "depth_cm": depth,
            "height_cm": height,
            "dimension_source": "amazon" if height or width else None,
            "rating": r.rating,
            "rating_count": r.number_of_ratings,
            "stock_quantity": random.randint(0, 50),
            "active": True,
        })
    out = pd.DataFrame(rows)
    out.to_csv(OUT_PATH, index=False)
    print(f"wrote {len(out)} products -> {OUT_PATH}")
    print(out.isna().sum().to_string())


if __name__ == "__main__":
    main()
