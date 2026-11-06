"""Shapes of the JSON the API returns. Only these fields ever leave the API."""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, computed_field


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # build from SQLAlchemy objects


class ProductOut(Schema):
    id: int
    name: str
    category: str
    price: Decimal
    currency: str
    image_url: str | None
    brand: str | None
    rating: Decimal | None
    rating_count: int | None
    stock_quantity: int


class ProductDetailOut(ProductOut):
    full_title: str | None
    description: str | None
    color: str | None
    material: str | None
    width_cm: Decimal | None
    depth_cm: Decimal | None
    height_cm: Decimal | None


class ProductBrief(Schema):
    id: int
    name: str
    image_url: str | None


class OrderItemOut(Schema):
    product: ProductBrief
    quantity: int
    unit_price: Decimal

    @computed_field
    def line_total(self) -> Decimal:
        return self.quantity * self.unit_price


class PaymentOut(Schema):
    payment_method: str
    status: str
    amount: Decimal
    transaction_reference: str | None
    paid_at: datetime | None


class ShipmentOut(Schema):
    carrier: str
    tracking_number: str | None
    status: str
    shipped_at: datetime | None
    estimated_delivery: date | None
    delivered_at: datetime | None


class OrderSummaryOut(Schema):
    order_id: int
    order_date: datetime
    status: str
    total_amount: Decimal


class OrderDetailOut(OrderSummaryOut):
    customer_id: int
    shipping_address: str | None
    updated_at: datetime
    items: list[OrderItemOut]
    payment: PaymentOut | None
    shipment: ShipmentOut | None
