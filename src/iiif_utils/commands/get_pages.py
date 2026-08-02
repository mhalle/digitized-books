"""`iiif-utils get-pages` — download a range of canvas images.

Canvas-list source:
  -i / --index SQLITE          existing SQLite index (preferred when available)
  --manifest REF               manifest URL or provider-resolvable ID
                                 (-P wellcome p747b7vs, -P loc 49043519, …)
                                 — lets you preview a work without indexing,
                                 useful when OCR is broken or absent and an
                                 index can't be built (e.g. Bourgery)

Collection navigation (--manifest only):
  --child N                    pick the Nth child manifest (1-based) when
                                 REF resolves to a IIIF Collection of manifests

Selection:
  -l / --leaves '1-10,15,20'   explicit leaf list
  --all                        every canvas
  --sample N                   N canvases evenly distributed across the work
                                 — the natural "preview" operation

Output modes:
  -p / --prefix STR            one file per canvas: {prefix}_NNNN.{fmt}
                                 (index mode only)
  --zip + -o PATH              one zip archive of all selected pages
                                 (index mode only)
  --mosaic + -o PATH           contact-sheet JPEG (works in both modes)
  --url-only                   just print the URLs (works in both modes)
"""
from __future__ import annotations

import asyncio
import io
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import image_api
from iiif_utils.core import manifest as manifest_mod
from iiif_utils.core import mosaic as mosaic_mod
from iiif_utils.providers import resolve as resolve_ref
from iiif_utils.utils.page import parse_leaf_spec


def _parse_leaf_range(spec: str, max_idx: int) -> list[int]:
    """Parse '1-10', '3', '1-5,10,20-22' into a sorted list of leaf indices."""
    return parse_leaf_spec(spec, max_idx)


def _sample_indices(total: int, n: int) -> list[int]:
    """Pick n evenly-spaced indices in [0, total). Always includes 0 and total-1."""
    if n <= 0 or total <= 0:
        return []
    if n >= total:
        return list(range(total))
    step = total / n
    return [min(int(i * step), total - 1) for i in range(n)]


def _rows_from_index(index_path: Path) -> list[dict[str, Any]]:
    """Read (leaf_num, image_service_url, book_page_number) from a SQLite index."""
    conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT leaf_num, image_service_url, book_page_number "
        "FROM page_numbers "
        "WHERE image_service_url IS NOT NULL ORDER BY leaf_num"
    ).fetchall()
    return [dict(r) for r in rows]


def _resolve_manifest_canvases(
    ref: str, provider: str | None, child: int | None,
    cfg: dict[str, Any], cache_dir: Path,
) -> list[dict[str, Any]]:
    """Resolve REF → manifest → list of pseudo-rows for the mosaic path.

    Rows have the same keys as `_rows_from_index` so downstream code
    doesn't care which source it came from. `book_page_number` is the
    canvas label (a printed page number when one was set, else '-'),
    which is the closest analogue available without a page_numbers table.
    """
    cfg_http = cfg.get("http", {})
    ref_obj = resolve_ref(ref, cfg=cfg, explicit_provider=provider,
                          cache_dir=cache_dir)
    if ref_obj.manifest_payload is not None:
        manifest = ref_obj.manifest_payload
    else:
        manifest = http_.fetch_json(
            ref_obj.manifest_url, cfg_http=cfg_http, cache_dir=cache_dir,
        )

    if manifest_mod.manifest_type(manifest) == "Collection":
        items = manifest.get("items") or manifest.get("manifests") or []
        if not items:
            raise click.ClickException(
                f"{ref_obj.manifest_url} is an empty Collection."
            )
        if child is None:
            raise click.ClickException(
                f"{ref_obj.manifest_url} is a Collection of {len(items)} "
                f"manifests. Pass --child N (1-based) to pick one."
            )
        if not (1 <= child <= len(items)):
            raise click.ClickException(
                f"--child {child} out of range; Collection has "
                f"{len(items)} manifests (1..{len(items)})."
            )
        child_item = items[child - 1]
        child_url = child_item.get("id") or child_item.get("@id")
        if not child_url:
            raise click.ClickException(
                f"Collection child {child} has no manifest URL."
            )
        manifest = http_.fetch_json(
            child_url, cfg_http=cfg_http, cache_dir=cache_dir,
        )
    elif child is not None:
        raise click.ClickException(
            "--child requires REF to resolve to a Collection, but "
            f"{ref_obj.manifest_url} is a single Manifest."
        )

    canvases = manifest_mod.canvases(manifest)
    out: list[dict[str, Any]] = []
    for c in canvases:
        if not c.image_service_url:
            continue
        out.append({
            "leaf_num": c.index,
            "image_service_url": c.image_service_url,
            "book_page_number": c.label,
        })
    return out


