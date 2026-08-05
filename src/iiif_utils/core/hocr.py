"""hOCR (text/vnd.hocr+html) parsing — block + bbox + confidence extraction.

Returns the same `AltoPage` dataclass that `core.alto` returns, so
downstream code (text_blocks insertion, FTS) works without branching.
hOCR has no `<Illustration>` analog, so `illustrations` will be empty.

Adapted from `ia-utils/core/parser.py::parse_hocr`. Uses lxml (which we
already depend on) instead of BeautifulSoup.

Two entry points:

  - `parse_hocr_bytes` — one page per file (MDZ's per-canvas hOCR).
    Blocks are `ocrx_block` elements; confidence is deliberately dropped
    (see the invariant note at the bottom of `_page_from_el` callers).
  - `parse_hocr_multipage` — one monolithic file for the whole book
    (IA's `{id}_hocr.html`). Every `ocr_page` div is parsed; the leaf
    number comes from the div's `id="page_N"` (falling back to sequence
    order). IA's Tesseract output nests paragraphs under `ocr_carea`
    column areas, so blocks are `ocr_par` / `ocr_caption` / `ocr_header`
    / `ocr_textfloat` — mirroring ia-utils' full-hOCR mode — and
    per-block mean `x_wconf` IS retained (the ia-utils dialect always
    stored it).

hOCR class taxonomy:
  ocr_page    one per page
  ocr_carea   column area (Tesseract)
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
from statistics import mean, median
from typing import Any

from lxml import html as lxml_html

from iiif_utils.core.alto import AltoPage, Illustration, TextBlock

_BBOX_RE = re.compile(r"bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)")
_WCONF_RE = re.compile(r"x_wconf\s+(\d+)")
_FSIZE_RE = re.compile(r"x_fsize\s+(\d+)")
_PAGE_ID_RE = re.compile(r"page_0*(\d+)")
# The hOCR spec puts the SOURCE IMAGE in the ocr_page title:
#   title="ppageno 4; image spyri_heidi_1880/00000005.tif; bbox 0 0 W H"
# That names the actual scan file, which is also what a IIIF canvas's
# Image API URL addresses — so the two join on a filename with no
# arithmetic and no per-item assumptions. Page ids and positions do NOT
# reliably equal the file number: verified against images, Gray 1918 has
# id == file number while anatomicaltermin00barkuoft has id == file - 1.
_PAGE_IMAGE_RE = re.compile(r"""\bimage\s+["']?([^;"']+)""")


def page_image_name(title: str) -> str | None:
    """Basename of the scan file an ocr_page describes, if it says."""
    m = _PAGE_IMAGE_RE.search(title or "")
    if not m:
        return None
    raw = m.group(1).strip().rstrip("'\"")
    if not raw:
        return None
    return raw.replace("\\", "/").rsplit("/", 1)[-1]

# Block-level classes per source shape. MDZ per-canvas files use
# `ocrx_block`; IA's monolithic Tesseract output uses paragraph-level
# classes (same set ia-utils collected).
_BLOCK_CLASSES_SINGLE = ("ocrx_block",)
_BLOCK_CLASSES_TESSERACT = ("ocr_par", "ocr_caption", "ocr_header",
                             "ocr_textfloat")


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


def _class_xpath(classes: tuple[str, ...]) -> str:
    preds = " or ".join(
        f"contains(concat(' ', normalize-space(@class), ' '), ' {c} ')"
        for c in classes
    )
    return f"descendant::*[{preds}]"


def _el_class(el: Any, classes: tuple[str, ...]) -> str | None:
    """First class from `classes` present on the element, if any."""
    have = (el.get("class") or "").split()
    for c in classes:
        if c in have:
            return c
    return None


def _page_from_el(page_el: Any, block_classes: tuple[str, ...],
                   keep_confidence: bool) -> AltoPage:
    """Parse one `ocr_page` element into an AltoPage."""
    page_bbox = _parse_bbox(page_el.get("title") or "")
    page_w = page_bbox[2] if page_bbox else 0
    page_h = page_bbox[3] if page_bbox else 0

    block_els = page_el.xpath(_class_xpath(block_classes))

    from iiif_utils.core.wordgeom import PageWords, Word
    page_words: list[Word] = []
    words_per_line: list[int] = []

    text_blocks: list[TextBlock] = []
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
        avg_conf = mean(confs) if (keep_confidence and confs) else None
        fsizes: list[int] = []

        # Word geometry, walked per line in the same order as the block
        # text above. x_fsize is retained because it makes heading
        # detection structural rather than regex-based (§3.6).
        for line_el in line_els:
            n_in_line = 0
            for w in line_el.xpath(
                "descendant::*[contains(concat(' ', normalize-space(@class),"
                " ' '), ' ocrx_word ')]"
            ):
                t = _word_text(w)
                if not t:
                    continue
                wbox = _parse_bbox(w.get("title") or "")
                if wbox is None:
                    continue
                wx0, wy0, wx1, wy1 = wbox
                wt = w.get("title") or ""
                mc = _WCONF_RE.search(wt)
                mf = _FSIZE_RE.search(wt)
                if mf:
                    fsizes.append(int(mf.group(1)))
                page_words.append(Word(
                    text=t, x=wx0, y=wy0,
                    w=max(0, wx1 - wx0), h=max(0, wy1 - wy0),
                    conf=int(mc.group(1)) if mc else None,
                    fsize=int(mf.group(1)) if mf else None,
                ))
                n_in_line += 1
            if n_in_line:
                words_per_line.append(n_in_line)

        text_blocks.append(TextBlock(
            block_number=bn,
            alto_id=block.get("id") or None,
            text=text,
            line_count=len(line_els),
            word_count=len(word_els),
            length=len(text),
            bbox_x0=x0, bbox_y0=y0, bbox_x1=x1, bbox_y1=y1,
            avg_confidence=avg_conf,
            block_type=_el_class(block, block_classes),
            avg_font_size=float(median(fsizes)) if fsizes else None,
        ))

    illustrations: list[Illustration] = []  # hOCR has no Illustration analog
    return AltoPage(
        page_w=page_w,
        page_h=page_h,
        measurement_unit="pixel",  # hOCR bboxes are always image pixels
        text_blocks=text_blocks,
        illustrations=illustrations,
        words=(PageWords(words=page_words,
                          words_per_line=words_per_line)
               if page_words else None),
    )


def _page_els(content: bytes) -> list[Any]:
    root = lxml_html.fromstring(content)  # type: ignore[no-untyped-call]
    return list(root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '),"
        " ' ocr_page ')]"
    ))


