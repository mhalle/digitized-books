"""`iiif-utils render-page` — reading order derived from word geometry.

The read side of WORD_GEOMETRY_PLAN. `create-index` stores per-word
boxes and a `layout_default`; this command renders a page through one
of the layout modes, resolving the mode by the plan's three layers of
authority (§3.2):

    index default (index_metadata.layout_default)
      → per-call override (--layout)
      → detection, as a labeled hint ONLY (--detect)

Detection never selects the mode. When it disagrees confidently with
the configured one, the disagreement is reported and configuration
still wins (§3.3) — silent auto-detection is what turns a wrong guess
into invisible corruption.

Reconstructed renderings (columns / table) carry `quotable: false`
(§3.4): they are evidence of what is on the page, not a transcription.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.core import layout as layout_mod
from iiif_utils.core import wordgeom
from iiif_utils.utils import output as output_
from iiif_utils.utils.page import page_ref, resolve_leaf


@click.command(name="render-page")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf", type=int, default=None,
              help="Canvas / leaf number, 0-based.")
@click.option("-b", "--book", "book_page", default=None,
              help="Printed page number (resolved via page_numbers).")
@click.option("--layout", "layout_override",
              type=click.Choice(list(layout_mod.LAYOUTS)), default=None,
              help="Override the index's layout_default for this call.")
@click.option("--detect", is_flag=True, default=False,
              help="Also report the detector's hint and signals. The hint "
                   "is never applied on its own.")
@output_.format_option(default="records")
def render_page(index: Path, leaf: int | None, book_page: str | None,
                 layout_override: str | None, detect: bool,
                 fmt: str) -> None:
    """Render one page's text in a chosen reading order."""
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "page_words" not in have:
        raise click.ClickException(
            "This index has no page_words table — it predates word "
            "geometry, or its OCR source carried no word boxes. Rebuild "
            "it with `iiif-utils create-index` to enable layout modes."
        )

    leaf_num = resolve_leaf(conn, leaf, book_page)
    row = conn.execute("SELECT blob FROM page_words WHERE page_id = ?",
                        (leaf_num,)).fetchone()
    if row is None:
        raise click.ClickException(
            f"No word geometry stored for canvas {leaf_num} — the page "
            f"may carry no OCR text."
        )
    page = wordgeom.decode(row["blob"])

    # Layer 1: index default. Layer 2: per-call override.
    meta = {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM index_metadata")}
    configured = layout_override or meta.get("layout_default") or "raw"
    if configured not in layout_mod.LAYOUTS:
        raise click.ClickException(
            f"index_metadata.layout_default={configured!r} is not one of "
            f"{layout_mod.LAYOUTS}")

    dims = conn.execute(
        "SELECT image_width, width FROM page_numbers WHERE leaf_num = ?",
        (leaf_num,)).fetchone()
    page_width = (dims["image_width"] or dims["width"]) if dims else None

    rendering = layout_mod.render(page, configured, page_width=page_width)

    rec: dict[str, Any] = {
        **page_ref(leaf_num),
        "layout": rendering.layout,
        "quotable": rendering.quotable,
        "lines": len(rendering.lines),
        "words": len(page.words),
        "text": rendering.text,
    }

    # Layer 3: detection — a labeled hint, never applied (§3.2).
    if detect:
        hint = layout_mod.detect(page)
        rec["layout_hint"] = hint.layout_hint
        rec["confidence"] = round(hint.confidence, 2)
        rec["signals"] = hint.signals
        rec["detector_calibrated"] = hint.calibrated
        warning = layout_mod.contradiction_warning(configured, hint)
        if warning:
            # Configuration still wins; the disagreement is never silent.
            click.echo(f"WARN: {warning}", err=True)
            rec["layout_warning"] = warning

    output_.write_records([rec], fmt)
