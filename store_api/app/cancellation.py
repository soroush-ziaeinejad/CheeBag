"""Can this order be cancelled right now?

The rules come from each seller's policy (data/policies/policy_facts.json), the same source the
policy PDFs were generated from, so the Store API never contradicts what the PDFs say.
An order with items from several sellers can be cancelled only if every seller allows it.
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import cache

POLICY_FACTS_PATH = os.environ.get("POLICY_FACTS_PATH", "/policies/policy_facts.json")


@cache
def seller_rules():
    """seller_id -> cancellation rule, read once from the policy facts file."""
    with open(POLICY_FACTS_PATH) as f:
        facts = json.load(f)
    rules = {}
    for seller in facts["sellers"]:
        kv = seller["key_values"]
        rules[kv["seller_id"]] = {
            "name": kv["seller_name"],
            "statuses": {s.lower() for s in kv["cancellable_statuses"]},  # e.g. {"pending", "processing"}
            "window_hours": kv["free_cancellation_window_hours"],          # None = any time in those statuses
            "fee_after_window": kv["cancellation_fee_after_window_cad"],   # None = not allowed after the window
            "refund_days": kv["cancellation_refund_business_days"],
        }
    return rules


@dataclass
class Decision:
    allowed: bool
    reason: str = ""                                      # why not, in words CHEE can repeat
    fee: Decimal = Decimal("0")
    fee_notes: list[str] = field(default_factory=list)
    refund_days: int = 0
    sellers: list[str] = field(default_factory=list)


def check_cancellation(order, now=None):
    """Decide for an Order loaded with items -> product. Never changes anything."""
    now = now or datetime.now(timezone.utc)
    if order.status == "cancelled":
        return Decision(False, "This order is already cancelled.")
    if order.status in ("shipped", "delivered"):
        return Decision(False, f"This order has already {'been delivered' if order.status == 'delivered' else 'shipped'}, "
                               "so it can't be cancelled. It can be returned after delivery instead.")

    rules = seller_rules()
    age = now - order.order_date
    decision = Decision(True)
    for seller_id in sorted({item.product.seller_id for item in order.items}):
        rule = rules.get(seller_id)
        if rule is None:
            return Decision(False, "Part of this order comes from a seller without a cancellation policy, "
                                   "so it can't be cancelled here.")
        name = rule["name"]
        decision.sellers.append(name)
        decision.refund_days = max(decision.refund_days, rule["refund_days"])
        if order.status not in rule["statuses"]:
            allowed = " or ".join(sorted(rule["statuses"]))
            return Decision(False, f"{name} only allows cancellation while an order is {allowed}, "
                                   f"and this order is {order.status}.")
        window = rule["window_hours"]
        if window is None or age <= timedelta(hours=window):
            continue
        if rule["fee_after_window"] is not None:
            fee = Decimal(str(rule["fee_after_window"]))
            decision.fee += fee
            decision.fee_notes.append(f"{name} charges a ${fee:.2f} cancellation fee after the free {window}-hour window.")
            continue
        return Decision(False, f"{name} allows cancellation only within {window} hours of ordering, "
                               f"and this order was placed {age.days} days ago. It can be returned after delivery instead.")
    return decision
