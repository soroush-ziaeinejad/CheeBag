"""New orders: from the website's shopping cart, or proposed by CHEE and confirmed by the customer.

    cart     POST /customers/{customer_id}/orders           {items: [{product_id, quantity}], shipping_address}
    CHEE     POST /customers/{customer_id}/order-proposal   {items, shipping_address (optional)}
             then the customer's click: POST /actions/confirm (actions.py hands it to confirm_order below)

The cart's Submit order is the customer's click, so it creates the order at once. A proposal only makes a
confirmation card; nothing is ordered until the customer clicks Place order on it. The card ships to the
customer's saved address unless CHEE was given another one, and the customer can change it on the card.

Either way place() makes the order: every product must be for sale and in stock, and prices come from the
database. CheeBag is a demo: no real payment is taken. The order is paid with the customer's most recent
payment method, so it can be cancelled with a refund like any other.
"""
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .actions import PAYMENT_NAMES, TOKEN_LIFETIME, hash_token, log_event, money, now_utc
from .db import get_db
from .models import Customer, Order, OrderItem, Payment, PendingAction, Product, Shipment

router = APIRouter()


class ItemIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=10)


class OrderIn(BaseModel):
    items: list[ItemIn] = Field(min_length=1, max_length=20)
    shipping_address: str = Field(min_length=10, max_length=200)


class ProposalIn(BaseModel):
    items: list[ItemIn] = Field(min_length=1, max_length=6)
    shipping_address: str | None = Field(default=None, min_length=10, max_length=200)   # None: the saved address


def merged(items):
    """{product_id: quantity}; the same product twice adds up."""
    quantities = {}
    for item in items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
    return quantities


def problem(products, quantities):
    """Why these can't be ordered right now, or None."""
    for product_id, quantity in quantities.items():
        p = products.get(product_id)
        if p is None or not p.active:
            return f"Product {product_id} isn't for sale any more."
        if p.stock_quantity < quantity:
            return f"Only {p.stock_quantity} of {p.name} left in stock." if p.stock_quantity else f"{p.name} is out of stock."
    return None


def payment_method(db, customer_id):
    return db.scalar(select(Payment.payment_method).join(Order).where(Order.customer_id == customer_id)
                     .order_by(Order.order_date.desc()).limit(1)) or "credit_card"


def place(db, customer_id, quantities, address, prices=None, **detail):
    """Create the order (not committed). Raises ValueError with the reason if it can't be placed.
    prices: {product_id: "12.99"} the customer was shown; the order fails if any changed."""
    # locked until commit, so two orders can't both take the last one
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(quantities)).with_for_update())}
    reason = problem(products, quantities)
    if reason is None and prices and any(money(products[k].price) != v for k, v in prices.items()):
        reason = "A price changed since this order was offered."
    if reason:
        raise ValueError(reason)

    now = now_utc()
    # paid at once, so (like the rest of the data, checks.sql) it is processing and has a pending shipment
    order = Order(customer_id=customer_id, order_date=now, status="processing", updated_at=now,
                  total_amount=sum(products[k].price * q for k, q in quantities.items()), shipping_address=address)
    db.add(order)
    db.flush()                                              # assigns order.order_id
    for product_id, quantity in quantities.items():
        p = products[product_id]
        db.add(OrderItem(order_id=order.order_id, product_id=p.id, quantity=quantity, unit_price=p.price))
        p.stock_quantity -= quantity
    db.add(Payment(order_id=order.order_id, amount=order.total_amount, payment_method=payment_method(db, customer_id),
                   status="paid", transaction_reference=f"SIM-{secrets.token_hex(6).upper()}", paid_at=now))
    db.add(Shipment(order_id=order.order_id, status="pending", carrier="Canada Post" if "canada" in address.lower() else "UPS",
                    estimated_delivery=(now + timedelta(days=5)).date()))
    log_event(db, "order_created", customer_id, order.order_id, total=money(order.total_amount), **detail)
    return order


@router.post("/customers/{customer_id}/orders")
def create_order(customer_id: int, body: OrderIn, db: Session = Depends(get_db)):
    if db.get(Customer, customer_id) is None:
        raise HTTPException(404, "Customer not found")
    try:
        order = place(db, customer_id, merged(body.items), body.shipping_address.strip(), source="cart")
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return {"order_id": order.order_id, "status": order.status, "total": money(order.total_amount)}


@router.post("/customers/{customer_id}/order-proposal")
def propose_order(customer_id: int, body: ProposalIn, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    quantities = merged(body.items)
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(quantities)))}
    reason = problem(products, quantities)
    address = (body.shipping_address or customer.address or "").strip()
    if reason is None and not address:
        reason = "There's no saved address for this customer. Ask them where to ship it."
    if reason:
        return {"allowed": False, "reason": reason}

    method = payment_method(db, customer_id)
    total = sum(products[k].price * q for k, q in quantities.items())
    card = {   # what the confirmation card shows; built here, never by the model
        "kind": "create_order",
        "items": [{"product_id": k, "name": products[k].name, "quantity": q, "unit_price": money(products[k].price),
                   "line_total": money(products[k].price * q)} for k, q in quantities.items()],
        "currency": "CAD",
        "total": money(total),
        "shipping_address": address,
        "address_is_saved": body.shipping_address is None,
        "consequences": [f"${money(total)} CAD will be charged to your {PAYMENT_NAMES.get(method, method)}.",
                         "Demo only: no real money is charged and nothing is shipped."],
    }
    token = secrets.token_urlsafe(32)
    action = PendingAction(token_hash=hash_token(token), customer_id=customer_id, action_type="create_order",
                           payload=card, status="pending", created_at=now_utc(), expires_at=now_utc() + TOKEN_LIFETIME)
    db.add(action)
    db.flush()                                              # assigns action.action_id
    log_event(db, "order_proposed", customer_id, action_id=action.action_id, total=card["total"])
    db.commit()
    return {"allowed": True, "token": token, "expires_at": action.expires_at.isoformat(), "card": card}


def confirm_order(db, action, address=None):
    """The customer clicked Place order: called by /actions/confirm for a pending, unexpired create_order action.
    address: the one the customer typed on the card, or None to keep the card's."""
    card = action.payload
    address = (address or card["shipping_address"]).strip()
    try:
        order = place(db, action.customer_id, {i["product_id"]: i["quantity"] for i in card["items"]}, address,
                      prices={i["product_id"]: i["unit_price"] for i in card["items"]},
                      action_id=action.action_id, source="chee")
    except ValueError as e:
        action.status, action.resolved_at = "failed", now_utc()
        log_event(db, "order_rejected", action.customer_id, action_id=action.action_id, reason=str(e))
        db.commit()
        raise HTTPException(409, {"code": "not_available", "message": f"{e} Nothing was ordered."})
    result = {"order_id": order.order_id, "status": order.status, "total": money(order.total_amount),
              "shipping_address": address, "message": f"Order #{order.order_id} is placed."}
    action.order_id, action.status, action.result, action.resolved_at = order.order_id, "confirmed", result, now_utc()
    db.commit()
    return {**result, "already_done": False}
