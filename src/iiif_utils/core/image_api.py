"""IIIF Image API URL builders (v2 / v3 compatible).

Format: {service}/{region}/{size}/{rotation}/{quality}.{format}
"""
from __future__ import annotations

from typing import Any, Mapping


def clamp_dims_from_page_row(
    row: Mapping[str, Any],
) -> tuple[int | None, int | None]:
    """Pick the right (canvas_w, canvas_h) for `padded_bbox` clamping.

    ALTO bboxes are in the image-native coordinate space recorded in
    `page_numbers.image_width/image_height` (from the ALTO `<Page>`
    element). The manifest's `width`/`height` are canvas dims and are
    slightly different — wrong for clamping. Prefer image dims, fall
    back to canvas dims.
    """
    iw = row["image_width"] if "image_width" in row.keys() else None
    ih = row["image_height"] if "image_height" in row.keys() else None
    if iw and ih:
        return iw, ih
    return row["width"] if "width" in row.keys() else None, \
           row["height"] if "height" in row.keys() else None


def region_url(
    service_url: str,
    bbox: tuple[int, int, int, int] | None = None,
    *,
    size: str = "full",
    rotation: int = 0,
    quality: str = "default",
    fmt: str = "jpg",
) -> str:
    """Build a IIIF Image-API URL.

    `bbox` is `(x0, y0, x1, y1)` in image pixels (matching ALTO HPOS/VPOS
    + WIDTH/HEIGHT). If None, region is 'full'. `size` is a IIIF size
    string ('full', 'max', '1200,', ',800', '!1024,1024', 'pct:50',
    'w,h', etc.).
    """
    if bbox is None:
        region = "full"
    else:
        x0, y0, x1, y1 = bbox
        region = f"{int(x0)},{int(y0)},{int(x1 - x0)},{int(y1 - y0)}"
    return f"{service_url.rstrip('/')}/{region}/{size}/{rotation}/{quality}.{fmt}"


def _resolve_pad(part: str, axis_size: int) -> int:
    """Convert one padding token to pixels. Pixels, '5%', or '5.5%'."""
    part = part.strip()
    if part.endswith("%"):
        return int(axis_size * float(part[:-1]) / 100.0)
    return int(float(part))


def parse_padding(
    spec: str | int | float,
    bbox_w: int, bbox_h: int,
) -> tuple[int, int, int, int]:
    """Parse a padding spec into pixel `(left, top, right, bottom)`.

    Accepts:
      - int / float — symmetric pixel padding on all 4 sides
      - "20" — same as int
      - "5%" — symmetric, percentage of the bbox's width/height per axis
      - "10,20,30,40" — per-side: left, top, right, bottom (pixels)
      - "5%,2%,5%,10%" — per-side percentages of width/height per axis
      - mix: "10,5%,10,5%" — pixels and percentages can interleave

    Percentages are taken against the bbox dimensions, not the canvas.
    """
    if isinstance(spec, (int, float)):
        v = int(spec)
        return (v, v, v, v)
    s = str(spec).strip()
    parts = [p.strip() for p in s.split(",")]
    if len(parts) == 1:
        dx = _resolve_pad(parts[0], bbox_w)
        dy = _resolve_pad(parts[0], bbox_h)
        return (dx, dy, dx, dy)
    if len(parts) == 4:
        return (
            _resolve_pad(parts[0], bbox_w),
            _resolve_pad(parts[1], bbox_h),
            _resolve_pad(parts[2], bbox_w),
            _resolve_pad(parts[3], bbox_h),
        )
    raise ValueError(
        f"--padding must be one value (symmetric) or four "
        f"comma-separated values (left,top,right,bottom); got {len(parts)}"
    )


def padded_bbox(
    bbox: tuple[int, int, int, int],
    padding: str | int | float,
    canvas_w: int | None = None,
    canvas_h: int | None = None,
) -> tuple[int, int, int, int]:
    """Expand `bbox` by `padding`.

    See `parse_padding` for accepted forms (single value or
    `left,top,right,bottom`). Optionally clamps to canvas dimensions.
    """
    x0, y0, x1, y1 = bbox
    w = x1 - x0
    h = y1 - y0
    pl, pt, pr, pb = parse_padding(padding, w, h)
    nx0, ny0 = x0 - pl, y0 - pt
    nx1, ny1 = x1 + pr, y1 + pb
    if canvas_w is not None:
        nx0 = max(0, nx0)
        nx1 = min(canvas_w, nx1)
    if canvas_h is not None:
        ny0 = max(0, ny0)
        ny1 = min(canvas_h, ny1)
    return (nx0, ny0, nx1, ny1)


def info_json_url(service_url: str) -> str:
    return f"{service_url.rstrip('/')}/info.json"
