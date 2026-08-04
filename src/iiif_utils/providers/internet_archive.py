"""Internet Archive (archive.org) IIIF adapter.

IA publishes a IIIF v3 Presentation manifest for every item at
`https://iiif.archive.org/iiif/{identifier}/manifest.json`. The manifest
is well-formed and carries:

  - per-canvas Image API v3 service URLs (level 2)
  - top-level `seeAlso` pointing at item metadata, page_numbers.json,
    hocr_pageindex.json.gz, MARC, scandata, etc.
  - `metadata` block with title/creator/subject/date/etc.

What it does NOT carry: per-canvas OCR seeAlso. IA's OCR is one
monolithic file per book — `{id}_hocr.html` (modern items) or
`{id}_djvu.xml` (older scans) — not per-page URLs. This adapter
surfaces those whole-book URLs in extra metadata (`ia_hocr_url`,
`ia_djvu_xml_url`, ...) and `create-index` consumes them through its
monolithic branch: one fetch, one multipage parse, the same
text_blocks/FTS shape as every other provider. So IA items get full
support — viewing / cropping / region extraction / mosaics AND
full-text indexing.

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


# IA derivative files worth surfacing as document metadata, matched by
# filename suffix (optionally gzipped) against the URL's basename.
#
# These are split across BOTH manifest arrays, and not the way you'd
# guess: `seeAlso` carries the metadata sidecars (pageindex, page
# numbers, MARC, scandata) while the OCR payloads we actually index
# from — `_hocr.html`, `_djvu.xml` — arrive in `rendering`. Scan both.
_DERIVATIVE_KEYS = (
    ("_page_numbers.json", "ia_page_numbers_url"),
    ("_hocr_pageindex.json", "ia_hocr_pageindex_url"),
    ("_hocr_searchtext.txt", "ia_hocr_searchtext_url"),
    ("_hocr.html", "ia_hocr_url"),
    ("_djvu.xml", "ia_djvu_xml_url"),
    ("_djvu.txt", "ia_djvu_txt_url"),
    ("_scandata.xml", "ia_scandata_url"),
    ("_meta.xml", "ia_meta_xml_url"),
    ("_marc.xml", "ia_marc_xml_url"),
    (".pdf", "ia_pdf_url"),
)


def _derivative_key(url: str) -> str | None:
    """Map a derivative URL to its stable metadata key, if recognized.

    Matches on the basename so `_chocr.html.gz` can never be mistaken
    for `_hocr.html`, and tolerates a trailing `.gz` (IA gzips some
    derivatives and not others, inconsistently across items).
    """
    base = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    if base.endswith(".gz"):
        base = base[:-3]
    for suffix, key in _DERIVATIVE_KEYS:
        if base.endswith(suffix):
            return key
    return None


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

    # Capture useful derivative URLs from BOTH top-level arrays.
    for field in ("seeAlso", "rendering"):
        entries = manifest.get(field) or []
        if isinstance(entries, dict):        # tolerate single-dict form
            entries = [entries]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            sid = entry.get("id") or entry.get("@id") or ""
            if not isinstance(sid, str) or not sid:
                continue
            if "/metadata/" in sid:
                out.setdefault("ia_metadata_api_url", sid)
                continue
            key = _derivative_key(sid)
            if key:
                out.setdefault(key, sid)

    return out


# The scan file number embedded in every canvas's Image API URL, e.g.
# `..._jp2%2Fanatomyofhumanbo1918gray_0688.jp2` -> leaf 688. Older items
# use `_tif`.
_LEAF_IN_URL_RE = re.compile(r"_(\d+)\.(?:jp2|tif|jpg)(?:$|[?#])",
                              re.IGNORECASE)


def canvas_leaf_map(canvases: list[Any]) -> dict[int, int]:
    """Map canvas index -> IA leaf number, or {} if not derivable.

    THE distinction this whole module has to get right. IA numbers every
    *leaf* it scanned, including scanner colour cards and leaves the
    operator marked `Delete`. The IIIF manifest contains only the leaves
    flagged `addToAccessFormats` in scandata, renumbered densely from 0 —
    so canvas N is generally NOT leaf N, and the gap grows through the
    book as exclusions accumulate. Gray 1918 has 1,414 leaves, 1,402
    canvases, and a canvas-to-leaf difference that walks 1, 3, 5, 7, 9.

    Everything else IA publishes is keyed by leaf: hOCR `page_N` ids,
    `_page_numbers.json` `leafNum`, the jp2/tif files, BookReader images.
    Storing any of it at a canvas index without this translation puts a
    page's text beside its neighbour's image, silently.

    The leaf number is recoverable because the Image API URL addresses
    the scan file directly, and the file number IS the leaf number.
    """
    out: dict[int, int] = {}
    for c in canvases:
        url = getattr(c, "image_service_url", None)
        if not url:
            continue
        m = _LEAF_IN_URL_RE.search(url)
        if m:
            out[c.index] = int(m.group(1))
    return out


def parse_scandata_access_leaves(content: bytes) -> list[int] | None:
    """Leaves IA includes in access formats, from `{id}_scandata.xml`.

    An independent second opinion on `canvas_leaf_map`: these are exactly
    the leaves that become canvases. Used to verify the URL-derived map
    rather than to replace it — two sources agreeing is what lets an
    item that breaks the pattern fail loudly instead of silently.
    """
    from lxml import etree  # type: ignore[attr-defined]
    try:
        root = etree.fromstring(content)
    except Exception:
        return None
    leaves: list[int] = []
    for pg in root.findall(".//page"):
        num = pg.get("leafNum")
        if num is None:
            continue
        flag = (pg.findtext("addToAccessFormats") or "").strip().lower()
        if flag != "false":
            try:
                leaves.append(int(num))
            except ValueError:
                continue
    return sorted(leaves) or None


def parse_page_numbers(content: bytes) -> dict[int, dict[str, Any]]:
    """Parse IA's `{id}_page_numbers.json` into {leaf_num: fields}.

    IA runs its own printed-page-number detector and publishes the
    result with per-leaf confidence. This is authoritative and must be
    preferred over IIIF canvas labels, which for IA are just sequential
    counters (leaf+1) — using them would mislabel every page in the
    book (verified on Gray 1918: leaf 24 is printed page 20, but its
    canvas label reads '25').

    `leafNum` uses the same numbering as the hOCR `page_N` ids and our
    canvas index. The array is sparse — leaves can be missing — so
    always map by leafNum, never by list position. Empty `pageNumber`
    (unnumbered plates, endpapers) becomes None.
    """
    import json
    payload = json.loads(content)
    pages = payload.get("pages") if isinstance(payload, dict) else payload
    out: dict[int, dict[str, Any]] = {}
    for entry in pages or []:
        if not isinstance(entry, dict):
            continue
        leaf = entry.get("leafNum")
        if not isinstance(leaf, int):
            continue
        num = (entry.get("pageNumber") or "").strip() or None
        out[leaf] = {
            "book_page_number": num,
            "confidence": entry.get("confidence"),
            "pageProb": entry.get("pageProb"),
            "wordConf": entry.get("wordConf"),
        }
    return out


def fetch_manifest(identifier: str, *, cfg_http: dict[str, Any],
                    cache_dir: Any) -> dict[str, Any]:
    """Fetch the IA IIIF manifest. No augmentation."""
    return http_.fetch_json(manifest_url_for(identifier),
                              cfg_http=cfg_http, cache_dir=cache_dir)


# IA serves page images two ways besides IIIF, and both matter when the
# IIIF Image endpoint refuses a request (it 400s on any upscale, and can
# fail outright on very large items).
BOOKREADER_SIZES = ("small", "medium", "large")


def bookreader_image_url(identifier: str, leaf: int,
                          size: str = "large") -> str:
    """IA's BookReader page image — `.../download/{id}/page/leaf{N}_{size}.jpg`.

    Keyed on the identifier and leaf number alone, so unlike the JP2 path
    it needs no knowledge of the item's internal zip naming. Sizes are
    IA's own three buckets, not pixel dimensions.
    """
    if size not in BOOKREADER_SIZES:
        raise ValueError(f"size must be one of {BOOKREADER_SIZES}")
    return (f"https://archive.org/download/{identifier}"
            f"/page/leaf{leaf}_{size}.jpg")


def bookreader_size_for(width: int | None) -> str:
    """Map a requested pixel width onto IA's three buckets."""
    if width is None:
        return "large"
    if width <= 400:
        return "small"
    if width <= 800:
        return "medium"
    return "large"


def jp2_url_from_service(service_url: str) -> str | None:
    """Original JP2 for a canvas, via IA's zip-as-directory download.

    IA serves individual members of a `_jp2.zip` without transferring the
    archive, so this is a single-file fetch. The path is recovered from
    the IIIF service URL rather than rebuilt from the identifier: the zip
    and its members are named after the item's *scan* prefix, which is
    often not the identifier — `1913-s.-s.-olympic-...` stores its pages
    under `1913 S.S. OLYMPIC White Star Line Postcard_jp2/`, so an
    identifier-derived guess 404s.

    Only the `%2F` separators are decoded; `%20` and friends stay encoded
    because they are part of the filenames.
    """
    marker = "/image/iiif/3/"
    if marker not in service_url:
        return None
    tail = service_url.split(marker, 1)[1]
    path = tail.replace("%2F", "/").replace("%2f", "/")
    if not path:
        return None
    return f"https://archive.org/download/{path}"


def is_ia_host(url: str) -> bool:
    """True if this URL is an IA-hosted (details/download/iiif) URL."""
    host = urlparse(url).hostname or ""
    return host in ("archive.org", "www.archive.org", "iiif.archive.org")
