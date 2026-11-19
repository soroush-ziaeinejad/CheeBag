"""Add furniture, decor, lamps and TVs to the store, so Room studio has more to place in a room.

They are real listings and reviews from Amazon Reviews 2023 (downloaded by fetch_furniture.py). PICKS was chosen by
hand from the most-rated listings of each category (clear product photos, no near-duplicates), with a
short store name for each (Amazon titles are long lists of keywords).
TVs are sold by Breezeway Home Appliances (seller 5); everything else by Nestwell Bed & Bath (seller 6).

Run (after prepare_products.py, assign_sellers.py and prepare_reviews.py, which rewrite these files):
    python fetch_furniture.py products home        (and tools, electronics)
    python fetch_furniture.py reviews home         (and tools, electronics)
    python add_furniture.py
    python generate_policies.py && python validate_policies.py
Adds rows to products_clean.csv, product_sellers.csv and reviews_clean.csv, and updates two seller
descriptions in sellers.csv. Safe to re-run: the rows it added before are replaced.
"""
import glob
import hashlib
import html
import json
import os
import random
import re
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the data/ folder
IN_DIR = os.path.join(HERE, "storage", "furniture")
SEED = 7

SELLER_OF = {"Televisions": 5}   # every other category: 6
DEFAULT_SELLER = 6
NEW_DESCRIPTIONS = {
    5: "Portable air conditioners, fans, vacuums, air and vacuum filters, TVs and home comfort appliances.",
    6: "Furniture, rugs, lamps, mirrors and wall art, plus bedding, pillows, mattress protectors, bath accessories, "
       "laundry and closet storage.",
}

