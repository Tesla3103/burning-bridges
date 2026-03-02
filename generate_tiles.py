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

# Modifier border styling
MOD_BORDER_WIDTH = 20
MODIFIER_BORDER_COLORS = {
    "dormant":   (0x1E, 0x88, 0xE5, 255),  # blue
    "awakened":  (0xE5, 0x39, 0x35, 255),  # red
    "gilded":    (0xFB, 0xC0, 0x2D, 255),  # gold
    "stackable": (0xEC, 0x40, 0x7A, 255),  # pink
    "milked":    (0xFF, 0xFF, 0xFF, 255),  # white
}

# Modifier icon styling
MOD_ICON_SLOT = 50     # slot is 50x50 in the bottom-right
MOD_ICON_PADDING = 10  # distance from edges

# Completion styling
COMPLETED_BG_COLOR = (0x43, 0xA0, 0x47)  # #43a047

# Output folders
NORMAL_DIR = "tiles_normal"
NORMAL_COMPLETED_DIR = "tiles_normal_completed"
# ─────────────────────────────────────────────────────────

font = ImageFont.truetype(FONT_PATH, FONT_SIZE)


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


def add_inner_border(canvas: Image.Image, width: int, color: tuple) -> Image.Image:
    out = canvas.copy()
    draw = ImageDraw.Draw(out)
    for i in range(width):
        draw.rectangle([i, i, CANVAS_SIZE - 1 - i, CANVAS_SIZE - 1 - i], outline=color)
    return out


def make_background(completed: bool) -> Image.Image:
    """
    Normal tiles: solid black.
    Completed tiles: strong green-tinted glow background.
    """
    base_black = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 255))
    if not completed:
        return base_black

    # Strong radial green tint
    cx = (CANVAS_SIZE - 1) / 2.0
    cy = (CANVAS_SIZE - 1) / 2.0
    max_dist = math.hypot(cx, cy)

    mask = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), 0)
    mpix = mask.load()

    gamma = 1.15      # lower => spreads further
    intensity = 255   # max alpha at center

    for y in range(CANVAS_SIZE):
        for x in range(CANVAS_SIZE):
            d = math.hypot(x - cx, y - cy) / max_dist
            t = max(0.0, 1.0 - d)
            t = t ** gamma
            mpix[x, y] = int(intensity * t)

    glow = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (*COMPLETED_BG_COLOR, 255))
    colored = Image.composite(glow, base_black, mask)

    colored = Image.blend(base_black, colored, 0.85)
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
        # Main
        draw.text((x, y), line, font=font, fill=FONT_COLOR)

        y += line_height + LINE_SPACING


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
    padding = 10
    out.paste(checkmark, (padding, padding), checkmark)
    return out


# ─── NEW: modifier icon loading + placement ───────────────────────────
def load_modifier_icons(modifier_names) -> dict:
    """
    Loads <modifier>.png from the script folder.
    Resizes each to fit within MOD_ICON_SLOT x MOD_ICON_SLOT (preserving aspect ratio).
    Returns dict: modifier -> RGBA Image.
    Missing icons are tolerated (warn once).
    """
    icons = {}
    for mod in modifier_names:
        path = f"{mod}.png"
        if not os.path.exists(path):
            print(f"⚠️  Missing modifier icon: {path} (tiles will be generated without it)")
            continue

        im = Image.open(path).convert("RGBA")
        im.thumbnail((MOD_ICON_SLOT, MOD_ICON_SLOT), Image.LANCZOS)
        icons[mod] = im
    return icons


def add_modifier_icon(canvas: Image.Image, icon: Image.Image) -> Image.Image:
    """
    Places icon bottom-right, centered within a MOD_ICON_SLOT x MOD_ICON_SLOT box,
    offset inward by MOD_ICON_PADDING.
    """
    out = canvas.copy()

    slot_x0 = CANVAS_SIZE - MOD_ICON_PADDING - MOD_ICON_SLOT
    slot_y0 = CANVAS_SIZE - MOD_ICON_PADDING - MOD_ICON_SLOT

    # Center icon within the slot
    x = slot_x0 + (MOD_ICON_SLOT - icon.width) // 2
    y = slot_y0 + (MOD_ICON_SLOT - icon.height) // 2

    out.paste(icon, (x, y), icon)
    return out
