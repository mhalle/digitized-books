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
        try:
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
        except ValueError:
            raise click.UsageError(
                f"{part!r} is not a leaf number. Leaves are integers "
                f"('5', '1-7,21'); for printed pages like 'xii' use "
                f"-b/--book."
            ) from None
    return sorted(out)


def parse_book_spec(spec: str) -> list[str]:
    """Parse a printed-page selection into literal page labels.

    Printed page numbers are TEXT, not integers: books carry roman
    front matter ('xii'), plate numbers ('12a'), and folio forms. So a
    token is taken literally unless it is a numeric `A-B` range, which
    expands — '100-150' means what you'd expect, while 'xii' and '12a'
    match themselves.

    Returned labels are matched exactly against
    `page_numbers.book_page_number`; a label no page carries simply
    selects nothing.
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        if label not in seen:
            seen.add(label)
            out.append(label)

    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = a.strip(), b.strip()
            if a.isdigit() and b.isdigit():
                lo, hi = int(a), int(b)
                for i in range(min(lo, hi), max(lo, hi) + 1):
                    add(str(i))
                continue
        # Anything else — roman, '12a', an en-dashed folio — is a label.
        add(part)
    return out


def resolve_leaf(conn: sqlite3.Connection,
                  leaf: int | None,
                  book: str | None) -> int:
    """One of -l/--leaf or -b/--book must be given. -b looks up
    page_numbers.book_page_number; raises UsageError or ClickException
    on no match, or on an ambiguous one.

    A printed page number is NOT unique. Plates repeat numbers, volumes
    bound together restart at 1, and OCR page-number detection
    misreads. When several leaves claim the same printed page, this
    refuses and names the candidates rather than silently returning
    whichever row SQLite happened to order first — picking one at
    random is how you end up cropping a figure out of the wrong page
    and never noticing.
    """
    if leaf is not None and book is not None:
        raise click.UsageError("Pass --leaf OR --book, not both.")
    if leaf is not None:
        return leaf
    if book is None:
        raise click.UsageError("One of --leaf / --book is required.")
    rows = conn.execute(
        "SELECT leaf_num FROM page_numbers WHERE book_page_number = ? "
        "ORDER BY leaf_num",
        (book,),
    ).fetchall()
    if not rows:
        raise click.ClickException(
            f"No leaf found for printed page {book!r}."
        )
    if len(rows) > 1:
        leaves = ", ".join(str(int(r["leaf_num"])) for r in rows)
        raise click.ClickException(
            f"Printed page {book!r} is ambiguous — {len(rows)} leaves "
            f"carry it: {leaves}. Pick one with -l/--leaf."
        )
    return int(rows[0]["leaf_num"])
