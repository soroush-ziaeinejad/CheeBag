"""The Claude parts of Room studio: looking at the room photo, and answering questions about it.

1. describe_room(): Claude looks at the photo once and fills in a fixed form (room type, style,
   colours, free spots). Forcing a tool call gives clean JSON instead of free text.
2. ask(): a small tool loop, like the agent's. Claude sees the photo and the conversation, searches
   for products, and calls recommend_products to show product cards. Only items that really exist
   (in our catalogue, or in a recent shop search) are shown, so Claude can't invent items.
3. plan(): the same loop for "furnish this room for $X". Claude proposes a set with propose_set, and
   the total is added up here from the real prices, never by the model. A set over budget is sent
   back to Claude to fix.

Both work with either source (catalog.py): CheeBag's own products ("store") or online shops ("shops").
"""
import base64
import json
import os
import time
from decimal import Decimal

import anthropic

from . import catalog, shops, store

MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
MAX_ROUNDS = 5
client = anthropic.Anthropic(timeout=45, max_retries=2)

ROOM_FORM = {
    "name": "describe_room",
    "description": "Record what you see in the customer's room photo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "room_type": {"type": "string", "description": "e.g. kitchen, living room, bedroom, home office"},
            "style": {"type": "string", "description": "the decor style in 1-4 words, e.g. 'warm Scandinavian'"},
            "colours": {"type": "array", "maxItems": 5, "description": "the main colours, most visible first",
                        "items": {"type": "object", "properties": {"name": {"type": "string"},
                                                                   "hex": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}},
                                  "required": ["name", "hex"]}},
            "free_spots": {"type": "array", "maxItems": 4, "items": {"type": "string"},
                           "description": "places where a new item could go, e.g. 'the empty counter left of the sink'"},
            "summary": {"type": "string", "description": "one friendly sentence about the room"},
        },
        "required": ["room_type", "style", "colours", "free_spots", "summary"],
    },
}

ITEM_ID = {"type": "string", "description": "the id exactly as search_products returned it"}
PICKS = {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
    "product_id": ITEM_ID, "reason": {"type": "string"}}, "required": ["product_id", "reason"]}}


def tools_for(source, planning=False):
    if source == "shops":
        search = {"name": "search_products",
                  "description": "Search these online shops for products: " + ", ".join(shops.SHOPS) + ". Returns up "
                                 "to 12 listings with id, name, price (CAD), store and rating. Each search costs money, "
                                 "so use few, specific searches (2-4 words, e.g. 'linen floor lamp').",
                  "input_schema": {"type": "object", "properties": {
                      "query": {"type": "string", "description": "what to look for, e.g. 'oak side table'"},
                      "max_price": {"type": "number", "description": "maximum price in CAD"}}, "required": ["query"]}}
    else:
        search = {"name": "search_products",
                  "description": "Search the CheeBag catalogue. Returns up to 10 products with id, name, category, "
                                 "price (CAD), rating and stock.",
                  "input_schema": {"type": "object", "properties": {
                      "query": {"type": "string", "description": "words to match in the product name or brand, e.g. 'kettle'"},
                      "category": {"type": "string", "description": "a category name, e.g. 'Coffee, Tea & Espresso'"},
                      "max_price": {"type": "number", "description": "maximum price in CAD"}}}}
    details = {"name": "get_product", "description": "Details of one product or listing.",
               "input_schema": {"type": "object", "properties": {"product_id": ITEM_ID}, "required": ["product_id"]}}
    if planning:
        final = {"name": "propose_set",
                 "description": "Propose the set of products for the room. The real prices are added up for you: if the "
                                "total is over the budget, or an id doesn't exist, you get an error and must propose "
                                "again. Up to 6 different products, one of each, each with a short reason tied to the room.",
                 "input_schema": {"type": "object", "properties": {"items": {**PICKS, "minItems": 1}}, "required": ["items"]}}
    else:
        final = {"name": "recommend_products",
                 "description": "Show the customer product cards next to your answer. Use it whenever you suggest "
                                "products. Give each a short reason tied to their room (colour, style, free space). At most 6.",
                 "input_schema": {"type": "object", "properties": {"items": PICKS}, "required": ["items"]}}
    return [search, details, final]


