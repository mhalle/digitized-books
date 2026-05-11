"""Build morris.sqlite from the cached manifest + ALTO files.

Schema follows docs/DESIGN.md (key tables only — manifest_raw,
index_metadata, document_metadata, archive_files, page_numbers,
text_blocks, illustrations) plus FTS5 over text_blocks and per-page
aggregated pages_fts.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import sqlite_utils
from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ALTO_DIR = DATA / "alto"
DB_PATH = ROOT / "morris.sqlite"

NS = {"a": "http://www.loc.gov/standards/alto/ns-v2#"}
ALTO_PROFILE_SUBSTR = "alto"


def label_str(label_obj) -> str | None:
    if isinstance(label_obj, dict):
        for lang in ("none", "en", "@none"):
            if lang in label_obj and label_obj[lang]:
                return label_obj[lang][0]
        for v in label_obj.values():
            if isinstance(v, list) and v:
                return v[0]
        return None
    if isinstance(label_obj, str):
        return label_obj
    return None


def alto_seealso(canvas: dict) -> str | None:
    for s in canvas.get("seeAlso", []):
        fmt = (s.get("format") or "").lower()
        prof = (s.get("profile") or "").lower()
        if fmt in ("text/xml", "application/xml") and ALTO_PROFILE_SUBSTR in prof:
            return s.get("id") or s.get("@id")
    return None


def image_service(canvas: dict) -> tuple[str | None, str | None, str | None]:
    """Return (service_url, image_id, image_api_version)."""
    for ap in canvas.get("items", []):
        for ann in ap.get("items", []):
            body = ann.get("body") or {}
            image_id = body.get("id")
            services = body.get("service") or []
            if isinstance(services, dict):
                services = [services]
            for svc in services:
                stype = svc.get("type") or svc.get("@type") or ""
                if "ImageService" in stype:
                    base = svc.get("id") or svc.get("@id")
                    ver = "2" if "2" in stype else ("3" if "3" in stype else None)
                    return base, image_id, ver
            if image_id:
                return None, image_id, None
    return None, None, None


def reconstruct_line_text(line: etree._Element) -> str:
    parts: list[str] = []
    for ch in line:
        tag = etree.QName(ch).localname
        if tag == "String":
            c = ch.get("CONTENT")
            if c:
                parts.append(c)
    return " ".join(parts)


def reconstruct_block_text(block: etree._Element) -> str:
    lines = [reconstruct_line_text(l) for l in block.findall("a:TextLine", NS)]
    return " ".join(t for t in lines if t)


def parse_alto(path: Path):
    """Yield TextBlock rows + Illustration rows for one ALTO page."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    page = root.find(".//a:Page", NS)
    page_w = int(page.get("WIDTH", 0)) if page is not None else 0
    page_h = int(page.get("HEIGHT", 0)) if page is not None else 0
    measurement_unit_el = root.find(".//a:MeasurementUnit", NS)
    munit = measurement_unit_el.text if measurement_unit_el is not None else None
    # We assume "pixel" — if not, the bboxes would need conversion. Flag.
    if munit and munit != "pixel":
        print(f"WARN: non-pixel MeasurementUnit ({munit}) in {path.name}")

    text_rows = []
    for bn, block in enumerate(root.findall(".//a:TextBlock", NS)):
        try:
            hpos = int(block.get("HPOS", 0))
            vpos = int(block.get("VPOS", 0))
            width = int(block.get("WIDTH", 0))
            height = int(block.get("HEIGHT", 0))
        except (TypeError, ValueError):
            continue
        text = reconstruct_block_text(block)
        lines = block.findall("a:TextLine", NS)
        text_rows.append({
            "block_number": bn,
            "hocr_id": f"{path.name}#{block.get('ID')}",  # mirror IA hocr_id slot
            "block_type": "ocr_textblock",
            "language": None,
            "text_direction": None,
            "bbox_x0": hpos,
            "bbox_y0": vpos,
            "bbox_x1": hpos + width,
            "bbox_y1": vpos + height,
            "text": text,
            "line_count": len(lines),
            "word_count": len(block.findall(".//a:String", NS)),
            "length": len(text),
            "avg_confidence": None,
            "avg_font_size": None,
            "parent_carea_id": None,
        })

    illus_rows = []
    for n, el in enumerate(
            root.findall(".//a:Illustration", NS)
            + root.findall(".//a:GraphicalElement", NS)):
        try:
            hpos = int(el.get("HPOS", 0))
            vpos = int(el.get("VPOS", 0))
            width = int(el.get("WIDTH", 0))
            height = int(el.get("HEIGHT", 0))
        except (TypeError, ValueError):
            continue
        illus_rows.append({
            "illustration_number": n,
            "bbox_x0": hpos,
            "bbox_y0": vpos,
            "bbox_x1": hpos + width,
            "bbox_y1": vpos + height,
            "illustration_type": etree.QName(el).localname,
            "alto_id": el.get("ID"),
        })

    return text_rows, illus_rows, page_w, page_h


