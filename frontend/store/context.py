from django.db.models import Count
from django.utils import timezone

from .models import Customer, Order, Product, Shipment


def current_customer(request):
    """The demo customer picked in the header, or None."""
    customer_id = request.session.get("customer_id")
    return Customer.objects.filter(pk=customer_id).first() if customer_id else None


def featured_customers():
    """Three demo customers whose orders show off different things CHEE can answer."""
    customers = Customer.objects.annotate(order_count=Count("orders"))
    late = Shipment.objects.filter(status="in_transit", estimated_delivery__lt=timezone.localdate())
    picks = [
        (customers.filter(pk__in=late.values("order__customer_id")), "Late delivery"),
        (customers.filter(pk__in=Order.objects.filter(status="pending").values("customer_id")), "Order not shipped yet"),
        (customers, "Frequent shopper"),
    ]
    featured, seen = [], set()
    for queryset, label in picks:
        customer = queryset.exclude(pk__in=seen).order_by("-order_count", "customer_id").first()
        if customer:
            seen.add(customer.pk)
            featured.append((customer, label))
    return featured


def demo_customer(request):
    """Adds the demo-customer switcher data to every page."""
    return {
        "current_customer": current_customer(request),
        "featured_customers": featured_customers(),
        "demo_customers": Customer.objects.annotate(order_count=Count("orders")).order_by("first_name", "last_name"),
        "nav_categories": (Product.objects.filter(active=True).values("category")
                           .annotate(n=Count("id")).order_by("-n", "category")[:10]),
    }
