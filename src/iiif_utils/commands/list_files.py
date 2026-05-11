"""`iiif-utils list-files` — list manifest renderings (PDF, plain text, …)."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.utils import output as output_


@click.command(name="list-files")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--format-filter", default=None,
              help="Substring match on the IIIF rendering 'format' field "
                   "(e.g. 'pdf', 'plain', 'xml').")
@output_.format_option(default="table")
def list_files(index: Path, format_filter: str | None, fmt: str) -> None:
    """List the manifest-level renderings (PDFs, plain text, etc.)."""
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    db_rows = list(conn.execute(
        "SELECT filename, format, source_type, download_url "
        "FROM archive_files ORDER BY filename"
    ))
    if format_filter:
        needle = format_filter.lower()
        db_rows = [r for r in db_rows
                    if needle in (r["format"] or "").lower()]
    if not db_rows:
        click.echo("No files.", err=True)
        return

    rows: list[dict[str, Any]] = [
        {"filename": r["filename"], "format": r["format"],
         "source_type": r["source_type"], "url": r["download_url"]}
        for r in db_rows
    ]
    output_.write_records(rows, fmt=fmt)
