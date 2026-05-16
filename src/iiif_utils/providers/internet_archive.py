"""Internet Archive (archive.org) IIIF adapter.

IA publishes a IIIF v3 Presentation manifest for every item at
`https://iiif.archive.org/iiif/{identifier}/manifest.json`. The manifest
is well-formed and carries:

  - per-canvas Image API v3 service URLs (level 2)
  - top-level `seeAlso` pointing at item metadata, page_numbers.json,
    hocr_pageindex.json.gz, MARC, scandata, etc.
  - `metadata` block with title/creator/subject/date/etc.

What it does NOT carry — and why this provider is intentionally thin:

  - **No per-canvas hOCR seeAlso.** IA's hOCR is one monolithic file
    (`{id}_hocr.html`) addressed by leaf number via the page index, not
    split into per-page URLs. The iiif-utils indexing pipeline expects
    per-canvas OCR URLs in `seeAlso`, so `create-index` against an IA
    manifest will produce a text-less index.

    For full-text indexing of IA items, use the sibling **ia-utils**
    package, which consumes IA's native fast-path (searchtext +
    pageindex) and handles the DjVu fallback for older items.

  - This provider supports viewing / cropping / region extraction /
    mosaics — i.e. the IIIF-side jobs — for IA items.

Accepted inputs:

  - Bare identifier:           `anatomyofhumanbo1918gray`
  - Details URL:               `https://archive.org/details/{id}`
  - Download URL:              `https://archive.org/download/{id}/...`
  - IIIF manifest URL:         `https://iiif.archive.org/iiif/{id}/manifest.json`
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from iiif_utils.core import http as http_

# IA identifiers are case-sensitive ASCII: letters, digits, ., _, -.
# Length 1-100. We require at least 3 chars and one alphanumeric.
# This is permissive on purpose; we never apply this heuristic to bare
# refs (see _guess_provider in providers/__init__.py). It's used only to
# validate identifiers parsed out of URLs.
IA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$")

DETAILS_URL_RE = re.compile(
    r"https?://(?:www\.)?archive\.org/details/([^/?#]+)"
)
DOWNLOAD_URL_RE = re.compile(
    r"https?://(?:www\.)?archive\.org/download/([^/?#]+)"
)
IIIF_MANIFEST_URL_RE = re.compile(
    r"https?://iiif\.archive\.org/iiif/([^/$?#]+)(?:\$\d+)?/manifest(?:\.json)?"
)


def looks_like_ia_id(ref: str) -> bool:
    """Permissive identifier check — used for URL-parsed IDs, not bare refs."""
    return bool(IA_ID_RE.match(ref))


def parse_ref(ref: str) -> str | None:
    """Return the IA identifier from a user-supplied ref, or None.

    Accepts bare identifiers only when explicitly attributed to this
    provider (the dispatcher in providers/__init__.py never calls us
    with a bare ref unless `--provider ia` was passed).
    """
    for pat in (IIIF_MANIFEST_URL_RE, DETAILS_URL_RE, DOWNLOAD_URL_RE):
        m = pat.match(ref)
        if m:
            ident = m.group(1)
            return ident if looks_like_ia_id(ident) else None
    if ref.startswith(("http://", "https://")):
        return None
    return ref if looks_like_ia_id(ref) else None


def manifest_url_for(identifier: str) -> str:
    return f"https://iiif.archive.org/iiif/{identifier}/manifest.json"


def _flatten_v3_value(val: Any) -> str | None:
    """v3 metadata values are LangMaps: {lang: [str, ...]}. Flatten."""
    if val is None:
        return None
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        parts = [str(x) for x in val if x]
        return " | ".join(parts) if parts else None
    if isinstance(val, dict):
        joined: list[str] = []
        for vs in val.values():
            if isinstance(vs, list):
                joined.extend(str(x) for x in vs if x)
            elif vs:
                joined.append(str(vs))
        return " | ".join(joined) if joined else None
    return str(val)


# seeAlso entries on the IA manifest worth surfacing as document
# metadata. Maps a substring match against the `id` URL to a stable key.
_SEEALSO_KEYS = (
    ("_page_numbers.json", "ia_page_numbers_url"),
    ("_hocr_pageindex.json", "ia_hocr_pageindex_url"),
    ("_hocr.html", "ia_hocr_url"),
    ("_hocr_searchtext.txt", "ia_hocr_searchtext_url"),
    ("_djvu.xml", "ia_djvu_xml_url"),
    ("_scandata.xml", "ia_scandata_url"),
    ("_meta.xml", "ia_meta_xml_url"),
    ("_marc.xml", "ia_marc_xml_url"),
    ("/metadata/", "ia_metadata_api_url"),
)


def extra_metadata_for(manifest: dict[str, Any],
                        identifier: str) -> dict[str, str]:
    """Pull useful fields out of the manifest into doc-metadata.

    Mirrors the shape used by other providers — flat `key: str` dict.
    Also captures the IA-specific derivative URLs from top-level seeAlso,
    which downstream callers (or ia-utils) can hand off without re-fetching
    the manifest.
    """
    out: dict[str, str] = {
        "identifier:ia": identifier,
        "ia_details_url": f"https://archive.org/details/{identifier}",
    }

    # Flatten v3 `metadata` block.
    for entry in manifest.get("metadata", []) or []:
        if not isinstance(entry, dict):
            continue
        lab = _flatten_v3_value(entry.get("label"))
        val = _flatten_v3_value(entry.get("value"))
        if lab and val:
            out[f"manifest_metadata:{lab}"] = val

    # Capture useful derivative URLs from top-level seeAlso.
    for entry in manifest.get("seeAlso", []) or []:
        if not isinstance(entry, dict):
            continue
        sid = entry.get("id") or entry.get("@id") or ""
        if not isinstance(sid, str):
            continue
        for needle, key in _SEEALSO_KEYS:
            if needle in sid and key not in out:
                out[key] = sid
                break

    return out


def fetch_manifest(identifier: str, *, cfg_http: dict[str, Any],
                    cache_dir: Any) -> dict[str, Any]:
    """Fetch the IA IIIF manifest. No augmentation."""
    return http_.fetch_json(manifest_url_for(identifier),
                              cfg_http=cfg_http, cache_dir=cache_dir)


def is_ia_host(url: str) -> bool:
    """True if this URL is an IA-hosted (details/download/iiif) URL."""
    host = urlparse(url).hostname or ""
    return host in ("archive.org", "www.archive.org", "iiif.archive.org")
