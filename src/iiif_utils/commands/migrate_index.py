"""`iiif-utils migrate-index` — read an ia-utils index into this dialect.

Phase 3 of the ia-utils convergence. Existing ia-utils indexes are
close to ours but not identical, which is what made a mixed bookshelf
awkward: different `document_metadata` shape, a different text_blocks
primary key, and no `index_metadata` to say what a file even is.

This converts one in place-of, never in-place: it always writes a NEW
file and never touches the source.

**Scope.** This is a schema translation, not a re-index. It carries
over everything the source actually holds — text, page numbers,
confidence, file manifest — and stamps `index_metadata` so a shelf
scanner can recognize it. It cannot invent what ia-utils never stored:

  - **Canvas / image columns stay NULL.** ia-utils addressed images
    through IA's download endpoints, not IIIF image services, so
    `get-page` and friends will not work against a migrated index.
  - **No `page_words`.** Word geometry has to come from re-parsing the
    OCR source, so layout modes are unavailable.

For either of those, rebuild from the identifier instead — the
migrated `index_metadata.identifier:ia` tells you what to pass:

    iiif-utils create-index https://archive.org/details/<identifier>

Migration is the cheap path for books you only need to search.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.core import database as db_mod
from iiif_utils.utils.logger import Logger

# ia-utils `document_metadata` is one wide row; ours is key/value. These
# are the columns worth carrying over, mapped to our key names.
_DOC_COLUMNS = {
    "ia_identifier": "identifier:ia",
    "title": "title",
    "creator_primary": "creator",
    "creator_secondary": "creator_secondary",
    "publisher": "publisher",
    "publication_date": "publication_date",
    "language": "language",
    "collection": "collection",
    "subject": "subject",
    "mediatype": "mediatype",
    "contributor": "contributor",
    "description": "description",
    "ark_identifier": "identifier:ark",
    "oclc_id": "identifier:oclc",
    "openlibrary_edition": "identifier:openlibrary_edition",
    "openlibrary_work": "identifier:openlibrary_work",
    "scan_quality_ppi": "scan_quality_ppi",
    "scan_camera": "scan_camera",
    "scan_date": "scan_date",
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


@click.command(name="migrate-index")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Output path. Default: <source-stem>_iiif.sqlite "
                   "alongside the source. Never overwrites the source.")
@click.pass_context
def migrate_index(ctx: click.Context, source: Path,
                   output_path: Path | None) -> None:
    """Convert an ia-utils index to the iiif-utils dialect (new file)."""
    verbose = bool(ctx.obj.get("verbose")) if ctx.obj else False
    log = Logger(verbose=verbose)

    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    have = _tables(src)
    if "text_blocks" not in have:
        raise click.ClickException(
            f"{source} has no text_blocks table — not an ia-utils index?")
    if "index_metadata" in have:
        raise click.ClickException(
            f"{source} already carries index_metadata — it looks like an "
            f"iiif-utils index, so there is nothing to migrate.")

    if output_path is None:
        output_path = source.with_name(f"{source.stem}_iiif.sqlite")
    if output_path.resolve() == source.resolve():
        raise click.ClickException(
            "Refusing to write over the source index. Migration always "
            "produces a new file.")
    if output_path.exists():
        raise click.ClickException(
            f"{output_path} already exists — remove it or pass -o.")

    log.info(f"migrating {source} → {output_path}")
    db = db_mod.open_db(output_path)

    # --- document_metadata: wide row → key/value --------------------------
    doc_md: dict[str, str] = {}
    identifier = ""
    if "document_metadata" in have:
        row = src.execute("SELECT * FROM document_metadata LIMIT 1").fetchone()
        if row is not None:
            present = set(row.keys())
            for col, key in _DOC_COLUMNS.items():
                if col in present and row[col] not in (None, ""):
                    doc_md[key] = str(row[col])
            identifier = doc_md.get("identifier:ia", "")
    if identifier:
        doc_md.setdefault(
            "ia_details_url", f"https://archive.org/details/{identifier}")
    db_mod.write_document_metadata(db, doc_md)

    # --- text_blocks: hocr_id → alto_id, derive word_count ----------------
    tb_cols = _columns(src, "text_blocks")
    tb_rows: list[dict[str, Any]] = []
    for r in src.execute("SELECT * FROM text_blocks "
                          "ORDER BY page_id, block_number"):
        text = r["text"] or ""
        tb_rows.append({
            "page_id": r["page_id"],
            "block_number": r["block_number"],
            "block_type": r["block_type"] if "block_type" in tb_cols else None,
            "language": r["language"] if "language" in tb_cols else None,
            "text_direction": (r["text_direction"]
                                if "text_direction" in tb_cols else None),
            "bbox_x0": r["bbox_x0"], "bbox_y0": r["bbox_y0"],
            "bbox_x1": r["bbox_x1"], "bbox_y1": r["bbox_y1"],
            "text": text,
            "line_count": r["line_count"] if "line_count" in tb_cols else None,
            # ia-utils didn't store word_count; derive it rather than
            # leaving a column our readers expect empty.
            "word_count": len(text.split()),
            "length": r["length"] if "length" in tb_cols else len(text),
            "avg_confidence": (r["avg_confidence"]
                                if "avg_confidence" in tb_cols else None),
            "avg_font_size": (r["avg_font_size"]
                               if "avg_font_size" in tb_cols else None),
            "parent_carea_id": (r["parent_carea_id"]
                                 if "parent_carea_id" in tb_cols else None),
            # ia-utils' hOCR element id lands in our generic id column.
            "alto_id": r["hocr_id"] if "hocr_id" in tb_cols else None,
        })
    if tb_rows:
        db_mod.write_text_blocks(db, tb_rows)

    # --- page_numbers: canvas/image columns unavailable (see module doc) --
    pn_rows: list[dict[str, Any]] = []
    if "page_numbers" in have:
        pn_cols = _columns(src, "page_numbers")
        for r in src.execute("SELECT * FROM page_numbers ORDER BY leaf_num"):
            pn_rows.append({
                "leaf_num": r["leaf_num"],
                "book_page_number": r["book_page_number"],
                "confidence": (r["confidence"]
                                if "confidence" in pn_cols else None),
                "pageProb": r["pageProb"] if "pageProb" in pn_cols else None,
                "wordConf": r["wordConf"] if "wordConf" in pn_cols else None,
                "canvas_id": None, "canvas_label": None, "image_id": None,
                "image_service_url": None, "image_api_version": None,
                "width": None, "height": None,
                "image_width": None, "image_height": None,
            })
        if pn_rows:
            db_mod.write_page_numbers(db, pn_rows)

    # --- archive_files ----------------------------------------------------
    af_rows: list[dict[str, Any]] = []
    if "archive_files" in have:
        used: set[str] = set()
        for r in src.execute("SELECT * FROM archive_files"):
            fname = db_mod.disambiguate_filename(r["filename"] or "", used)
            used.add(fname)
            af_rows.append({
                "filename": fname,
                "format": r["format"],
                "size_bytes": r["size_bytes"],
                "source_type": r["source_type"],
                "md5_checksum": r["md5_checksum"],
                "sha1_checksum": r["sha1_checksum"],
                "crc32_checksum": r["crc32_checksum"],
                "download_url": r["download_url"],
            })
        db_mod.write_archive_files(db, af_rows)

    # --- index_metadata: what makes the file self-describing --------------
    from iiif_utils import __version__
    idx_md = {
        "slug": output_path.stem,
        "created_at": db_mod.now_iso(),
        "index_mode": "migrated",
        "ocr_source": "hocr",          # ia-utils indexes are hOCR/DjVu-derived
        "ocr_shape": "monolithic",
        "provider": "ia",
        "provider_kind": "iiif",
        "iiif_utils_version": __version__,
        "migrated_from": str(source.name),
        "migrated_tool": "ia-utils",
        # Loud, because a migrated index silently lacks image access.
        "migration_limits": (
            "no canvas/image columns (get-page unavailable) and no "
            "page_words (layout modes unavailable); rebuild with "
            "create-index for either"),
    }
    if identifier:
        idx_md["manifest_url"] = (
            f"https://iiif.archive.org/iiif/{identifier}/manifest.json")
    db_mod.write_index_metadata(db, idx_md)

    log.info("building FTS indexes")
    db_mod.build_fts(db)

    size_mb = output_path.stat().st_size / 1024 / 1024
    click.echo(f"\nMigrated: {output_path}  ({size_mb:.1f} MB)")
    click.echo(f"  source:        {source}  (unchanged)")
    click.echo(f"  text_blocks:   {len(tb_rows):,}")
    click.echo(f"  page_numbers:  {len(pn_rows):,}")
    click.echo(f"  archive_files: {len(af_rows):,}")
    click.echo("\nSearch works. Images and layout modes do not — for those, "
               "rebuild:")
    ref = (f"https://archive.org/details/{identifier}" if identifier
           else "<archive.org details URL>")
    click.echo(f"  iiif-utils create-index {ref}")
