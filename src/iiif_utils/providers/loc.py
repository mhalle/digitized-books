"""Library of Congress adapter.

LoC publishes IIIF Image (level 2) at tile.loc.gov but does NOT expose
a IIIF Presentation manifest at a clean URL. Instead, the per-item
`?fo=json` payload at `loc.gov/item/{lccn}/` carries all the structural
info needed to assemble a manifest in memory:

  resources[0].files[] — ordered list of canvases; each canvas is a
                          list of file alternatives (jpg sizes, jp2,
                          optional alto.xml, optional .txt)
  resources[0].pdf     — whole-work PDF
  resources[0].fulltext_file — whole-work plain text (sometimes)

This module accepts LCCNs / item URLs, fetches the JSON, and returns a
synthesized IIIF v2 manifest dict via `ManifestRef.manifest_payload`.
"""
from __future__ import annotations

import re
from typing import Any

from iiif_utils.core import http as http_

# LCCN patterns we accept:
#   - 8-10 pure digits  ('49043519', '2021667096')
#   - 1-3 lowercase letters + 6+ digits ('a33000991', 'mm12345678')
# Excluded: anything matching a Wellcome b-number (b + 7 digits + digit/x).
LCCN_PURE_DIGIT_RE = re.compile(r"^\d{8,10}$")
LCCN_PREFIXED_RE = re.compile(r"^[a-z]{1,3}\d{6,9}$")
WELLCOME_B_RE = re.compile(r"^b\d{7}[\dx]$")
ITEM_URL_RE = re.compile(r"https?://(?:www\.)?loc\.gov/item/([a-z0-9]+)/?")


def looks_like_lccn(ref: str) -> bool:
    """Heuristic: LCCN-style identifier, excluding Wellcome b-numbers."""
    if WELLCOME_B_RE.match(ref):
        return False
    return bool(LCCN_PURE_DIGIT_RE.match(ref) or LCCN_PREFIXED_RE.match(ref))


def parse_ref(ref: str) -> str | None:
    """Return the LCCN from a user-supplied ref, or None."""
    if looks_like_lccn(ref):
        return ref
    m = ITEM_URL_RE.match(ref)
    return m.group(1) if m else None


# IIIF Image API service URL is embedded in the image/jpeg URLs:
#   https://tile.loc.gov/image-services/iiif/<service>/full/pct:100/0/default.jpg
_SERVICE_RE = re.compile(
    r"(https?://tile\.loc\.gov/image-services/iiif/[^/]+)/[^/]+/[^/]+/[^/]+/[^/]+$"
)


def _service_base_from_jpg(url: str) -> str | None:
    """Strip /{region}/{size}/{rotation}/{quality}.{format} → service base."""
    m = _SERVICE_RE.match(url)
    return m.group(1) if m else None


def _build_canvas(idx: int, files_for_canvas: list[dict[str, Any]],
                   lccn: str) -> dict[str, Any] | None:
    """Build one IIIF v2 sc:Canvas from one entry of resources[0].files[]."""
    service_base: str | None = None
    image_jpg: str | None = None
    alto_url: str | None = None
    text_url: str | None = None
    jp2_url: str | None = None

    for f in files_for_canvas:
        mt = (f.get("mimetype") or "").lower()
        url = f.get("url") or ""
        if not url:
            continue
        if mt == "image/jpeg":
            base = _service_base_from_jpg(url)
            if base and not service_base:
                service_base = base
                image_jpg = url
        elif mt == "image/jp2" and not jp2_url:
            jp2_url = url
        elif mt == "text/xml" and ".alto.xml" in url.lower():
            alto_url = url
        elif mt == "text/plain":
            text_url = url

    if not service_base:
        return None  # no image — skip; should be rare

    canvas_id = f"https://www.loc.gov/item/{lccn}/canvas/{idx}"
    image_id = image_jpg or service_base + "/full/full/0/default.jpg"

    see_also: list[dict[str, Any]] = []
    if alto_url:
        see_also.append({
            "@id": alto_url,
            "format": "text/xml",
            "profile": "http://www.loc.gov/standards/alto/v3/alto.xsd",
            "label": "ALTO XML (LoC)",
        })
    if text_url:
        see_also.append({
            "@id": text_url,
            "format": "text/plain",
            "label": "Plain text (LoC)",
        })

    canvas: dict[str, Any] = {
        "@id": canvas_id,
        "@type": "sc:Canvas",
        "label": str(idx + 1),
        # LoC doesn't ship canvas dims in the item JSON; use placeholders
        # like NLM does. Real pixel dims live in the IIIF info.json (which
        # we'd fetch lazily for --padding clamping if ever needed).
        "width": 99999,
        "height": 99999,
        "images": [{
            "@type": "oa:Annotation",
            "motivation": "sc:painting",
            "on": canvas_id,
            "resource": {
                "@id": image_id,
                "@type": "dctypes:Image",
                "service": {
                    "@id": service_base,
                    "@context": "http://iiif.io/api/image/2/context.json",
                    "profile": "http://iiif.io/api/image/2/level2.json",
                },
            },
        }],
    }
    if see_also:
        canvas["seeAlso"] = see_also
    return canvas


