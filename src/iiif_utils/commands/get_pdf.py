"""`iiif-utils get-pdf` — download the manifest-level PDF rendering."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_


@click.command(name="get-pdf")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Output path. Default: <slug>.pdf in cwd.")
@click.option("--url-only", is_flag=True, default=False)
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_pdf(index: Path, output_path: Path | None, url_only: bool,
             config_path: Path | None) -> None:
    """Download the PDF rendering of an indexed work, if available."""
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT download_url, filename FROM archive_files "
        "WHERE format LIKE '%pdf%' ORDER BY filename LIMIT 1"
    ).fetchone()
    if not row:
        raise click.ClickException("No PDF rendering recorded in this index.")

    url = row["download_url"]
    if url_only:
        click.echo(url)
        return

    if output_path is None:
        # Build a default name from the index slug
        slug_row = conn.execute(
            "SELECT value FROM index_metadata WHERE key='slug'"
        ).fetchone()
        slug = slug_row[0] if slug_row else "out"
        output_path = Path.cwd() / f"{slug}.pdf"

    cfg = load_config(config_path)
    content = http_.fetch_bytes(url, cfg_http=cfg.get("http", {}))
    output_path.write_bytes(content)
    click.echo(f"saved {output_path}  ({len(content)/1024/1024:.1f} MB)")
