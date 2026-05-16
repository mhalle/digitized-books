"""`iiif-utils get-url` — emit a URL without downloading.

Replaces a fan-out of `--url-only` flags with one consolidated command.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.core import image_api


@click.command(name="get-url")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, default=None,
              help="Canvas (leaf) index. Required for --image/--info/--figure/--region.")
@click.option("-n", "--number", "ill_num", type=int, default=None,
              help="Illustration number on the canvas (with --figure).")
@click.option("--bbox", "bbox_str", default=None,
              help="With --region: 'x0,y0,x1,y1' image-pixel bbox.")
@click.option("--size", default="full",
              help="IIIF size string (default 'full'). Aliases:"
                   " small,medium,large,max. 'max' resolves to the source's"
                   " native width via info.json (use this if a server rejects"
                   " '/full/full/').")
@click.option("--format", "fmt", default="jpg")
@click.option("--padding", default=None,
              help="Pad the bbox (with --figure or --region). Symmetric: "
                   "'20' or '5%'. Per-side: 'left,top,right,bottom'.")
# Mode flags — exactly one of:
@click.option("--image", "mode", flag_value="image", default="image",
              help="Whole-canvas image URL (default).")
@click.option("--info", "mode", flag_value="info",
              help="Image API info.json URL.")
@click.option("--manifest", "mode", flag_value="manifest",
              help="The manifest URL.")
@click.option("--figure", "mode", flag_value="figure",
              help="Region URL for one illustration (needs -l, -n).")
@click.option("--region", "mode", flag_value="region",
              help="Region URL for an arbitrary bbox (needs -l, --bbox).")
@click.option("--pdf", "mode", flag_value="pdf",
              help="First PDF rendering URL from archive_files.")
def get_url(index: Path, leaf_num: int | None, ill_num: int | None,
             bbox_str: str | None, size: str, fmt: str,
             padding: str | None, mode: str) -> None:
    """Emit a URL — no download."""
    aliases = {"small": "400,", "medium": "800,", "large": "1600,",
               "max": "max"}
    size = aliases.get(size, size)

    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    if mode == "manifest":
        row = conn.execute(
            "SELECT value FROM index_metadata WHERE key='manifest_url'"
        ).fetchone()
        if not row:
            raise click.ClickException("manifest_url not in index_metadata.")
        click.echo(row["value"])
        return

    if mode == "pdf":
        row = conn.execute(
            "SELECT download_url FROM archive_files "
            "WHERE format LIKE '%pdf%' ORDER BY filename LIMIT 1"
        ).fetchone()
        if not row:
            raise click.ClickException("No PDF rendering recorded for this index.")
        click.echo(row["download_url"])
        return

    if leaf_num is None:
        raise click.UsageError(f"--{mode} requires -l / --leaf.")

    pn = conn.execute(
        "SELECT image_service_url, width, height, "
        "image_width, image_height FROM page_numbers "
        "WHERE leaf_num = ?", (leaf_num,)
    ).fetchone()
    if not pn or not pn["image_service_url"]:
        raise click.ClickException(
            f"Canvas {leaf_num} has no image_service_url."
        )
    service = pn["image_service_url"]
    # Only fetch info.json when --padding will need it (cheap if not).
    cache_dir = None
    cfg_http: dict[str, Any] = {}
    if padding:
        from iiif_utils.config import load_config
        cfg = load_config()
        cfg_http = cfg.get("http", {})
        cache_dir = Path(cfg_http.get(
            "cache_dir", "./.iiif-cache")).expanduser()
        clamp_w, clamp_h = image_api.resolve_dims(
            pn, cfg_http=cfg_http, cache_dir=cache_dir)
    else:
        clamp_w, clamp_h = image_api.clamp_dims_from_page_row(pn)

    if mode == "info":
        click.echo(image_api.info_json_url(service))
        return

    # 'max' needs info.json to expand to '{width},' — load http cfg if not
    # already loaded for --padding.
    if size == "max":
        if not cfg_http:
            from iiif_utils.config import load_config
            cfg_http = load_config().get("http", {})
            cache_dir = Path(cfg_http.get(
                "cache_dir", "./.iiif-cache")).expanduser()
        size = image_api.resolve_max_size(size, service,
                                           cfg_http=cfg_http,
                                           cache_dir=cache_dir)

    if mode == "image":
        click.echo(image_api.region_url(service, None, size=size, fmt=fmt))
        return

    if mode == "figure":
        if ill_num is None:
            raise click.UsageError("--figure requires -n / --number.")
        ill = conn.execute(
            "SELECT bbox_x0, bbox_y0, bbox_x1, bbox_y1 FROM illustrations "
            "WHERE page_id = ? AND illustration_number = ?",
            (leaf_num, ill_num),
        ).fetchone()
        if not ill:
            raise click.ClickException(
                f"No illustration #{ill_num} on canvas {leaf_num}."
            )
        bbox = (ill["bbox_x0"], ill["bbox_y0"], ill["bbox_x1"], ill["bbox_y1"])
        if padding:
            bbox = image_api.padded_bbox(bbox, padding,
                                          canvas_w=clamp_w,
                                          canvas_h=clamp_h)
        click.echo(image_api.region_url(service, bbox, size=size, fmt=fmt))
        return

    if mode == "region":
        if not bbox_str:
            raise click.UsageError("--region requires --bbox 'x0,y0,x1,y1'.")
        parts = bbox_str.split(",")
        if len(parts) != 4:
            raise click.UsageError("--bbox must be 'x0,y0,x1,y1'.")
        try:
            bbox = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        except ValueError as e:
            raise click.UsageError(f"--bbox parse error: {e}") from e
        if padding:
            bbox = image_api.padded_bbox(bbox, padding,
                                          canvas_w=clamp_w,
                                          canvas_h=clamp_h)
        click.echo(image_api.region_url(service, bbox, size=size, fmt=fmt))
        return