@click.command(name="get-pages")
@click.option("-i", "--index", default=None,
              type=click.Path(exists=True, path_type=Path),
              help="SQLite index built by create-index.")
@click.option("--manifest", "manifest_ref", default=None,
              help="Manifest URL or provider-resolvable id (use with -P). "
                   "Mutually exclusive with -i/--index.")
@click.option("-P", "--provider", default=None,
              help="Override provider for --manifest (e.g. wellcome, loc, mdz).")
@click.option("--child", "child", type=int, default=None,
              help="Pick the Nth child manifest (1-based) when --manifest "
                   "resolves to a IIIF Collection.")
@click.option("-l", "--leaves", "leaf_spec", default=None,
              help="Range/list, e.g. '1-10,15,20-25'. Mutually exclusive with --all/--sample.")
@click.option("--all", "all_pages", is_flag=True, default=False)
@click.option("--sample", "sample_n", type=int, default=None,
              help="Pick N canvases evenly spaced across the work — "
                   "the natural 'preview' selection.")
@click.option("-p", "--prefix", "prefix", default=None,
              help="Output per page as {prefix}_NNNN.{fmt}. Requires -i/--index.")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="With --zip or --mosaic: output path.")
@click.option("--zip", "as_zip", is_flag=True, default=False,
              help="Write one zip archive of all selected pages. Requires -i/--index.")
@click.option("--mosaic", "as_mosaic", is_flag=True, default=False,
              help="Compose pages into a single contact-sheet image "
                   "(for LLM-vision input or visual browsing).")
@click.option("--mosaic-width", "mosaic_width", type=int, default=1536,
              help="Mosaic output width in px (default 1536).")
@click.option("--cols", "cols", type=int, default=12,
              help="Mosaic columns (default 12).")
@click.option("--label", "label_type",
              type=click.Choice(["leaf", "book", "none"]), default="leaf",
              help="Mosaic tile labels: leaf number, printed page, or none. "
                   "In --manifest mode, 'book' uses the canvas label.")
@click.option("--grid", "grid", is_flag=True, default=False,
              help="Draw grid lines between mosaic tiles.")
@click.option("--size", default="1400,",
              help="IIIF size string. Aliases: small,medium,large,full,max."
                   " 'max' resolves to each source's native width via info.json"
                   " (use this if a server rejects '/full/full/').")
