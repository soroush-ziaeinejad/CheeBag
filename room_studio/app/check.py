"""Checking a preview: does each product in the picture look like the real one?

An image model can change a product on the way in: a grey sofa comes out blue, a small lamp comes out huge.
After each preview, Claude compares the picture with every product's catalogue photo, its colour and its real
size, and says where each product ended up (so the studio's markers sit on the real items).

    check_preview(preview_jpeg, items) -> [{"box": [left, top, right, bottom] or None, "point": [x, y] or None,
                                            "ok": bool, "fix": "...", "note": "..."} for each item]

    items: dicts {"name", "photo" (JPEG bytes), "size", "colour" (the colour asked for, or None), "colour_sold"}
    box:   where the product is in the picture, in % of its width and height (None if Claude couldn't find it)
    point: a spot on the product itself, in %, where the studio puts its marker (the middle of a box can be
           empty space, e.g. under an arc lamp). Claude answers in pixels of the exact image it is sent, which
           it places more accurately than percentages; we convert.
    fix:   what to change, written for the image model (empty when ok)
    note:  one short line for the customer

main.py asks the image model to fix the items that failed, once, and checks the fixed picture again.
CHECK_MODEL is a stronger model than the rest of Room studio uses, because finding objects and judging
colours and sizes is the hard part.
"""
import io
import os

from PIL import Image

from . import vision

CHECK_MODEL = os.environ.get("CHECK_MODEL", "claude-sonnet-5-5")

TOOL = {
    "name": "report_check",
    "description": "Record, for every product, where it is in the room picture and whether it matches the real product.",
    "input_schema": {"type": "object", "properties": {
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "number": {"type": "integer", "description": "the product's number in the list"},
            "found": {"type": "boolean", "description": "false if the product isn't in the room picture at all"},
            "x": {"type": "number", "description": "a point on the product itself: x in pixels of the room picture"},
            "y": {"type": "number", "description": "y of that point, in pixels"},
            "left": {"type": "number", "description": "left edge of the product, in pixels of the room picture"},
            "top": {"type": "number", "description": "top edge, in pixels"},
            "right": {"type": "number", "description": "right edge, in pixels"},
            "bottom": {"type": "number", "description": "bottom edge, in pixels"},
            "colour_ok": {"type": "boolean"}, "shape_ok": {"type": "boolean"}, "size_ok": {"type": "boolean"},
            "fix": {"type": "string", "description": "if anything is wrong: what to change, in one sentence for an image "
                                                     "editor, e.g. 'make the sofa light grey like its photo, not blue'"},
            "note": {"type": "string", "description": "one short line for the customer, e.g. 'Matches the product' or "
                                                      "'Looks bigger than its real size'"}},
            "required": ["number", "found", "colour_ok", "shape_ok", "size_ok", "note"]}}},
        "required": ["items"]},
}

TASK = """The first image is an AI-edited photo of a customer's room, {width} x {height} pixels. The other images are photos \
of the products that were put into it, in this order:
{products}

For every product:
1. Find it in the room picture. Give a point (x, y) in the middle of its most solid visible part: on the product \
itself, never on empty space, the floor or another object (for an arc lamp, its shade; for a table, its top). Then give \
the tightest box around it. All in pixels of the room picture, from its top-left corner.
2. Compare it with its product photo: the same colour (or the colour asked for), the same shape and details, and a \
size that fits its real size next to the room and the other furniture.
Be strict about colour and size: these are real products the customer may buy.

Call report_check with every product exactly once."""


def line(i, it):
    colour = f"should be {it['colour']} (a colour the customer asked for)" if it.get("colour") not in (None, "original") else \
             f"colour as sold: {it['colour_sold']}" if it.get("colour_sold") else "colour: as in its photo"
    return f"{i}) {it['name']}: {it.get('size') or 'size unknown'}; {colour}"


MAX_SIDE, MAX_PIXELS = 1568, 1_150_000   # bigger images are scaled down by the API, and the pixels would no longer match


def sized(jpeg):
    """The preview at a size Claude sees unchanged, and that size."""
    image = Image.open(io.BytesIO(jpeg))
    scale = min(1, MAX_SIDE / max(image.size), (MAX_PIXELS / (image.width * image.height)) ** 0.5)
    if scale < 1:
        image = image.convert("RGB").resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)
        out = io.BytesIO(); image.save(out, "JPEG", quality=90); jpeg = out.getvalue()
    return jpeg, image.width, image.height


def check_preview(preview_jpeg, items):
    preview_jpeg, width, height = sized(preview_jpeg)
    content = [vision._photo_block(preview_jpeg)]
    for it in items:
        content.append(vision._photo_block(it["photo"]))
    content.append({"type": "text", "text": TASK.format(width=width, height=height,
                                                        products="\n".join(line(i, it) for i, it in enumerate(items, 1)))})
    response = vision.client.messages.create(model=CHECK_MODEL, max_tokens=1500, tools=[TOOL],
                                             tool_choice={"type": "tool", "name": "report_check"},
                                             messages=[{"role": "user", "content": content}])
    form = next(b.input for b in response.content if b.type == "tool_use")

    by_number = {}
    for entry in form.get("items") or []:
        try:
            number = int(entry["number"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 1 <= number <= len(items) or number in by_number:
            continue
        box = point = None
        pct = lambda k, size: min(max(float(entry[k]) / size * 100, 0), 100)     # pixels -> % of the picture
        try:
            l, t, r, b = pct("left", width), pct("top", height), pct("right", width), pct("bottom", height)
            if r - l >= 1 and b - t >= 1:
                box = [round(l, 1), round(t, 1), round(r, 1), round(b, 1)]
        except (KeyError, TypeError, ValueError):
            pass
        try:
            point = [round(pct("x", width), 1), round(pct("y", height), 1)]
        except (KeyError, TypeError, ValueError):
            pass
        if box and point and not (box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]):
            point = None                                    # a point outside its own box: use the box's middle
        found = bool(entry.get("found", True)) and box is not None
        ok = found and all(entry.get(k, True) for k in ("colour_ok", "shape_ok", "size_ok"))
        name = items[number - 1]["name"]
        fix = "" if ok else (str(entry.get("fix") or "")[:200] if found else
                             f"product {number} ({name}) is missing: add it where it fits best")
        by_number[number] = {"box": box, "point": point if box else None, "ok": ok, "fix": fix,
                             "note": str(entry.get("note") or ("Matches the product" if ok else "Not found"))[:120]}
    # a product Claude skipped: no marker, nothing to fix
    return [by_number.get(i) or {"box": None, "point": None, "ok": True, "fix": "", "note": ""} for i in range(1, len(items) + 1)]
