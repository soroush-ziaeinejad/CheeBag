"""Planning where products go before the image model draws them: CHEE as an interior designer.

Asked to add several products at once, an image model tends to line them up in a row. So before a new
preview, Claude looks at the room photo and the products (their category and real size) and plans the
layout with common interior-design rules: where each item goes, which way it faces, what it sits next to.

    plan_layout(room_jpeg, analysis, items) -> {"places": [...one per item, or None...], "notes": "..."}
    each place: {"x", "y", "placement", "warning", "colours" (up to 3 other colours that would suit the room)}

The plan goes into the image prompt (images.py), the pins in the studio start where Claude put each item,
and the notes and any warnings are shown to the customer. If planning fails, main.py makes the preview
without a plan, as before.
"""
import json

from . import vision
from .images import COLOURS

TOOL = {
    "name": "place_items",
    "description": "Record your layout: one entry for every product, then short notes for the customer.",
    "input_schema": {"type": "object", "properties": {
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "number": {"type": "integer", "description": "the product's number in the list"},
            "x": {"type": "number", "description": "% from the left edge of the photo (0-100)"},
            "y": {"type": "number", "description": "% from the top of the photo (0-100): where a floor item touches the "
                                                   "floor, or the centre of a wall item"},
            "placement": {"type": "string", "description": "where and how it stands, for the image model, e.g. 'against "
                                                           "the back wall under the windows, facing the camera'"},
            "fits": {"type": "boolean", "description": "false if this product doesn't really belong in this room"},
            "warning": {"type": "string", "description": "only when fits is false: why, and what to try instead (one sentence)"},
            "colours": {"type": "array", "maxItems": 3, "items": {"type": "string", "enum": list(COLOURS)},
                        "description": "other colours this product would look good in, in this room"}},
            "required": ["number", "x", "y", "placement", "fits"]}},
        "notes": {"type": "string", "description": "two or three short sentences for the customer on why this layout works"}},
        "required": ["items", "notes"]},
}

TASK = """You are CHEE, the interior designer of CheeBag, a home store. Plan where to put these products in the \
customer's room photo, before an image model draws them in.

What you know about the room: {analysis}

Products (with their real sizes, where known):
{products}

Design rules:
- Start from the room as it is: windows, doors, walls, existing furniture and light. Never block a window, door \
or radiator, and keep walkways about 90 cm wide.
- Choose one focal point (a TV, a view, a bed's headboard) and arrange the seating to face it or each other.
- Group items into zones that make sense: a coffee table about 45 cm in front of the sofa and centred on it; side \
tables and lamps next to seats or beds; a rug under at least the front legs of the seating group; a TV on its stand \
or on the wall opposite the main seating, at eye height; plants in corners or near windows; wall art and mirrors on \
walls at eye height.
- Use the real sizes: large pieces go against walls, nothing overlaps, and everything is at a realistic scale for \
the room in the photo. Don't line the products up in a row.
- Small items (a kettle, a mug, a vase) go on a suitable surface (a counter, a table, a shelf), never on the floor.
- For each product, suggest up to three other colours from the list that would suit this room's colours and style.
- If a product doesn't belong in this kind of room (a bed in a kitchen, a kettle in a bedroom), still place it in \
the most sensible spot, set fits to false and say why in one sentence.

Call place_items with every product exactly once."""


def size(it):
    """The product's real size in words for the image model, or "" if the catalogue doesn't have it."""
    p = it.get("product") or {}
    parts = [f"{float(p[k]):.0f} cm {word}" for k, word in (("width_cm", "wide"), ("depth_cm", "deep"), ("height_cm", "tall"))
             if p.get(k)]
    return "about " + ", ".join(parts) if parts else ""


def describe(it):
    """One product line for Claude: name, category and size."""
    p = it.get("product") or {}
    return f"{it['name']} ({p.get('category') or it.get('store') or 'product'}, {size(it) or 'size unknown'})"


def plan_layout(room_jpeg, analysis, items):
    products = "\n".join(f"{i}) {describe(it)}" for i, it in enumerate(items, 1))
    response = vision.client.messages.create(
        model=vision.MODEL, max_tokens=1200, tools=[TOOL], tool_choice={"type": "tool", "name": "place_items"},
        messages=[{"role": "user", "content": [vision._photo_block(room_jpeg), {"type": "text", "text":
                   TASK.format(analysis=json.dumps(analysis) if analysis else "nothing yet", products=products)}]}])
    form = next(b.input for b in response.content if b.type == "tool_use")

    # keep only well-formed entries, one per product, inside the picture
    by_number = {}
    for entry in form.get("items") or []:
        try:
            number, x, y = int(entry["number"]), float(entry["x"]), float(entry["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= number <= len(items) and number not in by_number:
            by_number[number] = {"x": round(min(max(x, 2), 98)), "y": round(min(max(y, 2), 98)),
                                 "placement": str(entry.get("placement") or "")[:200],
                                 "warning": "" if entry.get("fits", True) else str(entry.get("warning") or "")[:200],
                                 "colours": [c for c in entry.get("colours") or [] if c in COLOURS][:3]}
    return {"places": [by_number.get(i) for i in range(1, len(items) + 1)],
            "notes": str(form.get("notes") or "")[:500]}
