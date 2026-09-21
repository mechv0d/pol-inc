"""Одноразовая генерация статической карты Тарбина.

Запуск из корня репозитория:
    .venv\\Scripts\\python tools\\make_map.py

Результат: pol_inc/assets/map_tarbin.jpg
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "pol_inc" / "assets" / "map_tarbin.jpg"

# Схема из дизайн-документа: R1 R2 / R3 R4 R5 / R6 R7 R8.
GRID = [
    [None, "R1", "R2", None],
    ["R3", "R4", "R5", None],
    ["R6", "R7", "R8", None],
]

NAMES = {
    "R1": "Северный Хадир",
    "R2": "Верхний Ирд",
    "R3": "Западная равнина",
    "R4": "Центральный округ",
    "R5": "Восточные высоты",
    "R6": "Южный Касим",
    "R7": "Южная долина",
    "R8": "Портовый Ирбид",
}

BG = (24, 32, 44)
BOX = (214, 196, 160)
BOX_BORDER = (122, 96, 64)
TITLE_COLOR = (240, 230, 200)
TEXT_COLOR = (40, 32, 24)


def load_font(size: int):
    candidates = [
        "C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main() -> None:
    cell_w, cell_h = 260, 170
    pad = 30
    cols, rows = 4, 3
    title_h = 110

    width = cols * cell_w + pad * 2
    height = title_h + rows * cell_h + pad * 2

    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)

    title_font = load_font(54)
    font = load_font(30)
    small_font = load_font(24)

    title = "ТАРБИН"
    bbox = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 20),
        title,
        font=title_font,
        fill=TITLE_COLOR,
    )

    for row, line in enumerate(GRID):
        for col, region_id in enumerate(line):
            if region_id is None:
                continue
            x0 = pad + col * cell_w
            y0 = title_h + pad + row * cell_h
            x1 = x0 + cell_w - 12
            y1 = y0 + cell_h - 12
            draw.rounded_rectangle(
                [x0, y0, x1, y1], radius=14, fill=BOX, outline=BOX_BORDER, width=4
            )
            draw.text((x0 + 18, y0 + 14), region_id, font=font, fill=TEXT_COLOR)
            draw.text(
                (x0 + 18, y0 + 62), NAMES[region_id], font=small_font, fill=TEXT_COLOR
            )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT_PATH, "JPEG", quality=88)
    print(f"saved {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
