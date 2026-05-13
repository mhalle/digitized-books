#!/usr/bin/env python3
"""resolve_outline.py — turn a flat TOC transcription into an outline-import
payload for `iiif-utils outline-import`.

Input (flat shape, what a human or LLM transcribes from the TOC image):

    {
      "work": "<filename-stem-of-the-sqlite>",
      "flat_entries": [
        {"level": 0, "title": "Chapter I — Origin", "printed_page": 17},
        {"level": 1, "title": "The Diffuse Nervous System", "printed_page": 19},
        ...
      ]
    }

Output (the nested shape that outline-import accepts):

    {
      "work": "<work-id>",
      "entries": [{"level": 0, "title": ..., "canvas_start": 16,
                    "canvas_end": 22, "printed_page_start": 17,
                    "printed_page_end": 23, "children": [...]}, ...]
    }

This script does the deterministic plumbing:
  - printed_page → canvas via the db's `page_numbers` table, with linear
    extrapolation from the nearest anchor for pages OCR missed
  - printed_page_end via the next-same-or-lower-level rule
  - tree assembly from the flat level-tagged list
  - same-canvas clamping (when next sibling starts on the same printed page)
  - parent-range extension (when the last child shares its end canvas with
    the parent's next sibling)
  - `notes` populated for inferred pages and clamped ranges

The output validates against `docs/OUTLINE_SCHEMA.json` and can be piped
directly to `iiif-utils outline-import`.

USAGE:

    python3 resolve_outline.py <db_path> <flat.json> [-o nested.json]
    cat flat.json | python3 resolve_outline.py <db_path> -

The script is idempotent and read-only against the db.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def _build_page_lookup(
    db_path: Path,
) -> tuple[dict[int, int], dict[str, int], dict[int, str], int]:
    """Build the page→canvas lookups.

    Returns:
      arabic2canvas:  {int_page → leaf}  for digit-parseable book_page_number
      label2canvas:   {str_label → leaf} for ALL non-empty book_page_number,
                      including Roman numerals, letter pagination ('a', 'g'),
                      plate labels ('Planche 1', 'Tafel I'), etc.
      canvas2label:   {leaf → str_label}  reverse lookup, first non-empty value
                      per leaf, used to derive printed_page_end from canvas_end
      max_leaf
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    arabic2canvas: dict[int, int] = {}
    label2canvas: dict[str, int] = {}
    canvas2label: dict[int, str] = {}
    for r in conn.execute(
        "SELECT leaf_num, book_page_number FROM page_numbers "
        "WHERE book_page_number IS NOT NULL AND book_page_number != '' "
        "ORDER BY leaf_num"
    ):
        leaf, label = r[0], r[1]
        # arabic numeric lookup (used by integer flat_entries and
        # linear-extrapolation fallback)
        if label.isdigit():
            arabic2canvas.setdefault(int(label), leaf)
        # string label lookup — accepts the verbatim label, case-folded
        # variants for Roman numeral ambiguity ("vii" vs "VII")
        label2canvas.setdefault(label, leaf)
        label2canvas.setdefault(label.upper(), leaf)
        label2canvas.setdefault(label.lower(), leaf)
        # reverse lookup — first occurrence per leaf wins
        canvas2label.setdefault(leaf, label)
    row = conn.execute("SELECT MAX(leaf_num) FROM page_numbers").fetchone()
    max_leaf = row[0] if row and row[0] is not None else -1
    conn.close()
    if not label2canvas:
        raise SystemExit(
            f"{db_path}: page_numbers table has no non-empty book_page_number values"
        )
    return arabic2canvas, label2canvas, canvas2label, max_leaf


