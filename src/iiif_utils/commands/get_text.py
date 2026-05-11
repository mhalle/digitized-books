"""`iiif-utils get-text` — fetch the whole-work plain-text rendering.

For when you want the entire book as one blob (LLM input, grep, etc.)
and don't care about per-page locality. ~30× smaller than the ALTO
source and one HTTP request instead of N.

Note: the rendering has no page boundaries (verified for Wellcome —
DESIGN.md §6). If you need per-page text, build an index with
`create-index` and query `text_blocks` instead.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import manifest as manifest_mod
from iiif_utils.providers import resolve


@click.command(name="get-text")
@click.argument("ref", required=False)
@click.option("-i", "--index", type=click.Path(exists=True, path_type=Path),
              default=None,
              help="Read the rendering URL from an existing index.")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write to file instead of stdout.")
@click.option("-P", "--provider", default=None)
@click.option("--url-only", is_flag=True, default=False,
              help="Print the rendering URL instead of fetching it.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_text(ref: str | None, index: Path | None, output_path: Path | None,
              provider: str | None, url_only: bool,
              config_path: Path | None) -> None:
    """Fetch the manifest-level plain-text rendering for a work."""
    cfg = load_config(config_path)
    cfg_http = cfg.get("http", {})

    if index and not ref:
        conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT download_url FROM archive_files "
            "WHERE format LIKE '%text/plain%' OR format = 'text/plain' "
            "ORDER BY filename LIMIT 1"
        ).fetchone()
        if not row:
            raise click.ClickException(
                "No text/plain rendering recorded in this index."
            )
        url = row[0]
    elif ref:
        cache_dir = Path(cfg_http.get("cache_dir", "./.iiif-cache")).expanduser()
        ref_obj = resolve(ref, cfg=cfg, explicit_provider=provider,
                           cache_dir=cache_dir)
        m = http_.fetch_json(ref_obj.manifest_url, cfg_http=cfg_http,
                              cache_dir=cache_dir)
        url = None
        for r in manifest_mod.renderings(m):
            if (r.format or "").lower() == "text/plain":
                url = r.url
                break
        if not url:
            raise click.ClickException(
                f"Manifest {ref_obj.manifest_url} has no text/plain rendering."
            )
    else:
        raise click.UsageError("Provide a manifest URL/identifier or -i INDEX.")

    if url_only:
        click.echo(url)
        return

    content = http_.fetch_bytes(url, cfg_http=cfg_http)
    if output_path is None:
        sys.stdout.buffer.write(content)
    else:
        output_path.write_bytes(content)
        click.echo(f"saved {output_path}  ({len(content)/1024/1024:.1f} MB)",
                   err=True)
