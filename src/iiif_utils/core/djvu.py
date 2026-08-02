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

from io import BytesIO
from statistics import mean

from lxml import etree  # type: ignore[attr-defined]

from iiif_utils.core.alto import AltoPage, TextBlock


def _int_or(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def parse_djvu_multipage(content: bytes) -> list[tuple[int, AltoPage]]:
    """Parse a whole-book `_djvu.xml` into (leaf, AltoPage) pairs.

    Leaf numbers are assigned by OBJECT sequence order (0-based) —
    IA emits one OBJECT per leaf, in leaf order (same assumption
    ia-utils shipped with). Pages with no words are still returned so
    callers get page dims for every leaf.

    Granularity: one TextBlock per PARAGRAPH, block_type='ocr_par',
    bbox = word-bbox union, avg_confidence = mean of per-word
    `x-confidence` when present.
    """
    out: list[tuple[int, AltoPage]] = []
    context = etree.iterparse(BytesIO(content), events=("end",),
                               tag="OBJECT")
    for leaf, (_event, obj) in enumerate(context):
        page_w = _int_or(obj.get("width"))
        page_h = _int_or(obj.get("height"))

        blocks: list[TextBlock] = []
        for para in obj.iter("PARAGRAPH"):
            words: list[str] = []
            confs: list[int] = []
            # bbox union in converted (x0,y0,x1,y1) space
            bx0 = by0 = bx1 = by1 = None
            for word in para.iter("WORD"):
                if not word.text:
                    continue
                words.append(word.text)
                conf = word.get("x-confidence")
                if conf:
                    try:
                        confs.append(int(conf))
                    except ValueError:
                        pass
                coords = (word.get("coords") or "").split(",")
                if len(coords) >= 4:
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
        )))
        obj.clear()  # streaming: free the subtree as we go
    return out
