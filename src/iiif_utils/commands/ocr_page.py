"""`iiif-utils ocr-page` — run local Tesseract on a canvas or region.

Specialized fallback for when ALTO is missing, wrong on a specific
region, or in a language Wellcome's ABBYY pipeline doesn't handle well
(Latin for Vesalius, blackletter German, Greek).

Pulls the region via the IIIF Image API (server-side crop in
image-native coordinates — the same coordinate space ALTO bboxes and
the `illustrations` table use), then hands the bytes to pytesseract.

Requires the `tesseract` binary installed system-wide:
  macOS:   brew install tesseract   (+ tesseract-lang for non-English)
  Debian:  apt install tesseract-ocr  tesseract-ocr-<lang>
  Windows: see https://github.com/UB-Mannheim/tesseract/wiki
"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import image_api
from iiif_utils.utils.page import resolve_leaf

# Map common ISO-639-3 / display-name language values stored in IIIF
# manifests / catalogue records to Tesseract's language codes.
_LANG_MAP = {
    "eng": "eng", "English": "eng",
    "ger": "deu", "deu": "deu", "German": "deu",
    "fre": "fra", "fra": "fra", "French": "fra",
    "spa": "spa", "Spanish": "spa",
    "ita": "ita", "Italian": "ita",
    "lat": "lat", "Latin": "lat",
    "grc": "grc", "Ancient Greek": "grc", "Greek": "grc",
    "dut": "nld", "nld": "nld", "Dutch": "nld",
    "por": "por", "Portuguese": "por",
}


def _check_tesseract() -> None:
    """Fail fast with an install hint if the binary isn't on PATH."""
    if shutil.which("tesseract") is None:
        raise click.ClickException(
            "tesseract binary not found on PATH. Install: "
            "`brew install tesseract` (macOS) or "
            "`apt install tesseract-ocr` (Debian). For non-English: "
            "install tesseract-lang / tesseract-ocr-<lang>."
        )


def _parse_bbox(spec: str) -> tuple[int, int, int, int]:
    """Parse a bbox in any of: 'x0,y0,x1,y1', 'x0 y0 x1 y1',
    'bbox x0 y0 x1 y1' (hOCR title form). All in image-pixel coords."""
    s = spec.strip()
    if s.lower().startswith("bbox "):
        s = s[5:].strip()
    parts = s.split(",") if "," in s else s.split()
    if len(parts) != 4:
        raise click.UsageError(
            f"--bbox needs 4 values (x0,y0,x1,y1); got {len(parts)}."
        )
    try:
        return (int(parts[0]), int(parts[1]),
                int(parts[2]), int(parts[3]))
    except ValueError as e:
        raise click.UsageError(f"--bbox parse error: {e}") from e


def _language_from_index(conn: sqlite3.Connection) -> str | None:
    """Read a likely-correct Tesseract lang from document_metadata."""
    for key in ("catalogue_languages", "language",
                 "manifest_metadata:Languages"):
        row = conn.execute(
            "SELECT value FROM document_metadata WHERE key = ?",
            (key,),
        ).fetchone()
        if row and row["value"]:
            # Take the first language listed (Wellcome separates with " | ")
            primary = row["value"].split("|")[0].strip()
            mapped = _LANG_MAP.get(primary)
            if mapped:
                return mapped
    return None


