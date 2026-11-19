"""Check that sellers, product assignments, policy PDFs, manifest and ground truth all agree.

Run:  python validate_policies.py   (needs: pip install pypdf pandas)
Every line should say PASS; the script exits with an error if any check fails.
"""
import hashlib
import json
import os
import sys

import pandas as pd
from pypdf import PdfReader

from generate_policies import OUT_DIR, PROJECT_ROOT, days_range, money, pdf_name
from policy_facts import POLICIES

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def main():
    sellers = pd.read_csv(os.path.join(HERE, "sellers.csv"))
    products = pd.read_csv(os.path.join(HERE, "products_clean.csv"))
    mapping = pd.read_csv(os.path.join(HERE, "product_sellers.csv"))
    manifest = json.load(open(os.path.join(OUT_DIR, "manifest.json")))["documents"]
    facts = json.load(open(os.path.join(OUT_DIR, "policy_facts.json")))["sellers"]
    seller_ids = set(sellers.seller_id)

    # ---- seller data
    check("seller IDs and names are unique", sellers.seller_id.is_unique and sellers.name.is_unique)
    check("every product has exactly one seller row", set(mapping.product_id) == set(products.id) and mapping.product_id.is_unique,
          f"{len(set(products.id) - set(mapping.product_id))} products without a seller")
    check("every assigned seller exists", set(mapping.seller_id) <= seller_ids)
    check("every seller sells at least one product", seller_ids <= set(mapping.seller_id))

    # ---- manifest <-> sellers
    by_id = {d["seller_id"]: d for d in manifest}
    check("exactly one current PDF per seller", len(manifest) == len(sellers) and set(by_id) == seller_ids
          and all(d["is_current"] for d in manifest))
    pdfs_on_disk = {f for f in os.listdir(OUT_DIR) if f.endswith(".pdf")}
    check("no extra or stale PDFs in the folder", pdfs_on_disk == {os.path.basename(d["pdf_path"]) for d in manifest},
          str(pdfs_on_disk ^ {os.path.basename(d["pdf_path"]) for d in manifest}))
    cats = products.merge(mapping, left_on="id", right_on="product_id").groupby("seller_id").category.apply(lambda c: sorted(set(c)))
    counts = mapping.seller_id.value_counts()

    texts = {}
    for s in sellers.to_dict("records"):
        d, f = by_id[s["seller_id"]], POLICIES[s["seller_id"]]
        path = os.path.join(PROJECT_ROOT, d["pdf_path"])
        tag = f"seller {s['seller_id']}"
        check(f"{tag}: manifest name, file name and categories match the database",
              d["seller_name"] == s["name"] and os.path.basename(path) == pdf_name(s["name"])
              and d["product_categories"] == cats[s["seller_id"]] and d["product_count"] == counts[s["seller_id"]])
        data = open(path, "rb").read()
        check(f"{tag}: checksum matches", d["document_checksum"] == "sha256:" + hashlib.sha256(data).hexdigest())
        reader = PdfReader(path)
        text = " ".join(" ".join((p.extract_text() or "").split()) for p in reader.pages)
        texts[s["seller_id"]] = text
        check(f"{tag}: readable, {len(reader.pages)} pages, text extractable",
              len(reader.pages) == d["page_count"] and len(text) > 15000, f"{len(text)} characters")
        sh, r = f["shipping"], f["returns"]
        must_contain = [s["name"], s["legal_name"], f"Version {f['policy_version']}", f"Effective {f['effective_date']}",
                        f"CheeBag seller ID {s['seller_id']}", f"within {r['window_days']} days of the delivery date",
                        f"orders of {money(sh['free_threshold_cad'])} or more", money(sh["standard_fee_cad"]),
                        days_range(sh["standard_business_days"]), f"within {f['refund_processing_business_days']} business days",
                        f"within {f['damage_report_days']} days of the delivery date", f["cancellation"]["rule"][:60],
                        "Frequently Asked Questions", "Key Policies at a Glance", "Fictional demonstration document"]
        if r["restocking_fee_percent"]:
            must_contain.append(f"{r['restocking_fee_percent']}%")
        missing = [m for m in must_contain if m not in text]
        check(f"{tag}: key policy values appear in the PDF text", not missing, f"missing: {missing}")
        others = [o["name"] for o in sellers.to_dict("records") if o["seller_id"] != s["seller_id"]]
        check(f"{tag}: no other seller's name in its handbook", not any(o in text for o in others))

    # ---- ground truth
    check("policy_facts.json has one entry per seller, matching policy_facts.py",
          sorted(x["key_values"]["seller_id"] for x in facts) == sorted(seller_ids)
          and all(x["details"] == json.loads(json.dumps(POLICIES[x["key_values"]["seller_id"]])) for x in facts))
    kv = [x["key_values"] for x in facts]
    for field in ("return_window_days", "free_shipping_threshold_cad", "refund_processing_business_days",
                  "damage_report_days", "standard_shipping_fee_cad"):
        distinct = len({json.dumps(k[field]) for k in kv})
        check(f"sellers differ on {field} ({distinct} distinct values)", distinct >= 4)

    # ---- internal consistency of the rules
    for sid, f in POLICIES.items():
        p, c = f["personalization"], f["cancellation"]
        ok = (not p or ("engraved_window_hours" in c or "monogram_window_hours" in c)) \
            and (bool(f["returns"]["restocking_fee_percent"]) == ("restocking" in f["returns"]["condition"] or "restocking_fee_applies_to" in f["returns"])) \
            and (f["exchanges"]["allowed"] == (f["exchanges"]["window_days"] > 0)) \
            and (c["fee_after_window_cad"] is None or c["free_window_hours"] is not None)
        check(f"seller {sid}: rules are internally consistent", ok)
    check("only sellers with oversized products have freight rules",
          {sid for sid, f in POLICIES.items() if f["large_items"]} == {5})

    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