# ──────────────────────────────────────────────────────────────────────


def make_tile(row: dict, completed: bool) -> Image.Image:
    # Background (completion controls this)
    canvas = make_background(completed=completed)

    # Icon
    img = fetch_image(row["image_url"]).convert("RGBA")
    img.thumbnail((IMAGE_MAX, IMAGE_MAX), Image.LANCZOS)
    img = apply_opacity_keep_alpha(img, IMAGE_OPACITY)

    ix = (CANVAS_SIZE - img.width) // 2
    iy = (CANVAS_SIZE - img.height) // 2
    canvas.paste(img, (ix, iy), img)

    # Text
    draw_centered_wrapped_text(canvas, row.get("text", ""))

    return canvas


def save_variant(tile: Image.Image, filename: str, out_dir: str, border_color=None, modifier_icon=None):
    ensure_dir(out_dir)
    out = tile

    # Border first
    if border_color is not None:
        out = add_inner_border(out, MOD_BORDER_WIDTH, border_color)

    # Modifier icon above border
    if modifier_icon is not None:
        out = add_modifier_icon(out, modifier_icon)

    out.convert("RGB").save(os.path.join(out_dir, filename), "PNG")


def save_completed_variant(
    tile: Image.Image,
    filename: str,
    out_dir: str,
    checkmark: Image.Image,
    border_color=None,
    modifier_icon=None
):
    """
    Completed tiles:
      - green background already baked into `tile`
      - optional modifier border
      - optional modifier icon (bottom-right, above border)
      - checkmark ALWAYS on top (last)
    """
    ensure_dir(out_dir)
    out = tile

    # Border first
    if border_color is not None:
        out = add_inner_border(out, MOD_BORDER_WIDTH, border_color)

    # Modifier icon above border
    if modifier_icon is not None:
        out = add_modifier_icon(out, modifier_icon)

    # Checkmark last = top layer
    out = add_checkmark(out, checkmark)

    out.convert("RGB").save(os.path.join(out_dir, filename), "PNG")


def main():
    checkmark = load_checkmark()

    # NEW: preload modifier icons once (faster + cleaner)
    modifier_icons = load_modifier_icons(MODIFIER_BORDER_COLORS.keys())

    with open("tiles.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        required = {"region_id", "region_name", "position_id", "image_url", "text"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"tiles.csv missing columns: {sorted(missing)}")

        for row in reader:
            filename = build_filename(row["region_id"], row["region_name"], row["position_id"])

            # Normal (no modifier border/icon, black background)
            tile_normal = make_tile(row, completed=False)
            save_variant(tile_normal, filename, NORMAL_DIR)

            # Normal completed (green background + checkmark)
            tile_completed = make_tile(row, completed=True)
            save_completed_variant(tile_completed, filename, NORMAL_COMPLETED_DIR, checkmark)

            # All modifier variants (modifier controls BORDER + icon)
            for mod, border_color in MODIFIER_BORDER_COLORS.items():
                mod_dir = f"tiles_{mod}"
                mod_completed_dir = f"tiles_{mod}_completed"
                mod_icon = modifier_icons.get(mod)  # may be None if missing

                # Modified (black background + colored border + modifier icon)
                t_mod = make_tile(row, completed=False)
                save_variant(t_mod, filename, mod_dir, border_color=border_color, modifier_icon=mod_icon)

                # Modified + completed (green background + border + modifier icon + checkmark on top)
                t_mod_completed = make_tile(row, completed=True)
                save_completed_variant(
                    t_mod_completed,
                    filename,
                    mod_completed_dir,
                    checkmark,
                    border_color=border_color,
                    modifier_icon=mod_icon
                )

    print("✅ Done. Modifiers => colored border + bottom-right icon. Completion => green background + top-left checkmark.")


if __name__ == "__main__":
    main()