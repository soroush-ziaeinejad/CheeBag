"""Making the preview: the customer's room photo with products placed in it, and adjusting it afterwards.

Claude can read images but not make them, so this step uses an image-editing model.
Each provider has the same small interface, so another model can be added without
touching the rest of the service:

    provider.render(room_jpeg, items, note=None, previous_jpeg=None, light=None) -> JPEG bytes

    items: 1 to MAX_ITEMS dicts {"name", "photo" (JPEG bytes), "x", "y", "colour", "placement", "size", "remove", "fix"}.
           x and y are where the item goes (0-100, % of the picture's width and height): where the customer
           dragged it, or where CHEE's layout put it (layout.py), or None to let the model choose.
           placement is CHEE's description of the spot ("against the back wall, facing the sofa") and size
           its real size ("about 198 cm wide, 81 cm deep and 88 cm tall"), both optional. colour is one of COLOURS, "original" (back to
           the colour in its photo), or None.
           remove: take this item out of the preview. fix: what the check (check.py) found wrong with this item.
    note: an extra change in the customer's words, e.g. "put the kettle on the counter".
    previous_jpeg: an earlier preview to adjust instead of starting again from the room photo.
    light: "night" or "day" to show the same preview at another time of day (only with previous_jpeg; items unused).

IMAGE_PROVIDER picks one: "gemini" (Google's Nano Banana, needs GEMINI_API_KEY) or "demo"
(no AI: pastes the product photos onto the room, so everything works without a key).
By default it is "gemini" when GEMINI_API_KEY is set, otherwise "demo".
"""
import base64
import io
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


class ImageError(Exception):
    pass


MAX_ITEMS = 6   # image models get less faithful with more objects in one picture

# colours a customer can pick for an item (a fixed list, so only these words reach the prompt)
COLOURS = {"black": (30, 30, 32), "white": (240, 240, 236), "grey": (140, 140, 140), "beige": (214, 196, 166),
           "brown": (120, 80, 50), "red": (190, 40, 45), "pink": (230, 150, 170), "orange": (230, 120, 40),
           "yellow": (235, 200, 60), "sage green": (150, 170, 140), "green": (50, 130, 70), "teal": (30, 130, 130),
           "blue": (50, 100, 190), "navy": (30, 40, 80), "purple": (110, 70, 150), "gold": (200, 160, 70),
           "silver": (190, 192, 196), "copper": (184, 115, 70)}

NEW = (
    "The first image is a photo of a customer's room. The next {count} image(s) are products from our store, "
    "in this order: {names}. "
    "Edit the room photo so {these} in it, each placed where it would naturally be used, arranged like a real, "
    "lived-in room (not in a row).{changes}\n"
    "Keep the room exactly as it is: the same walls, windows, floor, furniture, lighting and camera angle. "
    "Keep each product's shape and details the same as in its photo{colour_rule}, at a realistic size for the room, "
    "with natural shadows and reflections. Do not add any other objects, people or text."
)
ADJUST = (
    "The first image is a preview of a customer's room that already shows some products from our store. "
    "The next {count} image(s) are those products, in this order: {names}. "
    "Make only these changes to the preview:{changes}\n"
    "Keep everything else exactly as it is: the room, the other products, the lighting and the camera angle. "
    "Keep each product's shape and details the same as in its photo{colour_rule}. "
    "Do not add any other objects, people or text."
)

LIGHT = {
    "night": "Show the same room at night: it is dark outside the windows, and the ceiling lights and any lamps in the "
             "room are switched on, giving warm, soft light with natural shadows.",
    "day": "Show the same room in the daytime: bright natural daylight comes through the windows and the lamps are off.",
}
LIGHT_RULE = ("\nKeep everything else exactly as it is: every object, its position, colour and size, the walls, the floor "
              "and the camera angle. Do not add any objects, people or text.")


def where(x, y):
    across = "left" if x < 34 else "right" if x > 66 else "centre"
    down = "top" if y < 34 else "bottom" if y > 66 else "middle"
    return f"at about {x:.0f}% from the left and {y:.0f}% from the top of the picture (the {down} {across} area)"


def prompt(items, note, adjusting):
    names = "; ".join(f"{i}) {item['name']}" for i, item in enumerate(items, 1))
    changes = []
    for i, item in enumerate(items, 1):
        if item.get("remove"):
            changes.append(f"Remove product {i} ({item['name']}) from the picture and fill its space so the room looks natural.")
            continue
        if item.get("fix"):
            changes.append(f"Fix product {i} ({item['name']}{', ' + item['size'] if item.get('size') else ''}): {item['fix']}.")
        size = f", {item['size']}" if item.get("size") else ""
        if item.get("placement") and item.get("x") is not None:
            changes.append(f"Place product {i} ({item['name']}{size}) {item['placement']}, {where(item['x'], item['y'])}.")
        elif item.get("x") is not None and item.get("y") is not None:
            changes.append(f"Place product {i} ({item['name']}{size}) {where(item['x'], item['y'])}.")
        elif size and not adjusting:
            changes.append(f"Product {i} ({item['name']}) is {item['size']}.")
        if item.get("colour") == "original":
            changes.append(f"Show product {i} ({item['name']}) in its original colours, exactly as in its photo.")
        elif item.get("colour"):
            changes.append(f"Show product {i} ({item['name']}) in {item['colour']}.")
    if note:
        changes.append(f"The customer also asks: {note}")
    listed = "".join(f"\n- {c}" for c in changes)
    colour_rule = ", except for any colour change asked for" if any(i.get("colour") for i in items) else \
                  ", including its colours"
    if adjusting:
        return ADJUST.format(count=len(items), names=names, changes=listed, colour_rule=colour_rule)
    return NEW.format(count=len(items), names=names, these="all of them appear" if len(items) > 1 else "the product appears",
                      changes=(" Follow this layout, planned by an interior designer:" + listed) if changes else "", colour_rule=colour_rule)


