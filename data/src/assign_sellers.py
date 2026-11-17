"""Create the store's sellers and assign every product to exactly one of them.

Sellers are the (fictional) retailers that sell and ship products through Chideman.
They are not the same as brands: `products.brand` is the manufacturer (e.g. YETI, Instant Pot),
and one seller sells many brands.

Run:  python assign_sellers.py   (after prepare_products.py)
Output: sellers.csv, product_sellers.csv   (products_clean.csv is not changed)
"""
import os

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the data/ folder (scripts live in data/src/)

SELLERS = [
    {"seller_id": 1, "name": "Copperline Kitchen Supply", "legal_name": "Copperline Kitchen Supply Ltd.",
     "description": "Cooking tools, kitchen gadgets, kitchen linens, tableware and kitchen storage.",
     "support_email": "care@copperline.example", "support_phone": "1-800-555-0141",
     "headquarters": "Toronto, Ontario", "founded_year": 2009},
    {"seller_id": 2, "name": "Kettle & Crema Co.", "legal_name": "Kettle and Crema Company Inc.",
     "description": "Electric kettles, coffee and tea makers, mug warmers and countertop appliances.",
     "support_email": "hello@kettleandcrema.example", "support_phone": "1-800-555-0152",
     "headquarters": "Vancouver, British Columbia", "founded_year": 2014},
    {"seller_id": 3, "name": "Cork & Pour Barware", "legal_name": "Cork and Pour Barware LLC",
     "description": "Wine and bar tools, bottle stoppers, pourers, ice buckets and party supplies.",
     "support_email": "cheers@corkandpour.example", "support_phone": "1-800-555-0163",
     "headquarters": "Sonoma, California", "founded_year": 2017},
    {"seller_id": 4, "name": "Trailmate Drinkware", "legal_name": "Trailmate Outfitters Inc.",
     "description": "Insulated water bottles, tumblers, travel mugs, lunch bags and can coolers.",
     "support_email": "support@trailmate.example", "support_phone": "1-800-555-0174",
     "headquarters": "Boulder, Colorado", "founded_year": 2012},
    {"seller_id": 5, "name": "Breezeway Home Appliances", "legal_name": "Breezeway Home Appliances Corp.",
     "description": "Portable air conditioners, fans, vacuums, air and vacuum filters, and home comfort appliances.",
     "support_email": "service@breezewayhome.example", "support_phone": "1-800-555-0185",
     "headquarters": "Mississauga, Ontario", "founded_year": 2006},
    {"seller_id": 6, "name": "Nestwell Bed & Bath", "legal_name": "Nestwell Home Goods Ltd.",
     "description": "Bedding, pillows, mattress protectors, bath accessories, laundry and closet storage, and home decor.",
     "support_email": "help@nestwell.example", "support_phone": "1-800-555-0196",
     "headquarters": "Halifax, Nova Scotia", "founded_year": 2011},
]

# rules are checked in order; the first match wins. Matching uses category + full product title.
APPLIANCE_CATEGORIES = {"Air Conditioners", "Household Fans", "Vacuums", "Vacuum Parts & Accessories", "Parts & Accessories"}
COFFEE_CATEGORIES = {"Coffee, Tea & Espresso", "Small Appliances"}
BED_BATH_HOME_CATEGORIES = {"Kids' Bedding", "Sheets & Pillowcases", "Bed Pillows & Positioners",
                            "Mattress Protectors & Encasements", "Decorative Pillows, Inserts & Covers",
                            "Bath Rugs", "Bathroom Accessories", "Laundry Storage & Organization",
                            "Clothing & Closet Storage", "Photo Albums, Frames & Accessories", "Home Décor Accents"}
BAR_WORDS = ["wine", "champagne", "pourer", "pour spout", "bottle stopper", "ice bucket", "ice serving", "corkscrew", "liquor"]
DRINKWARE_WORDS = ["water bottle", "tumbler", "mug", "flask", "lunch", "can cooler", "cup sleeve", "insulated"]


def seller_for(product):
    text = f"{product['name']} {product['full_title']}".lower()
    category = product["category"]
    if category in APPLIANCE_CATEGORIES or "towel warmer" in text:
        return 5, "home comfort appliance or filter"
    if category in COFFEE_CATEGORIES:
        return 2, "coffee, tea or countertop appliance"
    if category in ("Wine Accessories", "Favors") or any(w in text for w in BAR_WORDS):
        return 3, "wine, bar or party item"
    # some drinkware titles are short (e.g. "STANLEY Quencher H2.0 FlowState Stainless Steel"), so also check how the description starts
    if any(w in f"{text} {str(product['description'])[:150].lower()}" for w in DRINKWARE_WORDS):
        return 4, "drinkware or lunch gear"
    if category in BED_BATH_HOME_CATEGORIES or "bathroom organizer" in text:
        return 6, "bed, bath or home item"
    return 1, "kitchen tool, linen, tableware or kitchen storage"


def main():
    products = pd.read_csv(os.path.join(HERE, "products_clean.csv"))
    rows = []
    for p in products.to_dict("records"):
        seller_id, reason = seller_for(p)
        rows.append({"product_id": p["id"], "seller_id": seller_id, "reason": reason})

    mapping = pd.DataFrame(rows)
    pd.DataFrame(SELLERS).to_csv(os.path.join(HERE, "sellers.csv"), index=False)
    mapping[["product_id", "seller_id"]].to_csv(os.path.join(HERE, "product_sellers.csv"), index=False)

    names = {s["seller_id"]: s["name"] for s in SELLERS}
    print(f"{len(SELLERS)} sellers, {len(mapping)} products assigned")
    for seller_id, n in mapping.seller_id.value_counts().sort_index().items():
        print(f"  {seller_id} {names[seller_id]:28} {n} products")


if __name__ == "__main__":
    main()
