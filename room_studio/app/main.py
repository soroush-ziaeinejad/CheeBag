"""CheeBag Room studio: upload a room photo, see a product in it, and ask CHEE what else would suit it.

Only Django talks to this service (it is not exposed to the internet). Django passes a random
visitor id from the visitor's session, and every room is tied to the visitor who uploaded it.

    POST /rooms?visitor=…                 body: the photo bytes   -> room id and size
    POST /rooms/{room_id}/analyze          {visitor}              -> room type, style, colours, free spots
    POST /rooms/{room_id}/render           {visitor, product_ids, edits?, note?, based_on?}
                                           -> a preview of the room with 1-6 products (based_on: adjust an earlier one)
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

from . import catalog, rooms, shops, store, vision
from .images import COLOURS, MAX_ITEMS, ImageError, get_provider

app = FastAPI(title="CheeBag · Room studio")
provider = get_provider()
CLAUDE_READY = bool(os.environ.get("ANTHROPIC_API_KEY"))

# daily limits, so a public demo can't run up the image and Claude bills
# (previews have no per-visitor limit, only the daily total for everyone in TOTALS)
LIMITS = {
    "upload": int(os.environ.get("STUDIO_UPLOADS_PER_DAY", "10")),     # per visitor
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
    """How the customer adjusted one product: where they dragged it (% of the picture) and/or a colour."""
    model_config = ConfigDict(coerce_numbers_to_str=True)
    product_id: ItemId
    x: float | None = Field(None, ge=0, le=100)
    y: float | None = Field(None, ge=0, le=100)
    colour: Literal[tuple(COLOURS)] | None = None


class RenderIn(VisitorIn):
    product_ids: ProductIds = Field(min_length=1, max_length=MAX_ITEMS)
    edits: list[ItemEdit] = Field([], max_length=MAX_ITEMS)
    note: str | None = Field(None, max_length=300)                       # e.g. "put the kettle on the counter"
    based_on: str | None = Field(None, pattern=r"^r[0-9]{1,3}$")          # adjust this earlier preview


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
    note = (body.note or "").strip() or None
    previous = None
    if body.based_on:
        if not edits and not note:
            raise HTTPException(422, "Tell CHEE what to change: move an item, pick a colour or write a note.")
        try:
            previous = rooms.image_path(meta, body.based_on).read_bytes()
        except rooms.RoomError as e:
            raise HTTPException(404, e.message)
    left = use("render", body.visitor)       # one preview counts once, however many products are in it
    try:
        items = [{"name": p["name"], "photo": catalog.photo(p),
                  "x": edits[p["id"]].x if p["id"] in edits else None,
                  "y": edits[p["id"]].y if p["id"] in edits else None,
                  "colour": edits[p["id"]].colour if p["id"] in edits else None} for p in products]
        preview = provider.render(rooms.room_photo(meta), items, note, previous)
    except (ImageError, store.StoreError) as e:
        give_back("render", body.visitor)
        raise HTTPException(502, str(e))
    render_id = rooms.save_render(meta, preview, products)
    return {"render_id": render_id, "product_ids": [p["id"] for p in products], "renders_left": left,
            "provider": provider.label, "demo": provider.is_demo}


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
