"""Order changes that CHEE proposes and the customer confirms.

    propose  POST /customers/{customer_id}/orders/{order_id}/cancel-proposal   (called by the agent)
    list     GET  /orders/cancellable                                         (demo customer picker)
    confirm  POST /actions/confirm   {customer_id, token}                       (called by Django when the customer clicks)
    discard  POST /actions/discard   {customer_id, token}

Proposing changes nothing. Only confirm changes the order, and only after checking again that the
token is valid and unused, belongs to this customer, hasn't expired, and that the order hasn't
changed since the proposal. The token is returned once; only its SHA-256 hash is stored.
New orders CHEE proposes (create_order) are confirmed and discarded here too; the rest is in new_orders.py.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from .cancellation import check_cancellation
from .db import get_db
from .models import Order, OrderEvent, OrderItem, PendingAction, Product

router = APIRouter()

TOKEN_LIFETIME = timedelta(minutes=10)
PAYMENT_NAMES = {"credit_card": "credit card", "paypal": "PayPal", "gift_card": "CheeBag gift card"}


class ActionIn(BaseModel):
    customer_id: int = Field(gt=0)
    token: str = Field(min_length=20, max_length=100)
    shipping_address: str | None = Field(default=None, min_length=10, max_length=200)   # new orders: changed on the card


def now_utc():
    return datetime.now(timezone.utc)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def money(value):
    return f"{value:.2f}"


def log_event(db, event_type, customer_id, order_id=None, action_id=None, **detail):
    db.add(OrderEvent(event_type=event_type, customer_id=customer_id, order_id=order_id,
                      action_id=action_id, detail=detail, created_at=now_utc()))


def load_order(db, customer_id, order_id, lock=False):
    """The customer's own order with items and payment, or None. lock=True holds a row lock until commit."""
    stmt = (select(Order).where(Order.order_id == order_id, Order.customer_id == customer_id)
            .options(selectinload(Order.items).selectinload(OrderItem.product), selectinload(Order.payments),
                     selectinload(Order.shipments)))
    if lock:
        stmt = stmt.with_for_update(of=Order)
    return db.scalar(stmt)


def card_for(order, decision):
    """What the confirmation card shows. Built here from the database, never by the model."""
    paid = order.payment is not None and order.payment.status == "paid"
    refund = order.total_amount - decision.fee if paid else None
    consequences = ["The order will be cancelled and won't ship."]
    if paid:
        method = PAYMENT_NAMES.get(order.payment.payment_method, order.payment.payment_method)
        consequences.append(f"${money(refund)} CAD goes back to your {method} "
                            f"within {decision.refund_days} business day{'s' if decision.refund_days != 1 else ''}.")
    else:
        consequences.append("You haven't been charged yet, so there's nothing to refund.")
    consequences += decision.fee_notes
    return {
        "order_id": order.order_id,
        "status": order.status,
        "order_date": order.order_date.isoformat(),
        "items": [{"name": i.product.name, "quantity": i.quantity, "line_total": money(i.quantity * i.unit_price)}
                  for i in order.items],
        "currency": "CAD",
        "total": money(order.total_amount),
        "fee": money(decision.fee),
        "refund": money(refund) if refund is not None else None,
        "sellers": decision.sellers,
        "consequences": consequences,
    }


@router.get("/orders/cancellable")
def cancellable_orders(db: Session = Depends(get_db)):
    """Orders that could be cancelled right now, so the demo can feature a customer who has one."""
    orders = db.scalars(select(Order).where(Order.status.in_(["pending", "processing"]))
                        .options(selectinload(Order.items).selectinload(OrderItem.product))).all()
    return [{"order_id": o.order_id, "customer_id": o.customer_id} for o in orders if check_cancellation(o).allowed]


