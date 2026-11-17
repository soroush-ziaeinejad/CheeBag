"""SQLAlchemy mappings of the tables created by data/postgreSQL/schema.sql."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


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
