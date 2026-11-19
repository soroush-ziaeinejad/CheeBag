"""Room studio: the browser talks to these views, and they talk to the room_studio service.

The browser never reaches room_studio directly. Each visitor gets a random id in their session
(no demo customer needed), and room_studio only shows a room to the visitor who uploaded it.
"""
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .models import Product

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def visitor_id(request):
    if "studio_visitor" not in request.session:
        request.session["studio_visitor"] = secrets.token_urlsafe(16)
    return request.session["studio_visitor"]


def call_studio(path, body=None, raw=None, timeout=90):
    """POST to room_studio. Returns (status, data). Errors become a short message for the visitor."""
    data, headers = (raw, {"Content-Type": "application/octet-stream"}) if raw is not None else \
                    (json.dumps(body).encode(), {"Content-Type": "application/json"})
    req = urllib.request.Request(f"{settings.STUDIO_URL}{path}", data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return 200, json.loads(response.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail")
        except ValueError:
            detail = None
        if e.code in (400, 404, 429, 502, 503) and isinstance(detail, str):
            return e.code, {"error": detail}
        if e.code == 422:                    # a value the service doesn't accept, e.g. a budget under $10
            return 400, {"error": detail if isinstance(detail, str) else "Please check what you entered and try again."}
        return 502, {"error": "Room studio couldn't do that right now. Please try again."}
    except (urllib.error.URLError, TimeoutError, ValueError):
        return 502, {"error": "Room studio is unavailable right now. Please try again."}


@require_POST
def studio_upload(request):
    photo = request.FILES.get("photo")
    if photo is None:
        return JsonResponse({"error": "Choose a photo first."}, status=400)
    if photo.size > MAX_UPLOAD_BYTES:
        return JsonResponse({"error": "That photo is too big. Please use one under 8 MB."}, status=400)
    status, data = call_studio(f"/rooms?visitor={visitor_id(request)}", raw=photo.read())
    return JsonResponse(data, status=status)


def _json(request):
    try:
        body = json.loads(request.body)
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


@require_POST
def studio_analyze(request, room_id):
    status, data = call_studio(f"/rooms/{room_id}/analyze", {"visitor": visitor_id(request)})
    return JsonResponse(data, status=status)


@require_POST
def studio_render(request, room_id):
    body = _json(request)
    status, data = call_studio(f"/rooms/{room_id}/render", {"visitor": visitor_id(request),
                                                            "product_ids": body.get("product_ids"),
                                                            "edits": body.get("edits") or [],      # moved / recoloured items
                                                            "note": body.get("note") or None,
                                                            "based_on": body.get("based_on") or None}, timeout=180)
    return JsonResponse(data, status=status)


@require_POST
def studio_ask(request, room_id):
    body = _json(request)
    status, data = call_studio(f"/rooms/{room_id}/ask", {"visitor": visitor_id(request),
                                                         "messages": body.get("messages"),
                                                         "product_ids": body.get("product_ids") or [],
                                                         "source": body.get("source") or "store"})
    return JsonResponse(data, status=status)


@require_POST
def studio_plan(request, room_id):
    body = _json(request)
    status, data = call_studio(f"/rooms/{room_id}/plan", {"visitor": visitor_id(request), "budget": body.get("budget"),
                                                          "wishes": body.get("wishes") or None,
                                                          "source": body.get("source") or "store"}, timeout=120)
    return JsonResponse(data, status=status)


@require_GET
def studio_image(request, room_id):
    """The room photo or a preview, fetched for this visitor only."""
    query = f"visitor={visitor_id(request)}"
    if request.GET.get("render", "").isalnum():
        query += f"&render={request.GET['render']}"
    try:
        with urllib.request.urlopen(f"{settings.STUDIO_URL}/rooms/{room_id}/image?{query}", timeout=15) as r:
            response = HttpResponse(r.read(), content_type="image/jpeg")
    except (urllib.error.URLError, TimeoutError):
        return HttpResponse(status=404)
    response["Cache-Control"] = "private, max-age=3600"
    return response


@require_GET
def studio_products(request):
    """Products for the picker: a name search, or the most reviewed ones."""
    products = Product.objects.filter(active=True)
    q = request.GET.get("q", "").strip()[:60]
    if q:
        products = products.filter(name__icontains=q)
    products = products.order_by("-rating_count")[:12]
    return JsonResponse({"products": [{"id": str(p.pk), "name": p.name, "price": str(p.price), "image_url": p.image_url,
                                       "store": "CheeBag", "link": f"/products/{p.pk}/"} for p in products]})


@require_GET
def studio_shop_search(request):
    """Listings from online shops for the picker (room_studio searches Google Shopping and counts the cost)."""
    q = request.GET.get("q", "").strip()[:80]
    if len(q) < 2:
        return JsonResponse({"error": "Type at least two letters to search the shops."}, status=400)
    query = urllib.parse.urlencode({"visitor": visitor_id(request), "q": q})
    try:
        with urllib.request.urlopen(f"{settings.STUDIO_URL}/shops/search?{query}", timeout=40) as r:
            return JsonResponse(json.loads(r.read()))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail")
        except ValueError:
            detail = None
        return JsonResponse({"error": detail if isinstance(detail, str) else "The shop search isn't working right now."},
                            status=e.code if e.code in (429, 502, 503) else 502)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return JsonResponse({"error": "Room studio is unavailable right now. Please try again."}, status=502)
