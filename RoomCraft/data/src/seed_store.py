"""Generate synthetic customers, orders, order_items, payments and shipments with Faker.

Run:  python seed_store.py   (after prepare_products.py)
Output: customers.csv, orders.csv, order_items.csv, payments.csv, shipments.csv
"""
import os
import random
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the data/ folder (scripts live in data/src/)
SEED = 42
NOW = datetime(2026, 11, 5, 12, 0)  # fixed "today" so every run gives the same data
N_CUSTOMERS = 100
N_ORDERS = 500

# order status -> (weight, min days ago, max days ago)
STATUSES = {
    "pending": (8, 0, 1),
    "processing": (10, 1, 3),
    "shipped": (12, 3, 8),
    "delivered": (60, 10, 365),
    "cancelled": (10, 1, 365),
}
CARRIERS = ["UPS", "FedEx", "USPS", "DHL"]
PAYMENT_METHODS = ["credit_card", "paypal", "gift_card"]

fake = Faker("en_US")


def make_customers():
    customers = []
    for cid in range(1, N_CUSTOMERS + 1):
        first, last = fake.first_name(), fake.last_name()
        customers.append({
            "customer_id": cid,
            "first_name": first,
            "last_name": last,
            "email": f"{first}.{last}.{cid}@example.com".lower(),  # example.com: never a real inbox
            "phone": fake.phone_number(),
            "created_at": NOW - timedelta(days=random.randint(400, 900)),
            "address": fake.address().replace("\n", ", "),  # used as default shipping address
        })
    return customers


def make_order(order_id, customer, products):
    status = random.choices(list(STATUSES), weights=[w for w, _, _ in STATUSES.values()])[0]
    _, min_days, max_days = STATUSES[status]
    order_date = NOW - timedelta(days=random.uniform(min_days, max_days))

    items = []
    for p in random.sample(products, k=random.randint(1, 4)):
        items.append({
            "order_id": order_id,
            "product_id": p["id"],
            "quantity": random.randint(1, 3),
            "unit_price": p["price"],  # price at purchase time
        })
    total = round(sum(i["quantity"] * i["unit_price"] for i in items), 2)

    # payment: pending orders not paid yet, cancelled orders refunded
    paid_at = order_date + timedelta(minutes=random.randint(1, 30))
    payment = {
        "order_id": order_id,
        "amount": total,
        "payment_method": random.choice(PAYMENT_METHODS),
        "status": {"pending": "pending", "cancelled": "refunded"}.get(status, "paid"),
        "transaction_reference": f"SIM-{fake.unique.bothify('????-########').upper()}",
        "paid_at": None if status == "pending" else paid_at,
    }

    # shipment: none before processing or after cancellation
    shipment = None
    updated_at = paid_at if status != "pending" else order_date
    if status == "cancelled":
        updated_at = order_date + timedelta(hours=random.randint(1, 48))
    elif status in ("processing", "shipped", "delivered"):
        carrier = random.choice(CARRIERS)
        shipped_at = order_date + timedelta(days=random.uniform(1, 2)) if status != "processing" else None
        estimated = (shipped_at or order_date) + timedelta(days=random.randint(3, 6))
        delivered_at = shipped_at + timedelta(days=random.uniform(2, 6)) if status == "delivered" else None
        shipment = {
            "order_id": order_id,
            "carrier": carrier,
            "tracking_number": fake.bothify("1Z#########???").upper() if shipped_at else None,
            "status": {"processing": "pending", "shipped": "in_transit", "delivered": "delivered"}[status],
            "shipped_at": shipped_at,
            "estimated_delivery": estimated.date(),
            "delivered_at": delivered_at,
        }
        updated_at = delivered_at or shipped_at or updated_at

    order = {
        "order_id": order_id,
        "customer_id": customer["customer_id"],
        "order_date": order_date,
        "status": status,
        "total_amount": total,
        "shipping_address": customer["address"],
        "updated_at": updated_at,
    }
    return order, items, payment, shipment


def main():
    random.seed(SEED)
    Faker.seed(SEED)
    products = pd.read_csv(os.path.join(HERE, "products_clean.csv")).to_dict("records")
    customers = make_customers()

    orders, items, payments, shipments = [], [], [], []
    for order_id in range(1001, 1001 + N_ORDERS):
        order, order_items, payment, shipment = make_order(order_id, random.choice(customers), products)
        orders.append(order)
        items.extend(order_items)
        payments.append(payment)
        if shipment:
            shipments.append(shipment)

    # add sequential ids to child tables
    for name, rows in [("order_item_id", items), ("payment_id", payments), ("shipment_id", shipments)]:
        for i, row in enumerate(rows, start=1):
            row[name] = i

    tables = {
        "customers": (customers, ["customer_id", "first_name", "last_name", "email", "phone", "address", "created_at"]),
        "orders": (orders, ["order_id", "customer_id", "order_date", "status", "total_amount", "shipping_address", "updated_at"]),
        "order_items": (items, ["order_item_id", "order_id", "product_id", "quantity", "unit_price"]),
        "payments": (payments, ["payment_id", "order_id", "amount", "payment_method", "status", "transaction_reference", "paid_at"]),
        "shipments": (shipments, ["shipment_id", "order_id", "carrier", "tracking_number", "status", "shipped_at", "estimated_delivery", "delivered_at"]),
    }
    for name, (rows, columns) in tables.items():
        df = pd.DataFrame(rows)[columns]
        df.to_csv(os.path.join(HERE, f"{name}.csv"), index=False, date_format="%Y-%m-%d %H:%M:%S")
        print(f"{name}: {len(df)} rows")


if __name__ == "__main__":
    main()
