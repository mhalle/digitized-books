"""ALTO XML parsing — TextBlocks + Illustrations.

Targets Wellcome's ALTO v2 (served despite ALTO-v3 profile string).
See docs/DESIGN.md §3.5 for the schema mapping rationale.
"""
from __future__ import annotations

from dataclasses import dataclass

from lxml import etree  # type: ignore[attr-defined]

# Wellcome serves ALTO v2 (despite the manifest seeAlso advertising ALTO v3).
# The namespace MUST match what's in the document.
ALTO_NS_V2 = "http://www.loc.gov/standards/alto/ns-v2#"
ALTO_NS_V3 = "http://www.loc.gov/standards/alto/ns-v3#"


@dataclass(frozen=True)
class TextBlock:
    block_number: int
    alto_id: str | None
    text: str
    line_count: int
    word_count: int
    length: int
    bbox_x0: int
    bbox_y0: int
    bbox_x1: int
    bbox_y1: int
    # Optional extras — populated by the monolithic-hOCR / DjVu parsers
    # (IA path). ALTO and per-canvas hOCR leave them None: Wellcome ALTO
    # has no confidence, and the MDZ path preserves its documented
    # NULL-confidence invariant (see core/hocr.py).
    avg_confidence: float | None = None
    block_type: str | None = None


@dataclass(frozen=True)
class Illustration:
    illustration_number: int
    alto_id: str | None
    illustration_type: str   # 'Illustration' | 'GraphicalElement'
    bbox_x0: int
    bbox_y0: int
    bbox_x1: int
    bbox_y1: int


@dataclass(frozen=True)
class AltoPage:
    page_w: int
    page_h: int
    measurement_unit: str | None
    text_blocks: list[TextBlock]
    illustrations: list[Illustration]


def _ns_of(root: etree._Element) -> str:
    """Return the ALTO namespace actually in use."""
    tag: str = str(root.tag)
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ALTO_NS_V2  # default


def _ns_map(root: etree._Element) -> dict[str, str]:
    return {"a": _ns_of(root)}


def _line_text(line: etree._Element, ns: str) -> str:
    parts: list[str] = []
    for ch in line:
        local = etree.QName(ch).localname
        if local == "String":
            c = ch.get("CONTENT")
            if c:
                parts.append(c)
    return " ".join(parts)


def _block_text(block: etree._Element, nsm: dict[str, str]) -> str:
    ns = nsm["a"]
    lines = block.findall("a:TextLine", nsm)
    return " ".join(t for t in (_line_text(line, ns) for line in lines) if t)


def parse_alto_bytes(content: bytes) -> AltoPage:
    """Parse ALTO XML from bytes. Idempotent, pure."""
    root = etree.fromstring(content)
    return _parse(root)


def parse_alto_path(path: str) -> AltoPage:
    root = etree.parse(path).getroot()
    return _parse(root)


def _parse(root: etree._Element) -> AltoPage:
    nsm = _ns_map(root)

    page_el = root.find(".//a:Page", nsm)
    page_w = int(page_el.get("WIDTH", 0)) if page_el is not None else 0
    page_h = int(page_el.get("HEIGHT", 0)) if page_el is not None else 0
    mu_el = root.find(".//a:MeasurementUnit", nsm)
    munit = mu_el.text if mu_el is not None else None

    text_blocks: list[TextBlock] = []
    for bn, b in enumerate(root.findall(".//a:TextBlock", nsm)):
        try:
            hpos = int(b.get("HPOS", 0))
            vpos = int(b.get("VPOS", 0))
            width = int(b.get("WIDTH", 0))
            height = int(b.get("HEIGHT", 0))
        except (TypeError, ValueError):
            continue
        text = _block_text(b, nsm)
        lines = b.findall("a:TextLine", nsm)
        strings = b.findall(".//a:String", nsm)
        text_blocks.append(TextBlock(
            block_number=bn,
            alto_id=b.get("ID"),
            text=text,
            line_count=len(lines),
            word_count=len(strings),
            length=len(text),
            bbox_x0=hpos,
            bbox_y0=vpos,
            bbox_x1=hpos + width,
            bbox_y1=vpos + height,
        ))

    illustrations: list[Illustration] = []
    n = 0
    for kind in ("Illustration", "GraphicalElement"):
        for el in root.findall(f".//a:{kind}", nsm):
            try:
                hpos = int(el.get("HPOS", 0))
                vpos = int(el.get("VPOS", 0))
                width = int(el.get("WIDTH", 0))
                height = int(el.get("HEIGHT", 0))
            except (TypeError, ValueError):
                continue
            illustrations.append(Illustration(
                illustration_number=n,
                alto_id=el.get("ID"),
                illustration_type=kind,
                bbox_x0=hpos,
                bbox_y0=vpos,
                bbox_x1=hpos + width,
                bbox_y1=vpos + height,
            ))
            n += 1

    return AltoPage(
        page_w=page_w,
        page_h=page_h,
        measurement_unit=munit,
        text_blocks=text_blocks,
        illustrations=illustrations,
    )