@router.post("/customers/{customer_id}/orders/{order_id}/cancel-proposal")
def propose_cancel(customer_id: int, order_id: int, db: Session = Depends(get_db)):
    order = load_order(db, customer_id, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")

    decision = check_cancellation(order)
    if not decision.allowed:
        log_event(db, "cancel_rejected", customer_id, order_id, reason=decision.reason, stage="proposal")
        db.commit()
        return {"allowed": False, "reason": decision.reason}

    # only one open proposal per order: an older one stops working
    db.execute(update(PendingAction)
               .where(PendingAction.order_id == order_id, PendingAction.action_type == "cancel_order",
                      PendingAction.status == "pending")
               .values(status="expired", resolved_at=now_utc()))

    token = secrets.token_urlsafe(32)
    card = card_for(order, decision)
    action = PendingAction(token_hash=hash_token(token), customer_id=customer_id, action_type="cancel_order",
                           order_id=order_id, payload=card, expected_status=order.status,
                           expected_updated_at=order.updated_at, status="pending",
                           created_at=now_utc(), expires_at=now_utc() + TOKEN_LIFETIME)
    db.add(action)
    db.flush()  # assigns action.action_id
    log_event(db, "cancel_proposed", customer_id, order_id, action.action_id, fee=card["fee"])
    db.commit()
    return {"allowed": True, "token": token, "expires_at": action.expires_at.isoformat(), "card": card}


def find_action(db, body):
    """The action this token belongs to, locked, or 404. Another customer's token looks the same as a fake one."""
    action = db.scalar(select(PendingAction).where(PendingAction.token_hash == hash_token(body.token))
                       .with_for_update())
    if action is None or action.customer_id != body.customer_id:
        raise HTTPException(404, {"code": "invalid_token", "message": "This confirmation isn't valid."})
    return action


def reject(db, action, code, message, status="failed"):
    """Close the action, record why, and answer 409. Committed before raising so the log survives."""
    action.status, action.resolved_at = status, now_utc()
    log_event(db, "cancel_rejected", action.customer_id, action.order_id, action.action_id, reason=code)
    db.commit()
    raise HTTPException(409, {"code": code, "message": message})


@router.post("/actions/confirm")
def confirm(body: ActionIn, db: Session = Depends(get_db)):
    action = find_action(db, body)

    if action.status == "confirmed":          # double-click or replay: same answer, nothing happens again
        return {**action.result, "already_done": True}
    if action.status != "pending":
        raise HTTPException(409, {"code": action.status, "message": f"This request was already {action.status}."})
    if now_utc() > action.expires_at:
        reject(db, action, "expired", "This confirmation expired. Ask CHEE again to get a new one.", status="expired")
    if action.action_type == "create_order":   # a new order, not a cancellation: new_orders.py
        from .new_orders import confirm_order
        return confirm_order(db, action, body.shipping_address)

    order = load_order(db, action.customer_id, action.order_id, lock=True)
    if order is None or order.status != action.expected_status or order.updated_at != action.expected_updated_at:
        reject(db, action, "stale", "This order changed after CHEE offered to cancel it, so nothing was changed.")
    decision = check_cancellation(order)       # e.g. the free window may have closed in the meantime
    if not decision.allowed:
        reject(db, action, "not_cancellable", decision.reason)

    paid = order.payment is not None and order.payment.status == "paid"
    order.status, order.updated_at = "cancelled", now_utc()
    # same rules as the rest of the data (checks.sql): a cancelled order's payment is closed as
    # refunded, and a shipment that hasn't left the warehouse is voided
    if order.payment is not None:
        order.payment.status = "refunded"
    for shipment in order.shipments:
        if shipment.status == "pending":
            db.delete(shipment)
    for item in order.items:                   # the items go back on the shelf
        db.execute(update(Product).where(Product.id == item.product_id)
                   .values(stock_quantity=Product.stock_quantity + item.quantity))

    result = {"order_id": order.order_id, "status": "cancelled", "fee": money(decision.fee),
              "refund": money(order.total_amount - decision.fee) if paid else None,
              "message": f"Order #{order.order_id} is cancelled."}
    action.status, action.result, action.resolved_at = "confirmed", result, now_utc()
    log_event(db, "cancel_confirmed", action.customer_id, order.order_id, action.action_id,
              refund=result["refund"], fee=result["fee"], items_restocked=len(order.items),
              shipments_voided=sum(s.status == "pending" for s in order.shipments))
    db.commit()
    return {**result, "already_done": False}


@router.post("/actions/discard")
def discard(body: ActionIn, db: Session = Depends(get_db)):
    action = find_action(db, body)
    if action.status == "confirmed":
        raise HTTPException(409, {"code": "confirmed", "message": "This order was already " +
                                  ("placed." if action.action_type == "create_order" else "cancelled.")})
    if action.status == "pending":
        action.status, action.resolved_at = "discarded", now_utc()
        log_event(db, "order_discarded" if action.action_type == "create_order" else "cancel_discarded",
                  action.customer_id, action.order_id, action.action_id)
        db.commit()
    return {"status": action.status, "order_id": action.order_id}