def _jpeg(image_bytes):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


class GeminiProvider:
    """Google's Gemini image model (Nano Banana): edits a photo using reference images."""
    name, label, is_demo = "gemini", "Gemini image model", False
    # aspect ratios the model can return; we pick the one closest to the room photo
    RATIOS = {"1:1": 1, "4:3": 4 / 3, "3:4": 3 / 4, "3:2": 3 / 2, "2:3": 2 / 3, "16:9": 16 / 9, "9:16": 9 / 16}

    def __init__(self):
        from google import genai   # imported here so the demo provider works without the package configured
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = os.environ.get("IMAGE_MODEL", "gemini-nano-banana-2.1")

    def render(self, room_jpeg, items, note=None, previous_jpeg=None, light=None):
        base = previous_jpeg or room_jpeg              # adjusting starts from the earlier preview
        width, height = Image.open(io.BytesIO(base)).size
        ratio = min(self.RATIOS, key=lambda r: abs(self.RATIOS[r] - width / height))
        image = lambda data: {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(data).decode()}
        try:
            result = self.client.interactions.create(
                model=self.model,
                input=[{"type": "text", "text": LIGHT[light] + LIGHT_RULE}, image(base)] if light else
                      [{"type": "text", "text": prompt(items, note, adjusting=previous_jpeg is not None)},
                       image(base), *[image(item["photo"]) for item in items]],
                response_format={"type": "image", "aspect_ratio": ratio, "image_size": "1K"},  # 1K is the cheapest size
            )
            return _jpeg(base64.b64decode(result.output_image.data))
        except Exception as e:
            print(f"Gemini image error: {e!r}")            # details for us, a simple message for the customer
            raise ImageError("The image model couldn't make a preview right now. Please try again.")


class DemoProvider:
    """No AI: pastes the product photos onto the room (where they were dragged, in the chosen colour),
    so the whole feature can be tried without a key."""
    name, label, is_demo = "demo", "demo preview (no image model configured)", True

    def render(self, room_jpeg, items, note=None, previous_jpeg=None, light=None):
        if light:                                                  # a rough day/night look, enough to show the idea
            image = Image.open(io.BytesIO(previous_jpeg)).convert("RGB")
            if light == "night":
                image = Image.blend(ImageEnhance.Brightness(image).enhance(0.45), Image.new("RGB", image.size, (20, 30, 70)), 0.25)
            out = io.BytesIO()
            image.save(out, "JPEG", quality=88)
            return out.getvalue()
        items = [it for it in items if not it.get("remove")]
        room = Image.open(io.BytesIO(room_jpeg)).convert("RGB")    # always the clean room: no pasted items twice
        slot = room.width // max(len(items), 3)                    # default: side by side along the bottom
        left = (room.width - slot * len(items)) // 2
        for i, it in enumerate(items):
            photo = Image.open(io.BytesIO(it["photo"])).convert("RGB")
            photo.thumbnail((int(slot * 0.85), int(room.height * 0.45)))
            # treat the white catalogue background as transparent
            mask = photo.convert("L").point(lambda v: 0 if v > 238 else 255).filter(ImageFilter.GaussianBlur(1))
            if it.get("colour") in COLOURS:                        # a rough tint, enough to show the idea
                photo = ImageOps.colorize(photo.convert("L"), black=(20, 20, 20), white=COLOURS[it["colour"]])
            if it.get("x") is not None and it.get("y") is not None:
                cx, bottom = room.width * it["x"] / 100, room.height * it["y"] / 100 + photo.height / 2
                x, y = int(cx - photo.width / 2), int(min(bottom, room.height - 26) - photo.height)
            else:
                x, y = left + i * slot + (slot - photo.width) // 2, int(room.height * 0.92) - photo.height
            shadow = Image.new("L", room.size, 0)
            ImageDraw.Draw(shadow).ellipse((x, y + photo.height - 14, x + photo.width, y + photo.height + 10), fill=110)
            room.paste((40, 30, 40), (0, 0), shadow.filter(ImageFilter.GaussianBlur(9)))
            room.paste(photo, (x, y), mask)
        draw = ImageDraw.Draw(room)
        draw.rectangle((0, room.height - 26, room.width, room.height), fill=(43, 29, 42))
        draw.text((10, room.height - 20), "Demo preview: add a GEMINI_API_KEY for a real AI render", fill=(251, 246, 236))
        out = io.BytesIO()
        room.save(out, "JPEG", quality=88)
        return out.getvalue()


def get_provider():
    choice = os.environ.get("IMAGE_PROVIDER") or ("gemini" if os.environ.get("GEMINI_API_KEY") else "demo")
    return GeminiProvider() if choice == "gemini" else DemoProvider()