def parse_hocr_bytes(content: bytes) -> AltoPage:
    """Parse hOCR bytes (text/vnd.hocr+html) into our AltoPage shape.

    Granularity: one row per `ocrx_block` element (matching the §3.5
    decision for ALTO TextBlocks). Pages with no text yield zero rows.

    Confidence is available in source but deliberately dropped at this
    boundary (avg_confidence=None), mirroring the §3.5 'NULL for
    Wellcome ALTO' invariant on per-canvas sources.
    """
    pages = _page_els(content)
    if not pages:
        return AltoPage(page_w=0, page_h=0, measurement_unit="pixel",
                         text_blocks=[], illustrations=[])
    # One canvas per file — only the first page element counts.
    return _page_from_el(pages[0], _BLOCK_CLASSES_SINGLE,
                          keep_confidence=False)


def parse_hocr_pages(content: bytes) -> list[tuple[int, str | None, AltoPage]]:
    """Like `parse_hocr_multipage`, but also returns each page's source
    image filename when the hOCR declares one.

    The filename is the only identifier that reliably ties an hOCR page
    to a particular scan: ids and positions have both been observed to
    disagree with the file number, in opposite directions, on real IA
    items.
    """
    out: list[tuple[int, str | None, AltoPage]] = []
    for seq, page_el in enumerate(_page_els(content)):
        title = page_el.get("title") or ""
        m = _PAGE_ID_RE.search(page_el.get("id") or "")
        leaf = int(m.group(1)) if m else seq
        out.append((leaf, page_image_name(title),
                    _page_from_el(page_el, _BLOCK_CLASSES_TESSERACT,
                                   keep_confidence=True)))
    return out


def parse_hocr_multipage(content: bytes) -> list[tuple[int, AltoPage]]:
    """Parse a monolithic hOCR file (IA's `{id}_hocr.html`).

    Returns (leaf_number, AltoPage) pairs in document order. The leaf
    number is taken from each page div's `id="page_N"`; sequence order
    is the fallback when the id is absent or unparseable. Pages with no
    text are still returned (empty text_blocks) so callers get page
    dims for every leaf.
    """
    out: list[tuple[int, AltoPage]] = []
    for seq, page_el in enumerate(_page_els(content)):
        m = _PAGE_ID_RE.search(page_el.get("id") or "")
        leaf = int(m.group(1)) if m else seq
        out.append((leaf, _page_from_el(page_el, _BLOCK_CLASSES_TESSERACT,
                                          keep_confidence=True)))
    return out
