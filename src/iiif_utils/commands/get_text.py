"""`iiif-utils get-text` — OCR text, whole-work or per page.

Two modes, because "the text" means two different things:

  - **Whole-work rendering** (default): the manifest's `text/plain`
    rendering as one blob, for LLM input or grep. ~30x smaller than the
    ALTO source and one request instead of N. It has no page
    boundaries (verified for Wellcome — DESIGN.md §6).

  - **Per page** (`-l/--leaf`, `-b/--book`): text pulled from an
    index's `text_blocks`, in OCR order, no network. Use `--blocks` for
    one record per block with bboxes and confidence.

Per-page mode is the ia-utils `get-text` behaviour. It reads
`text_blocks`, so it works on every index including migrated ones —
unlike `render-page`, which needs the word geometry only newer indexes
carry. Reach for `render-page` when you want a *reconstructed* reading
order; reach for this when you want what the OCR actually said.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import manifest as manifest_mod
from iiif_utils.providers import resolve
from iiif_utils.utils import output as output_
from iiif_utils.utils.page import parse_book_spec, parse_leaf_spec


@click.command(name="get-text")
@click.argument("ref", required=False)
@click.option("-i", "--index", type=click.Path(exists=True, path_type=Path),
              default=None,
              help="Read the rendering URL from an existing index.")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write to file instead of stdout.")
@click.option("-P", "--provider", default=None)
@click.option("-l", "--leaf", "leaf_spec", default=None,
              help="Leaf range ('175', '1-7,21'). Reads text_blocks from "
                   "-i INDEX; no network.")
@click.option("-b", "--book", "book_spec", default=None,
              help="Printed-page range, resolved via page_numbers.")
@click.option("--blocks", is_flag=True, default=False,
              help="One record per block (bbox + confidence) instead of "
                   "aggregated page text. Per-page mode only.")
@click.option("--url-only", is_flag=True, default=False,
              help="Print the rendering URL instead of fetching it.")
@output_.format_option(default="records")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def get_text(ref: str | None, index: Path | None, output_path: Path | None,
              provider: str | None, leaf_spec: str | None,
              book_spec: str | None, blocks: bool, url_only: bool,
              fmt: str, config_path: Path | None) -> None:
    """Fetch OCR text — whole-work rendering, or per page from an index."""
    cfg = load_config(config_path)
    cfg_http = cfg.get("http", {})

    if leaf_spec or book_spec:
        if not index:
            raise click.UsageError(
                "-l/--leaf and -b/--book read from an index; pass -i INDEX.")
        _per_page_text(index, leaf_spec=leaf_spec, book_spec=book_spec,
                        blocks=blocks, fmt=fmt, output_path=output_path)
        return
    if blocks:
        raise click.UsageError("--blocks applies to -l/--leaf or -b/--book.")

    if index and not ref:
        conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT download_url FROM archive_files "
            "WHERE format LIKE '%text/plain%' OR format = 'text/plain' "
            "ORDER BY filename LIMIT 1"
        ).fetchone()
        if not row:
            raise click.ClickException(
                "No text/plain rendering recorded in this index."
            )
        url = row[0]
    elif ref:
        cache_dir = Path(cfg_http.get("cache_dir", "./.iiif-cache")).expanduser()
        ref_obj = resolve(ref, cfg=cfg, explicit_provider=provider,
                           cache_dir=cache_dir)
        m = http_.fetch_json(ref_obj.manifest_url, cfg_http=cfg_http,
                              cache_dir=cache_dir)
        url = None
        for r in manifest_mod.renderings(m):
            if (r.format or "").lower() == "text/plain":
                url = r.url
                break
        if not url:
            raise click.ClickException(
                f"Manifest {ref_obj.manifest_url} has no text/plain rendering."
            )
    else:
        raise click.UsageError("Provide a manifest URL/identifier or -i INDEX.")

    if url_only:
        click.echo(url)
        return

    content = http_.fetch_bytes(url, cfg_http=cfg_http)
    if output_path is None:
        sys.stdout.buffer.write(content)
    else:
        output_path.write_bytes(content)
        click.echo(f"saved {output_path}  ({len(content)/1024/1024:.1f} MB)",
                   err=True)


def _per_page_text(index: Path, *, leaf_spec: str | None,
                    book_spec: str | None, blocks: bool, fmt: str,
                    output_path: Path | None) -> None:
    """Pull text for selected pages out of an index's text_blocks."""
    if leaf_spec and book_spec:
        raise click.UsageError("Pass -l or -b, not both.")

    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    if leaf_spec:
        leaves = parse_leaf_spec(leaf_spec)
    else:
        books = set(parse_book_spec(book_spec or ""))
        leaves = sorted(
            r["leaf_num"] for r in conn.execute(
                "SELECT leaf_num, book_page_number FROM page_numbers "
                "WHERE book_page_number IS NOT NULL")
            if r["book_page_number"] in books
        )
        if not leaves:
            raise click.ClickException(
                f"No leaves found for printed page(s) {book_spec!r}.")

    placeholders = ",".join("?" * len(leaves))
    if not leaves:
        raise click.ClickException("No pages selected.")

    rows: list[dict[str, Any]] = []
    if blocks:
        for r in conn.execute(f"""
            SELECT tb.page_id, tb.block_number, tb.block_type,
                   tb.bbox_x0, tb.bbox_y0, tb.bbox_x1, tb.bbox_y1,
                   tb.avg_confidence, tb.text, pn.book_page_number
            FROM text_blocks tb
            LEFT JOIN page_numbers pn ON pn.leaf_num = tb.page_id
            WHERE tb.page_id IN ({placeholders})
            ORDER BY tb.page_id, tb.block_number
        """, leaves):
            rows.append({
                "leaf": r["page_id"],
                "page": r["book_page_number"],
                "block": r["block_number"],
                "block_type": r["block_type"],
                "bbox": [r["bbox_x0"], r["bbox_y0"],
                          r["bbox_x1"], r["bbox_y1"]],
                "confidence": (round(r["avg_confidence"], 1)
                                if r["avg_confidence"] is not None else None),
                "text": r["text"],
            })
    else:
        for r in conn.execute(f"""
            SELECT tb.page_id, pn.book_page_number,
                   group_concat(tb.text, ' ') AS page_text
            FROM text_blocks tb
            LEFT JOIN page_numbers pn ON pn.leaf_num = tb.page_id
            WHERE tb.page_id IN ({placeholders})
            GROUP BY tb.page_id
            ORDER BY tb.page_id
        """, leaves):
            rows.append({
                "leaf": r["page_id"],
                "page": r["book_page_number"],
                "text": r["page_text"],
            })

    if not rows:
        raise click.ClickException(
            "No text found for the selected page(s). The index may be "
            "image-only, or those leaves may carry no OCR.")

    if output_path is not None:
        with output_path.open("w") as fp:
            output_.write_records(rows, fmt, fp=fp)
        click.echo(f"saved {output_path}", err=True)
    else:
        output_.write_records(rows, fmt)
