"""IIIF Presentation v2/v3 manifest parsing — provider-agnostic.

Functions take a manifest dict (as returned by `httpx.get(...).json()`)
and return normalized Python data. No I/O here, no DB writes — pure.
"""
from __future__ import annotations

from typing import Any
from dataclasses import dataclass


@dataclass(frozen=True)
class Canvas:
    index: int
    canvas_id: str
    label: str | None        # raw label string (first language-array element)
    image_id: str | None
    image_service_url: str | None
    image_api_version: str | None
    width: int | None
    height: int | None
    alto_url: str | None     # canvas-level ALTO seeAlso, if any
    text_url: str | None     # canvas-level plain-text seeAlso, if any
                              # (used as fallback when ALTO is absent;
                              # e.g. LoC items that have per-page .txt but
                              # no per-page ALTO)
    hocr_url: str | None     # canvas-level hOCR seeAlso, if any
                              # (used by MDZ — they emit hOCR not ALTO)


@dataclass(frozen=True)
class Rendering:
    url: str
    format: str | None
    label: str | None


@dataclass(frozen=True)
class RangeEntry:
    index: int
    range_id: str | None
    parent_id: str | None
    depth: int
    label: str | None
    behavior: str | None
    canvas_ids: list[str]


def label_string(label_obj: Any) -> str | None:
    """First-language-array element of a v3 label dict, or a plain string."""
    if label_obj is None:
        return None
    if isinstance(label_obj, str):
        return label_obj
    if isinstance(label_obj, dict):
        # v3: language map
        for lang in ("none", "en", "@none"):
            if lang in label_obj and label_obj[lang]:
                v = label_obj[lang][0]
                return str(v) if v is not None else None
        for v in label_obj.values():
            if isinstance(v, list) and v:
                return str(v[0])
            if isinstance(v, str):
                return v
    return None


def presentation_version(manifest: dict[str, Any]) -> str:
    """Return '3' or '2'."""
    ctx = manifest.get("@context")
    if isinstance(ctx, list):
        ctx_str = " ".join(c for c in ctx if isinstance(c, str))
    else:
        ctx_str = str(ctx) if ctx else ""
    if "presentation/3" in ctx_str:
        return "3"
    if "presentation/2" in ctx_str:
        return "2"
    # Default to v3 — modern Wellcome, Bodleian, etc.
    return "3"


def manifest_type(manifest: dict[str, Any]) -> str:
    return manifest.get("type") or manifest.get("@type") or "Manifest"