@click.command(name="ocr-page")
@click.option("-i", "--index", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("-l", "--leaf", "leaf_num", type=int, default=None,
              help="Canvas (leaf) index, 0-based. Mutually exclusive with -b.")
@click.option("-b", "--book", default=None,
              help="Printed page number (looks up via page_numbers).")
@click.option("--bbox", "bbox_str", default=None,
              help="Region 'x0,y0,x1,y1' (commas or spaces; "
                   "hOCR-style 'bbox x0 y0 x1 y1' also accepted). "
                   "Omit to OCR the whole canvas.")
@click.option("-n", "--number", "ill_num", type=int, default=None,
              help="OCR an illustration by number (alternative to --bbox).")
@click.option("--padding", default=None,
              help="Pad the region. Symmetric '20' / '5%' or per-side "
                   "'left,top,right,bottom'.")
@click.option("--size", default="full",
              help="IIIF size: 'full' preserves source resolution "
                   "(recommended). 'large'/'medium'/'small' aliases also "
                   "accepted.")
@click.option("--lang", default=None,
              help="Tesseract language code(s), '+'-separated "
                   "(eg eng, lat, eng+lat). Default: inferred from "
                   "document_metadata.")
@click.option("--psm", type=int, default=3,
              help="Tesseract page-segmentation mode (default 3 = auto). "
                   "6 = uniform block, 7 = single text line, "
                   "11 = sparse text.")
@click.option("--oem", type=int, default=3,
              help="Tesseract OCR engine mode (default 3 = best available).")
@click.option("-o", "--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write to file (.txt or .json) instead of stdout.")
@click.option("--output-format", "output_format",
              type=click.Choice(["text", "json"]), default=None,
              help="Output format. Default: auto from -o suffix, else text.")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def ocr_page(index: Path, leaf_num: int | None, book: str | None,
              bbox_str: str | None, ill_num: int | None,
              padding: str | None, size: str, lang: str | None,
              psm: int, oem: int, output_path: Path | None,
              output_format: str | None,
              config_path: Path | None) -> None:
    """Run Tesseract on a region of a canvas image."""
    _check_tesseract()
    if bbox_str and ill_num is not None:
        raise click.UsageError("Pass --bbox OR -n, not both.")

    # Defer heavy imports
    import pytesseract
    from PIL import Image

    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    leaf = resolve_leaf(conn, leaf_num, book)
    pn = conn.execute(
        "SELECT image_service_url, width, height, "
        "image_width, image_height FROM page_numbers WHERE leaf_num=?",
        (leaf,),
    ).fetchone()
    if not pn or not pn["image_service_url"]:
        raise click.ClickException(f"Canvas {leaf} has no image_service_url.")

    # Resolve bbox (explicit, by illustration, or full canvas).
    bbox: tuple[int, int, int, int] | None = None
    if bbox_str:
        bbox = _parse_bbox(bbox_str)
    elif ill_num is not None:
        ill = conn.execute(
            "SELECT bbox_x0, bbox_y0, bbox_x1, bbox_y1 FROM illustrations "
            "WHERE page_id=? AND illustration_number=?",
            (leaf, ill_num),
        ).fetchone()
        if not ill:
            raise click.ClickException(
                f"No illustration #{ill_num} on canvas {leaf}."
            )
        bbox = (ill["bbox_x0"], ill["bbox_y0"],
                ill["bbox_x1"], ill["bbox_y1"])
    if bbox is not None and padding:
        cw, ch = image_api.clamp_dims_from_page_row(pn)
        bbox = image_api.padded_bbox(bbox, padding, canvas_w=cw, canvas_h=ch)

    # Language: explicit > index > eng default.
    if lang is None:
        lang = _language_from_index(conn) or "eng"

    # Build the IIIF Image API URL — server-side crop. The user's bbox is
    # in image-native pixel coords (the same space ALTO uses), and IIIF's
    # region syntax `x,y,w,h` consumes exactly those coords.
    aliases = {"small": "400,", "medium": "800,", "large": "1600,"}
    iiif_size = aliases.get(size, size)
    url = image_api.region_url(pn["image_service_url"], bbox,
                                 size=iiif_size, fmt="jpg")

    cfg = load_config(config_path)
    img_bytes = http_.fetch_bytes(url, cfg_http=cfg.get("http", {}))
    img = Image.open(io.BytesIO(img_bytes))

    # Run OCR
    config = f"--oem {oem} --psm {psm}"
    text: str = pytesseract.image_to_string(  # type: ignore[attr-defined,no-untyped-call]
        img, lang=lang, config=config)

    # Choose output format
    if output_format is None and output_path is not None:
        output_format = "json" if output_path.suffix.lower() == ".json" \
            else "text"
    elif output_format is None:
        output_format = "text"

    if output_format == "json":
        result_obj: dict[str, Any] = {
            "leaf": leaf,
            "book_page_number": (book if book is not None
                                  else _book_page(conn, leaf)),
            "bbox": list(bbox) if bbox else None,
            "lang": lang,
            "psm": psm,
            "oem": oem,
            "iiif_url": url,
            "text": text,
        }
        rendered = json.dumps(result_obj, indent=2, ensure_ascii=False)
    else:
        rendered = text

    if output_path is None:
        sys.stdout.write(rendered)
        if not rendered.endswith("\n"):
            sys.stdout.write("\n")
    else:
        output_path.write_text(rendered)
        click.echo(f"saved {output_path}  ({len(rendered)/1024:.1f} KB)",
                    err=True)


def _book_page(conn: sqlite3.Connection, leaf: int) -> str | None:
    row = conn.execute(
        "SELECT book_page_number FROM page_numbers WHERE leaf_num=?",
        (leaf,),
    ).fetchone()
    return row["book_page_number"] if row else None
