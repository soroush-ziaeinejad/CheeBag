import json
import urllib.request

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone

from .models import Customer, Product, Shipment


def current_customer(request):
    """The demo customer picked in the header, or None."""
    customer_id = request.session.get("customer_id")
    return Customer.objects.filter(pk=customer_id).first() if customer_id else None


def cancellable_customer_ids():
    """Customers who own an order that could be cancelled right now. The seller rules live in the
    Store API, so we ask it, and remember the answer for 5 minutes."""
    ids = cache.get("cancellable_customers")
    if ids is None:
        try:
            with urllib.request.urlopen(f"{settings.STORE_API_URL}/orders/cancellable", timeout=2) as response:
                ids = sorted({o["customer_id"] for o in json.loads(response.read())})
        except (OSError, ValueError):
            ids = []  # Store API unreachable: that demo customer is simply left out
        cache.set("cancellable_customers", ids, 300)
    return ids


def featured_customers():
    """Three demo customers whose orders show off different things CHEE can do."""
    customers = Customer.objects.annotate(order_count=Count("orders"), kinds=Count("orders__status", distinct=True))
    late = Shipment.objects.filter(status="in_transit", estimated_delivery__lt=timezone.localdate())
    picks = [  # (who, best first, label)
        (customers.filter(pk__in=late.values("order__customer_id")), ["-order_count"], "Late delivery"),
        # the most varied order history among customers who can still cancel something
        (customers.filter(pk__in=cancellable_customer_ids()), ["-kinds", "-order_count"], "Order you can cancel"),
        (customers, ["-order_count"], "Frequent shopper"),
    ]
    featured, seen = [], set()
    for queryset, ordering, label in picks:
        customer = queryset.exclude(pk__in=seen).order_by(*ordering, "customer_id").first()
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