def _make_resolver(
    arabic2canvas: dict[int, int],
    label2canvas: dict[str, int],
    max_leaf: int,
):
    """Return (resolve(page), was_inferred(page)) closures.

    Accepts either an integer (arabic page) or a string (Roman, letter,
    plate label, or stringified arabic). Integers and digit-only strings
    use the arabic lookup with linear-extrapolation fallback for OCR misses.
    Non-numeric strings (Roman, letter, plate-labels) require an exact match
    in `label2canvas`; no extrapolation since there's no integer sequence
    to interpolate within.
    """
    anchors = sorted(arabic2canvas.items())
    inferred: set[object] = set()  # tracks anything resolved via extrapolation

    def resolve(p: int | str) -> int:
        # Normalize: integer-as-string ("7") → int; everything else stays str
        if isinstance(p, str) and p.isdigit():
            p = int(p)

        if isinstance(p, int):
            if p in arabic2canvas:
                return arabic2canvas[p]
            # Linear extrapolation from the nearest arabic anchor at or below p.
            if not anchors:
                raise KeyError(p)
            lo_p, lo_leaf = anchors[0]
            for ap, al in anchors:
                if ap <= p:
                    lo_p, lo_leaf = ap, al
                else:
                    break
            leaf = lo_leaf + (p - lo_p)
            leaf = min(max(leaf, 0), max_leaf)
            inferred.add(p)
            return leaf

        # Non-numeric string: exact-match-only lookup with case fallbacks.
        for candidate in (p, p.upper(), p.lower()):
            if candidate in label2canvas:
                return label2canvas[candidate]
        raise KeyError(p)

    def was_inferred(p: int | str) -> bool:
        return p in inferred

    return resolve, was_inferred


def _assign_printed_page_ends_int(
    flat: list[dict[str, Any]], parent_end: int
) -> None:
    """Compute printed_page_end for entries whose printed_page is an integer.

    Rule: an entry's printed_page_end is one less than the next same-or-lower-
    level entry's printed_page, falling back to parent_end for the last sibling.
    For mixed integer/string sequences, only adjacent integer pairs use this
    rule; otherwise the end is left unset (filled in later from canvas_end via
    the reverse lookup).
    """
    n = len(flat)
    for i, e in enumerate(flat):
        if not isinstance(e["printed_page"], int):
            # leave for canvas-derived backfill
            continue
        level = e["level"]
        j = i + 1
        while j < n and flat[j]["level"] > level:
            j += 1
        next_p = flat[j].get("printed_page") if j < n else None
        if isinstance(next_p, int):
            end_p = next_p - 1
        else:
            end_p = parent_end
        if end_p < e["printed_page"]:
            end_p = e["printed_page"]
        e["printed_page_end"] = end_p


def _build_tree(
    flat: list[dict[str, Any]],
    resolve,
    was_inferred,
    canvas2label: dict[int, str],
    max_leaf: int,
) -> list[dict[str, Any]]:
    """Turn the flat list into a nested tree, attaching canvas indices and notes.

    `printed_page_end` is taken from the entry if already set (integer path);
    otherwise derived from `canvas_end` via the reverse lookup. This handles
    mixed arabic/Roman/letter sequences uniformly: the canvas index is always
    integer-monotonic, so its bounds are unambiguous, and the printed label
    at that canvas is whatever the source actually printed there.
    """
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []  # (level, node)

    # First pass: compute canvas_start / canvas_end from printed_page (start)
    # using the same next-same-or-lower-level rule for canvas_end. The very
    # last entry at any level whose successor doesn't exist gets max_leaf as
    # its end — its range extends to the end of the book.
    n = len(flat)
    canvases: list[tuple[int, int]] = []  # (cs, ce) per entry in order
    for i, e in enumerate(flat):
        cs = resolve(e["printed_page"])
        level = e["level"]
        j = i + 1
        while j < n and flat[j]["level"] > level:
            j += 1
        if j < n:
            ce = resolve(flat[j]["printed_page"]) - 1
        else:
            ce = max_leaf  # last at its level → extend to end of book
        if ce < cs:
            ce = cs
        canvases.append((cs, ce))

    for i, e in enumerate(flat):
        cs, ce = canvases[i]
        p_start = e["printed_page"]
        # printed_page_end: prefer the explicit value if already set
        # (integer path filled by _assign_printed_page_ends_int);
        # otherwise derive from canvas_end via reverse lookup
        p_end = e.get("printed_page_end")
        if p_end is None:
            p_end = canvas2label.get(ce, p_start)

        node: dict[str, Any] = {
            "level": e["level"],
            "title": e["title"],
            "canvas_start": cs,
            "canvas_end": ce,
            "printed_page_start": p_start,
            "printed_page_end": p_end,
            "children": [],
        }
        notes: list[str] = []
        if was_inferred(p_start):
            notes.append(
                f"page {p_start!r} → canvas {cs} inferred (missing from page_numbers)"
            )
        if e.get("notes"):
            notes.append(str(e["notes"]))
        if notes:
            node["notes"] = "; ".join(notes)

        while stack and stack[-1][0] >= e["level"]:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
        stack.append((e["level"], node))

    return roots


