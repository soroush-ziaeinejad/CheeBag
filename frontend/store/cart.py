"""The shopping cart: kept in the session, one cart per demo customer, {product id: quantity}.

Submit order sends the cart to the Store API, which checks stock, takes prices from the database and
creates the order. Only ids and quantities leave the browser; never prices.
"""
import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .context import current_customer
from .models import Product

MAX_QUANTITY = 10   # per product, the same limit as the Store API


def get_cart(request, customer):
    return request.session.get(f"cart_{customer.pk}", {})


def save_cart(request, customer, cart):
    request.session[f"cart_{customer.pk}"] = cart


def quantity(value):
    return int(value) if str(value).isdigit() else 0


def cart_count(request):
    """Context processor: the number of items for the header's Cart link."""
    customer = current_customer(request)
    return {"cart_count": sum(get_cart(request, customer).values()) if customer else 0}


def cart_page(request, error=""):
    customer = current_customer(request)
    if customer is None:
        return render(request, "store/cart.html", {"customer": None})
    cart = get_cart(request, customer)
    products = Product.objects.filter(pk__in=cart, active=True).order_by("name")
    lines = [{"product": p, "quantity": cart[str(p.pk)], "total": p.price * cart[str(p.pk)]} for p in products]
    return render(request, "store/cart.html", {
        "customer": customer,
        "lines": lines,
        "total": sum(line["total"] for line in lines),
        "address": request.POST.get("shipping_address", customer.address or ""),
        "error": error,
    })


@require_POST
def cart_add(request, pk):
    customer = current_customer(request)
    if customer is None:
        return redirect("cart")
    if Product.objects.filter(pk=pk, active=True, stock_quantity__gt=0).exists():
        cart = get_cart(request, customer)
        cart[str(pk)] = min(cart.get(str(pk), 0) + max(quantity(request.POST.get("quantity", 1)), 1), MAX_QUANTITY)
        save_cart(request, customer, cart)
    return redirect("cart")


@require_POST
def cart_add_json(request, pk):
    """Add one to the cart from a product card in the CHEE chat, without leaving the page."""
    customer = current_customer(request)
    if customer is None:
        return JsonResponse({"error": "Pick a demo shopper first."}, status=403)
    if not Product.objects.filter(pk=pk, active=True, stock_quantity__gt=0).exists():
        return JsonResponse({"error": "This product is out of stock."}, status=409)
    cart = get_cart(request, customer)
    cart[str(pk)] = min(cart.get(str(pk), 0) + 1, MAX_QUANTITY)
    save_cart(request, customer, cart)
    return JsonResponse({"quantity": cart[str(pk)], "count": sum(cart.values())})


@require_POST
def cart_update(request, pk):
    """Change one line's quantity; 0 removes it."""
    customer = current_customer(request)
    if customer is None:
        return redirect("cart")
    cart = get_cart(request, customer)
    n = min(quantity(request.POST.get("quantity", 0)), MAX_QUANTITY)
    if n:
        cart[str(pk)] = n
    else:
        cart.pop(str(pk), None)
    save_cart(request, customer, cart)
    return redirect("cart")


@require_POST
def cart_submit(request):
    customer = current_customer(request)
    if customer is None:
        return redirect("cart")
    cart = get_cart(request, customer)
    if not cart:
        return cart_page(request, "Your cart is empty.")
    address = request.POST.get("shipping_address", "").strip()
    if len(address) < 10:
        return cart_page(request, "Please enter the full shipping address.")

    store_request = urllib.request.Request(
        f"{settings.STORE_API_URL}/customers/{customer.pk}/orders",
        data=json.dumps({"items": [{"product_id": int(k), "quantity": v} for k, v in cart.items()],
                         "shipping_address": address[:200]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(store_request, timeout=15) as response:
            order = json.loads(response.read())
    except urllib.error.HTTPError as e:
        if e.code == 409:   # out of stock, no longer sold: the Store API says which product
            try:
                message = json.loads(e.read()).get("detail")
            except ValueError:
                message = None
            return cart_page(request, f"{message or 'Something in your cart is not available.'} Nothing was ordered.")
        return cart_page(request, "The store couldn't place this order right now. Nothing was ordered; try again.")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return cart_page(request, "The store couldn't place this order right now. Nothing was ordered; try again.")

    save_cart(request, customer, {})
    cache.delete("cancellable_customers")   # the "Order you can cancel" demo customer may change
    return redirect("order_detail", pk=order["order_id"])
