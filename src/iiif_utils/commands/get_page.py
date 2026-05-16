"""`iiif-utils get-page` — download a whole canvas image."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import image_api
from iiif_utils.utils.page import resolve_leaf


@click.command(name="get-page")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, default=None,
              help="Canvas (leaf) index, 0-based. Mutually exclusive with -b.")
@click.option("-b", "--book", default=None,
              help="Printed page number (looks up via page_numbers).")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--size", default="1400,",
              help="IIIF size string. Aliases: small,medium,large,full,max."
                   " 'max' resolves to the source's native width via info.json"
                   " (use this if a server rejects '/full/full/').")
@click.option("--format", "fmt", default="jpg")
@click.option("--url-only", is_flag=True, default=False)
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_page(index: Path, leaf_num: int | None, book: str | None,
              output_path: Path | None, size: str, fmt: str,
              url_only: bool, config_path: Path | None) -> None:
    """Download a whole canvas image."""
    aliases = {"small": "400,", "medium": "800,", "large": "1600,",
               "full": "full", "max": "max"}
    size = aliases.get(size, size)

    cfg = load_config(config_path)
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    leaf_num = resolve_leaf(conn, leaf_num, book)
    row = conn.execute(
        "SELECT image_service_url FROM page_numbers WHERE leaf_num = ?",
        (leaf_num,),
    ).fetchone()
    if not row or not row["image_service_url"]:
        raise click.ClickException(f"Canvas {leaf_num} has no image_service_url.")

    size = image_api.resolve_max_size(size, row["image_service_url"],
                                       cfg_http=cfg.get("http", {}))
    url = image_api.region_url(row["image_service_url"], None,
                                 size=size, fmt=fmt)
    if url_only:
        click.echo(url)
        return
    if output_path is None:
        output_path = Path.cwd() / f"page_l{leaf_num}.{fmt}"
    content = http_.fetch_bytes(url, cfg_http=cfg.get("http", {}))
    output_path.write_bytes(content)
    click.echo(f"saved {output_path}  ({len(content)/1024:.1f} KB)")
