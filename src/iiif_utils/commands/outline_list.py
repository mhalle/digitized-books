"""`iiif-utils outline-list` — pretty-print the derived navigation outline."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.utils import output as output_

FORMATS = ("tree", "table", "records", "json", "jsonl", "csv")


@click.command(name="outline-list")
@click.argument(
    "index_path", type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(FORMATS),
    default="tree",
    help="Output format (default tree).",
)
def outline_list(index_path: Path, fmt: str) -> None:
    """Print the derived outline for a book.

    The default `tree` format renders an indented hierarchical view;
    other formats emit one row per entry (suitable for piping).
    """
    conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    if "derived_outline" not in {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }:
        click.echo(
            "(no derived_outline table; use outline-import to populate)",
            err=True,
        )
        return

    rows = list(conn.execute(
        """
        WITH RECURSIVE walk(id, level, parent_id, title, canvas_start, canvas_end,
                            printed_page_start, printed_page_end, notes, depth) AS (
          SELECT id, level, parent_id, title, canvas_start, canvas_end,
                 printed_page_start, printed_page_end, notes, 0
          FROM derived_outline WHERE parent_id IS NULL
          UNION ALL
          SELECT d.id, d.level, d.parent_id, d.title, d.canvas_start, d.canvas_end,
                 d.printed_page_start, d.printed_page_end, d.notes, w.depth + 1
          FROM derived_outline d JOIN walk w ON d.parent_id = w.id
        )
        SELECT * FROM walk ORDER BY id
        """
    ))

    if not rows:
        click.echo("(derived_outline is empty)", err=True)
        return

    if fmt == "tree":
        for r in rows:
            indent = "  " * r["depth"]
            cs, ce = r["canvas_start"], r["canvas_end"]
            range_str = f"c.{cs}" if cs == ce else f"c.{cs}-{ce}"
            ps, pe = r["printed_page_start"], r["printed_page_end"]
            if ps is not None and pe is not None:
                pp_str = f" pp.{ps}" if ps == pe else f" pp.{ps}-{pe}"
            else:
                pp_str = ""
            click.echo(f"{indent}{r['title']}{pp_str}  [{range_str}]")
            if r["notes"]:
                click.echo(f"{indent}  ↳ {r['notes']}")
        return

    out_rows: list[dict[str, Any]] = [
        {
            "id": r["id"],
            "level": r["level"],
            "parent_id": r["parent_id"],
            "title": r["title"],
            "printed_page_start": r["printed_page_start"],
            "printed_page_end": r["printed_page_end"],
            "canvas_start": r["canvas_start"],
            "canvas_end": r["canvas_end"],
            "notes": r["notes"],
        }
        for r in rows
    ]
    output_.write_records(out_rows, fmt=fmt)
