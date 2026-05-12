"""Compose a contact-sheet / mosaic image from multiple page JPEGs.

For feeding a multi-page overview to a vision-capable LLM (or for quick
visual browsing). Lifted from ia-utils' image.create_mosaic with minor
tweaks.
"""
from __future__ import annotations

import io
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont


def create_mosaic(
    images: Sequence[bytes],
    *,
    labels: Sequence[str | None] | None = None,
    width: int = 1536,
    cols: int = 12,
    grid: bool = False,
) -> bytes:
    """Compose `images` into a grid; return JPEG bytes.

    Tile width is computed from `width / cols`; tile height is derived
    from the FIRST image's aspect ratio (all tiles are uniform).
    `labels` (same length as `images`) are drawn bottom-right of each
    tile with a small white background. `grid` draws gray separators.
    """
    if not images:
        raise ValueError("create_mosaic: no images provided")
    if labels is not None and len(labels) != len(images):
        raise ValueError(
            "labels length must equal images length "
            f"({len(labels)} vs {len(images)})"
        )

    # Tile cell width is fixed by the grid; cell height is set by the
    # FIRST image's aspect ratio. Tiles with different aspects (e.g. fold-out
    # plates) are *letterboxed* — fit inside the cell preserving aspect,
    # with white bars on the excess axis. Without this, fold-outs get
    # vertically squished into the standard cell shape.
    tile_w = width // cols
    cell_h: int | None = None
    tiles: list[Image.Image] = []
    for raw in images:
        loaded = Image.open(io.BytesIO(raw))
        aspect = loaded.height / loaded.width if loaded.width else 1.0
        if cell_h is None:
            cell_h = max(1, int(tile_w * aspect))
        # Fit-within: scale so neither side exceeds (tile_w, cell_h)
        s = min(tile_w / loaded.width, cell_h / loaded.height) if loaded.width and loaded.height else 1.0
        new_w = max(1, int(loaded.width * s))
        new_h = max(1, int(loaded.height * s))
        resized: Image.Image = loaded.resize((new_w, new_h),
                                              Image.Resampling.LANCZOS)
        if resized.mode != "RGB":
            resized = resized.convert("RGB")
        if new_w == tile_w and new_h == cell_h:
            tiles.append(resized)
        else:
            cell = Image.new("RGB", (tile_w, cell_h), (255, 255, 255))
            cell.paste(resized, ((tile_w - new_w) // 2, (cell_h - new_h) // 2))
            tiles.append(cell)
    assert cell_h is not None
    tile_h = cell_h

    rows = (len(tiles) + cols - 1) // cols
    canvas_w = cols * tile_w
    canvas_h = rows * tile_h
    canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))

    for idx, tile in enumerate(tiles):
        r, c = divmod(idx, cols)
        canvas.paste(tile, (c * tile_w, r * tile_h))

    if labels:
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.load_default(size=18)
        except TypeError:
            font = ImageFont.load_default()
        for idx, label in enumerate(labels):
            if not label:
                continue
            r, c = divmod(idx, cols)
            tx = c * tile_w
            ty = r * tile_h
            tbox = draw.textbbox((0, 0), label, font=font)
            tw, th = tbox[2] - tbox[0], tbox[3] - tbox[1]
            edge_pad, bg_pad = 6, 5
            bg_right = tx + tile_w - edge_pad
            bg_bot = ty + tile_h - edge_pad
            bg_left = bg_right - tw - bg_pad * 2
            bg_top = bg_bot - th - bg_pad * 2
            draw.rectangle([bg_left, bg_top, bg_right, bg_bot], fill="white")
            draw.text((bg_left + bg_pad, bg_top + bg_pad), label,
                       fill="black", font=font)

    if grid:
        draw = ImageDraw.Draw(canvas)
        gray = (128, 128, 128)
        for c in range(1, cols):
            x = c * tile_w
            draw.line([(x, 0), (x, canvas_h)], fill=gray, width=1)
        for r in range(1, rows):
            y = r * tile_h
            draw.line([(0, y), (canvas_w, y)], fill=gray, width=1)

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=85)
    return out.getvalue()
