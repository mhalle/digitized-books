"""`iiif-utils get-figure` — pull an illustration by (page, n)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import image_api


@click.command(name="get-figure")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, required=True,
              help="Canvas index (0-indexed).")
@click.option("-n", "--number", "ill_num", type=int, default=0,
              help="Illustration number on that canvas (default 0).")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path),
              default=None,
              help="Output file path. Default: figure_lN_nM.jpg in cwd.")
@click.option("--padding", default=None,
              help="Padding for the crop: int pixels or '5%'.")
@click.option("--size", default="1400,",
              help="IIIF size string (default '1400,').")
@click.option("--format", "fmt", default="jpg",
              help="IIIF format (default 'jpg').")
@click.option("--url-only", is_flag=True, default=False,
              help="Print the URL instead of downloading.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_figure(index: Path, leaf_num: int, ill_num: int,
                output_path: Path | None, padding: str | None,
                size: str, fmt: str, url_only: bool,
                config_path: Path | None) -> None:
    """Download (or emit a URL for) one illustration."""
    cfg = load_config(config_path)
    cfg_http = cfg.get("http", {})

    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT
            i.bbox_x0, i.bbox_y0, i.bbox_x1, i.bbox_y1,
            pn.image_service_url,
            pn.width, pn.height, pn.image_width, pn.image_height
        FROM illustrations i
        JOIN page_numbers pn ON pn.leaf_num = i.page_id
        WHERE i.page_id = ? AND i.illustration_number = ?
    """, (leaf_num, ill_num)).fetchone()

    if not row:
        raise click.ClickException(
            f"No illustration #{ill_num} on canvas {leaf_num}."
        )
    if not row["image_service_url"]:
        raise click.ClickException(
            f"Canvas {leaf_num} has no image_service_url; can't build URL."
        )

    bbox = (row["bbox_x0"], row["bbox_y0"], row["bbox_x1"], row["bbox_y1"])
    if padding:
        cw, ch = image_api.clamp_dims_from_page_row(row)
        bbox = image_api.padded_bbox(bbox, padding, canvas_w=cw, canvas_h=ch)
    url = image_api.region_url(row["image_service_url"], bbox,
                                 size=size, fmt=fmt)

    if url_only:
        click.echo(url)
        return

    if output_path is None:
        output_path = Path.cwd() / f"figure_l{leaf_num}_n{ill_num}.{fmt}"
    content = http_.fetch_bytes(url, cfg_http=cfg_http)
    output_path.write_bytes(content)
    click.echo(f"saved {output_path}  ({len(content)/1024:.1f} KB)")