def main() -> None:
    manifest = json.loads((DATA / "manifest.json").read_text())
    catalogue = json.loads((DATA / "catalogue.json").read_text())
    canvases = manifest.get("items", [])
    print(f"Manifest: {len(canvases)} canvases")

    if DB_PATH.exists():
        DB_PATH.unlink()
    db = sqlite_utils.Database(str(DB_PATH))

    # index_metadata
    now = datetime.now(timezone.utc).isoformat()
    db["index_metadata"].insert_all([
        {"key": k, "value": v} for k, v in [
            ("slug", "morris-anatomy-1914-b21212600"),
            ("created_at", now),
            ("index_mode", "alto"),
            ("provider", "wellcome"),
            ("provider_kind", "iiif"),
            ("manifest_url", manifest.get("id") or manifest.get("@id", "")),
            ("presentation_api_version", "3"),
            ("iiif_utils_experiment", "morris_index"),
        ]
    ], pk="key", replace=True)

    # document_metadata — pull from manifest + catalogue
    doc_meta = {}
    # Title from manifest label
    title = label_str(manifest.get("label"))
    if title:
        doc_meta["title"] = title
    # Rights, requiredStatement
    if manifest.get("rights"):
        doc_meta["rights"] = manifest["rights"]
    rs = manifest.get("requiredStatement")
    if rs:
        rs_val = label_str(rs.get("value"))
        if rs_val:
            doc_meta["required_statement"] = rs_val
    # Manifest-level metadata array
    for entry in manifest.get("metadata", []):
        key = label_str(entry.get("label"))
        val_obj = entry.get("value")
        if isinstance(val_obj, dict):
            for v in val_obj.values():
                if isinstance(v, list):
                    if key:
                        doc_meta[f"manifest_metadata:{key}"] = " | ".join(v)
        elif isinstance(val_obj, str) and key:
            doc_meta[f"manifest_metadata:{key}"] = val_obj
    # From catalogue
    doc_meta["catalogue_id"] = catalogue.get("id", "")
    if catalogue.get("title"):
        doc_meta["catalogue_title"] = catalogue["title"]
    for ident in catalogue.get("identifiers", []):
        idtype = ident.get("identifierType", {}).get("id", "")
        if idtype:
            doc_meta[f"identifier:{idtype}"] = ident.get("value", "")
    # Contributors
    contribs = [c.get("agent", {}).get("label", "")
                for c in catalogue.get("contributors", [])]
    if contribs:
        doc_meta["catalogue_contributors"] = " | ".join(filter(None, contribs))
    # Subjects
    subjects = [s.get("label", "") for s in catalogue.get("subjects", [])]
    if subjects:
        doc_meta["catalogue_subjects"] = " | ".join(filter(None, subjects))
    # Languages
    langs = [l.get("label", "") for l in catalogue.get("languages", [])]
    if langs:
        doc_meta["catalogue_languages"] = " | ".join(filter(None, langs))
    # Production dates
    prods = catalogue.get("production", [])
    if prods:
        dates = []
        for p in prods:
            for d in p.get("dates", []):
                if d.get("label"):
                    dates.append(d["label"])
        if dates:
            doc_meta["catalogue_production_dates"] = " | ".join(dates)

    db["document_metadata"].insert_all(
        [{"key": k, "value": v} for k, v in doc_meta.items()],
        pk="key", replace=True)

    # archive_files (renderings)
    af_rows = []
    for r in manifest.get("rendering", []):
        url = r.get("id") or r.get("@id")
        if not url:
            continue
        af_rows.append({
            "filename": url.rstrip("/").rsplit("/", 1)[-1],
            "format": r.get("format"),
            "size_bytes": None,
            "source_type": "rendering",
            "md5_checksum": None,
            "sha1_checksum": None,
            "crc32_checksum": None,
            "download_url": url,
        })
    if af_rows:
        db["archive_files"].insert_all(af_rows, pk="filename", replace=True)

    # page_numbers — for every canvas regardless of whether it has ALTO
    pn_rows = []
    for idx, canvas in enumerate(canvases):
        lab = label_str(canvas.get("label"))
        book_pn = None
        if lab and lab.strip() and not re.match(r"^-+$", lab.strip()):
            book_pn = lab.strip()
        svc, image_id, img_ver = image_service(canvas)
        pn_rows.append({
            "leaf_num": idx,
            "book_page_number": book_pn,
            "confidence": None,
            "pageProb": None,
            "wordConf": None,
            "canvas_id": canvas.get("id"),
            "canvas_label": lab,
            "image_id": image_id,
            "image_service_url": svc,
            "image_api_version": img_ver,
            "width": canvas.get("width"),
            "height": canvas.get("height"),
        })
    db["page_numbers"].insert_all(pn_rows, pk="leaf_num", replace=True)

    # text_blocks + illustrations
    print("Parsing ALTO files...")
    tb_rows = []
    il_rows = []
    parsed = 0
    no_alto = 0
    for idx, canvas in enumerate(canvases):
        alto_url = alto_seealso(canvas)
        if not alto_url:
            no_alto += 1
            continue
        asset = alto_url.rstrip("/").rsplit("/", 1)[-1]
        path = ALTO_DIR / f"{asset}.alto.xml"
        if not path.exists():
            print(f"  missing ALTO file for canvas {idx}: {path.name}")
            continue
        try:
            text_rows, illus_rows, page_w, page_h = parse_alto(path)
        except Exception as e:
            print(f"  parse error canvas {idx}: {e}")
            continue
        for r in text_rows:
            r["page_id"] = idx
            tb_rows.append(r)
        for r in illus_rows:
            r["page_id"] = idx
            il_rows.append(r)
        parsed += 1
        if parsed % 200 == 0:
            print(f"  parsed {parsed}/{len(canvases) - no_alto}")

    print(f"Parsed {parsed} ALTOs ({no_alto} canvases had no ALTO seeAlso)")
    print(f"  text_blocks rows: {len(tb_rows):,}")
    print(f"  illustrations rows: {len(il_rows):,}")

    if tb_rows:
        db["text_blocks"].insert_all(tb_rows, pk="hocr_id", replace=True,
                                      batch_size=500)
    if il_rows:
        db["illustrations"].insert_all(
            il_rows, pk=("page_id", "illustration_number"), replace=True,
            batch_size=500)

    # FTS over text_blocks
    print("Building FTS indexes...")
    db["text_blocks"].enable_fts(["text"], create_triggers=True,
                                  replace=True, tokenize="porter unicode61")
    # pages_fts: one row per page (group_concat)
    db.executescript("""
        DROP TABLE IF EXISTS pages_fts;
        CREATE VIRTUAL TABLE pages_fts USING fts5(
            page_text, page_id UNINDEXED, tokenize="porter unicode61"
        );
        INSERT INTO pages_fts(rowid, page_text, page_id)
        SELECT
            ROW_NUMBER() OVER (ORDER BY page_id),
            group_concat(text, ' '),
            page_id
        FROM text_blocks
        GROUP BY page_id;
    """)

    # manifest_raw
    db["manifest_raw"].insert_all([{
        "id": 1,
        "fetched_at": now,
        "etag": None,
        "body": (DATA / "manifest.json").read_text(),
    }], pk="id", replace=True)

    print(f"\nDB written: {DB_PATH}  ({DB_PATH.stat().st_size/1024/1024:.1f} MB)")
    # Summary
    print()
    print("Summary:")
    print(f"  index_metadata rows:    {db['index_metadata'].count}")
    print(f"  document_metadata rows: {db['document_metadata'].count}")
    print(f"  archive_files rows:     {db['archive_files'].count}")
    print(f"  page_numbers rows:      {db['page_numbers'].count}")
    print(f"  text_blocks rows:       {db['text_blocks'].count:,}")
    print(f"  illustrations rows:     {db['illustrations'].count:,}")
    print(f"  pages_fts rows:         "
          f"{db.execute('SELECT count(*) FROM pages_fts').fetchone()[0]:,}")


if __name__ == "__main__":
    main()
