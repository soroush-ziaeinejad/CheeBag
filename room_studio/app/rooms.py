"""Uploaded room photos and their previews.

Each room is a folder on disk: room.jpg, the previews (render-*.jpg) and meta.json.
Nothing goes into PostgreSQL, and every folder is deleted after ROOM_KEEP_HOURS.
"""
import io
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from PIL import Image, ImageOps

DATA_DIR = Path(os.environ.get("STUDIO_DATA_DIR", "/data"))
KEEP_HOURS = float(os.environ.get("ROOM_KEEP_HOURS", "6"))
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1600                        # big enough for a good preview, small enough to keep Claude cheap
Image.MAX_IMAGE_PIXELS = 40_000_000    # refuse "decompression bomb" images
ROOM_ID = re.compile(r"^[A-Za-z0-9_-]{16}$")


class RoomError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _folder(room_id):
    if not ROOM_ID.match(room_id or ""):   # also stops paths like ../../etc
        raise RoomError("not_found", "This room photo wasn't found. It may have expired; upload it again.")
    return DATA_DIR / room_id


def save_room(data, visitor):
    """Check and store an uploaded photo. Re-encoding as JPEG also drops EXIF data such as GPS location."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise RoomError("too_large", "That photo is too big. Please use one under 8 MB.")
    try:
        Image.open(io.BytesIO(data)).verify()           # is it really an image?
        image = Image.open(io.BytesIO(data))
        if image.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError(image.format)
        image = ImageOps.exif_transpose(image).convert("RGB")   # phone photos: apply the rotation
    except Exception:
        raise RoomError("bad_image", "That file isn't a photo we can use. Please upload a JPG, PNG or WebP.")
    image.thumbnail((MAX_SIDE, MAX_SIDE))

    cleanup()
    room_id = secrets.token_urlsafe(12)                  # 16 characters, unguessable
    folder = _folder(room_id)
    folder.mkdir(parents=True)
    image.save(folder / "room.jpg", "JPEG", quality=88)
    meta = {"room_id": room_id, "visitor": visitor, "created": time.time(),
            "width": image.width, "height": image.height, "analysis": None, "renders": []}
    save_meta(meta)
    return meta


def load_room(room_id, visitor):
    """The room's details, but only for the visitor who uploaded it. Anyone else gets 'not found'."""
    path = _folder(room_id) / "meta.json"
    if not path.exists():
        raise RoomError("not_found", "This room photo wasn't found. It may have expired; upload it again.")
    meta = json.loads(path.read_text())
    if meta["visitor"] != visitor or time.time() - meta["created"] > KEEP_HOURS * 3600:
        raise RoomError("not_found", "This room photo wasn't found. It may have expired; upload it again.")
    return meta


def save_meta(meta):
    (_folder(meta["room_id"]) / "meta.json").write_text(json.dumps(meta))


def room_photo(meta):
    return (_folder(meta["room_id"]) / "room.jpg").read_bytes()


def save_render(meta, jpeg_bytes, products):
    render_id = f"r{len(meta['renders']) + 1}"
    (_folder(meta["room_id"]) / f"render-{render_id}.jpg").write_bytes(jpeg_bytes)
    meta["renders"].append({"render_id": render_id, "products": [{"id": p["id"], "name": p["name"]} for p in products]})
    save_meta(meta)
    return render_id


def image_path(meta, render_id=None):
    if render_id is None:
        return _folder(meta["room_id"]) / "room.jpg"
    if render_id not in {r["render_id"] for r in meta["renders"]}:
        raise RoomError("not_found", "That preview wasn't found.")
    return _folder(meta["room_id"]) / f"render-{render_id}.jpg"


def cleanup():
    """Delete rooms older than KEEP_HOURS. Called on every upload, so no scheduler is needed."""
    if not DATA_DIR.exists():
        return
    limit = time.time() - KEEP_HOURS * 3600
    for folder in DATA_DIR.iterdir():
        if folder.is_dir() and folder.stat().st_mtime < limit:
            shutil.rmtree(folder, ignore_errors=True)
