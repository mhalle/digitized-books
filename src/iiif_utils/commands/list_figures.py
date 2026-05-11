"""`iiif-utils list-figures` — list illustrations from an index."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.core import image_api


@click.command(name="list-figures")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, default=None,
              help="Restrict to a single canvas (0-indexed leaf number).")
@click.option("--all", "all_pages", is_flag=True, default=False,
              help="List every illustration in the index.")
@click.option("--padding", default=None,
              help="Padding for region URL: int pixels or '5%'.")
@click.option("--size", default="1400,",
              help="IIIF size string (default: '1400,').")
def list_figures(index: Path, leaf_num: int | None, all_pages: bool,
                  padding: str | None, size: str) -> None:
    """List illustrations with their bboxes and IIIF region URLs."""
    if leaf_num is None and not all_pages:
        raise click.UsageError("Pass -l <leaf> or --all.")

    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT
            i.page_id, i.illustration_number, i.illustration_type,
            i.bbox_x0, i.bbox_y0, i.bbox_x1, i.bbox_y1,
            pn.book_page_number,
            pn.image_service_url,
            pn.width, pn.height, pn.image_width, pn.image_height
        FROM illustrations i
        JOIN page_numbers pn ON pn.leaf_num = i.page_id
    """
    params: tuple[Any, ...] = ()
    if leaf_num is not None:
        sql += " WHERE i.page_id = ?"
        params = (leaf_num,)
    sql += " ORDER BY i.page_id, i.illustration_number"

    rows = list(conn.execute(sql, params))
    if not rows:
        click.echo("No illustrations found.", err=True)
        return

    pad_val: int | str | None = None
    if padding:
        pad_val = padding

    for r in rows:
        if not r["image_service_url"]:
            continue
        bbox = (r["bbox_x0"], r["bbox_y0"], r["bbox_x1"], r["bbox_y1"])
        if pad_val is not None:
            cw, ch = image_api.clamp_dims_from_page_row(r)
            bbox = image_api.padded_bbox(bbox, pad_val, canvas_w=cw, canvas_h=ch)
        url = image_api.region_url(r["image_service_url"], bbox, size=size)
        pn = r["book_page_number"] or "—"
        click.echo(f"canvas {r['page_id']:>4} (p.{pn}) #{r['illustration_number']}"
                   f"  [{r['illustration_type']}]")
        click.echo(f"  bbox: {bbox}")
        click.echo(f"  url:  {url}")
