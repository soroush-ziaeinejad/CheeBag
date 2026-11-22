"""CheeBag Room studio: upload a room photo, see a product in it, and ask CHEE what else would suit it.

Only Django talks to this service (it is not exposed to the internet). Django passes a random
visitor id from the visitor's session, and every room is tied to the visitor who uploaded it.

    POST /rooms?visitor=…                 body: the photo bytes   -> room id and size
    POST /rooms/{room_id}/analyze          {visitor}              -> room type, style, colours, free spots
    POST /rooms/{room_id}/render           {visitor, product_ids, edits?, note?, based_on?, light?}
                                           -> a preview of the room with 1-6 products (based_on: adjust an earlier one;
                                              edits can move, recolour or remove items; light: "night" or "day").
                                              A new preview is planned first (layout.py): the reply has CHEE's layout.
                                              Every preview is checked against the real products (check.py) and
                                              fixed once if needed: the reply says where each item is and how it matched.
    POST /rooms/{room_id}/ask              {visitor, messages, product_ids?, source?} -> reply + product cards
    POST /rooms/{room_id}/plan             {visitor, budget, wishes?, source?} -> a set of products within the budget
    GET  /rooms/{room_id}/image?visitor=…&render=r1                -> the photo or a preview (JPEG)
    GET  /shops/search?visitor=…&q=…                               -> listings from the online shops

source is "store" (CheeBag's own products, the default) or "shops" (online shops, see shops.py).
Product ids are text: "123" for our products, "s1a2b3c4d5e6f" for shop listings.
"""
import os
from collections import Counter
from datetime import date
from typing import Annotated, Literal

import anthropic
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from . import catalog, check, layout, rooms, shops, store, vision
from .images import COLOURS, MAX_ITEMS, ImageError, get_provider

app = FastAPI(title="CheeBag · Room studio")
provider = get_provider()
CLAUDE_READY = bool(os.environ.get("ANTHROPIC_API_KEY"))

# daily limits, so a public demo can't run up the image and Claude bills
LIMITS = {
    "upload": int(os.environ.get("STUDIO_UPLOADS_PER_DAY", "10")),     # per visitor
    "render": int(os.environ.get("STUDIO_RENDERS_PER_DAY", "10")),     # per visitor
    "ask": int(os.environ.get("STUDIO_QUESTIONS_PER_DAY", "30")),      # per visitor
    "shop_search": int(os.environ.get("STUDIO_SHOP_SEARCHES_PER_DAY", "8")),   # per visitor (only paid, not cached)
}
# all visitors together (shop searches have a monthly budget instead: see shops.py)
TOTALS = {"render": int(os.environ.get("STUDIO_RENDERS_PER_DAY_TOTAL", "100"))}
usage = Counter()   # in memory: resets when the service restarts, which is fine for a demo


def use(kind, visitor):
    """Count one use of `kind` today, or refuse with 429 when the daily limit is reached.
    Returns how many uses this visitor has left today, or None when there's no per-visitor limit."""
    today = date.today().isoformat()
    if kind in LIMITS and usage[(today, kind, visitor)] >= LIMITS[kind]:
        raise HTTPException(429, f"You've reached today's limit for this demo ({LIMITS[kind]}). Please come back tomorrow.")
    if kind in TOTALS and usage[(today, kind, "*")] >= TOTALS[kind]:
        raise HTTPException(429, "The demo has made all of today's previews. Please come back tomorrow.")
    usage[(today, kind, visitor)] += 1
    if kind in TOTALS:
        usage[(today, kind, "*")] += 1
    return LIMITS[kind] - usage[(today, kind, visitor)] if kind in LIMITS else None


def give_back(kind, visitor):
    """A failed attempt shouldn't use up the visitor's limit."""
    today = date.today().isoformat()
    usage[(today, kind, visitor)] -= 1
    if kind in TOTALS:
        usage[(today, kind, "*")] -= 1


def shop_spend(visitor):
    """What shops.search calls before each paid search: counts it, or stops it when today's limit is used up."""
    def spend():
        try:
            use("shop_search", visitor)
        except HTTPException as e:
            raise shops.ShopLimit(e.detail)
    return spend


def need_source(source):
    if source == "shops" and not shops.ready():
        raise HTTPException(503, "Online shops aren't set up yet.")


def need_claude():
    if not CLAUDE_READY:
        raise HTTPException(503, "The AI service is not configured yet.")


def room_or_404(room_id, visitor):
    try:
        return rooms.load_room(room_id, visitor)
    except rooms.RoomError as e:
        raise HTTPException(404, e.message)


