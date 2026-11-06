from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .context import current_customer
from .models import Customer, Order, OrderItem, Product

SORT_OPTIONS = [
    ("popular", "Most reviewed", "-rating_count"),
    ("rating", "Top rated", "-rating"),
    ("price_low", "Price: low to high", "price"),
    ("price_high", "Price: high to low", "-price"),
]
ORDER_STATUSES = ["pending", "processing", "shipped", "delivered", "cancelled"]
PICK_TABS = [("for_you", "For You"), ("best_sellers", "Best Sellers"), ("top_rated", "Top Rated"), ("under_25", "Under $25")]


def home(request):
    customer = current_customer(request)
    tab = request.GET.get("tab", "for_you")
    products = Product.objects.filter(active=True)
    best_sellers = products.annotate(sold=Sum("orderitem__quantity")).order_by(F("sold").desc(nulls_last=True), "id")

    if tab == "top_rated":
        picks = products.filter(rating_count__gte=1000).order_by("-rating", "-rating_count")
    elif tab == "under_25":
        picks = products.filter(price__lt=25).order_by("-rating_count")
    elif tab == "for_you" and customer:
        # best sellers from categories this customer buys, minus what they already bought
        bought = OrderItem.objects.filter(order__customer=customer)
        picks = (best_sellers.filter(category__in=bought.values("product__category"))
                 .exclude(pk__in=bought.values("product_id")))
    else:
        picks = best_sellers
    picks = list(picks[:8]) or list(best_sellers[:8])

    # one tile per category, pictured by its most-reviewed product, biggest categories first
    tiles, counts = {}, dict(products.values_list("category").annotate(n=Count("id")))
    for p in products.order_by("-rating_count"):
        tiles.setdefault(p.category, p)
    categories = sorted(tiles.items(), key=lambda item: -counts[item[0]])[:12]

    selected_id = request.GET.get("product", "")
    selected = products.filter(pk=selected_id).first() if selected_id.isdigit() else None

    return render(request, "store/home.html", {
        "picks": picks,
        "tab": tab,
        "tabs": PICK_TABS,
        "categories": categories,
        "selected": selected or picks[0],
    })


def product_list(request):
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    sort = request.GET.get("sort", "popular")

    products = Product.objects.filter(active=True)
    if q:
        products = products.filter(Q(name__icontains=q) | Q(brand__icontains=q))
    if category:
        products = products.filter(category=category)
    order_by = next((field for key, _, field in SORT_OPTIONS if key == sort), "-rating_count")
    products = products.order_by(order_by, "id")

    return render(request, "store/product_list.html", {
        "page": Paginator(products, 24).get_page(request.GET.get("page")),
        "categories": Product.objects.filter(active=True).values_list("category", flat=True).distinct().order_by("category"),
        "sort_options": [(key, label) for key, label, _ in SORT_OPTIONS],
        "q": q, "category": category, "sort": sort,
    })


def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk, active=True)
    return render(request, "store/product_detail.html", {
        "product": product,
        "reviews": product.reviews.order_by("-helpful_count", "-review_date")[:10],
        "review_count": product.reviews.count(),
    })


@require_POST
def switch_customer(request):
    customer_id = request.POST.get("customer_id", "")
    if customer_id.isdigit() and Customer.objects.filter(pk=customer_id).exists():
        request.session["customer_id"] = int(customer_id)
    else:
        request.session.pop("customer_id", None)
    return redirect("order_list")


def order_list(request):
    customer = current_customer(request)
    if customer is None:
        return render(request, "store/order_list.html", {"customer": None})

    status = request.GET.get("status", "")
    orders = customer.orders.annotate(item_count=Count("items")).order_by("-order_date")
    counts = dict(customer.orders.values_list("status").annotate(n=Count("pk")))
    if status in ORDER_STATUSES:
        orders = orders.filter(status=status)

    return render(request, "store/order_list.html", {
        "customer": customer,
        "orders": orders,
        "status": status,
        "status_filters": [(s, counts.get(s, 0)) for s in ORDER_STATUSES],
        "total_count": sum(counts.values()),
    })


def order_detail(request, pk):
    customer = current_customer(request)
    if customer is None:
        return redirect("order_list")
    # ownership check: another customer's order looks exactly like a missing one
    order = Order.objects.filter(pk=pk, customer=customer).first()
    if order is None:
        raise Http404("Order not found")

    payment = order.payments.first()
    shipment = order.shipments.first()

    timeline = [("Order placed", order.order_date)]
    if payment and payment.paid_at:
        timeline.append(("Payment received", payment.paid_at))
    if order.status == "cancelled":
        timeline.append(("Cancelled and refunded", order.updated_at))
    if shipment and shipment.shipped_at:
        timeline.append((f"Shipped with {shipment.carrier}", shipment.shipped_at))
    if shipment and shipment.delivered_at:
        timeline.append(("Delivered", shipment.delivered_at))

    delayed = bool(shipment and shipment.status == "in_transit"
                   and shipment.estimated_delivery and shipment.estimated_delivery < timezone.localdate())

    return render(request, "store/order_detail.html", {
        "order": order,
        "items": order.items.select_related("product").order_by("order_item_id"),
        "payment": payment,
        "shipment": shipment,
        "timeline": timeline,
        "delayed": delayed,
    })
