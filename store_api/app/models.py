"""SQLAlchemy mappings of the tables created by data/postgreSQL/schema.sql."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Seller(Base):
    __tablename__ = "sellers"

    seller_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_asin: Mapped[str]
    name: Mapped[str]
    full_title: Mapped[str | None]
    category: Mapped[str]
    description: Mapped[str | None]
    original_price: Mapped[Decimal | None]
    price: Mapped[Decimal]
    currency: Mapped[str]
    image_url: Mapped[str | None]
    brand: Mapped[str | None]
    color: Mapped[str | None]
    material: Mapped[str | None]
    width_cm: Mapped[Decimal | None]
    depth_cm: Mapped[Decimal | None]
    height_cm: Mapped[Decimal | None]
    rating: Mapped[Decimal | None]
    rating_count: Mapped[int | None]
    stock_quantity: Mapped[int]
    active: Mapped[bool]
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.seller_id"))

    seller: Mapped[Seller] = relationship()


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str]
    last_name: Mapped[str]
    email: Mapped[str]
    phone: Mapped[str | None]
    address: Mapped[str | None]
    created_at: Mapped[datetime]


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"))
    order_date: Mapped[datetime]
    status: Mapped[str]
    total_amount: Mapped[Decimal]
    shipping_address: Mapped[str | None]
    updated_at: Mapped[datetime]

    items: Mapped[list["OrderItem"]] = relationship(order_by="OrderItem.order_item_id")
    payments: Mapped[list["Payment"]] = relationship()
    shipments: Mapped[list["Shipment"]] = relationship()

    # MVP: each order has at most one payment and one shipment
    @property
    def payment(self):
        return self.payments[0] if self.payments else None

    @property
    def shipment(self):
        return self.shipments[0] if self.shipments else None


class OrderItem(Base):
    __tablename__ = "order_items"

    order_item_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.order_id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int]
    unit_price: Mapped[Decimal]

    product: Mapped[Product] = relationship()


class Payment(Base):
    __tablename__ = "payments"

    payment_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.order_id"))
    amount: Mapped[Decimal]
    payment_method: Mapped[str]
    status: Mapped[str]
    transaction_reference: Mapped[str | None]
    paid_at: Mapped[datetime | None]


class Shipment(Base):
    __tablename__ = "shipments"

    shipment_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.order_id"))
    carrier: Mapped[str]
    tracking_number: Mapped[str | None]
    status: Mapped[str]
    shipped_at: Mapped[datetime | None]
    estimated_delivery: Mapped[date | None]
    delivered_at: Mapped[datetime | None]


class PendingAction(Base):
    """An action CHEE proposed (data/postgreSQL/migrations/001_actions.sql)."""
    __tablename__ = "pending_actions"

    action_id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str]
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"))
    action_type: Mapped[str]
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.order_id"))
    payload: Mapped[dict] = mapped_column(JSONB)
    expected_status: Mapped[str | None]
    expected_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderEvent(Base):
    __tablename__ = "order_events"

    event_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.order_id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"))
    action_id: Mapped[int | None] = mapped_column(ForeignKey("pending_actions.action_id"))
    event_type: Mapped[str]
    detail: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