Visitor = Field(min_length=10, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class VisitorIn(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)   # product ids may arrive as 123 or "123"
    visitor: str = Visitor


ItemId = Annotated[str, Field(pattern=r"^([0-9]{1,9}|s[0-9a-f]{12})$")]
ProductIds = list[ItemId]
Source = Literal["store", "shops"]


class ItemEdit(BaseModel):
    """How the customer adjusted one product: where they dragged it (% of the picture), a colour, or remove it."""
    model_config = ConfigDict(coerce_numbers_to_str=True)
    product_id: ItemId
    x: float | None = Field(None, ge=0, le=100)
    y: float | None = Field(None, ge=0, le=100)
    colour: Literal[(*COLOURS, "original")] | None = None      # "original": back to the colour it's sold in
    remove: bool = False


class RenderIn(VisitorIn):
    product_ids: ProductIds = Field(min_length=1, max_length=MAX_ITEMS)
    edits: list[ItemEdit] = Field([], max_length=MAX_ITEMS)
    note: str | None = Field(None, max_length=300)                       # e.g. "put the kettle on the counter"
    based_on: str | None = Field(None, pattern=r"^r[0-9]{1,3}$")          # adjust this earlier preview
    light: Literal["day", "night"] | None = None                         # the same preview at another time of day


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AskIn(VisitorIn):
    messages: list[Message] = Field(min_length=1, max_length=20)
    product_ids: ProductIds = Field([], max_length=MAX_ITEMS)
    source: Source = "store"


class PlanIn(VisitorIn):
    budget: float = Field(ge=10, le=10000)               # CAD
    wishes: str | None = Field(None, max_length=200)     # optional, e.g. "for a coffee corner"
    source: Source = "store"


def products_or_404(ids):
    items = [catalog.item(i) for i in dict.fromkeys(ids)]   # dict.fromkeys drops repeated ids
    if None in items:
        raise HTTPException(404, "One of those products wasn't found. Shop listings expire after a few hours: search again.")
    return items


@app.get("/health")
def health():
    return {"status": "ok", "claude": CLAUDE_READY, "model": vision.MODEL,
            "image_provider": provider.name, "demo_images": provider.is_demo, "online_shops": shops.ready(),
            "shop_searches_this_month": f"{shops.used_this_month()} of {shops.SHOP_SEARCHES_PER_MONTH}"}


@app.get("/shops/search")
def shop_search(visitor: str = Query(min_length=10, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
                q: str = Query(min_length=2, max_length=80)):
    """Listings from the online shops, for the product picker. A repeated search is free (cached)."""
    need_source("shops")
    try:
        return {"products": shops.search(q, spend=shop_spend(visitor)), "shops": list(shops.SHOPS)}
    except shops.ShopLimit as e:
        raise HTTPException(429, str(e))
    except shops.ShopError as e:
        raise HTTPException(502, str(e))


@app.post("/rooms")
async def upload(request: Request, visitor: str = Query(min_length=10, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")):
    data = await request.body()
    use("upload", visitor)
    try:
        meta = rooms.save_room(data, visitor)
    except rooms.RoomError as e:
        raise HTTPException(400, e.message)
    return {"room_id": meta["room_id"], "width": meta["width"], "height": meta["height"],
            "keep_hours": rooms.KEEP_HOURS, "demo_images": provider.is_demo}


@app.post("/rooms/{room_id}/analyze")
def analyze(room_id: str, body: VisitorIn):
    meta = room_or_404(room_id, body.visitor)
    if meta["analysis"] is None:            # Claude looks at each photo only once
        need_claude()
        try:
            meta["analysis"] = vision.describe_room(rooms.room_photo(meta))
        except anthropic.AnthropicError as e:
            print(f"Claude API error: {e!r}")
            raise HTTPException(502, "CHEE couldn't look at the photo right now. Please try again.")
        rooms.save_meta(meta)
    return meta["analysis"]


@app.post("/rooms/{room_id}/render")
def render(room_id: str, body: RenderIn):
    meta = room_or_404(room_id, body.visitor)
    products = products_or_404(body.product_ids)
    edits = {e.product_id: e for e in body.edits}
    if set(edits) - {p["id"] for p in products}:
        raise HTTPException(422, "An adjustment is for a product that isn't in this preview.")
    if sum(e.remove for e in edits.values()) >= len(products):
        raise HTTPException(422, "Keep at least one product in the preview. To see the empty room, choose 'Your room'.")
    note = (body.note or "").strip() or None
    previous = None
    if body.light and not body.based_on:
        raise HTTPException(422, "Day and night views are made from a preview.")
    if body.based_on:
        if not edits and not note and not body.light:
            raise HTTPException(422, "Tell CHEE what to change: move an item, pick a colour or write a note.")
        try:
            previous = rooms.image_path(meta, body.based_on).read_bytes()
        except rooms.RoomError as e:
            raise HTTPException(404, e.message)
    left = use("render", body.visitor)       # one preview counts once, however many products are in it
    if body.light:
        return relight(meta, body, products, previous, left)
    plan = new_layout(meta, products) if previous is None and not edits else None
    places = plan["places"] if plan else [None] * len(products)
    try:
        items = []
        for p, place in zip(products, places):
            e = edits.get(p["id"])
            items.append({"name": p["name"], "photo": catalog.photo(p), "size": layout.size(p),
                          "x": e.x if e and e.x is not None else (place or {}).get("x"),
                          "y": e.y if e and e.y is not None else (place or {}).get("y"),
                          "placement": (place or {}).get("placement") if not (e and e.x is not None) else None,
                          "colour": e.colour if e else None, "remove": bool(e and e.remove),
                          "colour_sold": (p.get("product") or {}).get("color") or ""})
        preview = provider.render(rooms.room_photo(meta), items, note, previous)
    except (ImageError, store.StoreError) as e:
        give_back("render", body.visitor)
        raise HTTPException(502, str(e))

    # the check: does each product look like the real one? If not, the image model fixes it once
    kept = [(p, it, place) for p, it, place in zip(products, items, places) if not it["remove"]]
    results = checked(preview, [it for _, it, _ in kept])
    fixed = []
    if results and not provider.is_demo and any(not r["ok"] and r["fix"] for r in results):
        fixes = [{**it, "x": None, "y": None, "placement": None, "fix": "" if r["ok"] else r["fix"]}
                 for (_, it, _), r in zip(kept, results)]
        try:
            preview = provider.render(rooms.room_photo(meta), fixes, None, preview)
            fixed = [it["name"] for it in fixes if it["fix"]]
            results = checked(preview, [it for _, it, _ in kept])
        except ImageError:
            pass                                   # keep the first preview and its check
    results = results or [None] * len(kept)

    render_id = rooms.save_render(meta, preview, [p for p, _, _ in kept])
    return {"render_id": render_id, "product_ids": [p["id"] for p, _, _ in kept], "renders_left": left,
            "provider": provider.label, "demo": provider.is_demo,
            "layout": [{"product_id": p["id"], "x": place["x"], "y": place["y"], "warning": place["warning"]}
                       for p, place in zip(products, places) if place],
            "layout_notes": plan["notes"] if plan else "",
            # per product: its real colour, colours CHEE suggests for this room, and the check's result
            "items": [{"product_id": p["id"], "colour_sold": it["colour_sold"], "colours": (place or {}).get("colours", []),
                       **({"box": r["box"], "point": r["point"], "ok": r["ok"], "note": r["note"]} if r else {})}
                      for (p, it, place), r in zip(kept, results)],
            "checked": any(results), "fixed": fixed}


def relight(meta, body, products, previous, left):
    """The same preview at night or in daylight. Nothing moves, so it isn't checked again."""
    try:
        preview = provider.render(rooms.room_photo(meta), [], None, previous, light=body.light)
    except ImageError as e:
        give_back("render", body.visitor)
        raise HTTPException(502, str(e))
    render_id = rooms.save_render(meta, preview, products)
    return {"render_id": render_id, "product_ids": [p["id"] for p in products], "renders_left": left,
            "provider": provider.label, "demo": provider.is_demo, "light": body.light}


def checked(preview, items):
    """The check's results (check.py), or None (no Claude key, or Claude failed: the preview is shown without them)."""
    if not CLAUDE_READY:
        return None
    try:
        return check.check_preview(preview, items)
    except (anthropic.AnthropicError, StopIteration, KeyError, TypeError, ValueError) as e:
        print(f"Preview check failed, showing the preview without it: {e!r}")
        return None


def new_layout(meta, products):
    """CHEE's plan for where the products go, or None (no Claude key, or Claude failed: the preview goes ahead)."""
    if not CLAUDE_READY:
        return None
    try:
        return layout.plan_layout(rooms.room_photo(meta), meta["analysis"], products)
    except (anthropic.AnthropicError, StopIteration, KeyError, TypeError, ValueError) as e:
        print(f"Layout planning failed, making the preview without it: {e!r}")
        return None


@app.post("/rooms/{room_id}/ask")
def ask(room_id: str, body: AskIn):
    meta = room_or_404(room_id, body.visitor)
    if body.messages[0].role != "user" or body.messages[-1].role != "user":
        raise HTTPException(422, "The conversation must start and end with the customer's message.")
    selected = products_or_404(body.product_ids)
    need_claude()
    need_source(body.source)
    use("ask", body.visitor)
    try:
        return vision.ask(rooms.room_photo(meta), meta["analysis"] or {}, [m.model_dump() for m in body.messages],
                          selected, body.source, shop_spend(body.visitor))
    except anthropic.AnthropicError as e:
        give_back("ask", body.visitor)
        print(f"Claude API error: {e!r}")
        raise HTTPException(502, "CHEE is unavailable right now. Please try again.")


@app.get("/rooms/{room_id}/image")
def image(room_id: str, visitor: str = Query(min_length=10, max_length=64), render: str | None = None):
    meta = room_or_404(room_id, visitor)
    try:
        return FileResponse(rooms.image_path(meta, render), media_type="image/jpeg")
    except rooms.RoomError as e:
        raise HTTPException(404, e.message)


@app.post("/rooms/{room_id}/plan")
def plan(room_id: str, body: PlanIn):
    meta = room_or_404(room_id, body.visitor)
    need_claude()
    need_source(body.source)
    use("ask", body.visitor)                 # a plan counts as one question
    try:
        return vision.plan(rooms.room_photo(meta), meta["analysis"] or {}, body.budget, body.wishes, MAX_ITEMS,
                           body.source, shop_spend(body.visitor))
    except anthropic.AnthropicError as e:
        give_back("ask", body.visitor)
        print(f"Claude API error: {e!r}")
        raise HTTPException(502, "CHEE is unavailable right now. Please try again.")
