"""IIIF Image API URL builders (v2 / v3 compatible).

Format: {service}/{region}/{size}/{rotation}/{quality}.{format}
"""
from __future__ import annotations


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


def padded_bbox(
    bbox: tuple[int, int, int, int],
    padding: str | int | float,
    canvas_w: int | None = None,
    canvas_h: int | None = None,
) -> tuple[int, int, int, int]:
    """Expand `bbox` by `padding`.

    Accepts a pixel count (int / float) or a percentage string ('5%').
    Optionally clamps to canvas dimensions.
    """
    x0, y0, x1, y1 = bbox
    w = x1 - x0
    h = y1 - y0
    if isinstance(padding, str) and padding.endswith("%"):
        pct = float(padding.rstrip("%")) / 100.0
        dx = int(w * pct)
        dy = int(h * pct)
    else:
        dx = dy = int(padding)
    nx0, ny0 = x0 - dx, y0 - dy
    nx1, ny1 = x1 + dx, y1 + dy
    if canvas_w is not None:
        nx0 = max(0, nx0)
        nx1 = min(canvas_w, nx1)
    if canvas_h is not None:
        ny0 = max(0, ny0)
        ny1 = min(canvas_h, ny1)
    return (nx0, ny0, nx1, ny1)


def info_json_url(service_url: str) -> str:
    return f"{service_url.rstrip('/')}/info.json"
