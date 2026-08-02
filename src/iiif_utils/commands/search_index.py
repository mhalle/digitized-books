"""`iiif-utils search-index` — FTS5 over an index."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.utils import output as output_
from iiif_utils.utils.page import page_ref

# Hyphenated terms confuse FTS5 — quote them automatically.
_HYPHEN = re.compile(r"\b[A-Za-z]+(-[A-Za-z]+)+\b")


def _massage(query: str, raw: bool) -> str:
    if raw:
        return query
    def quote(m: re.Match[str]) -> str:
        return f'"{m.group(0)}"'
    return _HYPHEN.sub(quote, query)


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
        db_rows = list(conn.execute("""
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
        """, (q, limit)))
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
        db_rows = list(conn.execute("""
            SELECT
                pf.page_id, pn.book_page_number,
                snippet(pages_fts, 0, '→', '←', '...', 24) AS snip
            FROM pages_fts pf
            LEFT JOIN page_numbers pn ON pn.leaf_num = pf.page_id
            WHERE pages_fts MATCH ?
            ORDER BY rank LIMIT ?
        """, (q, limit)))
        for r in db_rows:
            out.append({
                **page_ref(r["page_id"]),
                "page": r["book_page_number"],
                "snippet": r["snip"],
            })

    output_.write_records(out, fmt=fmt)