SOURCE_RULES = {
    "store": "You suggest products from CheeBag's own catalogue: kitchen, coffee, storage and small home items, plus "
             "furniture (sofas, chairs, tables, beds, storage), rugs, lamps, mirrors, wall art, plants and TVs. If they "
             "ask for something the store doesn't sell, say so kindly and suggest the closest real items.",
    "shops": "You suggest products from these online shops: {shops}. CheeBag doesn't sell these items: the customer "
             "buys them from the shop. Prices are what the listing showed when searched and can change. Mention the "
             "shop for each product.",
}

SYSTEM = """You are CHEE, the friendly assistant of CheeBag, an online home and kitchen store. You are in Room \
studio: the customer uploaded a photo of their room, and you help them choose products that suit it. Be warm, \
short and practical. Always reply in English. Prices are in Canadian dollars (CAD).

What you know about the room (from an earlier look at the photo): {analysis}
{selected}
Rules:
- {source_rules}
- Base what you say about the room on the photo. If you can't tell something from it, say so.
- Only suggest products that your tools returned. Never invent products, prices or sizes.
- When you suggest products, call recommend_products so the customer sees cards, then explain briefly.
- Product previews in the room are made by an image model and are only an impression, not exact sizes."""

PLAN_TASK = """Put together the best set of products {where} for this room, with a total of at most ${budget} CAD\
{wishes}. Up to {max_items} different products, one of each. Pick items that suit the room's style, colours and \
free spots and work well together, and use the budget sensibly; don't add items just to spend it. Search, then call \
propose_set. When the set is accepted, reply with two or three short sentences on why it works."""


def _photo_block(jpeg_bytes):
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(jpeg_bytes).decode()}}


def _system(analysis, source, selected=()):
    chosen = ("The customer has picked these products to place in the room: " +
              "; ".join(f"{p['name']} (id {p['id']}, {p['store']}, ${p['price']} CAD)" for p in selected) + ".\n") \
        if selected else ""
    rules = SOURCE_RULES[source].format(shops=", ".join(shops.SHOPS))
    return SYSTEM.format(analysis=json.dumps(analysis), selected=chosen, source_rules=rules)


def describe_room(jpeg_bytes):
    response = client.messages.create(
        model=MODEL, max_tokens=600, tools=[ROOM_FORM], tool_choice={"type": "tool", "name": "describe_room"},
        messages=[{"role": "user", "content": [_photo_block(jpeg_bytes), {"type": "text", "text":
                   "Describe this room for a home store assistant. If it isn't a photo of a room, "
                   "set room_type to 'not a room' and explain in the summary."}]}])
    form = next(b.input for b in response.content if b.type == "tool_use")
    return {"room_type": form.get("room_type", ""), "style": form.get("style", ""),
            "colours": form.get("colours", [])[:5], "free_spots": form.get("free_spots", [])[:4],
            "summary": form.get("summary", "")}


def _card(it, reason):
    return {"id": it["id"], "name": it["name"], "price": it["price"], "image_url": it["image_url"],
            "store": it["store"], "link": it["link"], "reason": reason[:200]}


def _details(it):
    if "product" in it:     # our own product: the catalogue's full details
        keep = ("name", "category", "price", "description", "color", "material",
                "width_cm", "depth_cm", "height_cm", "rating", "stock_quantity")
        return {"id": it["id"], **{k: it["product"].get(k) for k in keep}}
    return {k: it.get(k) for k in ("id", "name", "price", "store", "rating", "snippet")}


def _pick(args, cards):
    """Turn Claude's picks into cards, checking each id really exists. Returns the ids that didn't."""
    missing = []
    for pick in args.get("items", [])[:6]:
        it = catalog.item(pick.get("product_id"))
        if it is None:
            missing.append(pick.get("product_id"))
        elif it["id"] not in {c["id"] for c in cards}:
            cards.append(_card(it, str(pick.get("reason", ""))))
    return missing


