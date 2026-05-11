"""Munich Digitisation Centre (MDZ / Bayerische Staatsbibliothek) adapter.

MDZ publishes IIIF v2 Presentation manifests at a clean URL pattern
and exposes hOCR per canvas — but the hOCR URL is **not** advertised
in the manifest's `seeAlso`. This adapter:

1. Fetches the manifest as-is from `api.digitale-sammlungen.de`.
2. Injects per-canvas hOCR `seeAlso` entries pointing at
   `https://api.digitale-sammlungen.de/ocr/{bsb_id}/{N}` (N is
   1-indexed canvas count).

The augmented manifest is passed back to `create-index` via
`ManifestRef.manifest_payload`, the same mechanism the LoC adapter uses.
"""
from __future__ import annotations

import re
from typing import Any

from iiif_utils.core import http as http_

# BSB ID: 'bsb' + 8-10 digits. We've seen bsb00056329 (8), bsb11107655 (8).
BSB_RE = re.compile(r"^bsb\d{8,10}$")
MANIFEST_URL_RE = re.compile(
    r"https?://api\.digitale-sammlungen\.de/iiif/presentation/v\d+/"
    r"(bsb\d{8,10})(?:_\d+)?/manifest"
)
OCR_URL_TMPL = "https://api.digitale-sammlungen.de/ocr/{bsb_id}/{n}"


def looks_like_bsb(ref: str) -> bool:
    return bool(BSB_RE.match(ref))


def parse_ref(ref: str) -> str | None:
    """Return the BSB ID from a user-supplied ref, or None."""
    if looks_like_bsb(ref):
        return ref
    m = MANIFEST_URL_RE.match(ref)
    return m.group(1) if m else None


def manifest_url_for(bsb_id: str) -> str:
    return (f"https://api.digitale-sammlungen.de/iiif/presentation/v2/"
            f"{bsb_id}/manifest")


def inject_hocr_urls(manifest: dict[str, Any], bsb_id: str) -> dict[str, Any]:
    """Mutate a manifest in place: add a hOCR `seeAlso` entry per canvas.

    Returns the same dict for chaining. Each canvas gets:

      seeAlso += [{"@id": "https://.../ocr/{bsb_id}/{N}",
                    "format": "text/vnd.hocr+html",
                    "profile": "http://kba.github.io/hocr-spec/1.2/"}]

    where N is 1-indexed canvas count. Existing `seeAlso` entries are
    preserved (and normalized to a list if they were a single dict —
    same v2 polymorphism handled in core/manifest.py).
    """
    seqs = manifest.get("sequences") or []
    if not seqs:
        return manifest
    canvases = seqs[0].get("canvases", [])
    for i, c in enumerate(canvases, start=1):
        hocr_entry = {
            "@id": OCR_URL_TMPL.format(bsb_id=bsb_id, n=i),
            "format": "text/vnd.hocr+html",
            "profile": "http://kba.github.io/hocr-spec/1.2/",
            "label": "hOCR (MDZ)",
        }
        existing = c.get("seeAlso")
        if existing is None:
            c["seeAlso"] = [hocr_entry]
        elif isinstance(existing, dict):
            c["seeAlso"] = [existing, hocr_entry]
        elif isinstance(existing, list):
            existing.append(hocr_entry)
            c["seeAlso"] = existing
    return manifest


def fetch_and_augment(bsb_id: str, *, cfg_http: dict[str, Any],
                      cache_dir: Any) -> dict[str, Any]:
    """Fetch the MDZ manifest and inject hOCR seeAlso URLs."""
    url = manifest_url_for(bsb_id)
    manifest = http_.fetch_json(url, cfg_http=cfg_http, cache_dir=cache_dir)
    return inject_hocr_urls(manifest, bsb_id)


def extra_metadata_for(manifest: dict[str, Any], bsb_id: str) -> dict[str, str]:
    """Pull a few catalog fields from manifest.metadata into doc-metadata."""
    out: dict[str, str] = {"identifier:bsb": bsb_id}
    # MDZ's manifest.metadata is a list of {label, value} pairs — values
    # can be string or LangMap. Use a generic flattener.
    for entry in manifest.get("metadata", []) or []:
        if not isinstance(entry, dict):
            continue
        lab = entry.get("label")
        val = entry.get("value")
        if not lab:
            continue
        if isinstance(val, list):
            val = " | ".join(str(x) for x in val)
        elif isinstance(val, dict):
            # v3-style LangMap
            joined: list[str] = []
            for vs in val.values():
                if isinstance(vs, list):
                    joined.extend(str(x) for x in vs)
            val = " | ".join(joined) if joined else None
        if val:
            label = str(lab) if isinstance(lab, str) else str(lab)
            out[f"manifest_metadata:{label}"] = str(val)
    return out