PICKS = {
    "Sofas & Couches": {
        "B09F9TW3CJ": "Serta Rane Convertible Sofa Bed",
        "B07SJ7V335": "Lilola Home Linen Reversible Sleeper Sectional Sofa",
        "B08FTTSXYW": "Zinus Josh Sofa",
        "B087CD89GM": "Rivet Revolve Modern Upholstered Sofa",
        "B08CNM1WDC": "Christopher Knight Home Karen Chesterfield Loveseat",
        "B09J23N374": "Lifestyle Solutions Grayson Loveseat",
        "B08CXWL47Y": "mopio Chloe Futon Sofa Bed",
        "B0862KK6MJ": "Rivet Aiden Mid-Century Velvet Sectional",
    },
    "Accent Chairs": {
        "B077MYRXND": "Homall Recliner Chair",
        "B08BRSZFW8": "Duhome Velvet Accent Chair",
        "B07ZGH2HJP": "HollyHOME Large Fabric Lazy Chair",
        "B0C3QG91HZ": "Yaheetech Velvet Barrel Chairs",
        "B0BF7MMC3X": "HomePop Velvet Swoop Arm Chair",
        "B0C1SR87R1": "Yaheetech Faux Leather Club Chairs",
    },
    "Coffee & Side Tables": {
        "B0BZJBT23T": "Furinno Simple Design Coffee Table",
        "B09QWFZWJC": "Yaheetech Lift Top Coffee Table",
        "B0C53B7HKC": "Household Essentials Walnut Cubby Coffee Table",
        "B0C53D6QGF": "WLIVE C Shaped End Table",
        "B0BS261J3X": "Convenience Concepts Oxford Console Table",
        "B07TWXW12F": "Amazon Basics Round Storage End Table",
        "B09C19CVV6": "Walker Edison Sedalia Farmhouse End Table",
    },
    "TV Stands": {
        "B09T1KWVP5": "Ameriwood Home Carson TV Stand",
        "B09C1DCSWK": "Walker Edison Barn Door Fireplace TV Stand",
        "B0BMR2TQNV": "Furinno Turn-N-Tube TV Stand",
        "B09MBT2MWY": "Walker Edison Richmond Barn Door TV Stand",
        "B08S6DNG7M": "Ameriwood Home Lumina Fireplace TV Stand",
    },
    "Beds & Bed Frames": {
        "B084QV5F98": "Amazon Basics Foldable Metal Platform Bed Frame",
        "B07D6QC9JX": "Crown Mark Erin Upholstered Panel Bed",
        "B08XN4RVFH": "Novogratz Bushwick Metal Bed",
        "B01G9B3GG8": "Home Life Platform Bed",
        "B07VQQ1FG2": "DHP Janford Upholstered Platform Bed",
        "B0C2QGT7RX": "Furinno Lille Button Tufted Bed Frame",
        "B0BJ89B3XD": "NEEBIRGELIA Metal Bed Frame with Headboard",
    },
    "Nightstands": {
        "B0B76H6FQS": "Winsome Wood Claire Accent Table",
        "B0BW16Y4YQ": "VASAGLE Nightstand",
        "B08X5S4R17": "Casual Home Owl Night Stand",
        "B0B646HPHS": "ADORNEVE Grey 3-Drawer Nightstand",
    },
    "Dressers": {
        "B07ZV2TR8N": "WLIVE 5-Drawer Fabric Dresser",
        "B0BQY6XZHX": "Sonoma 6-Drawer Double Dresser",
        "B0BZFJPRN1": "Sorbus 9-Drawer Fabric Dresser",
        "B0BLHLLXC1": "Prepac Sonoma 5-Drawer Chest",
    },
    "Dining Tables & Chairs": {
        "B07PX37VZG": "Furmax Mid-Century Dining Chairs",
        "B07PRDGJF7": "Zinus Juliet Dining Table with Two Benches",
        "B0C62BVQCG": "Best Choice Products 5-Piece Dining Set",
        "B078TSRSMS": "Zinus Jen 47-Inch Dining Table",
        "B08MPTR1NT": "Yaheetech Stackable Metal Dining Chairs",
        "B079ZNGZGP": "Ashley Owingsville Dining Table",
    },
    "Bookcases & Shelves": {
        "B0C5DXV5HW": "Furinno Jaya 3-Tier Bookcase",
        "B07P4CBZ9W": "Sauder Select 5-Shelf Bookcase",
        "B07XQHYHGB": "Amazon Basics 5-Tier Ladder Bookshelf",
        "B07P243Q2Q": "Sauder Select 3-Shelf Bookcase",
        "B07M5HRY1V": "South Shore Axess 5-Shelf Bookcase",
    },
    "Desks": {
        "B08PTYGCR6": "CubiCubi 47-Inch Computer Desk",
        "B08BLHXHQR": "Coavas Folding Desk",
        "B0BTHDXBZT": "SHW 48-Inch Computer Desk",
        "B0BM3PT42T": "SHW L-Shaped Corner Desk",
    },
    "Area Rugs": {
        "B091HQFKS2": "LOCHAS Ultra Soft Area Rug",
        "B092Q8Y4L6": "Maples Rugs Pelham Vintage Rug",
        "B0BX75448M": "Unique Loom Trellis Frieze Rug",
        "B0CCK4D5L3": "Artistic Weavers Odelia Round Rug",
        "B0BLL8D1PF": "SAFAVIEH Madison Boho Rug",
    },
    "Lamps": {
        "B0BHFLZDWB": "Limelights Stick Table Lamp",
        "B0BCYB8ZJ1": "Simple Designs Etagere Floor Lamp",
        "B0C5ZTM7GD": "Simple Designs Mother-Daughter Floor Lamp",
        "B078JYD34J": "Brightech Sky LED Torchiere",
        "B0C6KBPSTZ": "Lifeholder Touch Lamps (set of 2)",
        "B09RYKV7C5": "Globe Electric Holden Arc Floor Lamp",
    },
    "Televisions": {
        "B07H5S7X4X": "TCL 75-Inch 4K Roku TV",
        "B08KXFRDZW": "Samsung 55-Inch Crystal UHD TV",
        "B0BTPBBL52": "Samsung 32-Inch Smart FHD TV",
        "B099P2JF9Y": "Insignia 43-Inch 4K Fire TV",
        "B09GQJ1RR7": "LG OLED C1 55-Inch 4K TV",
        "B0B2951T3W": "Hisense 50-Inch 4K Android TV",
    },
    "Wall Art": {
        "B07C2KW596": "Wieco Art Abstract Tree Canvas",
        "B0BMQPGDSF": "Bird Canvas Wall Art (4 pieces)",
        "B085DG6C1G": "TutuBeer 3-Panel Beach Canvas",
    },
    "Artificial Plants": {
        "B084KD2964": "Nearly Natural 6 ft Ficus Tree",
        "B0BXSH9TRY": "Der Rose Mini Potted Fake Plants",
        "B0B56SQMZK": "The Bloom Times Fake Plants (2)",
    },
    "Mirrors": {
        "B0BC2WPMMW": "NeuType Arched Full Length Mirror",
        "B07KNWTZTR": "Black Round Wall Mirror",
        "B0BY2Z37R6": "Stonebriar Gold Geometric Mirror",
    },
}


