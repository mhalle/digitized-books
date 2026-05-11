"""Tabular output helpers — uniform `--format` across listing commands.

Supported formats:
  table   aligned columns (default for multiple results)
  records key: value pairs, blank line between (default for single results)
  json    indented JSON array
  jsonl   one JSON object per line (stream-friendly)
  csv     comma-separated values with header
"""
from __future__ import annotations

import csv
import json
import sys
from typing import Any, Callable, IO

import click

FORMATS = ("table", "records", "json", "jsonl", "csv")


def format_option(default: str = "table") -> Callable[[Callable[..., Any]],
                                                       Callable[..., Any]]:
    """Reusable click decorator for --format."""
    return click.option(
        "--format", "fmt",
        type=click.Choice(FORMATS),
        default=default,
        help=f"Output format (default {default}).",
    )


def _stringify(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v)


def write_records(rows: list[dict[str, Any]],
                   fmt: str = "table",
                   columns: list[str] | None = None,
                   fp: IO[str] | None = None) -> None:
    """Write a list of dicts in the chosen format. No-op on empty input."""
    if fp is None:
        fp = sys.stdout
    if not rows:
        return
    if columns is None:
        # Preserve first-row key order
        columns = list(rows[0].keys())

    if fmt == "json":
        json.dump(rows, fp, indent=2, default=str)
        fp.write("\n")
        return

    if fmt == "jsonl":
        for r in rows:
            json.dump(r, fp, default=str)
            fp.write("\n")
        return

    if fmt == "csv":
        # csv writer can't directly take a generic dict — coerce values.
        flat = [{c: _stringify(r.get(c)) for c in columns} for r in rows]
        w = csv.DictWriter(fp, fieldnames=columns)
        w.writeheader()
        w.writerows(flat)
        return

    if fmt == "records":
        for i, r in enumerate(rows):
            if i > 0:
                fp.write("\n")
            for c in columns:
                fp.write(f"{c}: {_stringify(r.get(c))}\n")
        return

    # default: table
    widths = {c: max(len(c),
                      max((len(_stringify(r.get(c))) for r in rows),
                          default=0))
               for c in columns}
    fp.write("  ".join(c.ljust(widths[c]) for c in columns) + "\n")
    for r in rows:
        fp.write("  ".join(_stringify(r.get(c)).ljust(widths[c])
                            for c in columns) + "\n")
