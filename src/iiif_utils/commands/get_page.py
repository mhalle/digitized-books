"""`iiif-utils get-page` — download a whole canvas image."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import image_api


@click.command(name="get-page")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, required=True)
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--size", default="1400,",
              help="IIIF size string. Aliases: small,medium,large,full.")
@click.option("--format", "fmt", default="jpg")
@click.option("--url-only", is_flag=True, default=False)
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_page(index: Path, leaf_num: int, output_path: Path | None,
              size: str, fmt: str, url_only: bool,
              config_path: Path | None) -> None:
    """Download a whole canvas image."""
    aliases = {"small": "400,", "medium": "800,", "large": "1600,",
               "full": "full"}
    size = aliases.get(size, size)

    cfg = load_config(config_path)
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT image_service_url FROM page_numbers WHERE leaf_num = ?",
        (leaf_num,),
    ).fetchone()
    if not row or not row["image_service_url"]:
        raise click.ClickException(f"Canvas {leaf_num} has no image_service_url.")

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
