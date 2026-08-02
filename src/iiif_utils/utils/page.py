"""Resolve `--leaf` / `--book` to a canvas index against an index DB."""
from __future__ import annotations

import sqlite3

import click


def parse_leaf_spec(spec: str, max_idx: int | None = None) -> list[int]:
    """Parse '1-10', '3', '1-5,10,20-22' into a sorted list of indices.

    `max_idx` clamps to a known canvas count; omit it when the caller
    filters against real rows anyway (a nonexistent leaf then simply
    matches nothing, rather than needing an upper bound up front).
    """
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            for i in range(min(lo, hi), max(lo, hi) + 1):
                if i >= 0 and (max_idx is None or i <= max_idx):
                    out.add(i)
        else:
            i = int(part)
            if i >= 0 and (max_idx is None or i <= max_idx):
                out.add(i)
    return sorted(out)


def resolve_leaf(conn: sqlite3.Connection,
                  leaf: int | None,
                  book: str | None) -> int:
    """One of -l/--leaf or -b/--book must be given. -b looks up
    page_numbers.book_page_number; raises UsageError or ClickException
    on no match.
    """
    if leaf is not None and book is not None:
        raise click.UsageError("Pass --leaf OR --book, not both.")
    if leaf is not None:
        return leaf
    if book is None:
        raise click.UsageError("One of --leaf / --book is required.")
    row = conn.execute(
        "SELECT leaf_num FROM page_numbers WHERE book_page_number = ?",
        (book,),
    ).fetchone()
    if not row:
        raise click.ClickException(
            f"No leaf found for printed page {book!r}."
        )
    return int(row["leaf_num"])
