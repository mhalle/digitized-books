"""`iiif-utils get-region` — pull an arbitrary (x,y,w,h) crop."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import image_api


@click.command(name="get-region")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, required=True)
@click.option("--bbox", "bbox_str", required=True,
              help="Region as 'x0,y0,x1,y1' (image pixels).")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--padding", default=None,
              help="Padding for the crop: int pixels or '5%'.")
@click.option("--size", default="1400,", help="IIIF size string.")
@click.option("--format", "fmt", default="jpg")
@click.option("--url-only", is_flag=True, default=False)
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_region(index: Path, leaf_num: int, bbox_str: str,
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
    row = conn.execute(
        "SELECT image_service_url, width, height FROM page_numbers "
        "WHERE leaf_num = ?", (leaf_num,)
    ).fetchone()
    if not row or not row["image_service_url"]:
        raise click.ClickException(
            f"Canvas {leaf_num} has no image_service_url."
        )

    if padding:
        bbox = image_api.padded_bbox(bbox, padding,  # type: ignore[arg-type]
                                       canvas_w=row["width"],
                                       canvas_h=row["height"])
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
