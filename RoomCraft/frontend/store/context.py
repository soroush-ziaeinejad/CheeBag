from django.db.models import Count

from .models import Customer, Product


def current_customer(request):
    """The demo customer picked in the header, or None."""
    customer_id = request.session.get("customer_id")
    return Customer.objects.filter(pk=customer_id).first() if customer_id else None


def demo_customer(request):
    """Adds the persona switcher data to every page."""
    return {
        "current_customer": current_customer(request),
        "demo_customers": Customer.objects.annotate(order_count=Count("orders")).order_by("customer_id"),
        "nav_categories": (Product.objects.filter(active=True).values("category")
                           .annotate(n=Count("id")).order_by("-n", "category")[:10]),
    }
