"""`iiif-utils get-pages` — download a range of canvas images.

Output modes:
  -p / --prefix STR    one file per canvas: {prefix}_NNNN.{fmt}
  --zip + -o PATH      one zip archive containing all pages
  --url-only           just print the URLs
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
from iiif_utils.core import mosaic as mosaic_mod


def _parse_leaf_range(spec: str, max_idx: int) -> list[int]:
    """Parse '1-10', '3', '1-5,10,20-22' into a sorted list of leaf indices."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            for i in range(min(lo, hi), max(lo, hi) + 1):
                if 0 <= i <= max_idx:
                    out.add(i)
        else:
            i = int(part)
            if 0 <= i <= max_idx:
                out.add(i)
    return sorted(out)


@click.command(name="get-pages")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaves", "leaf_spec", default=None,
              help="Range/list, e.g. '1-10,15,20-25'. Mutually exclusive with --all.")
@click.option("--all", "all_pages", is_flag=True, default=False)
@click.option("-p", "--prefix", "prefix", default=None,
              help="Output per page as {prefix}_NNNN.{fmt}.")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="With --zip: zip output path.")
@click.option("--zip", "as_zip", is_flag=True, default=False)
@click.option("--mosaic", "as_mosaic", is_flag=True, default=False,
              help="Compose pages into a single contact-sheet image "
                   "(for LLM-vision input or visual browsing).")
@click.option("--mosaic-width", "mosaic_width", type=int, default=1536,
              help="Mosaic output width in px (default 1536).")
@click.option("--cols", "cols", type=int, default=12,
              help="Mosaic columns (default 12).")
@click.option("--label", "label_type",
              type=click.Choice(["leaf", "book", "none"]), default="leaf",
              help="Mosaic tile labels: leaf number, printed page, or none.")
@click.option("--grid", "grid", is_flag=True, default=False,
              help="Draw grid lines between mosaic tiles.")
@click.option("--size", default="1400,",
              help="IIIF size string. Aliases: small,medium,large,full.")
@click.option("--format", "fmt", default="jpg")
@click.option("--url-only", is_flag=True, default=False)
@click.option("-j", "--jobs", "jobs", type=int, default=None,
              help="Override max_concurrency from config.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_pages(index: Path, leaf_spec: str | None, all_pages: bool,
               prefix: str | None, output_path: Path | None,
               as_zip: bool, as_mosaic: bool, mosaic_width: int,
               cols: int, label_type: str, grid: bool,
               size: str, fmt: str, url_only: bool,
               jobs: int | None, config_path: Path | None) -> None:
    """Download many canvas images concurrently."""
    if not leaf_spec and not all_pages:
        raise click.UsageError("Pass --leaves RANGE or --all.")
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

    aliases = {"small": "400,", "medium": "800,", "large": "1600,",
               "full": "full"}
    # Mosaic tiles get downsampled to ~128px wide anyway; use 'small'
    # as the default so we don't waste bandwidth on big originals.
    if as_mosaic and size == "1400,":
        size = "400,"
    size = aliases.get(size, size)

    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT leaf_num, image_service_url, book_page_number "
        "FROM page_numbers "
        "WHERE image_service_url IS NOT NULL ORDER BY leaf_num"
    ))
    if not rows:
        raise click.ClickException("No canvases with image_service_url.")
    max_idx = max(r["leaf_num"] for r in rows)

    if all_pages:
        wanted = [r["leaf_num"] for r in rows]
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
        urls.append((i, image_api.region_url(by_idx[i], None,
                                              size=size, fmt=fmt)))

    if url_only:
        for _i, u in urls:
            click.echo(u)
        return

    cfg = load_config(config_path)
    cfg_http: dict[str, Any] = dict(cfg.get("http", {}))
    if jobs is not None:
        cfg_http["max_concurrency"] = jobs

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
