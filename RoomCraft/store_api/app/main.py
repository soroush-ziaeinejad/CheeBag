"""RoomCraft Store API: the only way other services read store data.

Customer identity comes from the URL path, set by a trusted backend (the Django
session or the agent server), never from text an LLM produced.
"""
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session, selectinload

from .db import get_db
from .models import Customer, Order, OrderItem, Product
from .schemas import OrderDetailOut, OrderSummaryOut, ProductDetailOut, ProductOut

app = FastAPI(title="RoomCraft Store API")

OrderStatus = Literal["pending", "processing", "shipped", "delivered", "cancelled"]


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/products", response_model=list[ProductOut])
def list_products(
    q: str | None = None,
    category: str | None = None,
    limit: int = Query(22, ge=1, le=110),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Product).where(Product.active)
    if q:
        stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"), Product.brand.ilike(f"%{q}%")))
    if category:
        stmt = stmt.where(Product.category.ilike(f"%{category}%"))
    stmt = stmt.order_by(Product.rating_count.desc().nulls_last(), Product.id).limit(limit).offset(offset)
    return db.scalars(stmt).all()


@app.get("/products/{product_id}", response_model=ProductDetailOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.scalar(select(Product).where(Product.id == product_id, Product.active))
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


@app.get("/customers/{customer_id}/orders", response_model=list[OrderSummaryOut])
def list_orders(
    customer_id: int,
    status: OrderStatus | None = None,
    db: Session = Depends(get_db),
):
    if db.get(Customer, customer_id) is None:
        raise HTTPException(404, "Customer not found")
    stmt = select(Order).where(Order.customer_id == customer_id)
    if status:
        stmt = stmt.where(Order.status == status)
    return db.scalars(stmt.order_by(Order.order_date.desc())).all()


@app.get("/customers/{customer_id}/orders/{order_id}", response_model=OrderDetailOut)
def get_order(customer_id: int, order_id: int, db: Session = Depends(get_db)):
    # ownership is part of the query: another customer's order is "not found", same as a missing one
    order = db.scalar(
        select(Order)
        .where(Order.order_id == order_id, Order.customer_id == customer_id)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.payments),
            selectinload(Order.shipments),
        )
    )
    if order is None:
        raise HTTPException(404, "Order not found")
    return order
