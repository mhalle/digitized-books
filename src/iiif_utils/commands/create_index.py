"""`iiif-utils create-index` — fetch a manifest + ALTO and write SQLite."""
from __future__ import annotations

import asyncio
import json
import math
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
from iiif_utils.providers import internet_archive as ia_mod
from iiif_utils.providers import resolve
from iiif_utils.utils.logger import Logger
from iiif_utils.utils.slug import slugify


# Wellcome b-number, plus optional child-volume suffix (`b22396147_0003`,
# `b20416301_001`). Without the suffix every volume of a multi-volume
# Collection would collide on one filename.
_BNUM_IN_URL = re.compile(r"/(b\d{7}[\dx](?:_\d{3,4})?)(?:$|[/?])")

# Provider-supplied identifier keys, in preference order. Checked before
# falling back to the manifest URL, which slugifies into nonsense like
# "httpsgallicabnffriiifark12148b".
_IDENTIFIER_KEYS = (
    "identifier:gallica_ark",
    "identifier:heidelberg_diglit",
    "identifier:bsb",
    "identifier:lccn",
    "identifier:ia",
)


def provider_identifier(ref_obj: Any) -> str:
    """The work's stable identifier within its provider.

    This is what names an index (`{provider}_{identifier}.sqlite`).
    Deliberately NOT title-derived: manifest labels vary between
    editions and get corrected over time, so a title-based filename can
    drift or mislabel, while the identifier round-trips back to the ref
    that built it.
    """
    m = _BNUM_IN_URL.search(ref_obj.manifest_url)
    if m:
        return m.group(1)
    for key in _IDENTIFIER_KEYS:
        val = ref_obj.extra_metadata.get(key)
        if val:
            return slugify(str(val), max_len=40)
    return slugify(ref_obj.manifest_url)[:40]


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
@click.option("--no-ocr", "no_ocr", is_flag=True, default=False,
              help="Skip per-canvas OCR fetch entirely. Produces an image-only "
                   "index with text_blocks + illustrations empty and "
                   "ocr_source='none'. Use for works where ALTO is broken "
                   "(e.g. Bourgery on Wellcome) or absent (plate atlases).")
