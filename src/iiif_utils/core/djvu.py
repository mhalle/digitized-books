"""DjVu XML parsing — whole-book fallback OCR for older IA items.

IA items scanned before the hOCR era carry a single `{id}_djvu.xml`
derivative holding OCR for every page. Structure per page:

    <OBJECT width="W" height="H" ...>
      <HIDDENTEXT><PAGECOLUMN><REGION>
        <PARAGRAPH>
          <LINE>
            <WORD coords="left,bottom,right,top[,baseline]"
                  x-confidence="NN">text</WORD>
    ...

AXIS ORDER WARNING (WORD_GEOMETRY_PLAN §9.1): DjVu coords are
`left,bottom,right,top` in top-left-origin pixel space — bottom is the
numerically LARGER y. Convert here, once, to the x0,y0,x1,y1
(left-top-right-bottom) convention every other parser uses; downstream
code must never see raw DjVu order.

Ported from `ia-utils/core/parser.py::parse_djvu_xml`, with two
upgrades: block bboxes are computed from word coords (ia-utils left
them NULL), and pages come back as (leaf, AltoPage) pairs compatible
with `core.alto` / `core.hocr` so downstream ingest doesn't branch.
Adapted to lxml.etree.iterparse streaming (the files run to tens of MB).
"""
from __future__ import annotations

import re
from io import BytesIO
from statistics import mean

from lxml import etree  # type: ignore[attr-defined]

from iiif_utils.core.alto import AltoPage, TextBlock
from iiif_utils.core.wordgeom import PageWords, Word

# `usemap="{identifier}_0533.djvu"` — DjVu's own 1-based leaf-file number.
_USEMAP_RE = re.compile(r"_(\d+)\.djvu\s*$")


def djvu_alignment_warning(pages: list[tuple[int, AltoPage]],
                            n_canvases: int) -> str | None:
    """Flag DjVu leaf numbering that can't be trusted against canvases.

    Observed on real items: `assessedpollscit1965newt` has 1166 DjVu
    OBJECTs numbered 1..1168 (a gap at 293-294) while its hOCR has 1170
    contiguous pages — so the page holding a known record sits at DjVu
    leaf 532 but hOCR leaf 533. `ecturesondiseas00chargoog` is
    contiguous and the two agree. There is no single offset that fixes
    both, so when the shapes disagree we say so rather than silently
    attaching text to the wrong images.
    """
    if not pages:
        return None
    leaves = [leaf for leaf, _ in pages]
    contiguous = leaves == list(range(leaves[0], leaves[0] + len(leaves)))
    if contiguous and len(pages) == n_canvases:
        return None
    return (f"DjVu leaf numbering is uncorroborated: {len(pages)} OCR "
            f"pages (leaves {leaves[0]}-{leaves[-1]}"
            f"{'' if contiguous else ', non-contiguous'}) vs "
            f"{n_canvases} canvases. Text may be offset against images; "
            f"prefer an item with hOCR, or spot-check a known page.")


def _int_or(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def parse_djvu_multipage(content: bytes) -> list[tuple[int, AltoPage]]:
    """Parse a whole-book `_djvu.xml` into (leaf, AltoPage) pairs.

    Leaf numbers come from each OBJECT's `usemap="{id}_NNNN.djvu"` —
    the scan FILE number, used verbatim. That is the same key
    `internet_archive.canvas_leaf_map` reads out of each canvas's Image
    API URL, so the two join directly.

    An earlier version subtracted 1 here to "convert to a 0-based leaf",
    which silently put every DjVu-sourced book one page out against its
    images once the canvas map landed. Do not reintroduce that: the file
    number is the identifier, not an ordinal to renormalise.

    Sequence position is the fallback when usemap is absent or
    unparseable (ia-utils used position unconditionally).

    **Leaf alignment here is not guaranteed** — see
    `djvu_alignment_warning`. DjVu files can be sparse, and DjVu leaf
    numbering is an independent sequence from the hOCR page ids that
    the rest of the IA path uses; the two were observed to disagree.
    This is why DjVu stays a fallback for items with no hOCR at all.

    Granularity: one TextBlock per PARAGRAPH, block_type='ocr_par',
    bbox = word-bbox union, avg_confidence = mean of per-word
    `x-confidence` when present.
    """
    out: list[tuple[int, AltoPage]] = []
    context = etree.iterparse(BytesIO(content), events=("end",),
                               tag="OBJECT")
    for pos, (_event, obj) in enumerate(context):
        m = _USEMAP_RE.search(obj.get("usemap") or "")
        leaf = int(m.group(1)) if m else pos
        page_w = _int_or(obj.get("width"))
        page_h = _int_or(obj.get("height"))

        blocks: list[TextBlock] = []
        page_words: list[Word] = []
        words_per_line: list[int] = []
        for para in obj.iter("PARAGRAPH"):
            words: list[str] = []
            confs: list[int] = []
            # bbox union in converted (x0,y0,x1,y1) space
            bx0 = by0 = bx1 = by1 = None
            for line_el in para.iter("LINE"):
                n_in_line = 0
                for word in line_el.iter("WORD"):
                    if not word.text:
                        continue
                    words.append(word.text)
                    wconf: int | None = None
                    conf = word.get("x-confidence")
                    if conf:
                        try:
                            wconf = int(conf)
                            confs.append(wconf)
                        except ValueError:
                            wconf = None
                    coords = (word.get("coords") or "").split(",")
                    if len(coords) < 4:
                        continue
                    try:
                        left, bottom, right, top = (int(c) for c in coords[:4])
                    except ValueError:
                        continue
                    # left,bottom,right,top → x0,y0,x1,y1 (see module doc)
                    x0, y0, x1, y1 = left, top, right, bottom
                    bx0 = x0 if bx0 is None else min(bx0, x0)
                    by0 = y0 if by0 is None else min(by0, y0)
                    bx1 = x1 if bx1 is None else max(bx1, x1)
                    by1 = y1 if by1 is None else max(by1, y1)
                    # DjVu gives coords + confidence but no font size.
                    page_words.append(Word(
                        text=word.text, x=x0, y=y0,
                        w=max(0, x1 - x0), h=max(0, y1 - y0),
                        conf=wconf, fsize=None,
                    ))
                    n_in_line += 1
                if n_in_line:
                    words_per_line.append(n_in_line)

            text = " ".join(words)
            if not text.strip():
                continue
            line_count = sum(1 for _ in para.iter("LINE"))
            blocks.append(TextBlock(
                block_number=len(blocks),
                alto_id=None,
                text=text,
                line_count=line_count,
                word_count=len(words),
                length=len(text),
                bbox_x0=bx0 if bx0 is not None else 0,
                bbox_y0=by0 if by0 is not None else 0,
                bbox_x1=bx1 if bx1 is not None else 0,
                bbox_y1=by1 if by1 is not None else 0,
                avg_confidence=mean(confs) if confs else None,
                block_type="ocr_par",
            ))

        out.append((leaf, AltoPage(
            page_w=page_w,
            page_h=page_h,
            measurement_unit="pixel",
            text_blocks=blocks,
            illustrations=[],
            words=(PageWords(words=page_words,
                              words_per_line=words_per_line)
                   if page_words else None),
        )))
        obj.clear()  # streaming: free the subtree as we go
    return out
