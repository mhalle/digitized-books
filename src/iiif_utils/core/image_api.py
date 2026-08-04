"""IIIF Image API URL builders (v2 / v3 compatible).

Format: {service}/{region}/{size}/{rotation}/{quality}.{format}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

# info.json placeholder sentinel: NLM and our LoC synthesizer set
# canvas width/height to this when the real value isn't known.
_PLACEHOLDER_DIM = 99999


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


def fetch_info_json(service_url: str, *, cfg_http: dict[str, Any],
                     cache_dir: Path | None = None) -> dict[str, Any]:
    """Fetch and cache the IIIF Image API `info.json` for a service.

    `service_url` is the base of the image service (no trailing slash),
    e.g. `https://iiif.wellcomecollection.org/image/b21212600_0199.jp2`.
    Cached under `cache_dir/info_json/` keyed by a hash of the URL.
    """
    # Lazy import to keep core.image_api a low-dep module.
    from iiif_utils.core import http as http_
    url = service_url.rstrip("/") + "/info.json"
    info_dir = (cache_dir / "info_json") if cache_dir else None
    if info_dir is not None:
        info_dir.mkdir(parents=True, exist_ok=True)
    body = http_.fetch_bytes(url, cfg_http=cfg_http,
                              cache_dir=info_dir, suffix=".json")
    return json.loads(body)  # type: ignore[no-any-return]


def dims_from_info(info: dict[str, Any]) -> tuple[int | None, int | None]:
    """Extract (width, height) from a parsed info.json dict."""
    w = info.get("width")
    h = info.get("height")
    try:
        return (int(w) if w is not None else None,
                int(h) if h is not None else None)
    except (TypeError, ValueError):
        return None, None


def resolve_dims(row: Mapping[str, Any], *,
                  cfg_http: dict[str, Any] | None = None,
                  cache_dir: Path | None = None) -> tuple[int | None, int | None]:
    """Return image-native (width, height) for a `page_numbers` row,
    falling back to the IIIF Image API's `info.json` when the row's
    stored dims are missing or placeholder.

    Cache hits make repeated calls cheap; first call per canvas is one
    extra HTTP request.
    """
    cw, ch = clamp_dims_from_page_row(row)
    # Anything plausible? Use it.
    if (cw and ch
            and cw != _PLACEHOLDER_DIM and ch != _PLACEHOLDER_DIM):
        return cw, ch
    svc = row.get("image_service_url") if hasattr(row, "get") else None
    if not svc or cfg_http is None:
        return cw, ch
    try:
        info = fetch_info_json(svc, cfg_http=cfg_http, cache_dir=cache_dir)
    except Exception:
        return cw, ch
    iw, ih = dims_from_info(info)
    return iw or cw, ih or ch


def resolve_max_size(
    size: str,
    service_url: str,
    *,
    cfg_http: dict[str, Any],
    cache_dir: Path | None = None,
) -> str:
    """If `size == 'max'`, fetch `info.json` and return `'{width},'`.

    Some IIIF servers (notably Wellcome) reject the canonical
    `full/full/0/default.jpg` URL with HTTP 403 when the source image
    exceeds their `max_pixels` threshold, even though the same image
    is fetchable via an explicit width like `full/2734,/0/default.jpg`.
    `--size max` is the workaround: resolve to the native width.

    Other size strings pass through unchanged.
    """
    if size != "max":
        return size
    info = fetch_info_json(service_url, cfg_http=cfg_http, cache_dir=cache_dir)
    w, _ = dims_from_info(info)
    if not w:
        return "full"  # fallback: best effort
    return f"{w},"


def parse_bbox_spec(spec: str, page_w: int | None,
                     page_h: int | None) -> tuple[int, int, int, int]:
    """Parse `--bbox` as pixels, percentages, or fractions.

    Pixels are exact but require knowing the page size and doing the
    arithmetic by hand, which is how you end up eyeballing proportions
    off a full-page image and iterating to trim stray text. Percentages
    and fractions say what you mean:

        2325,1200,4650,2400     pixels
        10%,20%,60%,80%         percent of page width/height
        0.1,0.2,0.6,0.8         fractions (any value <= 1 with a dot)

    Percent and fraction forms need the page dimensions; without them
    there is nothing to resolve against, so this raises rather than
    guessing.
    """
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must have four comma-separated values")

    relative = any(p.endswith("%") for p in parts) or all(
        ("." in p and abs(float(p)) <= 1.0) for p in parts
        if _is_number(p))
    if not relative:
        return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))

    if not page_w or not page_h:
        raise ValueError(
            "relative bbox needs the page size, which this index does not "
            "record for that canvas — use pixel coordinates")

    out: list[int] = []
    for i, p in enumerate(parts):
        axis = page_w if i % 2 == 0 else page_h
        val = float(p[:-1]) / 100.0 if p.endswith("%") else float(p)
        out.append(int(round(val * axis)))
    return (out[0], out[1], out[2], out[3])


def _is_number(text: str) -> bool:
    try:
        float(text.rstrip("%"))
        return True
    except ValueError:
        return False


def clamp_size_to_native(size: str, avail_w: int | None,
                          avail_h: int | None) -> str:
    """Reduce a IIIF size string so it never asks for an upscale.

    IIIF Image API level 2 does not have to support upscaling, and
    servers that don't answer an oversized request with **400**, not by
    clamping. IA is one of them: a 1280x808 postcard scan rejects the
    default `1400,` outright, so `get-page` failed on an item that is
    perfectly fetchable at its own size.

    `avail_w`/`avail_h` are the dimensions of what is actually being
    requested — the full image for a whole-canvas fetch, the *region*
    for a crop, since size applies to the returned region rather than
    the source. Unknown dims (None) mean pass through unchanged: better
    to send the caller's request than to guess a bound.

    `full`, `max` and anything unparseable pass through — they are not
    upscale requests.
    """
    spec = size.strip()
    if not spec or spec in ("full", "max"):
        return spec or size

    if spec.startswith("pct:"):
        try:
            pct = float(spec[4:])
        except ValueError:
            return size
        return "pct:100" if pct > 100 else size

    # `!w,h` means "fit within", which is already bounded on both axes,
    # but an oversized box still upscales on servers that honour it.
    bang = spec.startswith("!")
    body = spec[1:] if bang else spec
    if "," not in body:
        return size
    w_s, h_s = body.split(",", 1)

    def _clamp(part: str, avail: int | None) -> str:
        if not part or avail is None:
            return part
        try:
            want = int(part)
        except ValueError:
            return part
        return str(avail) if want > avail else part

    w_out, h_out = _clamp(w_s, avail_w), _clamp(h_s, avail_h)
    if (w_out, h_out) == (w_s, h_s):
        return size
    return ("!" if bang else "") + f"{w_out},{h_out}"


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
