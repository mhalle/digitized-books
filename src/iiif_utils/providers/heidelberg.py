"""Heidelberg University Library (digi.ub.uni-heidelberg.de) adapter.

Heidelberg publishes IIIF v2 Presentation manifests at a clean URL pattern
and exposes per-page ALTO XML — but the ALTO URL is **not** advertised in
the manifest's canvas-level `seeAlso`. Instead, the manifest has a
manifest-level `seeAlso` pointing at a METS XML, and METS's `FULLTEXT`
fileGrp lists one ALTO URL per physical image. This adapter:

1. Fetches the manifest from `digi.ub.uni-heidelberg.de/diglit/iiif/<stem>/manifest.json`
2. Fetches the METS XML from the manifest's `seeAlso` link
3. Parses METS `FULLTEXT` fileGrp to get one ALTO URL per page
4. Maps canvas index → ALTO URL (METS file order == canvas order, both
   reflecting physical-image-number ordering — verified empirically for
   Bourgery 1832bd2)
5. Injects each ALTO URL as a canvas `seeAlso`

The augmented manifest is returned via `ManifestRef.manifest_payload` —
same mechanism as the LoC and MDZ adapters.

Heidelberg cataloging quirk: text volumes use the stem `bourgery...`
(two r's) while atlas volumes use `bourgey...` (one r) — a typo
preserved in Heidelberg's permalinks. Both spellings are accepted by
this adapter unchanged.
"""
from __future__ import annotations

import re
from typing import Any

from lxml import etree  # type: ignore[attr-defined]

from iiif_utils.core import http as http_

# Heidelberg diglit stems are <word><year>bd<vol>_<part>, where word is
# typically "bourgery"/"bourgey" but in general any lowercase letters.
# Examples: bourgey1832bd1_1, bourgery1844bd3_1, place1867bd1, eko2,
# cpg642. Be permissive — Heidelberg uses thousands of stems across
# their collections.
STEM_RE = re.compile(r"^[a-z][a-z0-9]+(_\d+)?$")
MANIFEST_URL_RE = re.compile(
    r"https?://digi\.ub\.uni-heidelberg\.de/diglit/(?:iiif/)?"
    r"([a-z][a-z0-9_]+?)(?:/manifest\.json)?/?$"
)

IIIF_BASE = "https://digi.ub.uni-heidelberg.de"
METS_NS = {"mets": "http://www.loc.gov/METS/",
            "xlink": "http://www.w3.org/1999/xlink"}


def looks_like_heidelberg_stem(ref: str) -> bool:
    """Heuristic — Heidelberg stems collide with too many other ID
    formats (Wellcome work IDs, LCCNs) to auto-detect without -P. So this
    only returns True for stems with the obvious `bdN_M` segment that
    marks a Heidelberg-format multi-volume work; the generic stem
    detector is left to the explicit `-P heidelberg` path.
    """
    return bool(STEM_RE.match(ref) and re.search(r"bd\d+_\d+$", ref))


def parse_ref(ref: str) -> str | None:
    """Return the diglit stem from a user-supplied ref, or None."""
    if STEM_RE.match(ref):
        return ref
    m = MANIFEST_URL_RE.match(ref)
    return m.group(1) if m else None


def manifest_url_for(stem: str) -> str:
    return f"{IIIF_BASE}/diglit/iiif/{stem}/manifest.json"


def _mets_url_from_manifest(manifest: dict[str, Any]) -> str | None:
    """Pull the METS XML URL from the manifest-level seeAlso.

    Heidelberg's manifest-level seeAlso is a string URL (v2 polymorphism),
    not the {id, format, profile} object form. Normalize.
    """
    sa = manifest.get("seeAlso")
    if sa is None:
        return None
    if isinstance(sa, str):
        return sa
    if isinstance(sa, dict):
        url = sa.get("@id") or sa.get("id")
        return str(url) if url else None
    if isinstance(sa, list):
        for entry in sa:
            if isinstance(entry, str):
                return entry
            if isinstance(entry, dict):
                url = entry.get("@id") or entry.get("id")
                if url:
                    return str(url)
    return None