def _run_tool(name, args, cards, source, spend):
    """Run one tool for Claude. Returns (result, is_error)."""
    try:
        if name == "search_products":
            return catalog.search(source, args.get("query"), args.get("category"), args.get("max_price"), spend), False
        if name == "get_product":
            it = catalog.item(args.get("product_id"))
            return (_details(it), False) if it else ({"error": "No such product."}, True)
        if name == "recommend_products":
            before = len(cards)
            missing = _pick(args, cards)
            return {"shown": [c["id"] for c in cards[before:]], "not_found": missing}, bool(missing) and len(cards) == before
        return {"error": f"Unknown tool {name}"}, True
    except (store.StoreError, shops.ShopError) as e:
        return {"error": str(e)}, True


def _loop(conversation, system, tools, on_tool, rounds):
    """The tool loop shared by ask() and plan(). Returns (reply text, tool calls)."""
    tool_calls = []
    for _ in range(rounds):
        response = client.messages.create(model=MODEL, max_tokens=900, tools=tools, messages=conversation, system=system)
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text"), tool_calls
        conversation.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                start = time.perf_counter()
                result, is_error = on_tool(block.name, block.input)
                tool_calls.append({"tool": block.name, "is_error": is_error,
                                   "ms": round((time.perf_counter() - start) * 1000)})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(result, default=str), "is_error": is_error})
        conversation.append({"role": "user", "content": results})
    return None, tool_calls


def ask(jpeg_bytes, analysis, messages, selected=(), source="store", spend=lambda: None):
    """Answer the latest question about the room. messages: [{role, content}], oldest first.
    selected: the items the customer has picked to place in the room."""
    conversation = [dict(m) for m in messages]
    # the photo goes with the first question, so Claude can look at the room itself every time
    conversation[0] = {"role": "user", "content": [_photo_block(jpeg_bytes), {"type": "text", "text": conversation[0]["content"]}]}
    cards = []
    reply, tool_calls = _loop(conversation, _system(analysis, source, selected), tools_for(source),
                              lambda name, args: _run_tool(name, args, cards, source, spend), MAX_ROUNDS)
    if reply is None:
        reply = "Sorry, I couldn't finish that. Could you ask in a simpler way?"
    return {"reply": reply or "Here are some ideas.", "products": cards, "tool_calls": tool_calls}


def _check_set(args, budget, max_items):
    """Check a proposed set against the real prices. Returns (result for Claude, is_error, accepted cards or None)."""
    cards = []
    missing = _pick(args, cards)
    total = sum(Decimal(c["price"]) for c in cards)
    if missing:
        return {"error": f"These ids don't exist: {missing}. Use ids from search_products."}, True, None
    if not cards or len(cards) > max_items:
        return {"error": f"Propose between 1 and {max_items} different products."}, True, None
    if total > budget:
        return {"error": f"The total is ${total} CAD, over the ${budget} budget. Remove or swap items."}, True, None
    return {"accepted": True, "total": str(total), "budget": str(budget)}, False, cards


def plan(jpeg_bytes, analysis, budget, wishes, max_items, source="store", spend=lambda: None):
    """Propose a set of products for the room within the budget. Returns reply, items and the real total."""
    budget = Decimal(str(budget)).quantize(Decimal("0.01"))
    where = "from CheeBag's catalogue" if source == "store" else "from these online shops: " + ", ".join(shops.SHOPS)
    task = PLAN_TASK.format(where=where, budget=budget, max_items=max_items,
                            wishes=f", with this wish: {wishes}" if wishes else "")
    conversation = [{"role": "user", "content": [_photo_block(jpeg_bytes), {"type": "text", "text": task}]}]
    accepted = []

    def on_tool(name, args):
        nonlocal accepted
        if name == "propose_set":
            result, is_error, cards = _check_set(args, budget, max_items)
            accepted = cards or accepted
            return result, is_error
        return _run_tool(name, args, [], source, spend)

    # a couple of extra rounds in case a set has to be fixed
    reply, tool_calls = _loop(conversation, _system(analysis, source), tools_for(source, planning=True),
                              on_tool, MAX_ROUNDS + 2)
    return {"reply": reply or ("Here's a set that suits your room." if accepted else
                               "Sorry, I couldn't put a set together for that budget. Try a different amount."),
            "items": accepted, "total": str(sum(Decimal(c["price"]) for c in accepted)), "budget": str(budget),
            "tool_calls": tool_calls}
