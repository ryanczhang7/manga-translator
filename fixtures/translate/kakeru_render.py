"""Render MT-045's synthetic two-page fixture: `kakeru-p1.png`, `kakeru-p2.png`
and `kakeru-ocr.json` (MT-045 C-1, PO-1).

Run once, from the repository root, on a machine with a Japanese font:

    uv run python fixtures/translate/kakeru_render.py

The font is NOT committed; the PNGs and the JSON are, so nothing at test time
needs this script or the font. Re-running it on the same machine with the same
font and the same Pillow reproduces the PNGs byte for byte (no randomness);
on another machine the font may differ, and the README records which font and
which SHA-256 the committed pages have.

The name 翔 (Shō / Sho / Shou / Kakeru - several defensible readings) is in
exactly one bubble per page, bare kanji, no furigana, in a different sentence
position on each page. No other name, no romaji. Text is set vertically,
right-to-left, as manga is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msgothic.ttc"),
    Path("C:/Windows/Fonts/YuGothM.ttc"),
)
PAGE_SIZE = (1000, 1414)  # portrait, long edge <= 1568: prepare_page_image never resizes
FONT_SIZE = 44
GUTTER = 24

# Characters drawn rotated 90 degrees in vertical text, and those nudged to the
# upper right of their cell.
ROTATE = set("…ー〜")
NUDGE = set("、。")
NO_LEAD = set("、。！？…ー")

# Each page: panels as (x0, y0, x1, y1), and bubbles as (centre_x, centre_y,
# text) in READING ORDER (right-to-left, top-to-bottom) - the order the JSON
# lists them in and the order the request numbers them.
PAGES: dict[str, dict[str, list]] = {
    "p1": {
        "panels": [(40, 40, 960, 520), (40, 544, 520, 1374), (544, 544, 960, 1374)],
        "bubbles": [
            (800, 250, "おい、急げ！"),
            (420, 270, "翔、こっちだ！"),
            (760, 900, "待ってくれよ…"),
            (280, 1000, "電車が出ちゃうぞ！"),
        ],
    },
    "p2": {
        "panels": [(40, 40, 600, 700), (624, 40, 960, 700), (40, 724, 960, 1374)],
        "bubbles": [
            (800, 330, "あれ？"),
            (330, 360, "もう翔けていったのか、翔は？"),
            (720, 1040, "うん、さっき駅の方へ走っていった。"),
            (260, 1050, "しょうがないな…"),
        ],
    },
}


def find_font() -> Path:
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    sys.exit("no Japanese font found; edit FONT_CANDIDATES")


def columns(text: str, per_column: int) -> list[str]:
    """Split into columns of `per_column`, never starting a column with
    punctuation (kinsoku): a leading mark is pulled back onto the column
    before it."""
    cols: list[str] = []
    for char in text:
        if cols and (len(cols[-1]) < per_column or char in NO_LEAD):
            cols[-1] += char
        else:
            cols.append(char)
    return cols


def draw_vertical(
    page: Image.Image, font: ImageFont.FreeTypeFont, cx: int, cy: int, text: str
) -> None:
    per_column = 7
    cols = columns(text, per_column)
    cell = FONT_SIZE + 4
    width = len(cols) * cell
    height = max(len(c) for c in cols) * cell
    draw = ImageDraw.Draw(page)
    pad_x, pad_y = 46, 56
    draw.ellipse(
        (
            cx - width // 2 - pad_x,
            cy - height // 2 - pad_y,
            cx + width // 2 + pad_x,
            cy + height // 2 + pad_y,
        ),
        fill="white",
        outline="black",
        width=4,
    )
    # Columns run right to left.
    for col_index, col in enumerate(cols):
        x = cx + width // 2 - (col_index + 1) * cell
        for row_index, char in enumerate(col):
            y = cy - height // 2 + row_index * cell
            if char in ROTATE:
                glyph = Image.new("L", (cell, cell), 0)
                ImageDraw.Draw(glyph).text((2, 2), char, font=font, fill=255)
                glyph = glyph.rotate(-90)
                page.paste((0, 0, 0), (x, y), glyph)
            elif char in NUDGE:
                draw.text((x + cell // 2, y - cell // 3), char, font=font, fill="black")
            else:
                draw.text((x + 2, y + 2), char, font=font, fill="black")


def render(name: str, spec: dict[str, list], font: ImageFont.FreeTypeFont) -> Image.Image:
    page = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(page)
    for panel in spec["panels"]:
        draw.rectangle(panel, outline="black", width=6)
    for cx, cy, text in spec["bubbles"]:
        draw_vertical(page, font, cx, cy, text)
    return page


def main() -> None:
    font_path = find_font()
    font = ImageFont.truetype(str(font_path), FONT_SIZE)
    ocr: dict[str, list[dict[str, object]]] = {}
    for name, spec in PAGES.items():
        render(name, spec, font).save(HERE / f"kakeru-{name}.png", optimize=True)
        ocr[name] = [{"text": text, "ocr_empty": False} for _, _, text in spec["bubbles"]]
    (HERE / "kakeru-ocr.json").write_text(
        json.dumps(ocr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"rendered with {font_path}")


if __name__ == "__main__":
    main()