@click.option("--layout", "layout",
              type=click.Choice(["raw", "columns", "table"]),
              default="raw", show_default=True,
              help="Default reading order for this book, stored in "
                   "index_metadata. 'raw' keeps OCR order (quotable); "
                   "'columns' unbraids multi-column prose; 'table' "
                   "reassembles tabular matter into rows. Word geometry "
                   "is retained regardless, so this can be overridden "
                   "per-call later without rebuilding.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
@click.pass_context
def create_index(ctx: click.Context, ref: str, output_dir: Path,
                  output_path: Path | None, provider: str | None,
                  allow_empty: bool, no_ocr: bool, layout: str,
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

    # Per-provider config overrides — used to honor host-specific
    # rate-limits (LoC's tight 429 ceiling, Gallica's hard ~5 req/s cap).
    provider_cfg = (cfg.get("providers") or {}).get(ref_obj.provider_key) or {}
    for k in ("max_concurrency", "max_retries", "retry_base_seconds",
               "request_interval_seconds"):
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
    identifier = provider_identifier(ref_obj)
    slug = f"{ref_obj.provider_key}_{identifier}"
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
    pw_rows: list[dict[str, Any]] = []
    leaf_to_canvas: dict[int, int] = {}
    mono_source: str | None = None
    if no_ocr:
        n_alto_canvases = n_hocr_canvases = n_text_canvases = 0
        if canvases:
            log.info(f"--no-ocr: skipping per-canvas OCR for "
                     f"{len(canvases)} canvases")
    else:
        n_alto_canvases = sum(1 for c in canvases if c.alto_url)
        n_hocr_canvases = sum(
            1 for c in canvases if not c.alto_url and c.hocr_url
        )
        n_text_canvases = sum(
            1 for c in canvases
            if not c.alto_url and not c.hocr_url and c.text_url
        )
        if canvases:
            tb_rows, il_rows, image_dims, pw_rows = _parse_altos(
                canvases, cfg_http=cfg_http, cache_dir=cache_dir, log=log,
            )
        if canvases and not tb_rows:
            # No per-canvas OCR anywhere. IA ships whole-book OCR
            # derivatives instead (one monolithic hOCR or DjVu-XML file);
            # when the provider surfaced those URLs, index from them.
            mono = _parse_monolithic_ocr(
                ref_obj.extra_metadata, canvases,
                cfg_http=cfg_http, cache_dir=cache_dir, log=log,
            )
            if mono is not None:
                (tb_rows, image_dims, mono_source, pw_rows,
                 leaf_to_canvas) = mono

    # --- index_metadata (after parse so we know the OCR provenance) --------
    from iiif_utils import __version__
    have = [k for k, v in (("alto", n_alto_canvases),
                             ("hocr", n_hocr_canvases),
                             ("text_plain", n_text_canvases)) if v]
    if mono_source:
        ocr_source = mono_source        # 'hocr' | 'djvu' (whole-book file)
    elif not have:
        ocr_source = "none"
    elif len(have) == 1:
        ocr_source = have[0]
    else:
        ocr_source = "mixed"
    idx_md = {
        "slug": slug,
        "created_at": db_mod.now_iso(),
        "index_mode": "image_only" if no_ocr else "alto",
        "ocr_source": ocr_source,
        "provider": ref_obj.provider_key,
        "provider_kind": "iiif",
        "manifest_url": ref_obj.manifest_url,
        "presentation_api_version": manifest_mod.presentation_version(manifest),
        "iiif_utils_version": __version__,
        "layout_default": layout,
    }
    if pw_rows:
        from iiif_utils.core.wordgeom import WORDS_SCHEMA
        idx_md["words_schema"] = WORDS_SCHEMA
    if mono_source:
        # Whole-book OCR file (IA shape) rather than per-canvas seeAlso.
        idx_md["ocr_shape"] = "monolithic"
        idx_md["leaf_mapping"] = _ALIGN.get("join", "none")
        if _FALLBACK.get("from"):
            idx_md["ocr_source_fallback_from"] = _FALLBACK["from"]
            idx_md["ocr_source_fallback_reason"] = _FALLBACK["reason"]
    if flags.partial_digitization:
        idx_md["partial_digitization"] = flags.partial_digitization
    if flags.contains_multiple_volumes:
        idx_md["contains_multiple_volumes"] = flags.contains_multiple_volumes
    db_mod.write_index_metadata(db, idx_md)

    # ALTO-less / OCR-less warnings — fire even without -v.
    # When --no-ocr is explicit the user asked for image-only, so the
    # "no OCR found" warning is just noise; skip it.
    if canvases and ocr_source == "none" and not no_ocr:
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
    # Providers that publish their own printed-page-number detection
    # override the canvas label, which is not always a page number.
    pn_override = _fetch_page_number_overrides(
        ref_obj.extra_metadata, cfg_http=cfg_http, cache_dir=cache_dir,
        log=log,
    )
    # `_page_numbers.json` is keyed by LEAF, like everything else IA
    # publishes. Re-key it to canvas, or `-b/--book` resolves to a page
    # that drifts further from the truth the deeper into the book you go.
    if pn_override and leaf_to_canvas:
        pn_override = {leaf_to_canvas[leaf]: vals
                       for leaf, vals in pn_override.items()
                       if leaf in leaf_to_canvas}
    canvas_to_leaf = {ci: leaf for leaf, ci in leaf_to_canvas.items()}
    pn_rows: list[dict[str, Any]] = []
    for c in canvases:
        img_dim = image_dims.get(c.index)
        ov = pn_override.get(c.index, {})
        # When the provider ships a page-number map, it is exhaustive:
        # a leaf missing from it is deliberately unnumbered (cover,
        # plates, endpapers). Falling back to the canvas label there
        # would invent a page number — for IA the label is just a
        # counter, so leaf 0 would claim to be page '1'.
        pn_rows.append({
            "leaf_num": c.index,
            "book_page_number": (
                ov.get("book_page_number") if pn_override
                else db_mod.book_page_from_label(c.label)),
            # The provider's own leaf number for this canvas — the inverse
            # of the leaf->canvas map, not a lookup by canvas index into it.
            "ia_leaf": canvas_to_leaf.get(c.index),
            "confidence": ov.get("confidence"),
            "pageProb": ov.get("pageProb"),
            "wordConf": ov.get("wordConf"),
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
    if pw_rows:
        db_mod.write_page_words(db, pw_rows)

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
    if _FALLBACK.get("from"):
        click.echo(f"  OCR SOURCE:    {_FALLBACK['from']} unavailable, used "
                   f"{mono_source} instead ({_FALLBACK['reason']})")
    if pw_rows:
        n_words = sum(1 for _ in pw_rows)
        blob_kb = sum(len(r["blob"]) for r in pw_rows) / 1024
        click.echo(f"  page_words:    {n_words:,} pages "
                   f"({blob_kb:.0f} KB, layout_default={layout})")


def _parse_altos(canvases: list[Any], *, cfg_http: dict[str, Any],
                  cache_dir: Path, log: Logger,
                  ) -> tuple[list[dict[str, Any]],
                             list[dict[str, Any]],
                             dict[int, tuple[int, int]],
                             list[dict[str, Any]]]:
    """Fetch + parse per-canvas OCR.

    Three sources, in priority order:
      1. ALTO seeAlso (Wellcome, LoC modern items): full bbox + illustrations
      2. hOCR seeAlso (MDZ via injected URLs): full bbox, no illustrations
      3. plain-text seeAlso (LoC older items): synthetic block, no bboxes

    `image_width`/`image_height` are populated only for ALTO and hOCR
    (where the page element carries dims); NULL for plain-text-only.
    """
    image_dims: dict[int, tuple[int, int]] = {}
    tb_rows: list[dict[str, Any]] = []
    il_rows: list[dict[str, Any]] = []
    pw_rows: list[dict[str, Any]] = []

    alto_dir = cache_dir / "alto"
    hocr_dir = cache_dir / "hocr"
    text_dir = cache_dir / "text"
    alto_dir.mkdir(parents=True, exist_ok=True)

    alto_canvases = [c for c in canvases if c.alto_url]
    hocr_only_canvases = [
        c for c in canvases if not c.alto_url and c.hocr_url
    ]
    text_only_canvases = [
        c for c in canvases
        if not c.alto_url and not c.hocr_url and c.text_url
    ]
    log.info(f"fetching {len(alto_canvases)} ALTO + "
             f"{len(hocr_only_canvases)} hOCR + "
             f"{len(text_only_canvases)} text-only files "
             f"(of {len(canvases)} canvases)")
    if (not alto_canvases and not hocr_only_canvases
            and not text_only_canvases):
        return tb_rows, il_rows, image_dims, pw_rows

    def _ingest_xml_blocks(c: Any, page: Any, kind: str) -> None:
        _rows_from_page(
            c.index, page,
            default_block_type=("ocr_textblock" if kind == "alto"
                                 else "ocrx_block"),
            tb_rows=tb_rows, il_rows=il_rows, image_dims=image_dims,
            pw_rows=pw_rows,
        )

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
            _ingest_xml_blocks(c, page, "alto")
        log.info(f"parsed {n_parsed} ALTOs")

    # --- hOCR branch -------------------------------------------------------
    if hocr_only_canvases:
        from iiif_utils.core import hocr as hocr_mod
        hocr_dir.mkdir(parents=True, exist_ok=True)
        urls = [c.hocr_url for c in hocr_only_canvases]
        fetched_h = asyncio.run(http_.fetch_many_bytes(
            urls, cfg_http=cfg_http, cache_dir=hocr_dir, suffix=".hocr",
        ))
        n_hocr = 0
        for c in hocr_only_canvases:
            content = fetched_h.get(c.hocr_url)
            if not content:
                log.warn(f"no hOCR bytes for canvas {c.index}")
                continue
            try:
                page = hocr_mod.parse_hocr_bytes(content)
            except Exception as e:
                log.warn(f"hOCR parse error canvas {c.index}: {e}")
                continue
            n_hocr += 1
            _ingest_xml_blocks(c, page, "hocr")
        log.info(f"parsed {n_hocr} hOCRs")

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

    return tb_rows, il_rows, image_dims, pw_rows


def _rows_from_page(page_index: int, page: Any, *, default_block_type: str,
                     tb_rows: list[dict[str, Any]],
                     il_rows: list[dict[str, Any]],
                     image_dims: dict[int, tuple[int, int]],
                     pw_rows: list[dict[str, Any]] | None = None) -> None:
    """Convert one parsed AltoPage into text_blocks / illustrations rows.

    Shared by the per-canvas branches (_parse_altos) and the monolithic
    branch (_parse_monolithic_ocr). Block type and confidence come from
    the TextBlock when the parser set them (monolithic hOCR / DjVu);
    otherwise the per-source default applies and confidence stays NULL.
    """
    if page.page_w and page.page_h:
        image_dims[page_index] = (page.page_w, page.page_h)
    # Word geometry: always retained when the source carries it, so a
    # miscoded layout is a wrong rendering rather than a lost index.
    if pw_rows is not None and getattr(page, "words", None):
        from iiif_utils.core import wordgeom
        pw_rows.append({
            "page_id": page_index,
            "blob": wordgeom.encode(page.words),
        })
    for b in page.text_blocks:
        tb_rows.append({
            "page_id": page_index,
            "block_number": b.block_number,
            "block_type": b.block_type or default_block_type,
            "language": None,
            "text_direction": None,
            "bbox_x0": b.bbox_x0, "bbox_y0": b.bbox_y0,
            "bbox_x1": b.bbox_x1, "bbox_y1": b.bbox_y1,
            "text": b.text,
            "line_count": b.line_count,
            "word_count": b.word_count,
            "length": b.length,
            "avg_confidence": b.avg_confidence,
            "avg_font_size": b.avg_font_size,
            "parent_carea_id": None,
            "alto_id": b.alto_id,
        })
    for ill in page.illustrations:
        il_rows.append({
            "page_id": page_index,
            "illustration_number": ill.illustration_number,
            "bbox_x0": ill.bbox_x0, "bbox_y0": ill.bbox_y0,
            "bbox_x1": ill.bbox_x1, "bbox_y1": ill.bbox_y1,
            "illustration_type": ill.illustration_type,
            "alto_id": ill.alto_id,
        })


def _fetch_page_number_overrides(
    extra_metadata: dict[str, str], *, cfg_http: dict[str, Any],
    cache_dir: Path, log: Logger,
) -> dict[int, dict[str, Any]]:
    """Authoritative printed page numbers, when the provider ships them.

    IA publishes `{id}_page_numbers.json` from its own detector, with
    per-leaf confidence. IA's IIIF canvas labels are only sequential
    counters, so without this every IA index would carry page numbers
    off by the front-matter offset. Best-effort: a failure here falls
    back to canvas labels rather than aborting the index.
    """
    url = extra_metadata.get("ia_page_numbers_url")
    if not url:
        return {}
    from iiif_utils.providers import internet_archive as ia_mod
    try:
        content = http_.fetch_bytes(url, cfg_http=cfg_http,
                                      cache_dir=cache_dir / "monolithic",
                                      suffix=".page_numbers.json")
        out = ia_mod.parse_page_numbers(content)
    except Exception as e:
        log.warn(f"page_numbers.json failed ({e}); "
                 f"falling back to canvas labels")
        return {}
    n_numbered = sum(1 for v in out.values() if v["book_page_number"])
    log.info(f"page numbers from IA detector: {n_numbered} numbered "
             f"of {len(out)} leaves")
    return out


# Set by _parse_monolithic_ocr when the preferred OCR source failed and a
# poorer one was used instead. Module-level because the summary and
# index_metadata are written outside that call; single-threaded by
# construction (one create-index per process).
_FALLBACK: dict[str, str] = {"from": "", "reason": ""}

# How OCR pages were tied to canvases: image_filename (preferred),
# file_number (fallback), or identity/none. Recorded in index_metadata so
# an index says how it was keyed rather than leaving it to be inferred.
_ALIGN: dict[str, str] = {"join": "none"}


def _verify_leaf_map(leaf_to_canvas: dict[int, int],
                      extra_metadata: dict[str, str], *,
                      cfg_http: dict[str, Any], cache_dir: Path,
                      log: Logger) -> None:
    """Check the URL-derived leaf map against IA's scandata.

    Two independent sources describe which leaves become canvases: the
    scan file number in each canvas's Image API URL, and scandata's
    `addToAccessFormats` flag. They agreed exactly on every item tested.
    Cross-checking means an item that breaks the pattern fails loudly
    instead of silently shifting a book's text against its images —
    which is the failure this whole change exists to remove.
    """
    url = extra_metadata.get("ia_scandata_url")
    if not url:
        return
    try:
        content = http_.fetch_bytes(url, cfg_http=cfg_http,
                                      cache_dir=cache_dir / "monolithic",
                                      suffix=".scandata.xml")
        access = ia_mod.parse_scandata_access_leaves(content)
    except Exception as e:
        log.info(f"scandata check skipped ({e})")
        return
    if not access:
        return
    derived = sorted(leaf_to_canvas)
    if derived == access:
        log.info(f"leaf map verified against scandata "
                 f"({len(derived)} access leaves)")
        return
    log.warn(
        f"leaf map DISAGREES with scandata: {len(derived)} leaves from "
        f"canvas URLs vs {len(access)} flagged addToAccessFormats. Using "
        f"the URL-derived map (it addresses the actual image), but text "
        f"and images may not line up — spot-check a known page.")


def _parse_monolithic_ocr(
    extra_metadata: dict[str, str], canvases: list[Any], *,
    cfg_http: dict[str, Any], cache_dir: Path, log: Logger,
) -> tuple[list[dict[str, Any]], dict[int, tuple[int, int]], str,
             list[dict[str, Any]], dict[int, int]] | None:
    """Whole-book OCR fallback for providers with no per-canvas OCR.

    IA publishes OCR as monolithic derivatives — one `{id}_hocr.html`
    (modern items) or `{id}_djvu.xml` (older scans) for the whole book —
    surfaced by the IA adapter as `ia_hocr_url` / `ia_djvu_xml_url` in
    extra metadata. One fetch, one multipage parse, same row shapes as
    the per-canvas branches.

    Returns (tb_rows, image_dims, ocr_source) or None when the provider
    surfaced no monolithic URLs. hOCR is preferred (richer: bboxes at
    paragraph level + confidence + Tesseract block classes); DjVu is
    the fallback, tried also when the hOCR fetch/parse fails.
    """
    hocr_url = extra_metadata.get("ia_hocr_url")
    djvu_url = extra_metadata.get("ia_djvu_xml_url")
    _FALLBACK["from"] = ""
    _FALLBACK["reason"] = ""
    if not hocr_url and not djvu_url:
        return None

    mono_dir = cache_dir / "monolithic"
    pages: list[tuple[int, Any]] | None = None
    source = ""
    page_images: dict[int, str] = {}   # leaf -> source image filename
    if hocr_url:
        from iiif_utils.core import hocr as hocr_mod
        log.info(f"fetching monolithic hOCR: {hocr_url}")
        try:
            content = http_.fetch_bytes(hocr_url, cfg_http=cfg_http,
                                          cache_dir=mono_dir,
                                          suffix=".hocr.html")
            triples = hocr_mod.parse_hocr_pages(content)
            pages = [(leaf, pg) for leaf, _img, pg in triples]
            page_images = {leaf: img for leaf, img, _pg in triples if img}
            source = "hocr"
        except Exception as e:
            log.warn(f"monolithic hOCR failed ({e}); "
                     + ("trying DjVu XML" if djvu_url else "no DjVu fallback"))
            # Record it: a downgrade to a poorer source is invisible after
            # the run otherwise, and on a bulk ingest the OCR quality of a
            # corpus would then vary with transient network luck.
            _FALLBACK["from"] = "hocr"
            _FALLBACK["reason"] = str(e)[:200]
            pages = None
    if pages is None and djvu_url:
        from iiif_utils.core import djvu as djvu_mod
        log.info(f"fetching DjVu XML: {djvu_url}")
        try:
            content = http_.fetch_bytes(djvu_url, cfg_http=cfg_http,
                                          cache_dir=mono_dir,
                                          suffix=".djvu.xml")
            pages = djvu_mod.parse_djvu_multipage(content)
            source = "djvu"
            warn = djvu_mod.djvu_alignment_warning(pages, len(canvases))
            if warn:
                log.warn(warn)
        except Exception as e:
            log.warn(f"DjVu XML failed ({e})")
            pages = None
    if pages is None:
        return None

    # IA keys its OCR by LEAF; canvases are a dense renumbering of only
    # the access-format leaves. Translate here, at the boundary, so
    # everything downstream keeps meaning canvas.
    # Preferred join: the scan filename. The hOCR page declares the image
    # it describes and the canvas URL addresses that same file, so this
    # needs no arithmetic and holds per item. Ids, positions and file
    # numbers do NOT: verified against page images, Gray 1918 has hOCR
    # id == file number while anatomicaltermin00barkuoft has id == file-1.
    # TWO domains, and they are not interchangeable. `_page_numbers.json`
    # is keyed by IA's leafNum — the scan FILE number (barkuoft: 1..234,
    # leafNum 41 -> printed '17') — so that map is what leaves this
    # function. OCR text is keyed by whatever the OCR file itself uses,
    # which for hOCR is the page id (barkuoft: 0..237, id 40 -> '17').
    # Conflating them shifts the page numbers by exactly the amount the
    # filename join just corrected the text by.
    file_leaf_to_canvas = {leaf: ci
                           for ci, leaf in
                           ia_mod.canvas_leaf_map(canvases).items()}
    text_leaf_to_canvas: dict[int, int] = {}
    join = "none"
    if page_images:
        by_name = {name: ci
                   for ci, name in ia_mod.canvas_image_names(canvases).items()}
        matched = {leaf: by_name[img]
                   for leaf, img in page_images.items() if img in by_name}
        # Only trust it if it explains essentially every canvas; a partial
        # match means the two sides name files differently and the
        # remainder would silently fall back to a different rule.
        distinct = len(set(matched.values())) == len(matched)
        if distinct and len(matched) >= math.ceil(0.98 * len(canvases)):
            text_leaf_to_canvas = matched
            join = "image_filename"
            log.info(f"OCR pages joined to canvases by scan filename "
                     f"({len(matched)}/{len(canvases)})")
        elif matched:
            log.warn(f"scan-filename join matched only {len(matched)} of "
                     f"{len(canvases)} canvases; falling back to the file "
                     f"number in the canvas URL")
    if not text_leaf_to_canvas:
        text_leaf_to_canvas = dict(file_leaf_to_canvas)
        if text_leaf_to_canvas:
            join = "file_number"
    if file_leaf_to_canvas:
        _verify_leaf_map(file_leaf_to_canvas, extra_metadata,
                          cfg_http=cfg_http, cache_dir=cache_dir, log=log)
    else:
        # Not an IA-shaped item: leaf and canvas coincide by definition.
        file_leaf_to_canvas = {c.index: c.index for c in canvases}
        text_leaf_to_canvas = dict(file_leaf_to_canvas)
        join = "identity"
    _ALIGN["join"] = join

    tb_rows: list[dict[str, Any]] = []
    il_rows: list[dict[str, Any]] = []  # always empty for hOCR/DjVu
    pw_rows: list[dict[str, Any]] = []
    image_dims: dict[int, tuple[int, int]] = {}
    dropped = 0
    for leaf, page in pages:
        canvas = text_leaf_to_canvas.get(leaf)
        if canvas is None:
            # A leaf IA excluded from access formats — a scanner colour
            # card, or one the operator marked Delete. It has no canvas,
            # so there is nothing to attach its text to.
            dropped += 1
            continue
        _rows_from_page(canvas, page, default_block_type="ocr_par",
                         tb_rows=tb_rows, il_rows=il_rows,
                         image_dims=image_dims, pw_rows=pw_rows)
    if dropped:
        log.info(f"monolithic {source}: {dropped} OCR pages have no canvas "
                 f"(colour cards / leaves IA excluded from access formats)")
    log.info(f"parsed {len(pages) - dropped} pages from monolithic {source}")
    return tb_rows, image_dims, source, pw_rows, file_leaf_to_canvas