def parse_mets_alto_urls(mets_bytes: bytes) -> list[str]:
    """Return the ordered list of ALTO URLs from a METS FULLTEXT fileGrp.

    Order matches METS file order, which matches manifest canvas order
    (both are driven by physical-image-number ascending).
    """
    root = etree.fromstring(mets_bytes)
    fg = root.xpath(
        ".//mets:fileGrp[@USE='FULLTEXT']", namespaces=METS_NS,
    )
    if not fg:
        return []
    urls: list[str] = []
    for floc in fg[0].xpath(".//mets:FLocat", namespaces=METS_NS):
        href = floc.get("{http://www.w3.org/1999/xlink}href")
        if href:
            urls.append(href)
    return urls


def inject_alto_urls(manifest: dict[str, Any],
                     alto_urls: list[str]) -> dict[str, Any]:
    """Mutate manifest in place: add ALTO seeAlso per canvas. Returns it.

    If `len(alto_urls)` doesn't match the canvas count, we inject only as
    many as align by index and skip the rest — partial coverage is fine
    (the indexer will warn about canvases without ALTO).
    """
    seqs = manifest.get("sequences") or []
    if not seqs:
        return manifest
    canvases = seqs[0].get("canvases", [])
    for i, c in enumerate(canvases):
        if i >= len(alto_urls):
            break
        alto_entry = {
            "@id": alto_urls[i],
            "format": "text/xml",
            "profile": "http://www.loc.gov/standards/alto/ns-v2#",
            "label": "ALTO (Heidelberg)",
        }
        existing = c.get("seeAlso")
        if existing is None:
            c["seeAlso"] = [alto_entry]
        elif isinstance(existing, dict):
            c["seeAlso"] = [existing, alto_entry]
        elif isinstance(existing, str):
            # v2 polymorphism: seeAlso can be a bare URL string. The
            # manifest-level seeAlso we saw uses this shape; canvases
            # might too on older Heidelberg manifests. Normalize.
            c["seeAlso"] = [
                {"@id": existing, "format": "application/xml"},
                alto_entry,
            ]
        elif isinstance(existing, list):
            existing.append(alto_entry)
            c["seeAlso"] = existing
    return manifest


def fetch_and_augment(stem: str, *, cfg_http: dict[str, Any],
                      cache_dir: Any) -> dict[str, Any]:
    """Fetch the IIIF manifest, fetch the linked METS, inject ALTO URLs."""
    manifest = http_.fetch_json(
        manifest_url_for(stem), cfg_http=cfg_http, cache_dir=cache_dir,
    )
    mets_url = _mets_url_from_manifest(manifest)
    if mets_url is None:
        # No METS = no per-page OCR exposure. Return manifest as-is and
        # let create-index produce an image-only index (the indexer's
        # "no OCR found" warning will fire).
        return manifest
    mets_bytes = http_.fetch_bytes(
        mets_url, cfg_http=cfg_http, cache_dir=cache_dir, suffix=".mets.xml",
    )
    alto_urls = parse_mets_alto_urls(mets_bytes)
    if alto_urls:
        inject_alto_urls(manifest, alto_urls)
    return manifest


def extra_metadata_for(manifest: dict[str, Any], stem: str) -> dict[str, str]:
    """Pull a few catalog fields from manifest.metadata into doc-metadata."""
    out: dict[str, str] = {"identifier:heidelberg_diglit": stem}
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
            joined: list[str] = []
            for vs in val.values():
                if isinstance(vs, list):
                    joined.extend(str(x) for x in vs)
            val = " | ".join(joined) if joined else None
        if val:
            label = str(lab)
            out[f"manifest_metadata:{label}"] = str(val)
    return out
