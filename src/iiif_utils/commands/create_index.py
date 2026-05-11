"""`iiif-utils create-index` — fetch a manifest + ALTO and write SQLite."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import click

from iiif_utils.config import load_config
from iiif_utils.core import alto as alto_mod
from iiif_utils.core import database as db_mod
from iiif_utils.core import health as health_mod
from iiif_utils.core import http as http_
from iiif_utils.core import manifest as manifest_mod
from iiif_utils.providers import resolve
from iiif_utils.utils.logger import Logger
from iiif_utils.utils.slug import slugify


@click.command(name="create-index")
@click.argument("ref")
@click.option("-d", "--output-dir", "output_dir",
              type=click.Path(file_okay=False, path_type=Path),
              default=Path("."),
              help="Directory for the resulting SQLite. Default: cwd.")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path),
              default=None,
              help="Exact output path (overrides -d).")
@click.option("-P", "--provider", default=None,
              help="Override provider (e.g. wellcome).")
@click.option("--allow-empty", is_flag=True, default=False,
              help="Build a metadata-only index even if manifest has 0 canvases.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
@click.pass_context
def create_index(ctx: click.Context, ref: str, output_dir: Path,
                  output_path: Path | None, provider: str | None,
                  allow_empty: bool,
                  config_path: Path | None) -> None:
    """Build a SQLite index for a IIIF manifest."""
    verbose = bool(ctx.obj.get("verbose")) if ctx.obj else False
    log = Logger(verbose=verbose)

    cfg = load_config(config_path)
    cfg_http = cfg.get("http", {})
    cache_dir = Path(cfg_http.get("cache_dir", "./.iiif-cache")).expanduser()

    ref_obj = resolve(ref, cfg=cfg, explicit_provider=provider,
                       cache_dir=cache_dir)
    log.info(f"resolved → {ref_obj.manifest_url} (provider={ref_obj.provider_key})")

    # Per-provider config overrides — currently we use this for LoC's
    # tighter rate-limit (max_concurrency).
    provider_cfg = (cfg.get("providers") or {}).get(ref_obj.provider_key) or {}
    for k in ("max_concurrency", "max_retries", "retry_base_seconds"):
        if k in provider_cfg:
            cfg_http[k] = provider_cfg[k]

    if ref_obj.manifest_payload is not None:
        # Provider supplied a synthesized manifest (LoC); use it directly.
        manifest = ref_obj.manifest_payload
    else:
        manifest = http_.fetch_json(ref_obj.manifest_url, cfg_http=cfg_http,
                                      cache_dir=cache_dir)

    mtype = manifest_mod.manifest_type(manifest)
    if mtype == "Collection":
        raise click.ClickException(
            f"{ref_obj.manifest_url} is a Collection of "
            f"{len(manifest.get('items', []))} manifests. v1 indexes one "
            f"manifest at a time; pass a child manifest URL."
        )

    canvases = manifest_mod.canvases(manifest)
    if not canvases and not allow_empty:
        raise click.ClickException(
            "Manifest has 0 canvases — bibliographic record only? "
            "Pass --allow-empty to build a metadata-only index anyway."
        )

    # Slug and output path
    title = manifest_mod.label_string(manifest.get("label")) or ref_obj.manifest_url
    bnum_match = re.search(r"/(b\d{7}[\dx])(?:$|[/?])", ref_obj.manifest_url)
    identifier = bnum_match.group(1) if bnum_match else slugify(ref_obj.manifest_url)[:30]
    slug = f"{ref_obj.provider_key}_{slugify(title, max_len=40)}_{identifier}"
    if output_path is None:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{slug}.sqlite"

    if output_path.exists():
        output_path.unlink()
    log.info(f"writing → {output_path}")
    db = db_mod.open_db(output_path)

    # --- health checks (surface in index_metadata + warn to stderr) ---------
    flags = health_mod.manifest_health(manifest)
    if flags.partial_digitization:
        log.warn(f"partial digitisation: {flags.partial_digitization}")
    if flags.contains_multiple_volumes:
        log.warn(f"multiple volumes concatenated: "
                 f"{flags.contains_multiple_volumes}")

    # --- document_metadata -------------------------------------------------
    doc_md: dict[str, str] = {}
    if title:
        doc_md["title"] = title
    if manifest.get("rights"):
        doc_md["rights"] = manifest["rights"]
    rs = manifest.get("requiredStatement")
    if rs:
        rs_val = manifest_mod.label_string(rs.get("value"))
        if rs_val:
            doc_md["required_statement"] = rs_val
    doc_md.update(manifest_mod.metadata_entries(manifest))
    doc_md.update(ref_obj.extra_metadata)
    db_mod.write_document_metadata(db, doc_md)

    # --- archive_files (manifest renderings) -------------------------------
    af_rows: list[dict[str, Any]] = []
    used_filenames: set[str] = set()
    for r in manifest_mod.renderings(manifest):
        base = r.url.rstrip("/").rsplit("/", 1)[-1]
        fname = db_mod.disambiguate_filename(base, used_filenames)
        used_filenames.add(fname)
        af_rows.append({
            "filename": fname,
            "format": r.format,
            "size_bytes": None,
            "source_type": "rendering",
            "md5_checksum": None,
            "sha1_checksum": None,
            "crc32_checksum": None,
            "download_url": r.url,
        })
    db_mod.write_archive_files(db, af_rows)

    # --- OCR parse first (so page_numbers can carry image-native dims) ----
    tb_rows: list[dict[str, Any]] = []
    il_rows: list[dict[str, Any]] = []
    image_dims: dict[int, tuple[int, int]] = {}
    n_alto_canvases = sum(1 for c in canvases if c.alto_url)
    n_text_canvases = sum(
        1 for c in canvases if not c.alto_url and c.text_url
    )
    if canvases:
        tb_rows, il_rows, image_dims = _parse_altos(
            canvases, cfg_http=cfg_http, cache_dir=cache_dir, log=log,
        )

    # --- index_metadata (after parse so we know the OCR provenance) --------
    from iiif_utils import __version__
    if n_alto_canvases > 0 and n_text_canvases > 0:
        ocr_source = "mixed"   # both ALTO and text fallback used
    elif n_alto_canvases > 0:
        ocr_source = "alto"
    elif n_text_canvases > 0:
        ocr_source = "text_plain"
    else:
        ocr_source = "none"
    idx_md = {
        "slug": slug,
        "created_at": db_mod.now_iso(),
        "index_mode": "alto",
        "ocr_source": ocr_source,
        "provider": ref_obj.provider_key,
        "provider_kind": "iiif",
        "manifest_url": ref_obj.manifest_url,
        "presentation_api_version": manifest_mod.presentation_version(manifest),
        "iiif_utils_version": __version__,
    }
    if flags.partial_digitization:
        idx_md["partial_digitization"] = flags.partial_digitization
    if flags.contains_multiple_volumes:
        idx_md["contains_multiple_volumes"] = flags.contains_multiple_volumes
    db_mod.write_index_metadata(db, idx_md)

    # ALTO-less / OCR-less warnings — fire even without -v
    if canvases and ocr_source == "none":
        log.warn(
            f"no per-canvas OCR found for any of {len(canvases)} canvases; "
            f"index will be image-only (text_blocks empty, no FTS hits). "
            f"Use `iiif-utils ocr-page` to run Tesseract on individual pages."
        )
    elif ocr_source == "text_plain":
        log.info(
            f"using plain-text fallback for OCR ({n_text_canvases} canvases); "
            f"text_blocks will have NULL bboxes (FTS still works)."
        )

    # --- page_numbers ------------------------------------------------------
    pn_rows: list[dict[str, Any]] = []
    for c in canvases:
        img_dim = image_dims.get(c.index)
        pn_rows.append({
            "leaf_num": c.index,
            "book_page_number": db_mod.book_page_from_label(c.label),
            "confidence": None,
            "pageProb": None,
            "wordConf": None,
            "canvas_id": c.canvas_id,
            "canvas_label": c.label,
            "image_id": c.image_id,
            "image_service_url": c.image_service_url,
            "image_api_version": c.image_api_version,
            "width": c.width,                # manifest canvas dims
            "height": c.height,
            "image_width": img_dim[0] if img_dim else None,   # ALTO Page dims
            "image_height": img_dim[1] if img_dim else None,  # = native image
        })
    if pn_rows:
        db_mod.write_page_numbers(db, pn_rows)

    if tb_rows:
        db_mod.write_text_blocks(db, tb_rows)
    if il_rows:
        db_mod.write_illustrations(db, il_rows)

    # --- ranges ------------------------------------------------------------
    range_entries = manifest_mod.ranges(manifest)
    if range_entries:
        canvas_id_to_idx = {c.canvas_id: c.index for c in canvases}
        range_rows: list[dict[str, Any]] = []
        for entry in range_entries:
            cidx: list[int] = []
            for cid in entry.canvas_ids:
                idx = canvas_id_to_idx.get(cid)
                if idx is not None:
                    cidx.append(idx)
            range_rows.append({
                "range_index": entry.index,
                "range_id": entry.range_id,
                "parent_range_id": entry.parent_id,
                "depth": entry.depth,
                "label": entry.label,
                "behavior": entry.behavior,
                "canvas_start": min(cidx) if cidx else None,
                "canvas_end": max(cidx) if cidx else None,
            })
        db_mod.write_ranges(db, range_rows)

    # --- manifest_raw ------------------------------------------------------
    db_mod.write_manifest_raw(db, json.dumps(manifest))

    # --- FTS ---------------------------------------------------------------
    log.info("building FTS indexes")
    db_mod.build_fts(db)

    # --- Summary ----------------------------------------------------------
    n_pages = db["page_numbers"].count if "page_numbers" in db.table_names() else 0
    n_blocks = db["text_blocks"].count if "text_blocks" in db.table_names() else 0
    n_illus = (db["illustrations"].count
               if "illustrations" in db.table_names() else 0)
    size_mb = output_path.stat().st_size / 1024 / 1024
    click.echo(f"\nIndex built: {output_path}  ({size_mb:.1f} MB)")
    click.echo(f"  canvases:      {n_pages}")
    click.echo(f"  text_blocks:   {n_blocks:,}")
    click.echo(f"  illustrations: {n_illus:,}")


def _parse_altos(canvases: list[Any], *, cfg_http: dict[str, Any],
                  cache_dir: Path, log: Logger,
                  ) -> tuple[list[dict[str, Any]],
                             list[dict[str, Any]],
                             dict[int, tuple[int, int]]]:
    """Fetch + parse per-canvas OCR.

    Returns (text_blocks rows, illustrations rows, {canvas_index:
    (image_width, image_height)}).

    For canvases with ALTO seeAlso: full bbox/illustration parsing.
    For canvases with only plain-text seeAlso (LoC's per-page .txt):
    one synthetic block per canvas, no bboxes, no illustrations.
    `image_width`/`image_height` come from ALTO `<Page>` and are NULL
    for plain-text-only canvases.
    """
    image_dims: dict[int, tuple[int, int]] = {}
    tb_rows: list[dict[str, Any]] = []
    il_rows: list[dict[str, Any]] = []

    alto_dir = cache_dir / "alto"
    text_dir = cache_dir / "text"
    alto_dir.mkdir(parents=True, exist_ok=True)

    alto_canvases = [c for c in canvases if c.alto_url]
    text_only_canvases = [
        c for c in canvases if not c.alto_url and c.text_url
    ]
    log.info(f"fetching {len(alto_canvases)} ALTO + "
             f"{len(text_only_canvases)} text-only files "
             f"(of {len(canvases)} canvases)")
    if not alto_canvases and not text_only_canvases:
        return tb_rows, il_rows, image_dims

    # --- ALTO branch -------------------------------------------------------
    if alto_canvases:
        urls = [c.alto_url for c in alto_canvases]
        fetched = asyncio.run(http_.fetch_many_bytes(
            urls, cfg_http=cfg_http, cache_dir=alto_dir, suffix=".alto.xml",
        ))
        n_parsed = 0
        for c in alto_canvases:
            content = fetched.get(c.alto_url)
            if not content:
                log.warn(f"no ALTO bytes for canvas {c.index}")
                continue
            try:
                page = alto_mod.parse_alto_bytes(content)
            except Exception as e:
                log.warn(f"parse error canvas {c.index}: {e}")
                continue
            n_parsed += 1
            if page.page_w and page.page_h:
                image_dims[c.index] = (page.page_w, page.page_h)
            for b in page.text_blocks:
                tb_rows.append({
                    "page_id": c.index,
                    "block_number": b.block_number,
                    "block_type": "ocr_textblock",
                    "language": None,
                    "text_direction": None,
                    "bbox_x0": b.bbox_x0, "bbox_y0": b.bbox_y0,
                    "bbox_x1": b.bbox_x1, "bbox_y1": b.bbox_y1,
                    "text": b.text,
                    "line_count": b.line_count,
                    "word_count": b.word_count,
                    "length": b.length,
                    "avg_confidence": None,
                    "avg_font_size": None,
                    "parent_carea_id": None,
                    "alto_id": b.alto_id,
                })
            for ill in page.illustrations:
                il_rows.append({
                    "page_id": c.index,
                    "illustration_number": ill.illustration_number,
                    "bbox_x0": ill.bbox_x0, "bbox_y0": ill.bbox_y0,
                    "bbox_x1": ill.bbox_x1, "bbox_y1": ill.bbox_y1,
                    "illustration_type": ill.illustration_type,
                    "alto_id": ill.alto_id,
                })
        log.info(f"parsed {n_parsed} ALTOs")

    # --- Plain-text fallback branch ----------------------------------------
    if text_only_canvases:
        text_dir.mkdir(parents=True, exist_ok=True)
        urls = [c.text_url for c in text_only_canvases]
        fetched = asyncio.run(http_.fetch_many_bytes(
            urls, cfg_http=cfg_http, cache_dir=text_dir, suffix=".txt",
        ))
        n_text = 0
        for c in text_only_canvases:
            content = fetched.get(c.text_url)
            if not content:
                continue
            try:
                text = content.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            if not text:
                continue
            n_text += 1
            tb_rows.append({
                "page_id": c.index,
                "block_number": 0,
                "block_type": "ocr_page",  # whole-page synthetic block
                "language": None,
                "text_direction": None,
                "bbox_x0": None, "bbox_y0": None,
                "bbox_x1": None, "bbox_y1": None,
                "text": text,
                "line_count": text.count("\n") + 1,
                "word_count": len(text.split()),
                "length": len(text),
                "avg_confidence": None,
                "avg_font_size": None,
                "parent_carea_id": None,
                "alto_id": None,
            })
        log.info(f"ingested {n_text} plain-text fallbacks")

    return tb_rows, il_rows, image_dims
