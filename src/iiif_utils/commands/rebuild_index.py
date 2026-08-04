"""`iiif-utils rebuild-index` — refresh an index in place.

Two levels:

  - default: drop and recreate the FTS5 tables. No network.
  - `--refetch`: re-fetch and re-parse the OCR source, rewriting
    `text_blocks`, `page_words` and the image dimensions on
    `page_numbers`, then rebuild FTS.

`--refetch` exists because `create-index` writes a fresh file and would
therefore discard a book's `derived_outline` — and those outlines
represent real work (tens of thousands of hand-checked entries across
the corpus). This is the upgrade path for indexes built before word
geometry: it adds `page_words` while leaving outlines, document
metadata, ranges and the file manifest untouched.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from iiif_utils.config import load_config
from iiif_utils.core import database as db_mod
from iiif_utils.core import http as http_
from iiif_utils.core import manifest as manifest_mod
from iiif_utils.utils.logger import Logger

# Tables rebuilt by --refetch. Everything else in the file is preserved;
# derived_outline in particular is expensive to recreate.
_REFETCH_REWRITES = ("text_blocks", "page_words")


@click.command(name="rebuild-index")
@click.argument("index_path", type=click.Path(exists=True, path_type=Path))
@click.option("--refetch", is_flag=True, default=False,
              help="Re-fetch and re-parse the OCR source, rewriting "
                   "text_blocks and page_words. Preserves derived_outline "
                   "and metadata. Use this to add word geometry to an "
                   "index built before it existed.")
@click.option("-P", "--provider", default=None,
              help="Override the provider recorded in the index.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
@click.pass_context
def rebuild_index(ctx: click.Context, index_path: Path, refetch: bool,
                   provider: str | None, config_path: Path | None) -> None:
    """Drop and recreate the FTS5 indexes on an existing SQLite.

    Useful after upgrading iiif-utils or if the FTS tables drift out of
    sync with text_blocks. Does not touch the network unless --refetch
    is given.
    """
    verbose = bool(ctx.obj.get("verbose")) if ctx.obj else False
    log = Logger(verbose=verbose)
    db = db_mod.open_db(index_path)

    if refetch:
        _refetch_ocr(db, provider=provider, config_path=config_path, log=log)

    log.info(f"rebuilding FTS in {index_path}")
    db_mod.build_fts(db)
    size_mb = index_path.stat().st_size / 1024 / 1024
    click.echo(f"FTS rebuilt in {index_path}  ({size_mb:.1f} MB)")


def _refetch_ocr(db: Any, *, provider: str | None,
                  config_path: Path | None, log: Logger) -> None:
    """Re-parse the OCR source and rewrite the text-derived tables."""
    # Imported here so the no-network default path stays light.
    from iiif_utils.commands.create_index import (
        _fetch_page_number_overrides,
        _parse_altos,
        _parse_monolithic_ocr,
    )
    from iiif_utils.providers import resolve

    if "index_metadata" not in db.table_names():
        raise click.ClickException(
            "This index has no index_metadata, so there is no record of "
            "where it came from. Use `migrate-index` first if it is an "
            "ia-utils file.")
    meta = {r["key"]: r["value"] for r in db["index_metadata"].rows}
    ref = meta.get("manifest_url")
    if not ref:
        raise click.ClickException(
            "This index records no manifest_url, so there is nothing to "
            "re-fetch from. Build a fresh index with `create-index`.")
    if meta.get("index_mode") == "image_only":
        raise click.ClickException(
            "This index was built with --no-ocr; re-fetching would change "
            "what it is. Run `create-index` without --no-ocr instead.")

    cfg = load_config(config_path)
    cfg_http = cfg.get("http", {})
    cache_dir = Path(cfg_http.get("cache_dir", "./.iiif-cache")).expanduser()

    ref_obj = resolve(ref, cfg=cfg,
                       explicit_provider=provider or meta.get("provider"),
                       cache_dir=cache_dir)
    log.info(f"re-fetching OCR for {ref_obj.manifest_url} "
             f"(provider={ref_obj.provider_key})")

    manifest = (ref_obj.manifest_payload
                if ref_obj.manifest_payload is not None
                else http_.fetch_json(ref_obj.manifest_url, cfg_http=cfg_http,
                                        cache_dir=cache_dir))
    canvases = manifest_mod.canvases(manifest)
    if not canvases:
        raise click.ClickException(
            f"{ref_obj.manifest_url} now has 0 canvases — refusing to wipe "
            f"text_blocks on the strength of that.")

    leaf_to_canvas: dict[int, int] = {}
    tb_rows, _il_rows, image_dims, pw_rows = _parse_altos(
        canvases, cfg_http=cfg_http, cache_dir=cache_dir, log=log)
    if not tb_rows:
        mono = _parse_monolithic_ocr(
            ref_obj.extra_metadata, canvases,
            cfg_http=cfg_http, cache_dir=cache_dir, log=log)
        if mono is not None:
            tb_rows, image_dims, _source, pw_rows, leaf_to_canvas = mono

    if not tb_rows:
        raise click.ClickException(
            "Re-fetch produced no text. Leaving the existing tables alone "
            "rather than replacing them with nothing.")

    existing = set(db.table_names())
    n_outline = (db["derived_outline"].count
                 if "derived_outline" in existing else 0)
    for table in _REFETCH_REWRITES:
        if table in existing:
            db[table].drop()
    db_mod.write_text_blocks(db, tb_rows)
    if pw_rows:
        db_mod.write_page_words(db, pw_rows)

    # Image-native dims may be newly available (or corrected). Update in
    # place so book_page_number and the canvas columns are undisturbed.
    if image_dims and "page_numbers" in existing:
        for leaf, (w, h) in image_dims.items():
            db.execute(
                "UPDATE page_numbers SET image_width = ?, image_height = ? "
                "WHERE leaf_num = ?", (w, h, leaf))

    # Providers with an authoritative page-number map: refresh it too, so
    # an index built before that fix picks up correct printed pages.
    pn_override = _fetch_page_number_overrides(
        ref_obj.extra_metadata, cfg_http=cfg_http, cache_dir=cache_dir,
        log=log)
    if pn_override and leaf_to_canvas:
        pn_override = {leaf_to_canvas[leaf]: vals
                       for leaf, vals in pn_override.items()
                       if leaf in leaf_to_canvas}
    if pn_override and "page_numbers" in existing:
        for leaf, vals in pn_override.items():
            db.execute(
                "UPDATE page_numbers SET book_page_number = ?, "
                "confidence = ?, pageProb = ?, wordConf = ? "
                "WHERE leaf_num = ?",
                (vals["book_page_number"], vals["confidence"],
                 vals["pageProb"], vals["wordConf"], leaf))

    # An outline's canvas_start/canvas_end were resolved through the
    # page_numbers that existed when it was built. If this rebuild changes
    # the leaf mapping, those references now point at the wrong pages —
    # and would be the only thing left wrong, which is harder to notice
    # than the original fault. Say so rather than silently keeping them.
    if n_outline and leaf_to_canvas:
        prev = {r["key"]: r["value"] for r in db["index_metadata"].rows}
        if prev.get("leaf_mapping") != "ia_file_number":
            log.warn(
                f"derived_outline has {n_outline} rows resolved under the "
                f"OLD leaf mapping; its canvas ranges are probably shifted. "
                f"Re-run the outline import for this book, or clear it with "
                f"`outline-clear`.")

    idx_updates = {"rebuilt_at": db_mod.now_iso()}
    if pw_rows:
        from iiif_utils.core.wordgeom import WORDS_SCHEMA
        idx_updates["words_schema"] = WORDS_SCHEMA
    if leaf_to_canvas:
        idx_updates["leaf_mapping"] = "ia_file_number"
    db_mod.write_index_metadata(db, idx_updates)

    click.echo(f"  text_blocks:     {len(tb_rows):,} (rewritten)")
    if pw_rows:
        click.echo(f"  page_words:      {len(pw_rows):,} pages")
    if pn_override:
        click.echo(f"  page_numbers:    {len(pn_override):,} refreshed "
                   f"from provider")
    if n_outline:
        click.echo(f"  derived_outline: {n_outline:,} rows (preserved)")
