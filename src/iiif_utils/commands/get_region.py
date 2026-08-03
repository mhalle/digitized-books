"""`iiif-utils get-region` — pull an arbitrary (x,y,w,h) crop."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import image_api
from iiif_utils.utils.page import resolve_leaf


@click.command(name="get-region")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, default=None,
              help="Canvas (leaf) index, 0-based. Mutually exclusive with -b.")
@click.option("-b", "--book", default=None,
              help="Printed page number (looks up via page_numbers).")
@click.option("--bbox", "bbox_str", required=True,
              help="Region as 'x0,y0,x1,y1' (image pixels).")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--padding", default=None,
              help="Pad the crop. Symmetric: '20' or '5%'. "
                   "Per-side: 'left,top,right,bottom', e.g. '20,40,20,40'.")
@click.option("--size", default="1400,", help="IIIF size string.")
@click.option("--format", "fmt", default="jpg")
@click.option("--url-only", is_flag=True, default=False)
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_region(index: Path, leaf_num: int | None, book: str | None,
                bbox_str: str,
                output_path: Path | None, padding: str | None,
                size: str, fmt: str, url_only: bool,
                config_path: Path | None) -> None:
    """Download (or emit a URL for) an arbitrary bbox on a canvas."""
    parts = bbox_str.split(",")
    if len(parts) != 4:
        raise click.UsageError("--bbox must be 'x0,y0,x1,y1'.")
    try:
        bbox = tuple(int(p) for p in parts)
    except ValueError as e:
        raise click.UsageError(f"--bbox parse error: {e}") from e

    cfg = load_config(config_path)
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    leaf_num = resolve_leaf(conn, leaf_num, book)
    row = conn.execute(
        "SELECT image_service_url, width, height, "
        "image_width, image_height FROM page_numbers "
        "WHERE leaf_num = ?", (leaf_num,)
    ).fetchone()
    if not row or not row["image_service_url"]:
        raise click.ClickException(
            f"Canvas {leaf_num} has no image_service_url."
        )

    if padding:
        cache_dir = Path(cfg.get("http", {}).get(
            "cache_dir", "./.iiif-cache")).expanduser()
        cw, ch = image_api.resolve_dims(row, cfg_http=cfg.get("http", {}),
                                          cache_dir=cache_dir)
        bbox = image_api.padded_bbox(bbox, padding,  # type: ignore[arg-type]
                                       canvas_w=cw, canvas_h=ch)
    # Size applies to the returned REGION, not the source image, so the
    # upscale bound is the crop's own dimensions. Asking for a width
    # wider than the crop is what IIIF servers answer with 400.
    if bbox:
        size = image_api.clamp_size_to_native(
            size, int(bbox[2]) - int(bbox[0]), int(bbox[3]) - int(bbox[1]))
    url = image_api.region_url(row["image_service_url"],
                                 bbox, size=size, fmt=fmt)  # type: ignore[arg-type]

    if url_only:
        click.echo(url)
        return
    if output_path is None:
        output_path = Path.cwd() / f"region_l{leaf_num}.{fmt}"
    content = http_.fetch_bytes(url, cfg_http=cfg.get("http", {}))
    output_path.write_bytes(content)
    click.echo(f"saved {output_path}  ({len(content)/1024:.1f} KB)")
