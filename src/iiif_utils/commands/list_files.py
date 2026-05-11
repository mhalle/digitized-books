"""`iiif-utils list-files` — list manifest renderings (PDF, plain text, …)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import click


@click.command(name="list-files")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--format-filter", default=None,
              help="Substring match on the IIIF rendering 'format' field "
                   "(e.g. 'pdf', 'plain', 'xml').")
def list_files(index: Path, format_filter: str | None) -> None:
    """List the manifest-level renderings (PDFs, plain text, etc.)."""
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT filename, format, source_type, download_url "
        "FROM archive_files ORDER BY filename"
    ))
    if format_filter:
        needle = format_filter.lower()
        rows = [r for r in rows if needle in (r["format"] or "").lower()]
    if not rows:
        click.echo("No files.", err=True)
        return
    for r in rows:
        click.echo(f"{r['filename']:<40} {r['format'] or '?':<22}  "
                   f"{r['download_url']}")
