"""`derived_outline` — synthesized navigation outline per work.

Each row is a self-contained entry: a title plus a canvas range. `parent_id`
links to a parent entry (for hierarchy) but is not load-bearing for ordering
or boundary computation; rows carry `canvas_start` / `canvas_end` explicitly.

This is a *derived* artifact, not a transcription of the printed TOC.
Entries may come from the TOC, from per-plate caption extraction, from
typographic detection, from IIIF manifest ranges, or from manual correction.
Per-row caveats live in the freeform `notes` column.

See `docs/OUTLINE.md` for the user-facing description and the import payload
format.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import sqlite_utils

OUTLINE_TABLE = "derived_outline"


def ensure_table(db: sqlite_utils.Database) -> None:
    """Create `derived_outline` if it doesn't exist. Idempotent."""
    if OUTLINE_TABLE in db.table_names():
        return
    db.executescript(
        """
        CREATE TABLE derived_outline (
          id                 INTEGER PRIMARY KEY,
          level              INTEGER NOT NULL,
          parent_id          INTEGER REFERENCES derived_outline(id),
          title              TEXT    NOT NULL,
          printed_page_start TEXT,
          printed_page_end   TEXT,
          canvas_start       INTEGER NOT NULL,
          canvas_end         INTEGER NOT NULL,
          notes              TEXT
        );
        CREATE INDEX ix_outline_canvas ON derived_outline(canvas_start);
        CREATE INDEX ix_outline_parent ON derived_outline(parent_id);
        """
    )


def work_id(db: sqlite_utils.Database) -> str | None:
    """Return the canonical work id for a db.

    The work id is the sqlite filename stem (e.g. `bjsh27ua` for
    `bjsh27ua.sqlite`). This is the provider-agnostic identifier we use
    across the corpus — Wellcome single-manifest works name their files
    after `catalogue_id`, Heidelberg names them after
    `identifier:heidelberg_diglit`, and Collection children follow a
    `<parent>_v<N>` convention. In every case the filename stem is the
    canonical id.

    Provider-specific metadata keys (`catalogue_id`, etc.) are stored
    pass-through for human reference, but they're absent on Wellcome
    Collection-child dbs — which is why we don't rely on them.
    """
    row = db.execute("PRAGMA database_list").fetchone()
    if row and row[2]:
        return Path(cast(str, row[2])).stem
    return None


def max_canvas(db: sqlite_utils.Database) -> int:
    """Return max(leaf_num) from page_numbers, or -1 if empty."""
    row = db.execute("SELECT MAX(leaf_num) FROM page_numbers").fetchone()
    return row[0] if row and row[0] is not None else -1


def validate_payload(
    payload: Any, *, expected_work: str, max_canvas_idx: int
) -> list[str]:
    """Return a list of validation error strings. Empty list = payload is OK."""
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["payload must be a JSON object"]

    work = payload.get("work")
    if work != expected_work:
        errors.append(
            f"payload.work = {work!r} does not match db work id "
            f"= {expected_work!r}"
        )

    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("payload.entries must be a non-empty array")
        return errors

    flat_canvas_starts: list[int] = []
    flat_titles: list[str] = []

    def walk(node: Any, depth: int, parent_range: tuple[int, int] | None,
             path: str) -> None:
        if not isinstance(node, dict):
            errors.append(f"{path}: entry must be an object (got {type(node).__name__})")
            return

        title = node.get("title")
        if not isinstance(title, str) or not title:
            errors.append(f"{path}: title must be a non-empty string")

        for required in ("level", "canvas_start", "canvas_end"):
            if required not in node:
                errors.append(f"{path} ({title!r}): missing required field {required!r}")

        level = node.get("level")
        if isinstance(level, int) and level != depth:
            errors.append(
                f"{path} ({title!r}): level={level} but nesting depth={depth}"
            )

        cs_raw = node.get("canvas_start")
        ce_raw = node.get("canvas_end")
        valid_range = isinstance(cs_raw, int) and isinstance(ce_raw, int)
        child_range: tuple[int, int] | None = None
        if valid_range:
            cs: int = cs_raw  # type: ignore[assignment]
            ce: int = ce_raw  # type: ignore[assignment]
            if ce < cs:
                errors.append(
                    f"{path} ({title!r}): canvas_end={ce} < canvas_start={cs}"
                )
            if cs < 0 or ce > max_canvas_idx:
                errors.append(
                    f"{path} ({title!r}): canvas range [{cs}, {ce}] "
                    f"outside work extent [0, {max_canvas_idx}]"
                )
            if parent_range is not None:
                ps, pe = parent_range
                if cs < ps or ce > pe:
                    errors.append(
                        f"{path} ({title!r}): child range [{cs}, {ce}] "
                        f"not within parent [{ps}, {pe}]"
                    )
            flat_canvas_starts.append(cs)
            flat_titles.append(str(title) if title else "")
            child_range = (cs, ce)

        for ppk in ("printed_page_start", "printed_page_end"):
            v = node.get(ppk)
            if v is not None and not isinstance(v, (int, str)):
                errors.append(
                    f"{path} ({title!r}): {ppk} must be int, string, or null"
                )
            if isinstance(v, str) and not v.strip():
                errors.append(f"{path} ({title!r}): {ppk} must not be empty string")

        notes = node.get("notes")
        if notes is not None and not isinstance(notes, str):
            errors.append(f"{path} ({title!r}): notes must be string or null")

        children = node.get("children")
        if children is None:
            children = []
        if not isinstance(children, list):
            errors.append(f"{path} ({title!r}): children must be an array")
            return

        for idx, child in enumerate(children):
            walk(child, depth + 1, child_range, f"{path}/children[{idx}]")

    for idx, entry in enumerate(entries):
        walk(entry, 0, None, f"entries[{idx}]")

    for i in range(1, len(flat_canvas_starts)):
        if flat_canvas_starts[i] < flat_canvas_starts[i - 1]:
            errors.append(
                f"flattened canvas_start sequence not monotonic at position {i}: "
                f"entry {flat_titles[i]!r} (canvas_start={flat_canvas_starts[i]}) "
                f"comes after entry {flat_titles[i - 1]!r} "
                f"(canvas_start={flat_canvas_starts[i - 1]})"
            )

    return errors


def count_entries(entries: list[dict[str, Any]]) -> int:
    """Total entries including nested children."""
    n = 0
    for e in entries:
        n += 1
        n += count_entries(e.get("children") or [])
    return n


def insert_tree(
    db: sqlite_utils.Database,
    entries: list[dict[str, Any]],
    parent_id: int | None = None,
) -> int:
    """Insert a tree of entries, returning the row count.

    Walks top-down so that parents are inserted before children and each
    child's `parent_id` references the freshly-assigned parent id.
    """
    n = 0
    for node in entries:
        row = {
            "level": node["level"],
            "parent_id": parent_id,
            "title": node["title"],
            "printed_page_start": node.get("printed_page_start"),
            "printed_page_end": node.get("printed_page_end"),
            "canvas_start": node["canvas_start"],
            "canvas_end": node["canvas_end"],
            "notes": node.get("notes"),
        }
        table = cast(sqlite_utils.db.Table, db[OUTLINE_TABLE])
        result = table.insert(row)
        new_id = cast(int, result.last_pk)
        n += 1
        children = node.get("children") or []
        if children:
            n += insert_tree(db, children, parent_id=new_id)
    return n