def full_size_image(url):
    # ".../61NZkejMUIL._AC_SL1169_.jpg" -> ".../61NZkejMUIL.jpg"
    return re.sub(r"\._[^/]+_\.", ".", url)


def rug_size_cm(size):
    """Sides in cm from a rug size such as "2'6 x 3'10" or "4' x 5.3'" (feet and inches)."""
    sides = [float(ft) * 30.48 + float(inch or 0) * 2.54
             for ft, inch in re.findall(r"(\d+(?:\.\d+)?)'\s*(\d+(?:\.\d+)?)?", size or "")]
    return sorted(sides) if len(sides) == 2 else None


def dimensions_cm(details, category):
    """Width, depth and height in cm from e.g. '30"D x 70"W x 33"H' or '74 x 53 x 1.5 inches; 20 Pounds'.
    Amazon isn't consistent about which side is which, so flat things are sorted by size instead."""
    text = (details.get("Product Dimensions") or details.get("Item Dimensions L x W x H") or details.get("Size") or "")
    text = text.split(";")[0]                                   # drop the weight
    factor = 1 if re.search(r"\b(cm|centimeters)\b", text) else 2.54
    if category == "Area Rugs" and rug_size_cm(details.get("Size")):
        width, depth = rug_size_cm(details["Size"])
        return round(width, 1), round(depth, 1), None
    sides = {axis[0].replace("T", "H"): float(num) * factor
             for num, axis in re.findall(r'([\d.]+)\s*"?\s*(Th|[LWDH])\b', text)}
    nums = [float(n) * factor for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if category in ("Area Rugs", "Wall Art", "Mirrors"):         # the two largest sides are the face
        all_three = re.findall(r"\d+(?:\.\d+)?", details.get("Item Dimensions LxWxH", "").split(";")[0])
        if len(all_three) == 3:                                  # better than a 2-number "Product Dimensions"
            nums = [float(n) * factor for n in all_three]
        face = sorted(nums)[-2:]
        if len(face) < 2:
            return None, None, None
        if category == "Area Rugs":
            return round(face[0], 1), round(face[1], 1), None
        if category == "Mirrors":
            return round(face[0], 1), None, round(face[1], 1)      # mirrors: taller than wide
        return round(face[1], 1), None, round(face[0], 1)          # wall art: wider than tall
    if sides:
        width, depth, height = sides.get("W"), sides.get("D") or sides.get("L"), sides.get("H")
    elif len(nums) == 3:
        width, depth, height = max(nums[:2]), min(nums[:2]), nums[2]     # usually L x W x H
    else:
        return None, None, None
    return tuple(round(v, 1) if v else None for v in (width, depth, height))


def text_of(parts):
    return " ".join(" ".join(str(p) for p in parts or []).split())[:2000]


def product_row(item, product_id, category, name):
    details = item.get("details") or {}
    width, depth, height = dimensions_cm(details, category)
    asin = item["parent_asin"]
    return {
        "id": product_id,
        "source_asin": asin,
        "source_url": f"https://www.amazon.com/dp/{asin}",
        "name": name,
        "full_title": item["title"],
        "category": category,
        "description": text_of(item.get("features")) or text_of(item.get("description")),
        "original_price": f"{item['price']:.2f}",     # the Amazon price
        "price": f"{item['price']:.2f}",              # storefront price
        "currency": "CAD",
        "image_url": full_size_image(item["image_url"]),
        "brand": details.get("Brand") or item.get("store") or "",
        "color": details.get("Color") or "",
        "material": details.get("Material") or details.get("Frame Material") or details.get("Material Type") or "",
        "width_cm": width or "",
        "depth_cm": depth or "",
        "height_cm": height or "",
        "dimension_source": "amazon" if width or height else "",
        "rating": item["average_rating"],
        "rating_count": item["rating_number"],
        "stock_quantity": random.randint(3, 40),
        "active": True,
    }


def review_row(r, review_id, product_id):
    review_key = f"{r['user_id']}|{r['parent_asin']}|{r['timestamp']}"
    return {
        "review_id": review_id,
        "product_id": product_id,
        "source_review_id": "A23-" + hashlib.sha1(review_key.encode()).hexdigest()[:16],  # the 2023 data has no review ids
        "rating": int(r["rating"]),
        "title": html.unescape(r.get("title") or "").strip(),
        "body": html.unescape(r["text"].replace("<br />", "\n")).strip(),
        "variation": "",
        "helpful_count": int(r.get("helpful_vote") or 0),
        "verified_purchase": bool(r.get("verified_purchase")),
        "review_date": datetime.fromtimestamp(r["timestamp"] / 1000, timezone.utc).date().isoformat(),
    }


def read(name):
    # everything as text, so the existing rows are written back exactly as they were
    return pd.read_csv(os.path.join(HERE, name), dtype=str, keep_default_na=False)


def write(df, name):
    df.to_csv(os.path.join(HERE, name), index=False)


def main():
    random.seed(SEED)
    candidates = {}
    for path in glob.glob(os.path.join(IN_DIR, "candidates_*.jsonl")):
        for line in open(path):
            item = json.loads(line)
            candidates[item["parent_asin"]] = item
    picked = {asin: cat for cat, names in PICKS.items() for asin in names}
    names = {asin: name for picks in PICKS.values() for asin, name in picks.items()}
    missing = set(picked) - set(candidates)
    if missing:
        raise SystemExit(f"not in the downloaded candidates (run fetch_furniture.py products): {sorted(missing)}")

    products, sellers_map, reviews, sellers = (read(n) for n in
        ("products_clean.csv", "product_sellers.csv", "reviews_clean.csv", "sellers.csv"))

    # replace what an earlier run added
    old_ids = set(products.loc[products.source_asin.isin(picked), "id"])
    products = products[~products.id.isin(old_ids)]
    sellers_map = sellers_map[~sellers_map.product_id.isin(old_ids)]
    reviews = reviews[~reviews.product_id.isin(old_ids)]

    next_id = max(map(int, products.id)) + 1
    new_products, new_sellers, ids = [], [], {}
    for asin, cat in picked.items():
        ids[asin] = next_id
        new_products.append(product_row(candidates[asin], next_id, cat, names[asin]))
        new_sellers.append({"product_id": next_id, "seller_id": SELLER_OF.get(cat, DEFAULT_SELLER)})
        next_id += 1

    new_reviews, seen = [], set(reviews.source_review_id)
    next_review = max(map(int, reviews.review_id)) + 1
    for path in sorted(glob.glob(os.path.join(IN_DIR, "reviews_*.jsonl"))):
        for line in open(path):
            r = json.loads(line)
            if r["parent_asin"] not in ids or not r["text"].strip():
                continue
            row = review_row(r, next_review, ids[r["parent_asin"]])
            if row["source_review_id"] in seen or not row["body"]:
                continue
            seen.add(row["source_review_id"])
            new_reviews.append(row)
            next_review += 1

    for sid, text in NEW_DESCRIPTIONS.items():
        sellers.loc[sellers.seller_id == str(sid), "description"] = text

    write(pd.concat([products, pd.DataFrame(new_products).astype(str).replace({"None": ""})]), "products_clean.csv")
    write(pd.concat([sellers_map, pd.DataFrame(new_sellers).astype(str)]), "product_sellers.csv")
    write(pd.concat([reviews, pd.DataFrame(new_reviews).astype(str)]), "reviews_clean.csv")
    write(sellers, "sellers.csv")
    per_product = pd.Series([r["product_id"] for r in new_reviews]).value_counts()
    print(f"added {len(new_products)} products ({next_id - len(new_products)}-{next_id - 1}) and {len(new_reviews)} reviews "
          f"(fewest for one product: {per_product.min() if len(per_product) else 0}, "
          f"products without reviews: {len(new_products) - len(per_product)})")


if __name__ == "__main__":
    main()