def _image_service_v3(canvas: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Walk v3 painting AnnotationPage → Annotation → body → service[].

    Return (service_base_url, image_id, image_api_version).
    """
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


def _image_service_v2(canvas: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Walk v2 images[] → resource → service."""
    images = canvas.get("images", [])
    for img in images:
        resource = img.get("resource") or {}
        image_id = resource.get("@id")
        svc = resource.get("service") or {}
        if isinstance(svc, list):
            svc = svc[0] if svc else {}
        if svc:
            base = svc.get("@id") or svc.get("id")
            prof = svc.get("profile") or ""
            if isinstance(prof, list):
                prof = " ".join(p for p in prof if isinstance(p, str))
            ver = "2" if "image/2" in prof else None
            return base, image_id, ver
        if image_id:
            return None, image_id, None
    return None, None, None


def _seealso_entries(canvas: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a canvas's `seeAlso` to a list of dicts.

    v2 allowed three shapes: a single dict, a list of dicts, or a list
    of strings. v3 standardized on a list of dicts. We normalize.
    """
    sa = canvas.get("seeAlso")
    if sa is None:
        return []
    if isinstance(sa, dict):
        return [sa]
    if isinstance(sa, list):
        return [s for s in sa if isinstance(s, dict)]
    return []


def _alto_seealso(canvas: dict[str, Any]) -> str | None:
    """Return canvas-level seeAlso URL with format=text/xml and profile ~alto."""
    for s in _seealso_entries(canvas):
        fmt = (s.get("format") or "").lower()
        prof_raw = s.get("profile") or ""
        prof = " ".join(prof_raw) if isinstance(prof_raw, list) else str(prof_raw)
        prof = prof.lower()
        if fmt in ("text/xml", "application/xml") and "alto" in prof:
            url = s.get("id") or s.get("@id")
            return str(url) if url else None
    return None


def _text_seealso(canvas: dict[str, Any]) -> str | None:
    """Return canvas-level seeAlso URL with format=text/plain, if any.

    Used as an OCR fallback when ALTO is not present per-canvas
    (e.g. LoC items expose `.txt` per page but not `.alto.xml`).
    """
    for s in _seealso_entries(canvas):
        fmt = (s.get("format") or "").lower()
        if fmt == "text/plain":
            url = s.get("id") or s.get("@id")
            return str(url) if url else None
    return None


def _hocr_seealso(canvas: dict[str, Any]) -> str | None:
    """Return canvas-level seeAlso URL pointing at hOCR, if any.

    Match on format `text/vnd.hocr+html` (preferred) or on a profile
    containing `hocr`.
    """
    for s in _seealso_entries(canvas):
        fmt = (s.get("format") or "").lower()
        prof_raw = s.get("profile") or ""
        prof = " ".join(prof_raw) if isinstance(prof_raw, list) else str(prof_raw)
        prof = prof.lower()
        if fmt == "text/vnd.hocr+html" or "hocr" in prof:
            url = s.get("id") or s.get("@id")
            return str(url) if url else None
    return None


def canvases(manifest: dict[str, Any]) -> list[Canvas]:
    """Return one Canvas per item in the manifest's sequence."""
    version = presentation_version(manifest)
    if version == "3":
        raw_canvases = manifest.get("items", [])
        image_service = _image_service_v3
    else:
        seqs = manifest.get("sequences", [])
        raw_canvases = (seqs[0].get("canvases", []) if seqs else [])
        image_service = _image_service_v2

    out: list[Canvas] = []
    for i, c in enumerate(raw_canvases):
        base, image_id, ver = image_service(c)
        out.append(Canvas(
            index=i,
            canvas_id=c.get("id") or c.get("@id") or "",
            label=label_string(c.get("label")),
            image_id=image_id,
            image_service_url=base,
            image_api_version=ver,
            width=c.get("width"),
            height=c.get("height"),
            alto_url=_alto_seealso(c),
            text_url=_text_seealso(c),
            hocr_url=_hocr_seealso(c),
        ))
    return out


def renderings(manifest: dict[str, Any]) -> list[Rendering]:
    """Manifest-level rendering entries (PDF, plain text, EPUB, …).

    IIIF v2 allowed either an object or a bare URL string here; v3
    standardized on objects. We accept either.
    """
    out: list[Rendering] = []
    for r in manifest.get("rendering", []) or []:
        if isinstance(r, str):
            out.append(Rendering(url=r, format=None, label=None))
            continue
        if not isinstance(r, dict):
            continue
        url = r.get("id") or r.get("@id")
        if not url:
            continue
        out.append(Rendering(
            url=url,
            format=r.get("format"),
            label=label_string(r.get("label")),
        ))
    return out


def metadata_entries(manifest: dict[str, Any]) -> dict[str, str]:
    """Flatten manifest.metadata[] into a key-value dict.

    Returns key prefixed with 'manifest_metadata:' to disambiguate from
    catalogue-derived metadata downstream.
    """
    out: dict[str, str] = {}
    for entry in manifest.get("metadata", []):
        key = label_string(entry.get("label"))
        val_obj = entry.get("value")
        if not key:
            continue
        if isinstance(val_obj, dict):
            joined: list[str] = []
            for v in val_obj.values():
                if isinstance(v, list):
                    joined.extend(str(x) for x in v)
                elif isinstance(v, str):
                    joined.append(v)
            if joined:
                out[f"manifest_metadata:{key}"] = " | ".join(joined)
        elif isinstance(val_obj, str):
            out[f"manifest_metadata:{key}"] = val_obj
    return out


def ranges(manifest: dict[str, Any]) -> list[RangeEntry]:
    """Parse manifest.structures[] into flat RangeEntry rows.

    v3: structures is an array of Range objects with `items` that are
    Canvas references or nested Ranges.
    """
    out: list[RangeEntry] = []
    structures = manifest.get("structures", [])
    counter = [0]

    def walk(r: dict[str, Any], parent_id: str | None, depth: int) -> None:
        rid = r.get("id") or r.get("@id")
        canvas_ids: list[str] = []
        for item in r.get("items", []):
            t = item.get("type") or item.get("@type") or ""
            if t == "Canvas" or (isinstance(item.get("id"), str)
                                  and "/canvases/" in item.get("id", "")):
                canvas_ids.append(item.get("id") or item.get("@id"))
            elif t == "Range":
                pass  # handled by recursion below
        out.append(RangeEntry(
            index=counter[0],
            range_id=rid,
            parent_id=parent_id,
            depth=depth,
            label=label_string(r.get("label")),
            behavior=(", ".join(r.get("behavior", []))
                       if isinstance(r.get("behavior"), list)
                       else r.get("behavior")),
            canvas_ids=canvas_ids,
        ))
        counter[0] += 1
        for item in r.get("items", []):
            t = item.get("type") or item.get("@type") or ""
            if t == "Range":
                walk(item, rid, depth + 1)

    for r in structures:
        walk(r, None, 0)
    return out
