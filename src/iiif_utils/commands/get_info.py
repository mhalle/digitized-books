"""`iiif-utils get-info` — fetch and print a canvas's IIIF Image API info.json."""
from __future__ import annotations

import json as json_mod
import sqlite3
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import image_api
from iiif_utils.utils.page import resolve_leaf


@click.command(name="get-info")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, default=None)
@click.option("-b", "--book", default=None)
@click.option("--url-only", is_flag=True, default=False,
              help="Just emit the info.json URL.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_info(index: Path, leaf_num: int | None, book: str | None,
              url_only: bool, config_path: Path | None) -> None:
    """Print a canvas's IIIF Image API info.json."""
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    leaf = resolve_leaf(conn, leaf_num, book)
    row = conn.execute(
        "SELECT image_service_url FROM page_numbers WHERE leaf_num=?",
        (leaf,),
    ).fetchone()
    if not row or not row["image_service_url"]:
        raise click.ClickException(f"Canvas {leaf} has no image_service_url.")

    if url_only:
        click.echo(image_api.info_json_url(row["image_service_url"]))
        return

    cfg = load_config(config_path)
    cfg_http = cfg.get("http", {})
    cache_dir = Path(cfg_http.get("cache_dir", "./.iiif-cache")).expanduser()
    info = image_api.fetch_info_json(row["image_service_url"],
                                       cfg_http=cfg_http, cache_dir=cache_dir)
    click.echo(json_mod.dumps(info, indent=2))
