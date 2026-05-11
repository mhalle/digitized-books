"""Demo queries against morris.sqlite — show what's in the index."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "morris.sqlite"


def heading(text):
    bar = "=" * 70
    print(f"\n{bar}\n  {text}\n{bar}")


def main():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    heading("Index metadata")
    for r in conn.execute("SELECT key, value FROM index_metadata"):
        v = r["value"][:80] + "..." if r["value"] and len(r["value"]) > 80 else r["value"]
        print(f"  {r['key']:>32}  {v}")

    heading("Document metadata (highlights)")
    keys = ["title", "catalogue_title", "catalogue_contributors",
            "catalogue_production_dates", "catalogue_languages",
            "catalogue_subjects", "manifest_metadata:Publication/creation",
            "identifier:sierra-system-number"]
    for k in keys:
        row = conn.execute("SELECT value FROM document_metadata WHERE key=?",
                            (k,)).fetchone()
        if row:
            v = row["value"]
            if len(v) > 100:
                v = v[:100] + "..."
            print(f"  {k:>40}  {v}")

    heading("Page-numbers coverage")
    cur = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(book_page_number IS NULL) AS unnumbered,
            SUM(book_page_number IS NOT NULL) AS numbered
        FROM page_numbers
    """).fetchone()
    print(f"  total canvases:  {cur['total']:>5}")
    print(f"  unnumbered:      {cur['unnumbered']:>5}")
    print(f"  numbered:        {cur['numbered']:>5}")
    print()
    print("  First 5 numbered canvases (leaf → printed page):")
    for r in conn.execute(
            "SELECT leaf_num, book_page_number FROM page_numbers "
            "WHERE book_page_number IS NOT NULL ORDER BY leaf_num LIMIT 5"):
        print(f"    {r['leaf_num']:>4} → {r['book_page_number']}")

    heading("Text content statistics")
    cur = conn.execute("""
        SELECT COUNT(*) AS rows,
               SUM(length) AS total_chars,
               AVG(length) AS mean_chars,
               MIN(length) AS min_chars,
               MAX(length) AS max_chars
        FROM text_blocks
    """).fetchone()
    print(f"  text_blocks rows:    {cur['rows']:>8,}")
    print(f"  total chars:         {cur['total_chars']:>8,}")
    print(f"  mean chars / block:  {cur['mean_chars']:>8.0f}")
    print(f"  min / max chars:     {cur['min_chars']} / {cur['max_chars']:,}")

    heading("Illustrations")
    cur = conn.execute("""
        SELECT COUNT(*) AS rows,
               COUNT(DISTINCT page_id) AS pages_with_illus
        FROM illustrations
    """).fetchone()
    print(f"  illustrations rows: {cur['rows']:,}")
    print(f"  pages with at least one illustration: {cur['pages_with_illus']}")

    heading("FTS search: 'femur'")
    for r in conn.execute("""
        SELECT pf.page_id, pn.book_page_number,
               snippet(pages_fts, 0, '→', '←', '...', 18) AS snip
        FROM pages_fts pf
        LEFT JOIN page_numbers pn ON pn.leaf_num = pf.page_id
        WHERE pages_fts MATCH 'femur'
        ORDER BY rank LIMIT 5
    """):
        pn = r['book_page_number'] or '—'
        print(f"  canvas {r['page_id']:>4} (p.{pn}):  {r['snip']}")

    heading("FTS phrase search: '\"circle of willis\"'")
    for r in conn.execute("""
        SELECT pf.page_id, pn.book_page_number,
               snippet(pages_fts, 0, '→', '←', '...', 20) AS snip
        FROM pages_fts pf
        LEFT JOIN page_numbers pn ON pn.leaf_num = pf.page_id
        WHERE pages_fts MATCH '"circle of willis"'
        ORDER BY rank LIMIT 5
    """):
        pn = r['book_page_number'] or '—'
        print(f"  canvas {r['page_id']:>4} (p.{pn}):  {r['snip']}")

    heading("Block-level FTS: 'sphenoid NEAR/5 sinus'")
    for r in conn.execute("""
        SELECT tb.page_id, pn.book_page_number, tb.block_number,
               tb.bbox_x0, tb.bbox_y0, tb.bbox_x1, tb.bbox_y1,
               snippet(text_blocks_fts, 0, '→', '←', '...', 14) AS snip
        FROM text_blocks_fts ts
        JOIN text_blocks tb ON ts.rowid = tb.rowid
        LEFT JOIN page_numbers pn ON pn.leaf_num = tb.page_id
        WHERE text_blocks_fts MATCH 'NEAR(sphenoid sinus, 5)'
        ORDER BY ts.rank LIMIT 5
    """):
        pn = r['book_page_number'] or '—'
        print(f"  canvas {r['page_id']:>4} (p.{pn}) block {r['block_number']}"
              f" bbox=({r['bbox_x0']},{r['bbox_y0']},{r['bbox_x1']},{r['bbox_y1']})")
        print(f"    {r['snip']}")

    heading("Roman-numeral front matter: confirmed via OCR scan")
    print("  Looking for top-of-page text matching a lone roman numeral on")
    print("  canvases whose `book_page_number` is NULL...")
    for r in conn.execute("""
        SELECT page_id, MIN(bbox_y0) AS top_y, text
        FROM text_blocks
        WHERE page_id IN (
            SELECT leaf_num FROM page_numbers WHERE book_page_number IS NULL
        )
          AND text GLOB '[IVXivx]*'
          AND length BETWEEN 2 AND 8
          AND bbox_y0 < 200
        GROUP BY page_id
        ORDER BY page_id
        LIMIT 12
    """):
        print(f"  canvas {r['page_id']:>4} top-y={r['top_y']:>4}: {r['text']!r}")

    heading("Sample 'femur' hit -> image URL builder")
    row = conn.execute("""
        SELECT pf.page_id, pn.image_service_url, pn.book_page_number
        FROM pages_fts pf
        LEFT JOIN page_numbers pn ON pn.leaf_num = pf.page_id
        WHERE pages_fts MATCH 'femur' ORDER BY rank LIMIT 1
    """).fetchone()
    if row and row["image_service_url"]:
        url = f"{row['image_service_url']}/full/1200,/0/default.jpg"
        print(f"  canvas {row['page_id']} (p.{row['book_page_number']})")
        print(f"  image:   {url}")


if __name__ == "__main__":
    main()
