"""`iiif-utils get-region` — pull an arbitrary (x,y,w,h) crop."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import image as image_mod
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
              help="Region as 'x0,y0,x1,y1'. Pixels ('120,300,900,1400'), "
                   "percentages ('10%,20%,60%,80%'), or fractions "
                   "('0.1,0.2,0.6,0.8'). Relative forms resolve against "
                   "the page size, so you don't have to do the "
                   "arithmetic by hand.")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--padding", default=None,
              help="Pad the crop. Symmetric: '20' or '5%'. "
                   "Per-side: 'left,top,right,bottom', e.g. '20,40,20,40'.")
@click.option("--size", default="1400,",
              help="IIIF size string. Aliases: small,medium,large,full,max.")
@click.option("--format", "fmt", default="jpg")
@click.option("--url-only", is_flag=True, default=False)
@click.option("--autocontrast", is_flag=True, default=False,
              help="Stretch contrast after download. A crop of flat "
                   "letterpress needs this more than a whole page does — "
                   "a crop is usually where you are reading fine detail.")
@click.option("--cutoff", type=int, default=None,
              help="Autocontrast cutoff percentage (default 2). Implies "
                   "--autocontrast.")
@click.option("--preserve-tone", is_flag=True, default=False,
              help="Keep colour balance while autocontrasting. Implies "
                   "--autocontrast.")
@click.option("--quality", type=int, default=None,
              help="JPEG quality, 1-95.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_region(index: Path, leaf_num: int | None, book: str | None,
                bbox_str: str,
                output_path: Path | None, padding: str | None,
                size: str, fmt: str, url_only: bool,
                autocontrast: bool, cutoff: int | None,
                preserve_tone: bool, quality: int | None,
                config_path: Path | None) -> None:
    """Download (or emit a URL for) an arbitrary bbox on a canvas."""
    # --bbox is parsed after the canvas row is read, not here: relative
    # forms resolve against that canvas's dimensions.
    aliases = {"small": "400,", "medium": "800,", "large": "1600,",
               "full": "full", "max": "max"}
    size = aliases.get(size, size)

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

    # Parsed here rather than up front: percentages and fractions resolve
    # against this canvas's dimensions, which only the row knows.
    cache_dir = Path(cfg.get("http", {}).get(
        "cache_dir", "./.iiif-cache")).expanduser()
    page_w, page_h = image_api.resolve_dims(
        row, cfg_http=cfg.get("http", {}), cache_dir=cache_dir)
    try:
        bbox = image_api.parse_bbox_spec(bbox_str, page_w, page_h)
    except ValueError as e:
        raise click.UsageError(f"--bbox: {e}") from e

    if padding:
        cw, ch = page_w, page_h
        bbox = image_api.padded_bbox(bbox, padding,
                                       canvas_w=cw, canvas_h=ch)
    # Size applies to the returned REGION, not the source image, so the
    # upscale bound is the crop's own dimensions. Asking for a width
    # wider than the crop is what IIIF servers answer with 400.
    if bbox:
        size = image_api.clamp_size_to_native(
            size, int(bbox[2]) - int(bbox[0]), int(bbox[3]) - int(bbox[1]))
    url = image_api.region_url(row["image_service_url"],
                                 bbox, size=size, fmt=fmt)

    if url_only:
        click.echo(url)
        return
    if output_path is None:
        output_path = Path.cwd() / f"region_l{leaf_num}.{fmt}"
    content = http_.fetch_bytes(url, cfg_http=cfg.get("http", {}))
    if image_mod.wants_processing(autocontrast=autocontrast, cutoff=cutoff,
                                    preserve_tone=preserve_tone,
                                    quality=quality):
        content = image_mod.process_image(
            content, output_format=fmt, quality=quality,
            autocontrast=autocontrast, cutoff=cutoff,
            preserve_tone=preserve_tone,
        )
    output_path.write_bytes(content)
    click.echo(f"saved {output_path}  ({len(content)/1024:.1f} KB)")
