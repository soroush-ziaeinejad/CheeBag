"""Read-only views of the tables created by data/postgreSQL/schema.sql.

managed = False: Django never creates or alters these tables; schema.sql owns them.
"""
from django.db import models


class Seller(models.Model):
    seller_id = models.IntegerField(primary_key=True)
    name = models.TextField()

    class Meta:
        managed = False
        db_table = "sellers"


class Product(models.Model):
    id = models.IntegerField(primary_key=True)
    source_asin = models.TextField()
    name = models.TextField()
    full_title = models.TextField(null=True)
    category = models.TextField()
    description = models.TextField(null=True)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    image_url = models.TextField(null=True)
    brand = models.TextField(null=True)
    color = models.TextField(null=True)
    material = models.TextField(null=True)
    width_cm = models.DecimalField(max_digits=7, decimal_places=1, null=True)
    depth_cm = models.DecimalField(max_digits=7, decimal_places=1, null=True)
    height_cm = models.DecimalField(max_digits=7, decimal_places=1, null=True)
    rating = models.DecimalField(max_digits=2, decimal_places=1, null=True)
    rating_count = models.IntegerField(null=True)
    stock_quantity = models.IntegerField()
    active = models.BooleanField()
    seller = models.ForeignKey(Seller, models.DO_NOTHING, db_column="seller_id")

    class Meta:
        managed = False
        db_table = "products"

    @property
    def dimensions(self):
        sides = [("W", self.width_cm), ("D", self.depth_cm), ("H", self.height_cm)]
        return " × ".join(f"{label} {value} cm" for label, value in sides if value is not None)


class Customer(models.Model):
    customer_id = models.IntegerField(primary_key=True)
    first_name = models.TextField()
    last_name = models.TextField()
    email = models.TextField()
    phone = models.TextField(null=True)
    address = models.TextField(null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "customers"


class Order(models.Model):
    order_id = models.IntegerField(primary_key=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING, db_column="customer_id", related_name="orders")
    order_date = models.DateTimeField()
    status = models.TextField()
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_address = models.TextField(null=True)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "orders"


class OrderItem(models.Model):
    order_item_id = models.IntegerField(primary_key=True)
    order = models.ForeignKey(Order, models.DO_NOTHING, db_column="order_id", related_name="items")
    product = models.ForeignKey(Product, models.DO_NOTHING, db_column="product_id")
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        managed = False
        db_table = "order_items"

    @property
    def line_total(self):
        return self.quantity * self.unit_price


class Payment(models.Model):
    payment_id = models.IntegerField(primary_key=True)
    order = models.ForeignKey(Order, models.DO_NOTHING, db_column="order_id", related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.TextField()
    status = models.TextField()
    transaction_reference = models.TextField(null=True)
    paid_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = "payments"

    @property
    def method_label(self):
        return self.payment_method.replace("_", " ").capitalize()


class Shipment(models.Model):
    shipment_id = models.IntegerField(primary_key=True)
    order = models.ForeignKey(Order, models.DO_NOTHING, db_column="order_id", related_name="shipments")
    carrier = models.TextField()
    tracking_number = models.TextField(null=True)
    status = models.TextField()
    shipped_at = models.DateTimeField(null=True)
    estimated_delivery = models.DateField(null=True)
    delivered_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = "shipments"

    @property
    def status_label(self):
        return self.status.replace("_", " ")


class Review(models.Model):
    review_id = models.IntegerField(primary_key=True)
    product = models.ForeignKey(Product, models.DO_NOTHING, db_column="product_id", related_name="reviews")
    rating = models.SmallIntegerField()
    title = models.TextField(null=True)
    body = models.TextField()
    variation = models.TextField(null=True)
    helpful_count = models.IntegerField()
    verified_purchase = models.BooleanField()
    review_date = models.DateField()

    class Meta:
        managed = False
        db_table = "reviews"

    @property
    def stars(self):
        return "★" * self.rating + "☆" * (5 - self.rating)
