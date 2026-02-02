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
FONT_SIZE = 24
FONT_COLOR = (255, 255, 255)

TEXT_MAX_WIDTH = 160
LINE_SPACING = 4

SHADOW_OFFSET = (1, 1)
SHADOW_COLOR = (0, 0, 0, 120)

CHECKMARK_PATH = "checkmark.png"
CHECKMARK_SIZE = 50

COMPLETED_BORDER_WIDTH = 20
COMPLETED_BORDER_COLOR = (0x43, 0xA0, 0x47, 255)

# Base folder names
NORMAL_DIR = "tiles_normal"
NORMAL_COMPLETED_DIR = "tiles_normal_completed"
# ─────────────────────────────────────────────────────────

font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

# Modifier -> glow color (RGB)
MODIFIER_COLORS = {
    "gilded":   (210, 170,  40),  # golden
    "awakened": (200,  40,  40),  # red
    "dormant":  ( 40, 170,  60),  # green
    "milked":   (255, 255, 255),  # white
    "stackable":( 40, 120, 255),  # blue
}

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def fetch_image(url):
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGBA")

def get_line_height(draw, font):
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return bbox[3] - bbox[1]

def apply_opacity_keep_alpha(img: Image.Image, opacity_0_255: int) -> Image.Image:
    """Keep existing transparency and multiply it by opacity_0_255/255."""
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    factor = opacity_0_255 / 255.0
    a = a.point(lambda p: int(p * factor))
    return Image.merge("RGBA", (r, g, b, a))

def add_inner_border(canvas: Image.Image, width: int, color: tuple) -> Image.Image:
    out = canvas.copy()
    draw = ImageDraw.Draw(out)
    for i in range(width):
        draw.rectangle([i, i, CANVAS_SIZE - 1 - i, CANVAS_SIZE - 1 - i], outline=color)
    return out

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

    # Glow feel knobs (your “stronger” settings)
    gamma = 1.3
    intensity = 245

    for y in range(CANVAS_SIZE):
        for x in range(CANVAS_SIZE):
            d = math.hypot(x - cx, y - cy) / max_dist
            t = max(0.0, 1.0 - d)
            t = t ** gamma
            mpix[x, y] = int(intensity * t)

    glow = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (*color, 255))
    colored = Image.composite(glow, base_black, mask)

    # Blend back toward black so it stays "black square + glow"
    colored = Image.blend(base_black, colored, 0.65)
    return colored

def draw_centered_wrapped_text(canvas: Image.Image, text: str):
    draw = ImageDraw.Draw(canvas)
    text = (text or "").strip()
    if not text:
        return

    lines = wrap_text(draw, text, font, TEXT_MAX_WIDTH)
    line_height = get_line_height(draw, font)

    total_height = line_height * len(lines) + LINE_SPACING * (len(lines) - 1)
    y = (CANVAS_SIZE - total_height) // 2

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        x = (CANVAS_SIZE - w) // 2

        # Shadow
        draw.text((x + SHADOW_OFFSET[0], y + SHADOW_OFFSET[1]), line, font=font, fill=SHADOW_COLOR)
        # Main text
        draw.text((x, y), line, font=font, fill=FONT_COLOR)

        y += line_height + LINE_SPACING

def load_checkmark():
    if not os.path.exists(CHECKMARK_PATH):
        raise FileNotFoundError(f"Missing {CHECKMARK_PATH}. Put a transparent PNG checkmark next to the script.")
    cm = Image.open(CHECKMARK_PATH).convert("RGBA")
    cm = cm.resize((CHECKMARK_SIZE, CHECKMARK_SIZE), Image.LANCZOS)
    return cm

def add_checkmark(canvas: Image.Image, checkmark: Image.Image) -> Image.Image:
    out = canvas.copy()
    padding = 10
    out.paste(checkmark, (padding, padding), checkmark)
    return out

def make_tile(row: dict, modifier_override: str) -> Image.Image:
    # Background
    canvas = make_background(modifier_override)

    # Main icon (50% opacity, preserving alpha)
    img = fetch_image(row["image_url"]).convert("RGBA")
    img.thumbnail((IMAGE_MAX, IMAGE_MAX), Image.LANCZOS)
    img = apply_opacity_keep_alpha(img, IMAGE_OPACITY)

    ix = (CANVAS_SIZE - img.width) // 2
    iy = (CANVAS_SIZE - img.height) // 2
    canvas.paste(img, (ix, iy), img)

    # Text
    draw_centered_wrapped_text(canvas, row.get("text", ""))

    return canvas

def save_variant(base_tile: Image.Image, filename: str, out_dir: str):
    ensure_dir(out_dir)
    out_path = os.path.join(out_dir, filename)
    base_tile.convert("RGB").save(out_path, "PNG")

def save_completed_variant(base_tile: Image.Image, filename: str, out_dir: str, checkmark: Image.Image):
    ensure_dir(out_dir)
    completed_tile = add_inner_border(base_tile, COMPLETED_BORDER_WIDTH, COMPLETED_BORDER_COLOR)
    completed_tile = add_checkmark(completed_tile, checkmark)
    out_path = os.path.join(out_dir, filename)
    completed_tile.convert("RGB").save(out_path, "PNG")

def main():
    checkmark = load_checkmark()

    with open("tiles.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # modifier removed from CSV on purpose
        required = {"region_id", "region_name", "position_id", "image_url", "text"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"tiles.csv missing columns: {sorted(missing)}")

        for row in reader:
            filename = build_filename(row["region_id"], row["region_name"], row["position_id"])

            # 1) Normal
            normal_tile = make_tile(row, modifier_override="")
            save_variant(normal_tile, filename, NORMAL_DIR)
            save_completed_variant(normal_tile, filename, NORMAL_COMPLETED_DIR, checkmark)

            # 2) All modifier variants
            for mod in MODIFIER_COLORS.keys():
                mod_dir = f"tiles_{mod}"
                mod_completed_dir = f"tiles_{mod}_completed"

                mod_tile = make_tile(row, modifier_override=mod)
                save_variant(mod_tile, filename, mod_dir)
                save_completed_variant(mod_tile, filename, mod_completed_dir, checkmark)

    print("✅ Done. Generated normal + all modifier variants (and completed variants).")

if __name__ == "__main__":
    main()
