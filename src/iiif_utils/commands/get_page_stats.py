"""`iiif-utils get-page-stats` — per-page text statistics from an index.

Ported from ia-utils. The practical use is finding plate pages without
looking at them: a page carrying a full-page figure has few blocks, a
low word count, and often a lower mean confidence than a page of
prose, so the outliers in this table are where the illustrations are.

`--figures` applies that heuristic directly rather than making you eyeball
the numbers.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.utils import output as output_
from iiif_utils.utils.page import parse_book_spec, parse_leaf_spec


@click.command(name="get-page-stats")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_spec", default=None,
              help="Leaf range: '5', '1-7,21,25'. Default: all pages.")
@click.option("-b", "--book", "book_spec", default=None,
              help="Printed-page range, resolved via page_numbers.")
@click.option("--figures", is_flag=True, default=False,
              help="Show only likely figure pages — those with fewer "
                   "blocks and lower word counts than the book's median.")
@click.option("--sort-by", type=click.Choice(["leaf", "words", "blocks"]),
              default="leaf", show_default=True)
@output_.format_option(default="table")
def get_page_stats(index: Path, leaf_spec: str | None, book_spec: str | None,
                    figures: bool, sort_by: str, fmt: str) -> None:
    """Per-page block / line / word / character counts."""
    if leaf_spec and book_spec:
        raise click.UsageError("Pass -l or -b, not both.")

    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rows = list(conn.execute("""
        SELECT
            tb.page_id                        AS leaf,
            pn.book_page_number               AS page,
            COUNT(*)                          AS blocks,
            COALESCE(SUM(tb.line_count), 0)   AS lines,
            COALESCE(SUM(tb.word_count), 0)   AS words,
            COALESCE(SUM(tb.length), 0)       AS chars,
            AVG(tb.avg_confidence)            AS avg_confidence
        FROM text_blocks tb
        LEFT JOIN page_numbers pn ON pn.leaf_num = tb.page_id
        GROUP BY tb.page_id
        ORDER BY tb.page_id
    """))
    if not rows:
        raise click.ClickException(
            "No text_blocks in this index — it may be image-only "
            "(built with --no-ocr, or from a source with no OCR).")

    wanted: set[int] | None = None
    if leaf_spec:
        wanted = set(parse_leaf_spec(leaf_spec))
    elif book_spec:
        books = set(parse_book_spec(book_spec))
        wanted = {r["leaf_num"] for r in conn.execute(
            "SELECT leaf_num, book_page_number FROM page_numbers "
            "WHERE book_page_number IS NOT NULL")
            if r["book_page_number"] in books}

    recs: list[dict[str, Any]] = []
    for r in rows:
        if wanted is not None and r["leaf"] not in wanted:
            continue
        conf = r["avg_confidence"]
        recs.append({
            "leaf": r["leaf"],
            "page": r["page"],
            "blocks": r["blocks"],
            "lines": r["lines"],
            "words": r["words"],
            "chars": r["chars"],
            "avg_confidence": round(conf, 1) if conf is not None else None,
        })

    if figures and recs:
        # Median-relative, so it adapts to the book's own density rather
        # than to a threshold tuned on some other volume.
        def median(vals: list[int]) -> float:
            s = sorted(vals)
            n = len(s)
            return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)
        med_words = median([r["words"] for r in recs])
        med_blocks = median([r["blocks"] for r in recs])
        recs = [r for r in recs
                if r["words"] < med_words * 0.5
                and r["blocks"] <= max(1.0, med_blocks * 0.5)]

    if sort_by == "words":
        recs.sort(key=lambda r: (r["words"], r["leaf"]))
    elif sort_by == "blocks":
        recs.sort(key=lambda r: (r["blocks"], r["leaf"]))

    output_.write_records(recs, fmt=fmt)
    if fmt in ("table", "records"):
        click.echo(f"\n  {len(recs)} pages"
                   + ("  (figure candidates)" if figures else ""), err=True)
