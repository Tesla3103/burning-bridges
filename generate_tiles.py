from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import csv
import os
import re
import math

# ─── CONFIG ──────────────────────────────────────────────
CANVAS_SIZE = 200
IMAGE_MAX = 180
IMAGE_OPACITY = 128  # 50%

FONT_PATH = "RuneScape-Quill-8.ttf"
FONT_SIZE = 20
FONT_COLOR = (255, 255, 255)

TEXT_MAX_WIDTH = 180
LINE_SPACING = 4

SHADOW_OFFSET = (1, 1)
SHADOW_COLOR = (0, 0, 0, 120)

CHECKMARK_PATH = "checkmark.png"
CHECKMARK_SIZE = 100  # 100x100 centered

NORMAL_DIR = "tiles_normal"
COMPLETED_DIR = "tiles_completed"
# ─────────────────────────────────────────────────────────

os.makedirs(NORMAL_DIR, exist_ok=True)
os.makedirs(COMPLETED_DIR, exist_ok=True)

font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

# Modifier -> glow color (RGB)
MODIFIER_COLORS = {
    "gilded":   (210, 170,  40),  # golden
    "awakened": (200,  40,  40),  # red
    "dormant":  ( 40, 170,  60),  # green
    "milked":   (255, 255, 255),  # white
    "millked":  (255, 255, 255),  # typo support
}

def fetch_image(url):
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGBA")

def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = current + (" " if current else "") + word
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)
    return lines

def safe_slug(s: str) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_\-]", "", s)
    s = re.sub(r"_+", "_", s)
    return s or "Region"

def build_filename(region_id_raw, region_name_raw, position_id_raw) -> str:
    region_id = int(region_id_raw)
    position_id = int(position_id_raw)
    xx = f"{region_id:02d}"
    yy = f"{position_id:02d}"
    region_name = safe_slug(region_name_raw)
    return f"{xx}_{region_name}_{yy}.png"

def make_background(modifier: str) -> Image.Image:
    """
    If modifier empty/unknown: solid black.
    Else: black with a soft radial colored glow towards center.
    """
    mod = (modifier or "").strip().lower()
    color = MODIFIER_COLORS.get(mod)

    if not color:
        return Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 255))

    base_black = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 255))

    cx = (CANVAS_SIZE - 1) / 2.0
    cy = (CANVAS_SIZE - 1) / 2.0
    max_dist = math.hypot(cx, cy)

    mask = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), 0)
    mpix = mask.load()

    # Glow feel knobs
    gamma = 1.6      # higher = tighter center
    intensity = 220  # alpha at center

    for y in range(CANVAS_SIZE):
        for x in range(CANVAS_SIZE):
            d = math.hypot(x - cx, y - cy) / max_dist
            t = max(0.0, 1.0 - d)
            t = t ** gamma
            mpix[x, y] = int(intensity * t)

    glow = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (*color, 255))
    colored = Image.composite(glow, base_black, mask)

    # Blend back toward black so it stays "black square + glow"
    colored = Image.blend(base_black, colored, 0.45)  # lower -> more subtle, higher -> stronger
    return colored

def draw_centered_wrapped_text(canvas: Image.Image, text: str):
    draw = ImageDraw.Draw(canvas)
    text = (text or "").strip()
    if not text:
        return

    lines = wrap_text(draw, text, font, TEXT_MAX_WIDTH)

    line_sizes = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_sizes.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))

    total_height = sum(h for _, h in line_sizes) + LINE_SPACING * (len(lines) - 1)
    y = (CANVAS_SIZE - total_height) // 2

    for (line, (w, h)) in zip(lines, line_sizes):
        x = (CANVAS_SIZE - w) // 2

        # Faint shadow
        draw.text(
            (x + SHADOW_OFFSET[0], y + SHADOW_OFFSET[1]),
            line,
            font=font,
            fill=SHADOW_COLOR
        )
        # Main
        draw.text((x, y), line, font=font, fill=FONT_COLOR)
        y += h + LINE_SPACING

def load_checkmark():
    if not os.path.exists(CHECKMARK_PATH):
        raise FileNotFoundError(
            f"Missing {CHECKMARK_PATH}. Put a transparent PNG checkmark next to the script."
        )
    cm = Image.open(CHECKMARK_PATH).convert("RGBA")
    cm = cm.resize((CHECKMARK_SIZE, CHECKMARK_SIZE), Image.LANCZOS)
    return cm

def add_checkmark(canvas: Image.Image, checkmark: Image.Image) -> Image.Image:
    out = canvas.copy()
    x = (CANVAS_SIZE - CHECKMARK_SIZE) // 2
    y = (CANVAS_SIZE - CHECKMARK_SIZE) // 2
    out.paste(checkmark, (x, y), checkmark)
    return out

def make_tile(row: dict) -> Image.Image:
    # Background
    canvas = make_background(row.get("modifier", ""))

    # Main icon (50% opacity)
    img = fetch_image(row["image_url"])
    img.thumbnail((IMAGE_MAX, IMAGE_MAX), Image.LANCZOS)
    img.putalpha(IMAGE_OPACITY)

    ix = (CANVAS_SIZE - img.width) // 2
    iy = (CANVAS_SIZE - img.height) // 2
    canvas.paste(img, (ix, iy), img)

    # Text
    draw_centered_wrapped_text(canvas, row.get("text", ""))

    return canvas

def main():
    checkmark = load_checkmark()

    with open("tiles.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        required = {"region_id", "region_name", "position_id", "modifier", "image_url", "text"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"tiles.csv missing columns: {sorted(missing)}")

        for row in reader:
            filename = build_filename(row["region_id"], row["region_name"], row["position_id"])

            base_tile = make_tile(row)
            normal_path = os.path.join(NORMAL_DIR, filename)
            base_tile.convert("RGB").save(normal_path, "PNG")

            completed_tile = add_checkmark(base_tile, checkmark)
            completed_path = os.path.join(COMPLETED_DIR, filename)
            completed_tile.convert("RGB").save(completed_path, "PNG")

    print(f"✅ Done. Normal tiles: {NORMAL_DIR}/  Completed tiles: {COMPLETED_DIR}/")

if __name__ == "__main__":
    main()