def synthesize_manifest(lccn: str, item_json: dict[str, Any]) -> dict[str, Any]:
    """Build a IIIF v2 manifest from LoC item JSON."""
    item = item_json.get("item") or {}
    resources = item_json.get("resources") or []
    if not resources:
        raise ValueError(
            f"LoC item {lccn} has no resources — no digitized scans available."
        )
    resource = resources[0]
    file_groups = resource.get("files") or []

    canvases: list[dict[str, Any]] = []
    for idx, group in enumerate(file_groups):
        cv = _build_canvas(idx, group, lccn)
        if cv:
            canvases.append(cv)

    title = item.get("title") or f"LoC item {lccn}"

    metadata: list[dict[str, Any]] = []
    for key, label in [
        ("date", "Date"),
        ("contributor_names", "Contributors"),
        ("subject", "Subjects"),
        ("language", "Languages"),
        ("location_str", "Location"),
        ("call_number", "Call number"),
        ("library_of_congress_control_number", "LCCN"),
    ]:
        v = item.get(key)
        if v:
            if isinstance(v, list):
                v = " | ".join(str(x) for x in v)
            metadata.append({"label": label, "value": str(v)})

    rendering: list[dict[str, Any]] = []
    pdf = resource.get("pdf")
    if pdf:
        rendering.append({
            "@id": pdf,
            "format": "application/pdf",
            "label": "PDF",
        })
    fulltext = resource.get("fulltext_file")
    if fulltext and isinstance(fulltext, str) and fulltext.startswith("http"):
        rendering.append({
            "@id": fulltext,
            "format": "text/plain",
            "label": "Plain text (whole work)",
        })

    manifest: dict[str, Any] = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@id": f"https://www.loc.gov/item/{lccn}/manifest.json",
        "@type": "sc:Manifest",
        "label": title,
        "metadata": metadata,
        "sequences": [{
            "@id": f"https://www.loc.gov/item/{lccn}/sequence/normal",
            "@type": "sc:Sequence",
            "canvases": canvases,
        }],
    }
    if rendering:
        manifest["rendering"] = rendering
    return manifest


def fetch_item_json(lccn: str, *, cfg_http: dict[str, Any],
                     cache_dir: Any) -> dict[str, Any]:
    url = f"https://www.loc.gov/item/{lccn}/?fo=json"
    return http_.fetch_json(url, cfg_http=cfg_http, cache_dir=cache_dir)


def extra_metadata_from_item(item_json: dict[str, Any]) -> dict[str, str]:
    """Pull the few high-value catalog fields into document_metadata."""
    item = item_json.get("item") or {}
    out: dict[str, str] = {}
    if item.get("title"):
        out["catalogue_title"] = item["title"]
    if item.get("date"):
        out["catalogue_date"] = str(item["date"])
    if item.get("contributor_names"):
        v = item["contributor_names"]
        out["catalogue_contributors"] = " | ".join(str(x) for x in v)
    if item.get("subject"):
        v = item["subject"]
        out["catalogue_subjects"] = " | ".join(str(x) for x in v)
    if item.get("language"):
        v = item["language"]
        out["catalogue_languages"] = " | ".join(str(x) for x in v)
    if item.get("call_number"):
        v = item["call_number"]
        out["identifier:loc-call-number"] = (
            " | ".join(str(x) for x in v) if isinstance(v, list) else str(v)
        )
    if item.get("library_of_congress_control_number"):
        out["identifier:lccn"] = str(item["library_of_congress_control_number"])
    return out
