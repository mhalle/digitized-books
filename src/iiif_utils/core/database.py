"""SQLite schema + writers for IIIF indexes.

Mirrors `ia-utils` shape where possible; see docs/DESIGN.md §3 for the
full schema rationale. All tables created lazily by insert_all().
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import sqlite_utils


def _table(db: sqlite_utils.Database, name: str) -> sqlite_utils.db.Table:
    """sqlite-utils returns Table|View; narrow to Table for writes."""
    return cast(sqlite_utils.db.Table, db[name])

# Wellcome encodes unnumbered pages as a literal dash.
_DASH = re.compile(r"^-+$")


def book_page_from_label(label: str | None) -> str | None:
    """Map a canvas label string to a book_page_number value.

    Wellcome: '-' or empty → NULL; digits → kept verbatim (TEXT).
    Other providers may pass roman / folio / compound labels through;
    keep them as-is and let downstream consumers cope.
    """
    if label is None:
        return None
    s = label.strip()
    if not s or _DASH.match(s):
        return None
    return s


def open_db(path: Path) -> sqlite_utils.Database:
    return sqlite_utils.Database(str(path))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_index_metadata(db: sqlite_utils.Database, rows: dict[str, str]) -> None:
    _table(db, "index_metadata").insert_all(
        [{"key": k, "value": v} for k, v in rows.items()],
        pk="key", replace=True,
    )


def write_document_metadata(db: sqlite_utils.Database, rows: dict[str, str]) -> None:
    _table(db, "document_metadata").insert_all(
        [{"key": k, "value": v} for k, v in rows.items() if v is not None],
        pk="key", replace=True,
    )


def write_archive_files(db: sqlite_utils.Database, rows: list[dict[str, Any]]) -> None:
    """Each row needs at least filename + download_url. PK is filename."""
    if not rows:
        return
    _table(db, "archive_files").insert_all(rows, pk="filename", replace=True)


def write_page_numbers(db: sqlite_utils.Database, rows: list[dict[str, Any]]) -> None:
    _table(db, "page_numbers").insert_all(rows, pk="leaf_num", replace=True)


def write_text_blocks(db: sqlite_utils.Database, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    _table(db, "text_blocks").insert_all(
        rows, pk=("page_id", "block_number"), replace=True, batch_size=500,
    )


def write_illustrations(db: sqlite_utils.Database,
                         rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    _table(db, "illustrations").insert_all(
        rows, pk=("page_id", "illustration_number"), replace=True, batch_size=500,
    )


def write_ranges(db: sqlite_utils.Database, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    _table(db, "ranges").insert_all(rows, pk="range_index", replace=True)


def write_manifest_raw(db: sqlite_utils.Database, body: str,
                        etag: str | None = None) -> None:
    _table(db, "manifest_raw").insert_all([{
        "id": 1,
        "fetched_at": now_iso(),
        "etag": etag,
        "body": body,
    }], pk="id", replace=True)


def build_fts(db: sqlite_utils.Database) -> None:
    """Build text_blocks FTS5 + page-level pages_fts.

    Idempotent: drops and rebuilds.
    """
    # Block-level FTS via sqlite-utils
    db.executescript("""
        DROP TRIGGER IF EXISTS text_blocks_ai;
        DROP TRIGGER IF EXISTS text_blocks_ad;
        DROP TRIGGER IF EXISTS text_blocks_au;
        DROP TABLE IF EXISTS text_blocks_fts;
    """)
    if "text_blocks" in db.table_names():
        _table(db, "text_blocks").enable_fts(
            ["text"], create_triggers=True, replace=True,
            tokenize="porter unicode61",
        )

    # Page-level FTS: aggregate text per page
    db.executescript("""
        DROP TABLE IF EXISTS pages_fts;
        CREATE VIRTUAL TABLE pages_fts USING fts5(
            page_text, page_id UNINDEXED, tokenize="porter unicode61"
        );
    """)
    if "text_blocks" in db.table_names():
        db.executescript("""
            INSERT INTO pages_fts(rowid, page_text, page_id)
            SELECT
                ROW_NUMBER() OVER (ORDER BY page_id),
                group_concat(text, ' '),
                page_id
            FROM text_blocks
            GROUP BY page_id;
        """)


def disambiguate_filename(filename: str, existing: set[str]) -> str:
    """If filename is already used, append numeric suffix.

    Avoids the PK collision noted in experiments/morris_index (manifest
    PDF and plain-text both ended with `b21212600`).
    """
    if filename not in existing:
        return filename
    base, dot, ext = filename.rpartition(".")
    if not dot:
        base, ext = filename, ""
    n = 2
    while True:
        cand = f"{base}-{n}" + (f".{ext}" if ext else "")
        if cand not in existing:
            return cand
        n += 1
