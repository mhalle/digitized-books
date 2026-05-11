"""E2 — Text overlap between Wellcome ALTO and IA hOCR (same work).

For each of our 30 Wellcome ALTO samples, reconstruct full-page text from
TextLines, then find the best-matching page in the IA `b31362138.sqlite`
index by token-Jaccard. Goal: estimate whether the two sides are running
the same OCR engine (high overlap, modulo serialisation), or different
ones (lower overlap with systematic differences).

Wellcome b31362126 (3-vol English Spalteholz, 1929/30 Lippincott).
IA b31362138 (One-volume bound English Spalteholz, 1933 Lippincott reprint
of the same translation). Text should be ~identical modulo edition tweaks.

Writes ../results/e2_text_overlap.{md,json}.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

IA_INDEX = Path(
    "/Users/halazar/Dropbox/development/internet-archive/b31362138.sqlite"
)
ALTO_NS = "http://www.loc.gov/standards/alto/ns-v2#"
NS = {"a": ALTO_NS}

WORD_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-']{2,}")


def tokenize(text: str) -> set[str]:
    """Lowercased word-set, words of >=3 letters, hyphens preserved."""
    return {m.group(0).lower() for m in WORD_RE.finditer(text)}


def alto_page_text(path: Path) -> str:
    """Reconstruct full-page text from an ALTO file."""
    root = etree.parse(str(path)).getroot()
    parts: list[str] = []
    for line in root.findall(".//a:TextLine", NS):
        bits: list[str] = []
        for child in line:
            tag = etree.QName(child).localname
            if tag == "String":
                c = child.get("CONTENT")
                if c:
                    bits.append(c)
        if bits:
            parts.append(" ".join(bits))
    return "\n".join(parts)


def ia_page_text(conn: sqlite3.Connection, page_id: str) -> str:
    cur = conn.execute(
        "SELECT group_concat(text, ' ') FROM text_blocks "
        "WHERE page_id = ? GROUP BY page_id",
        (page_id,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else ""


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def fts_prefilter(
    conn: sqlite3.Connection,
    needle_tokens: set[str],
    k: int = 8,
) -> list[str]:
    """Use IA's pages_fts to find top-k candidate page_ids.

    Build an FTS5 query from the longest distinctive tokens.
    """
    # Pick rare-looking tokens (longer == more distinctive heuristic).
    candidates = sorted(needle_tokens, key=lambda t: (-len(t), t))[:8]
    candidates = [t for t in candidates if len(t) >= 5][:6]
    if not candidates:
        return []
    # FTS5 OR query
    query = " OR ".join(f'"{t}"' for t in candidates)
    try:
        rows = conn.execute(
            "SELECT page_id FROM pages_fts WHERE pages_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


def main() -> None:
    samples = json.loads((DATA / "samples.json").read_text())
    alto_samples = [s for s in samples if s.get("alto_url")]
    print(f"Comparing {len(alto_samples)} Wellcome ALTO pages against IA "
          f"{IA_INDEX.name}")

    conn = sqlite3.connect(f"file:{IA_INDEX}?mode=ro", uri=True)
    # Confirm IA total pages for context
    n_ia = conn.execute("SELECT COUNT(DISTINCT page_id) FROM text_blocks") \
                .fetchone()[0]
    print(f"IA index has {n_ia} unique page_ids")

    results: list[dict] = []
    for s in alto_samples:
        wt = alto_page_text(ROOT / s["alto_path"])
        wt_tokens = tokenize(wt)

        # Skip pages with negligible text (covers, all-plate pages)
        if len(wt_tokens) < 5:
            results.append({
                "volume": s["volume"],
                "canvas_index": s["canvas_index"],
                "wt_tokens": len(wt_tokens),
                "skipped_reason": "wellcome page has <5 tokens",
            })
            continue

        # Use FTS prefilter to bound the search
        candidates = fts_prefilter(conn, wt_tokens, k=8)

        best = None
        for cand in candidates:
            it = ia_page_text(conn, cand)
            it_tokens = tokenize(it)
            j = jaccard(wt_tokens, it_tokens)
            if best is None or j > best["jaccard"]:
                best = {
                    "ia_page_id": cand,
                    "jaccard": j,
                    "ia_tokens": len(it_tokens),
                    "common_tokens": len(wt_tokens & it_tokens),
                    "wellcome_only": len(wt_tokens - it_tokens),
                    "ia_only": len(it_tokens - wt_tokens),
                }

        row = {
            "volume": s["volume"],
            "canvas_index": s["canvas_index"],
            "wt_tokens": len(wt_tokens),
            "fts_candidates": len(candidates),
        }
        if best:
            row.update(best)
        else:
            row["skipped_reason"] = "no FTS candidates"
        results.append(row)

    conn.close()

    # Aggregate over rows with a real match
    matched = [r for r in results if "jaccard" in r]
    if matched:
        jaccards = sorted(r["jaccard"] for r in matched)
        agg = {
            "n_compared": len(matched),
            "n_skipped": len(results) - len(matched),
            "median_jaccard": jaccards[len(jaccards) // 2],
            "p10_jaccard": jaccards[max(0, int(0.1 * len(jaccards)) - 1)],
            "p90_jaccard": jaccards[min(len(jaccards) - 1, int(0.9 * len(jaccards)))],
            "mean_jaccard": sum(jaccards) / len(jaccards),
            "n_perfect_or_near": sum(1 for j in jaccards if j >= 0.9),
            "n_high":             sum(1 for j in jaccards if 0.7 <= j < 0.9),
            "n_medium":           sum(1 for j in jaccards if 0.4 <= j < 0.7),
            "n_low":              sum(1 for j in jaccards if j < 0.4),
        }
    else:
        agg = {"n_compared": 0, "n_skipped": len(results)}

    (RESULTS / "e2_text_overlap.json").write_text(
        json.dumps({"results": results, "aggregate": agg}, indent=2))

    md = [
        "# E2 — Text overlap: Wellcome ALTO ↔ IA hOCR (Spalteholz)",
        "",
        "**Wellcome**: `b31362126` (3-vol English Spalteholz, 1929/30 Lippincott)",
        "  ",
        "**IA**: `b31362138` (One-volume bound English Spalteholz, 1933"
        " Lippincott reprint).",
        "",
        f"30 sampled Wellcome ALTO pages compared against IA's"
        f" {conn_total if (conn_total := 0) else 'pages_fts'} (top-8 FTS-prefilter,"
        " best-Jaccard match).",
        "",
        "## Aggregate",
        "",
    ]
    if matched:
        md += [
            f"- Pages compared: **{agg['n_compared']}** (skipped"
            f" {agg['n_skipped']} — too few tokens)",
            f"- **Median Jaccard: {agg['median_jaccard']:.3f}**",
            f"- p10 / p90 Jaccard: {agg['p10_jaccard']:.3f} / {agg['p90_jaccard']:.3f}",
            f"- Mean Jaccard: {agg['mean_jaccard']:.3f}",
            "",
            "**Distribution:**",
            "",
            f"- ≥0.9 (near-identical OCR): **{agg['n_perfect_or_near']}**",
            f"- 0.7–0.9 (high):              **{agg['n_high']}**",
            f"- 0.4–0.7 (medium):            **{agg['n_medium']}**",
            f"- <0.4 (low):                  **{agg['n_low']}**",
        ]
    else:
        md.append("_No comparable pages._")

    md += [
        "",
        "## Per-page detail",
        "",
        "| volume | canvas | Wellcome tokens | IA tokens | common | Wellcome-only | IA-only | Jaccard | IA page |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        if "jaccard" in r:
            md.append(
                f"| {r['volume']} | {r['canvas_index']} | {r['wt_tokens']} |"
                f" {r['ia_tokens']} | {r['common_tokens']} |"
                f" {r['wellcome_only']} | {r['ia_only']} |"
                f" {r['jaccard']:.3f} | {r['ia_page_id']} |"
            )
        else:
            md.append(
                f"| {r['volume']} | {r['canvas_index']} | {r['wt_tokens']} |"
                f" — | — | — | — | — | _{r.get('skipped_reason','no match')}_ |"
            )

    (RESULTS / "e2_text_overlap.md").write_text("\n".join(md) + "\n")
    print(f"Wrote {RESULTS / 'e2_text_overlap.md'}")
    print(f"      {RESULTS / 'e2_text_overlap.json'}")
    if matched:
        print()
        print(f"Headline: median Jaccard = {agg['median_jaccard']:.3f}"
              f" across {agg['n_compared']} compared pages")


if __name__ == "__main__":
    main()
