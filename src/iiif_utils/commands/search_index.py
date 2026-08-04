"""`iiif-utils search-index` — FTS5 over an index."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.utils import output as output_
from iiif_utils.utils.page import page_ref

# FTS5 treats most punctuation as syntax, so a bare term containing it is a
# parse error rather than a search. That shape is routine in scanned text —
# figure references ("Fig. 591"), abbreviations ("U.S. Army"), and in name
# registers nearly every string ("Bailey, Allie D., b.'92"). Quote such
# tokens unless the caller asked for raw FTS5 syntax.
_FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}
_NEEDS_QUOTE = re.compile(r"[^\w\s*]")


def _tokenize(query: str) -> list[str]:
    """Split on whitespace, but keep a "quoted phrase" as one token.

    Splitting naively breaks an already-correct query: a quoted phrase
    is torn in half, and the trailing half — which now contains a stray
    quote character — gets quoted again into nonsense.
    """
    toks: list[str] = []
    buf: list[str] = []
    in_quote = False
    for ch in query:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
        elif ch.isspace() and not in_quote:
            if buf:
                toks.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        toks.append("".join(buf))
    return toks


def _massage(query: str, raw: bool) -> str:
    if raw:
        return query
    out: list[str] = []
    for tok in _tokenize(query):
        if (tok in _FTS_OPERATORS or tok.startswith('"')
                or tok.startswith("(") or tok.endswith(")")):
            out.append(tok)
        elif _NEEDS_QUOTE.search(tok):
            # FTS5 escapes an embedded double quote by doubling it.
            out.append('"' + tok.replace('"', '""') + '"')
        else:
            out.append(tok)
    return " ".join(out)


@click.command(name="search-index")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-q", "--query", required=True, help="FTS5 query string.")
@click.option("--blocks", is_flag=True, default=False,
              help="Search at block (TextBlock) granularity with bboxes.")
@click.option("-l", "--limit", type=int, default=10)
@click.option("--raw", is_flag=True, default=False,
              help="Don't auto-quote hyphenated tokens.")
@output_.format_option(default="records")
def search_index(index: Path, query: str, blocks: bool, limit: int,
                  raw: bool, fmt: str) -> None:
    """Run an FTS5 query against the index."""
    q = _massage(query, raw)
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    out: list[dict[str, Any]] = []
    if blocks:
        db_rows = _fts(conn, """
            SELECT
                tb.page_id, tb.block_number,
                tb.bbox_x0, tb.bbox_y0, tb.bbox_x1, tb.bbox_y1,
                pn.book_page_number,
                snippet(text_blocks_fts, 0, '→', '←', '...', 16) AS snip
            FROM text_blocks_fts ts
            JOIN text_blocks tb ON ts.rowid = tb.rowid
            LEFT JOIN page_numbers pn ON pn.leaf_num = tb.page_id
            WHERE text_blocks_fts MATCH ?
            ORDER BY ts.rank LIMIT ?
        """, (q, limit), query, raw)
        for r in db_rows:
            out.append({
                **page_ref(r["page_id"]),
                "page": r["book_page_number"],
                "block": r["block_number"],
                "bbox": [r["bbox_x0"], r["bbox_y0"],
                          r["bbox_x1"], r["bbox_y1"]],
                "snippet": r["snip"],
            })
    else:
        db_rows = _fts(conn, """
            SELECT
                pf.page_id, pn.book_page_number,
                snippet(pages_fts, 0, '→', '←', '...', 24) AS snip
            FROM pages_fts pf
            LEFT JOIN page_numbers pn ON pn.leaf_num = pf.page_id
            WHERE pages_fts MATCH ?
            ORDER BY rank LIMIT ?
        """, (q, limit), query, raw)
        for r in db_rows:
            out.append({
                **page_ref(r["page_id"]),
                "page": r["book_page_number"],
                "snippet": r["snip"],
            })

    output_.write_records(out, fmt=fmt)


def _fts(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...],
          original: str, raw: bool) -> list[Any]:
    """Run an FTS5 query, turning a parse error into a usable message.

    An unquoted punctuated term is a syntax error to FTS5, not a search,
    and surfaced as a bare OperationalError traceback.
    """
    try:
        return list(conn.execute(sql, params))
    except sqlite3.OperationalError as e:
        if "fts5" not in str(e).lower():
            raise
        hint = ("--raw passes the query to FTS5 unchanged; drop it and "
                "punctuated terms are quoted for you."
                if raw else
                "Wrap the phrase in double quotes, e.g. -q '\"Fig. 591\"'.")
        raise click.ClickException(
            f"FTS5 could not parse {original!r}: {e}. {hint}") from e
