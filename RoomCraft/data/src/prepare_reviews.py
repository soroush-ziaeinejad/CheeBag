"""Keep the Amazon reviews of our store products and clean them for the reviews table.

Run:  python prepare_reviews.py   (after prepare_products.py)
Output: reviews_clean.csv
"""
import os

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the data/ folder (scripts live in data/src/)
IN_PATH = os.path.join(HERE, "storage", "reviews.csv")
OUT_PATH = os.path.join(HERE, "reviews_clean.csv")


def main():
    products = pd.read_csv(os.path.join(HERE, "products_clean.csv"), usecols=["id", "source_asin"]).rename(columns={"id": "product_id"})
    reviews = pd.read_csv(IN_PATH)

    # keep reviews of our products, with text, each review once
    reviews = reviews.merge(products, left_on="asin", right_on="source_asin")
    reviews = reviews[reviews.body.fillna("").str.strip() != ""]
    reviews = reviews.drop_duplicates(subset="id")

    out = pd.DataFrame({
        "review_id": range(1, len(reviews) + 1),
        "product_id": reviews["product_id"].values,
        "source_review_id": reviews["id"].values,
        "rating": reviews["stars"].values,
        "title": reviews["title"].values,
        "body": reviews["body"].str.strip().values,
        "variation": reviews["variation"].values,
        "helpful_count": reviews["found_helpful"].values,
        "verified_purchase": reviews["verified_purchase"].fillna(0).astype(bool).values,
        "review_date": pd.to_datetime(reviews["date"], format="%a %b %d %Y").dt.date.values,
    })
    # Amazon user_id, review url, images and videos are left out on purpose
    out.to_csv(OUT_PATH, index=False)
    print(f"wrote {len(out)} reviews for {out.product_id.nunique()} products -> {OUT_PATH}")


if __name__ == "__main__":
    main()
