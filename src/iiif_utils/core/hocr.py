"""hOCR (text/vnd.hocr+html) parsing — block + bbox + confidence extraction.

Returns the same `AltoPage` dataclass that `core.alto` returns, so
downstream code (text_blocks insertion, FTS) works without branching.
hOCR has no `<Illustration>` analog, so `illustrations` will be empty.

Adapted from `ia-utils/core/parser.py::parse_hocr`. Uses lxml (which we
already depend on) instead of BeautifulSoup.

hOCR class taxonomy:
  ocr_page    one per page
  ocrx_block  layout block (OCR engine's notion)
  ocr_par     paragraph
  ocr_line    single text line
  ocrx_word   single word (carries x_wconf, x_fsize in title attr)

bbox is encoded in the `title` attribute as `bbox X1 Y1 X2 Y2`
(left-top-right-bottom, image pixels). Other title properties
(`x_wconf NN`, `x_fsize NN`) are space-separated, semicolon-joined.
"""
from __future__ import annotations

import re
from statistics import mean

from lxml import html as lxml_html

from iiif_utils.core.alto import AltoPage, Illustration, TextBlock

_BBOX_RE = re.compile(r"bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)")
_WCONF_RE = re.compile(r"x_wconf\s+(\d+)")
_FSIZE_RE = re.compile(r"x_fsize\s+(\d+)")


def _parse_bbox(title: str) -> tuple[int, int, int, int] | None:
    m = _BBOX_RE.search(title or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def _word_text(word_el: object) -> str:
    """Get a word's text content (handles nested formatting)."""
    text_content = getattr(word_el, "text_content", None)
    if text_content is None:
        return ""
    return str(text_content()).strip()


def parse_hocr_bytes(content: bytes) -> AltoPage:
    """Parse hOCR bytes (text/vnd.hocr+html) into our AltoPage shape.

    Granularity: one row per `ocrx_block` element (matching the §3.5
    decision for ALTO TextBlocks). Pages with no text yield zero rows.
    """
    root = lxml_html.fromstring(content)  # type: ignore[no-untyped-call]
    # ocr_page — one per page; we only handle the first (one canvas per file).
    pages = root.xpath("//*[contains(concat(' ', normalize-space(@class), ' '),"
                       " ' ocr_page ')]")
    if not pages:
        return AltoPage(page_w=0, page_h=0, measurement_unit="pixel",
                         text_blocks=[], illustrations=[])
    page_el = pages[0]
    page_bbox = _parse_bbox(page_el.get("title") or "")
    page_w = page_bbox[2] if page_bbox else 0
    page_h = page_bbox[3] if page_bbox else 0

    blocks_xp = ("descendant::*[contains(concat(' ', "
                  "normalize-space(@class), ' '), ' ocrx_block ')]")
    block_els = page_el.xpath(blocks_xp)

    text_blocks: list[TextBlock] = []
    avg_conf: float | None = None  # set per-block below
    for bn, block in enumerate(block_els):
        title = block.get("title") or ""
        bbox = _parse_bbox(title)
        if bbox is None:
            continue
        x0, y0, x1, y1 = bbox

        word_els = block.xpath(
            "descendant::*[contains(concat(' ', normalize-space(@class),"
            " ' '), ' ocrx_word ')]"
        )
        words: list[str] = []
        confs: list[int] = []
        for w in word_els:
            t = _word_text(w)
            if t:
                words.append(t)
            wt = w.get("title") or ""
            mc = _WCONF_RE.search(wt)
            if mc:
                try:
                    confs.append(int(mc.group(1)))
                except ValueError:
                    pass
        text = " ".join(words)
        if not text.strip():
            continue

        line_els = block.xpath(
            "descendant::*[contains(concat(' ', normalize-space(@class),"
            " ' '), ' ocr_line ')]"
        )
        avg_conf = mean(confs) if confs else None

        text_blocks.append(TextBlock(
            block_number=bn,
            alto_id=block.get("id") or None,
            text=text,
            line_count=len(line_els),
            word_count=len(word_els),
            length=len(text),
            bbox_x0=x0, bbox_y0=y0, bbox_x1=x1, bbox_y1=y1,
        ))

    # AltoPage carries the same dataclass; avg_confidence is stored on
    # AltoPage indirectly through TextBlock (we don't propagate it here
    # because the existing TextBlock doesn't have a confidence field —
    # the write-side maps `avg_confidence=None` for ALTO too. hOCR
    # confidence is available in source but currently dropped at this
    # boundary, mirroring the §3.5 'NULL for Wellcome ALTO' invariant.)
    _ = avg_conf  # acknowledged but not stored (see note above)

    illustrations: list[Illustration] = []  # hOCR has no Illustration analog
    return AltoPage(
        page_w=page_w,
        page_h=page_h,
        measurement_unit="pixel",  # hOCR bboxes are always image pixels
        text_blocks=text_blocks,
        illustrations=illustrations,
    )