def _clamp_same_canvas_siblings(entries: list[dict[str, Any]]) -> None:
    """Walk siblings; if a sibling's canvas_end < canvas_start, clamp & note."""
    for e in entries:
        if e["canvas_end"] < e["canvas_start"]:
            msg = "shares canvas with next sibling; range clamped to single canvas"
            e["notes"] = f"{e['notes']}; {msg}" if e.get("notes") else msg
            e["canvas_end"] = e["canvas_start"]
            e["printed_page_end"] = e["printed_page_start"]
        _clamp_same_canvas_siblings(e.get("children") or [])


def _extend_parent_to_cover_children(node: dict[str, Any]) -> tuple[int, int]:
    """Bottom-up: a parent's canvas_end must be >= every descendant's canvas_end.

    Necessary when the last child of a section shares its end canvas with the
    parent's next sibling — the parent's computed canvas_end would be one less
    than the last child's canvas_start, which violates the validator's
    "children within parent range" rule.
    """
    cs, ce = node["canvas_start"], node["canvas_end"]
    for c in node["children"]:
        child_cs, child_ce = _extend_parent_to_cover_children(c)
        ce = max(ce, child_ce)
    node["canvas_end"] = ce
    return cs, ce


def _strip_empty_children(node: dict[str, Any]) -> None:
    """Remove the `children` key when empty — keeps output JSON compact."""
    if not node.get("children"):
        node.pop("children", None)
        return
    for c in node["children"]:
        _strip_empty_children(c)


def resolve(payload: dict[str, Any], db_path: Path) -> dict[str, Any]:
    """Top-level entry point. Pure function; does not mutate input."""
    flat = [dict(e) for e in payload["flat_entries"]]  # copy
    arabic2canvas, label2canvas, canvas2label, max_leaf = _build_page_lookup(db_path)
    resolve_p, was_inferred = _make_resolver(arabic2canvas, label2canvas, max_leaf)

    last_page = max(arabic2canvas) if arabic2canvas else 0
    _assign_printed_page_ends_int(flat, last_page)

    roots = _build_tree(flat, resolve_p, was_inferred, canvas2label, max_leaf)
    _clamp_same_canvas_siblings(roots)
    for r in roots:
        _extend_parent_to_cover_children(r)
    for r in roots:
        _strip_empty_children(r)

    return {"work": payload["work"], "entries": roots}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db_path", type=Path, help="path to the work's sqlite index")
    ap.add_argument("flat_path", type=str, help="flat-JSON input file, or - for stdin")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="output nested-JSON path (default: stdout)")
    args = ap.parse_args(argv)

    if args.flat_path == "-":
        payload = json.loads(sys.stdin.read())
    else:
        payload = json.loads(Path(args.flat_path).read_text())

    expected_work = args.db_path.stem
    if payload.get("work") != expected_work:
        print(
            f"WARNING: payload.work = {payload.get('work')!r} but db filename "
            f"stem = {expected_work!r}; using payload value",
            file=sys.stderr,
        )

    result = resolve(payload, args.db_path)

    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output)
        print(
            f"wrote {args.output} ({sum(1 + _count(e.get('children', [])) for e in result['entries'])} entries)",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(output)
    return 0


def _count(entries: list[dict[str, Any]]) -> int:
    return sum(1 + _count(e.get("children", [])) for e in entries)


if __name__ == "__main__":
    raise SystemExit(main())
