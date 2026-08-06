"""`iiif-utils get-page` — download a whole canvas image."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import image as image_mod
from iiif_utils.core import image_api
from iiif_utils.providers import internet_archive as ia_mod
from iiif_utils.utils.page import resolve_leaf


@click.command(name="get-page")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, default=None,
              help="Canvas (leaf) index, 0-based. Mutually exclusive with -b.")
@click.option("-b", "--book", default=None,
              help="Printed page number (looks up via page_numbers).")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--size", default="1400,",
              help="IIIF size string. Aliases: small,medium,large,full,max."
                   " 'max' resolves to the source's native width via info.json"
                   " (use this if a server rejects '/full/full/').")
@click.option("--format", "fmt", default="jpg")
@click.option("--url-only", is_flag=True, default=False)
@click.option("--source", "source",
              type=click.Choice(["auto", "iiif", "bookreader", "jp2"]),
              default="auto", show_default=True,
              help="Where to fetch the image. 'auto' uses IIIF and falls "
                   "back to IA's own endpoints if it fails. 'bookreader' "
                   "and 'jp2' are Internet Archive only.")
@click.option("--autocontrast", is_flag=True, default=False,
              help="Stretch contrast after download. Old letterpress "
                   "scans are often flat and grey; this is what makes "
                   "them legible.")
@click.option("--cutoff", type=int, default=None,
              help="Autocontrast cutoff percentage (default 2). Implies "
                   "--autocontrast.")
@click.option("--preserve-tone", is_flag=True, default=False,
              help="Keep colour balance while autocontrasting. Implies "
                   "--autocontrast.")
@click.option("--quality", type=int, default=None,
              help="JPEG quality, 1-95.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_page(index: Path, leaf_num: int | None, book: str | None,
              output_path: Path | None, size: str, fmt: str,
              url_only: bool, source: str, autocontrast: bool,
              cutoff: int | None, preserve_tone: bool, quality: int | None,
              config_path: Path | None) -> None:
    """Download a whole canvas image."""
    aliases = {"small": "400,", "medium": "800,", "large": "1600,",
               "full": "full", "max": "max"}
    size = aliases.get(size, size)

    cfg = load_config(config_path)
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    leaf_num = resolve_leaf(conn, leaf_num, book)
    # `ia_leaf` postdates the first indexes, and plenty are still on
    # disk. Select it only when it is there rather than making every
    # older index fail to fetch a page at all.
    have_ia_leaf = any(
        r[1] == "ia_leaf"
        for r in conn.execute("PRAGMA table_info(page_numbers)").fetchall()
    )
    row = conn.execute(
        "SELECT image_service_url, image_width, image_height, width, height, "
        "book_page_number" + (", ia_leaf" if have_ia_leaf else "") +
        " FROM page_numbers WHERE leaf_num = ?",
        (leaf_num,),
    ).fetchone()
    if not row or not row["image_service_url"]:
        raise click.ClickException(f"Canvas {leaf_num} has no image_service_url.")

    cfg_http = cfg.get("http", {})
    size = image_api.resolve_max_size(size, row["image_service_url"],
                                       cfg_http=cfg_http)
    # Never ask for an upscale: IIIF level 2 need not support one, and
    # servers that don't answer 400 rather than clamping. The default
    # `1400,` is wider than plenty of real scans.
    nat_w, nat_h = image_api.resolve_dims(row, cfg_http=cfg_http)
    size = image_api.clamp_size_to_native(size, nat_w, nat_h)

    # Internet Archive serves the same page outside the Image API: the
    # BookReader endpoint (identifier + leaf, three fixed sizes) and the
    # original JP2 via zip-as-directory, which fetches ONE member without
    # transferring the archive. Both bypass Image-API constraints, so
    # they are the fallback when IIIF refuses.
    ia_ident = _doc_value(conn, "identifier:ia")
    ia_fallbacks: list[tuple[str, str]] = []
    if ia_ident:
        want_w = None
        if "," in size and size.split(",")[0].isdigit():
            want_w = int(size.split(",")[0])
        elif nat_w:
            want_w = nat_w
        # BookReader is keyed by IA's LEAF — "a leaf number that
        # corresponds to an image in the jp2.zip file" — not by the dense
        # canvas index this index calls `leaf_num`. Passing the canvas
        # index fetched the wrong page on every item where IA excluded a
        # leaf from access formats, and did so silently: you get a
        # perfectly good image of a different page. `ia_leaf` is that
        # number; when it is NULL the two coincide by definition.
        br_leaf = (row["ia_leaf"]
                   if have_ia_leaf and row["ia_leaf"] is not None
                   else leaf_num)
        ia_fallbacks.append((
            "bookreader",
            ia_mod.bookreader_image_url(
                ia_ident, int(br_leaf), ia_mod.bookreader_size_for(want_w))))
        jp2 = ia_mod.jp2_url_from_service(row["image_service_url"])
        if jp2:
            ia_fallbacks.append(("jp2 (original)", jp2))

    if source in ("bookreader", "jp2"):
        if not ia_ident:
            raise click.ClickException(
                f"--source {source} is Internet Archive only; this index "
                f"has no IA identifier.")
        picked = [u for label, u in ia_fallbacks if label.startswith(source)]
        if not picked:
            raise click.ClickException(
                f"--source {source} is unavailable for canvas {leaf_num}.")
        url = picked[0]
    else:
        url = image_api.region_url(row["image_service_url"], None,
                                     size=size, fmt=fmt)
    if url_only:
        click.echo(url)
        return
    if output_path is None:
        output_path = Path.cwd() / f"page_l{leaf_num}.{fmt}"
    try:
        content = http_.fetch_bytes(url, cfg_http=cfg_http)
    except Exception as e:
        if source != "auto" or not ia_fallbacks:
            native = (f"{nat_w}x{nat_h}" if nat_w and nat_h else "unknown")
            raise click.ClickException(
                f"Image fetch failed for canvas {leaf_num}: {e}\n"
                f"  requested size: {size}   source is {native}\n"
                f"  try --size max, or a smaller explicit width\n"
                f"  other derivatives: iiif-utils list-files -i {index}"
            ) from e
        # IA publishes the same page through endpoints that don't share
        # the Image API's constraints. Fall back rather than fail, but
        # say so — the bytes you get are not the ones you asked for.
        fetched: bytes | None = None
        for label, fb_url in ia_fallbacks:
            try:
                fetched = http_.fetch_bytes(fb_url, cfg_http=cfg_http)
            except Exception:
                continue
            click.echo(f"WARN: IIIF fetch failed ({e}); used IA {label} "
                       f"instead — size/format differ from --size {size}",
                       err=True)
            url = fb_url
            break
        if fetched is None:
            raise click.ClickException(
                f"Image fetch failed for canvas {leaf_num} on IIIF and on "
                f"IA's bookreader/jp2 endpoints: {e}"
            ) from e
        content = fetched

    if image_mod.wants_processing(autocontrast=autocontrast, cutoff=cutoff,
                                    preserve_tone=preserve_tone,
                                    quality=quality):
        content = image_mod.process_image(
            content, output_format=fmt, quality=quality,
            autocontrast=autocontrast, cutoff=cutoff,
            preserve_tone=preserve_tone,
        )
    output_path.write_bytes(content)
    # Name both numbers: the whole class of leaf/page mistakes is silent
    # otherwise — you get a page, just not the one you meant.
    printed = row["book_page_number"]
    where = (f"leaf {leaf_num} = printed page {printed}" if printed
             else f"leaf {leaf_num} (no printed page number)")
    click.echo(f"saved {output_path}  ({len(content)/1024:.1f} KB)  "
               f"[{where}]")


def _doc_value(conn: sqlite3.Connection, key: str) -> str | None:
    """Read one key from document_metadata, tolerating older indexes."""
    try:
        row = conn.execute(
            "SELECT value FROM document_metadata WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None