@click.option("--format", "fmt", default="jpg")
@click.option("--url-only", is_flag=True, default=False)
@click.option("-j", "--jobs", "jobs", type=int, default=None,
              help="Override max_concurrency from config.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_pages(index: Path | None, manifest_ref: str | None,
               provider: str | None, child: int | None,
               leaf_spec: str | None, all_pages: bool, sample_n: int | None,
               prefix: str | None, output_path: Path | None,
               as_zip: bool, as_mosaic: bool, mosaic_width: int,
               cols: int, label_type: str, grid: bool,
               size: str, fmt: str, url_only: bool,
               jobs: int | None, config_path: Path | None) -> None:
    """Download many canvas images concurrently."""
    # Canvas-list source mutual-exclusion
    if index is None and manifest_ref is None:
        raise click.UsageError("Pass -i/--index INDEX or --manifest REF.")
    if index is not None and manifest_ref is not None:
        raise click.UsageError("Cannot combine -i/--index and --manifest.")
    if provider is not None and manifest_ref is None:
        raise click.UsageError("-P/--provider only applies with --manifest.")
    if child is not None and manifest_ref is None:
        raise click.UsageError("--child only applies with --manifest.")

    # Selection mutual-exclusion — accept exactly one of {leaves, all, sample}
    selection_modes = sum(
        bool(x) for x in (leaf_spec, all_pages, sample_n is not None)
    )
    if selection_modes == 0:
        raise click.UsageError("Pass --leaves RANGE, --all, or --sample N.")
    if selection_modes > 1:
        raise click.UsageError(
            "--leaves, --all, and --sample are mutually exclusive."
        )

    if as_zip and as_mosaic:
        raise click.UsageError("Cannot combine --zip and --mosaic.")
    if as_zip and not output_path:
        raise click.UsageError("--zip requires -o OUTPUT.")
    if as_mosaic and not output_path:
        raise click.UsageError("--mosaic requires -o OUTPUT.")
    if not (as_zip or as_mosaic or url_only or prefix):
        raise click.UsageError(
            "Pass -p PREFIX, --zip -o OUTPUT, --mosaic -o OUTPUT, "
            "or --url-only."
        )
    # Manifest mode supports only --mosaic and --url-only (we have no
    # printed-page metadata or page_numbers table to fall back on).
    if manifest_ref is not None and (as_zip or prefix is not None):
        raise click.UsageError(
            "--manifest mode supports --mosaic and --url-only; for --zip or "
            "-p/--prefix, build an index with `create-index` first."
        )

    aliases = {"small": "400,", "medium": "800,", "large": "1600,",
               "full": "full", "max": "max"}
    # Mosaic tiles get downsampled to ~128px wide anyway; use 'small'
    # as the default so we don't waste bandwidth on big originals.
    if as_mosaic and size == "1400,":
        size = "400,"
    size = aliases.get(size, size)

    cfg = load_config(config_path)
    cfg_http: dict[str, Any] = dict(cfg.get("http", {}))
    cache_dir = Path(cfg_http.get("cache_dir", "./.iiif-cache")).expanduser()
    if jobs is not None:
        cfg_http["max_concurrency"] = jobs

    if index is not None:
        rows = _rows_from_index(index)
    else:
        assert manifest_ref is not None
        rows = _resolve_manifest_canvases(
            manifest_ref, provider, child, cfg, cache_dir,
        )
    if not rows:
        raise click.ClickException("No canvases with image_service_url.")
    max_idx = max(r["leaf_num"] for r in rows)

    if all_pages:
        wanted = [r["leaf_num"] for r in rows]
    elif sample_n is not None:
        idxs = _sample_indices(len(rows), sample_n)
        wanted = [rows[i]["leaf_num"] for i in idxs]
    else:
        assert leaf_spec is not None
        wanted = _parse_leaf_range(leaf_spec, max_idx)
    if not wanted:
        raise click.ClickException("Empty leaf selection.")

    by_idx = {r["leaf_num"]: r["image_service_url"] for r in rows}
    book_pn = {r["leaf_num"]: r["book_page_number"] for r in rows}
    urls: list[tuple[int, str]] = []
    for i in wanted:
        if i not in by_idx:
            continue
        # 'max' resolves per-canvas via info.json (each canvas has its own
        # native width). Other sizes pass through unchanged.
        eff_size = (image_api.resolve_max_size(size, by_idx[i],
                                                cfg_http=cfg_http,
                                                cache_dir=cache_dir)
                    if size == "max" else size)
        urls.append((i, image_api.region_url(by_idx[i], None,
                                              size=eff_size, fmt=fmt)))

    if url_only:
        for _i, u in urls:
            click.echo(u)
        return

    click.echo(f"fetching {len(urls)} page images "
                f"(j={cfg_http.get('max_concurrency', 8)})...",
                err=True)
    fetched = asyncio.run(http_.fetch_many_bytes(
        [u for (_i, u) in urls], cfg_http=cfg_http,
    ))

    if as_mosaic:
        assert output_path is not None
        images_in_order: list[bytes] = []
        labels: list[str | None] = []
        for i, u in urls:
            content = fetched.get(u)
            if not content:
                continue
            images_in_order.append(content)
            if label_type == "leaf":
                labels.append(str(i))
            elif label_type == "book":
                labels.append(book_pn.get(i) or "")
            else:
                labels.append(None)
        if not images_in_order:
            raise click.ClickException("No images fetched; cannot build mosaic.")
        mosaic_bytes = mosaic_mod.create_mosaic(
            images_in_order,
            labels=labels if label_type != "none" else None,
            width=mosaic_width, cols=cols, grid=grid,
        )
        output_path.write_bytes(mosaic_bytes)
        click.echo(f"saved {output_path}  "
                    f"({len(mosaic_bytes)/1024/1024:.1f} MB, "
                    f"{len(images_in_order)} tiles, {cols} cols)")
    elif as_zip:
        assert output_path is not None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            for i, u in urls:
                content = fetched.get(u)
                if not content:
                    continue
                zf.writestr(f"page_{i:04d}.{fmt}", content)
        output_path.write_bytes(buf.getvalue())
        click.echo(f"saved {output_path}  "
                    f"({output_path.stat().st_size/1024/1024:.1f} MB, "
                    f"{len(urls)} pages)")
    else:
        assert prefix is not None
        out_root = Path(prefix).parent
        out_root.mkdir(parents=True, exist_ok=True)
        n_saved = 0
        for i, u in urls:
            content = fetched.get(u)
            if not content:
                continue
            p = Path(f"{prefix}_{i:04d}.{fmt}")
            p.write_bytes(content)
            n_saved += 1
        click.echo(f"saved {n_saved} pages to {Path(prefix).parent}/")
