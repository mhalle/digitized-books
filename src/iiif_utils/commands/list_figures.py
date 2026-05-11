"""`iiif-utils list-figures` — list illustrations from an index."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.config import load_config
from iiif_utils.core import image_api
from iiif_utils.utils import output as output_


@click.command(name="list-figures")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, default=None,
              help="Restrict to a single canvas (0-indexed leaf number).")
@click.option("--all", "all_pages", is_flag=True, default=False,
              help="List every illustration in the index.")
@click.option("--padding", default=None,
              help="Pad the bboxes in emitted region URLs. Symmetric: "
                   "'20' or '5%'. Per-side: 'left,top,right,bottom'.")
@click.option("--size", default="1400,",
              help="IIIF size string (default: '1400,').")
@output_.format_option(default="table")
def list_figures(index: Path, leaf_num: int | None, all_pages: bool,
                  padding: str | None, size: str, fmt: str) -> None:
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

    db_rows = list(conn.execute(sql, params))
    if not db_rows:
        click.echo("No illustrations found.", err=True)
        return

    out_rows: list[dict[str, Any]] = []
    cfg = load_config() if padding else None
    cfg_http = cfg.get("http", {}) if cfg else {}
    cache_dir = (Path(cfg_http.get("cache_dir", "./.iiif-cache")).expanduser()
                  if padding else None)
    for r in db_rows:
        bbox = (r["bbox_x0"], r["bbox_y0"], r["bbox_x1"], r["bbox_y1"])
        if padding:
            cw, ch = image_api.resolve_dims(r, cfg_http=cfg_http,
                                              cache_dir=cache_dir)
            bbox = image_api.padded_bbox(bbox, padding,
                                          canvas_w=cw, canvas_h=ch)
        url = (image_api.region_url(r["image_service_url"], bbox, size=size)
                if r["image_service_url"] else None)
        out_rows.append({
            "canvas": r["page_id"],
            "n": r["illustration_number"],
            "page": r["book_page_number"],
            "type": r["illustration_type"],
            "bbox": list(bbox),
            "url": url,
        })

    output_.write_records(out_rows, fmt=fmt)
