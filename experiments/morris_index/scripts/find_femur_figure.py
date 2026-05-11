"""Find an illustration of a femur in the Morris index and produce its
IIIF region URL.

Strategy:
  1. FTS for blocks containing "femur" that look like figure captions
     (start with 'Fig.').
  2. For each match, look up illustrations on the same page.
  3. Score each caption-illustration pair by vertical proximity (caption
     usually sits directly below its figure in this atlas).
  4. Construct IIIF region URLs and download the best candidate(s).
"""
from __future__ import annotations

import sqlite3
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "morris.sqlite"
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

# Step 1: candidate caption blocks — must mention femur AND start with 'Fig.'
candidates = list(conn.execute("""
    SELECT
        tb.page_id, tb.block_number, tb.text,
        tb.bbox_x0, tb.bbox_y0, tb.bbox_x1, tb.bbox_y1,
        pn.book_page_number, pn.image_service_url,
        pn.width AS canvas_w, pn.height AS canvas_h
    FROM text_blocks tb
    JOIN page_numbers pn ON pn.leaf_num = tb.page_id
    WHERE tb.text MATCH ('femur')      -- FTS5 prefilter via implicit join? no
    """ if False else """
    SELECT
        tb.page_id, tb.block_number, tb.text,
        tb.bbox_x0, tb.bbox_y0, tb.bbox_x1, tb.bbox_y1,
        pn.book_page_number, pn.image_service_url,
        pn.width AS canvas_w, pn.height AS canvas_h
    FROM text_blocks_fts ts
    JOIN text_blocks tb ON ts.rowid = tb.rowid
    JOIN page_numbers pn ON pn.leaf_num = tb.page_id
    WHERE text_blocks_fts MATCH 'femur'
      AND tb.text LIKE 'Fig.%'
      AND tb.length < 200          -- captions are short
    ORDER BY ts.rank LIMIT 20
"""))

print(f"Candidate caption blocks (femur + Fig.): {len(candidates)}\n")
for c in candidates[:8]:
    print(f"  canvas {c['page_id']:>4} (p.{c['book_page_number'] or '—'}) "
          f"blk{c['block_number']}  bbox y0={c['bbox_y0']:>4} y1={c['bbox_y1']:>4}")
    print(f"    {c['text'][:110]!r}")

if not candidates:
    print("No candidates — try widening.")
    raise SystemExit

# Step 2-3: for each candidate, find the illustration on the same page
# that is geometrically nearest (above the caption).
print("\nMatching captions to illustrations on the same page:\n")

def match_illustration(c):
    """Return (best_illus_row, distance, hint) or (None, None, hint)."""
    illus = list(conn.execute("""
        SELECT illustration_number, bbox_x0, bbox_y0, bbox_x1, bbox_y1
        FROM illustrations WHERE page_id = ?
    """, (c["page_id"],)))
    if not illus:
        return None, None, "no <Illustration> on page"

    # Caption assumed to be below figure → score = caption.y0 - illus.y1
    # Only count illustrations whose y1 is above caption.y0.
    above = [(c["bbox_y0"] - i["bbox_y1"], i) for i in illus
             if i["bbox_y1"] < c["bbox_y0"]]
    if above:
        above.sort(key=lambda t: t[0])  # smallest vertical gap wins
        dist, best = above[0]
        return best, dist, "above-caption"
    # Else nearest in absolute centre-y distance
    cap_cy = (c["bbox_y0"] + c["bbox_y1"]) / 2
    illus.sort(key=lambda i: abs((i["bbox_y0"] + i["bbox_y1"]) / 2 - cap_cy))
    return illus[0], None, "no above-match, taking nearest"

selected = []
for c in candidates[:8]:
    best, dist, hint = match_illustration(c)
    print(f"  canvas {c['page_id']:>4} (p.{c['book_page_number'] or '—'}):  {hint}")
    if best is None:
        continue
    print(f"    illus bbox: ({best['bbox_x0']}, {best['bbox_y0']}, "
          f"{best['bbox_x1']}, {best['bbox_y1']})  "
          f"dist={dist}")
    selected.append((c, dict(best)))

# Step 4: construct IIIF Image API URLs (v2) for the picks
print("\nIIIF region URLs:\n")

def region_url(service_url, x0, y0, x1, y1, max_w=1400):
    """Build a IIIF Image v2 region URL.

    Region format: x,y,w,h in image coords (matching ALTO pixel bboxes,
    since canvas width/height = full image width/height for Wellcome).
    Size format: ',h' or 'w,' — we cap width to max_w.
    """
    x = int(x0); y = int(y0)
    w = int(x1 - x0); h = int(y1 - y0)
    return f"{service_url}/{x},{y},{w},{h}/{max_w},/0/default.jpg"

# Download the top 3
with httpx.Client(timeout=120.0, follow_redirects=True,
                  headers={"User-Agent": "iiif-utils-experiment/0"}) as client:
    for i, (cap, illus) in enumerate(selected[:3]):
        url = region_url(cap["image_service_url"],
                         illus["bbox_x0"], illus["bbox_y0"],
                         illus["bbox_x1"], illus["bbox_y1"])
        print(f"#{i+1}  canvas {cap['page_id']} "
              f"(p.{cap['book_page_number']}):")
        print(f"     caption: {cap['text'][:90]!r}")
        print(f"     URL:     {url}")
        # Save the image
        fname = OUT / f"femur_canvas{cap['page_id']}_p{cap['book_page_number']}.jpg"
        if not fname.exists():
            r = client.get(url); r.raise_for_status()
            fname.write_bytes(r.content)
            print(f"     saved:   {fname.relative_to(ROOT)}  "
                  f"({fname.stat().st_size/1024:.1f} KB)")
        print()
