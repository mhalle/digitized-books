"""Gallica (Bibliothèque nationale de France) adapter.

Gallica publishes IIIF v2 Presentation manifests under a clean URL
pattern and exposes per-page ALTO XML — but the ALTO URL is **not**
advertised in the manifest's `seeAlso`. Instead, ALTO is served from a
separate endpoint keyed by ARK + folio number:

    https://gallica.bnf.fr/RequestDigitalElement?O=<ark>&E=ALTO&Deb=<N>

where N is 1-indexed and matches the canvas `@id` suffix (e.g.
`.../canvas/f50`). This adapter:

1. Fetches the manifest from
   `https://gallica.bnf.fr/iiif/ark:/12148/<ark>/manifest.json`
2. Injects an ALTO `seeAlso` per canvas pointing at the
   RequestDigitalElement endpoint above.

The augmented manifest is returned via `ManifestRef.manifest_payload`
— same mechanism the LoC, MDZ, and Heidelberg adapters use.

Gallica's ARK identifiers use the NAAN `12148` and a stem made of
lowercase alphanumerics (e.g. `bpt6k323992j`, `btv1b8602717r`,
`cb34378485f`). Stems vary in length and prefix by collection; this
adapter accepts any `^[a-z0-9]+$`. Inputs accepted:

  - bare ARK stem: `bpt6k323992j`
  - ARK URI: `ark:/12148/bpt6k323992j`
  - presentation URL: `https://gallica.bnf.fr/ark:/12148/bpt6k323992j`
  - IIIF manifest URL: `https://gallica.bnf.fr/iiif/ark:/12148/<ark>/manifest.json`

Gallica 403s on the default `curl/...` User-Agent — `iiif-utils` sends
its own UA via `core.http`, so this is handled at the HTTP layer.
"""
from __future__ import annotations

import re
from typing import Any

from iiif_utils.core import http as http_

IIIF_BASE = "https://gallica.bnf.fr"
ARK_NAAN = "12148"
ALTO_URL_TMPL = (
    "https://gallica.bnf.fr/RequestDigitalElement"
    "?O={ark}&E=ALTO&Deb={n}"
)

# Gallica ARK stems are lowercase alphanumerics, typically 9-16 chars.
# Be permissive: 6+ chars to admit unusual collections, no upper bound.
ARK_STEM_RE = re.compile(r"^[a-z0-9]{6,}$")
ARK_URI_RE = re.compile(r"^ark:/" + ARK_NAAN + r"/([a-z0-9]+)$")
URL_RE = re.compile(
    r"^https?://gallica\.bnf\.fr"
    r"(?:/iiif)?/ark:/" + ARK_NAAN + r"/([a-z0-9]+)"
    r"(?:/manifest\.json)?/?$"
)
# Canvas @id suffix is `/canvas/f<N>` — Gallica's folio-numbered scheme.
CANVAS_FOLIO_RE = re.compile(r"/canvas/f(\d+)$")


def parse_ref(ref: str) -> str | None:
    """Return the Gallica ARK stem from a user-supplied ref, or None."""
    if ARK_STEM_RE.match(ref):
        return ref
    m = ARK_URI_RE.match(ref)
    if m:
        return m.group(1)
    m = URL_RE.match(ref)
    if m:
        return m.group(1)
    return None


def manifest_url_for(ark: str) -> str:
    return f"{IIIF_BASE}/iiif/ark:/{ARK_NAAN}/{ark}/manifest.json"


def _folio_number_for_canvas(canvas: dict[str, Any], fallback: int) -> int:
    """Extract the folio number from a canvas `@id`.

    Returns `fallback` (1-indexed position in the sequence) when the
    canvas `@id` doesn't match Gallica's expected pattern — rare but
    possible if Gallica revises canvas URI shapes.
    """
    cid = canvas.get("@id") or canvas.get("id") or ""
    m = CANVAS_FOLIO_RE.search(cid)
    if m:
        return int(m.group(1))
    return fallback


def inject_alto_urls(manifest: dict[str, Any], ark: str) -> dict[str, Any]:
    """Mutate manifest in place: add an ALTO `seeAlso` per canvas.

    Returns the same dict for chaining. Each canvas gets:

      seeAlso += [{"@id": "https://.../RequestDigitalElement?O=<ark>&E=ALTO&Deb=<N>",
                    "format": "text/xml",
                    "profile": "http://www.loc.gov/standards/alto/ns-v3#"}]

    Gallica serves ALTO v3 per the `xsi:schemaLocation` in the XML we
    see at probe time. The core ALTO parser handles both v2 and v3 via
    namespace-based dispatch (see `iiif_utils/core/alto.py`).

    Existing canvas `seeAlso` entries are preserved and normalized into
    a list — same v2 polymorphism handled in `core/manifest.py`.
    """
    seqs = manifest.get("sequences") or []
    if not seqs:
        return manifest
    canvases = seqs[0].get("canvases", [])
    for i, c in enumerate(canvases, start=1):
        n = _folio_number_for_canvas(c, fallback=i)
        alto_entry = {
            "@id": ALTO_URL_TMPL.format(ark=ark, n=n),
            "format": "text/xml",
            "profile": "http://www.loc.gov/standards/alto/ns-v3#",
            "label": "ALTO (Gallica)",
        }
        existing = c.get("seeAlso")
        if existing is None:
            c["seeAlso"] = [alto_entry]
        elif isinstance(existing, dict):
            c["seeAlso"] = [existing, alto_entry]
        elif isinstance(existing, str):
            c["seeAlso"] = [
                {"@id": existing, "format": "application/xml"},
                alto_entry,
            ]
        elif isinstance(existing, list):
            existing.append(alto_entry)
            c["seeAlso"] = existing
    return manifest


def fetch_and_augment(ark: str, *, cfg_http: dict[str, Any],
                       cache_dir: Any) -> dict[str, Any]:
    """Fetch the Gallica manifest and inject per-canvas ALTO seeAlso URLs."""
    url = manifest_url_for(ark)
    manifest = http_.fetch_json(url, cfg_http=cfg_http, cache_dir=cache_dir)
    return inject_alto_urls(manifest, ark)


def extra_metadata_for(manifest: dict[str, Any], ark: str) -> dict[str, str]:
    """Pull catalog fields from manifest.metadata into doc-metadata."""
    out: dict[str, str] = {
        "identifier:gallica_ark": ark,
        "identifier:ark": f"ark:/{ARK_NAAN}/{ark}",
    }
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
            out[f"manifest_metadata:{lab}"] = str(val)
    return out
