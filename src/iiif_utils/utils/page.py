"""Resolve `--leaf` / `--book` to a canvas index against an index DB."""
from __future__ import annotations

import sqlite3

import click


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
