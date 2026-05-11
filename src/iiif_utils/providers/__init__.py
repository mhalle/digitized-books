"""Provider dispatch — picks an adapter for a user-supplied reference."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from iiif_utils.core import http as http_

B_NUMBER_RE = re.compile(r"^b\d{7}[\dx]$", re.IGNORECASE)


@dataclass(frozen=True)
class ManifestRef:
    """Result of resolving a user-supplied reference to a manifest."""
    manifest_url: str
    provider_key: str           # 'wellcome' | 'generic'
    extra_metadata: dict[str, str]  # provider-specific document_metadata to merge


def resolve(ref: str, *, cfg: dict[str, Any], explicit_provider: str | None = None,
            cache_dir: Any = None) -> ManifestRef:
    """Resolve a user input to a ManifestRef.

    Inputs accepted:
      - HTTPS URL — if hostname matches a configured provider, attribute to it
      - Wellcome b-number (b + 7 digits + digit-or-x) — Wellcome only
      - Wellcome work ID — resolves via catalogue to a b-number, then to a manifest
    """
    cfg_http = cfg.get("http", {})

    if explicit_provider:
        provider_key = explicit_provider
    else:
        provider_key = _guess_provider(ref, cfg)

    if ref.startswith(("http://", "https://")):
        return ManifestRef(
            manifest_url=ref,
            provider_key=provider_key,
            extra_metadata={},
        )

    if provider_key == "wellcome":
        return _resolve_wellcome(ref, cfg=cfg, cfg_http=cfg_http, cache_dir=cache_dir)

    raise ValueError(
        f"Cannot resolve {ref!r} — pass a manifest URL or use a "
        f"provider-specific identifier (e.g. a Wellcome b-number)."
    )


def _guess_provider(ref: str, cfg: dict[str, Any]) -> str:
    if ref.startswith(("http://", "https://")):
        host = urlparse(ref).hostname or ""
        # Hostname → provider key, if any configured provider declares an iiif_base
        for key, p in (cfg.get("providers") or {}).items():
            base = p.get("iiif_base")
            if base and host == urlparse(base).hostname:
                return str(key)
        return str(cfg.get("default_provider", "generic"))
    if B_NUMBER_RE.match(ref):
        return "wellcome"
    # Wellcome work IDs are 8 lowercase alphanumeric — heuristic.
    if re.match(r"^[a-z0-9]{8}$", ref):
        return "wellcome"
    return str(cfg.get("default_provider", "generic"))


def _resolve_wellcome(ref: str, *, cfg: dict[str, Any], cfg_http: dict[str, Any],
                       cache_dir: Any) -> ManifestRef:
    iiif_base = cfg["providers"]["wellcome"]["iiif_base"]
    if B_NUMBER_RE.match(ref):
        return ManifestRef(
            manifest_url=f"{iiif_base}/presentation/{ref.lower()}",
            provider_key="wellcome",
            extra_metadata={},
        )

    # Otherwise assume it's a catalogue work ID: resolve to a b-number.
    catalogue_api = cfg["providers"]["wellcome"]["catalogue_api"]
    work_url = (f"{catalogue_api}/works/{ref}"
                f"?include=identifiers,items,subjects,contributors,production,languages")
    work = http_.fetch_json(work_url, cfg_http=cfg_http, cache_dir=cache_dir)

    # Prefer the b-number whose IIIF location is iiif-presentation.
    bnum: str | None = None
    for it in work.get("items", []):
        for loc in it.get("locations", []):
            if loc.get("locationType", {}).get("id") == "iiif-presentation":
                url = loc.get("url", "")
                m = re.search(r"/(b\d{7}[\dx])(?:$|[/?])", url)
                if m:
                    bnum = m.group(1)
                    break
        if bnum:
            break
    if not bnum:
        for ident in work.get("identifiers", []):
            if ident.get("identifierType", {}).get("id") == "sierra-system-number":
                bnum = ident.get("value")
                break
    if not bnum:
        raise ValueError(f"Wellcome work {ref!r} has no b-number / IIIF location.")

    extra = {
        "catalogue_id": work.get("id", ""),
        "catalogue_title": work.get("title", ""),
    }
    contribs = [c.get("agent", {}).get("label", "")
                for c in work.get("contributors", [])]
    if contribs:
        extra["catalogue_contributors"] = " | ".join(filter(None, contribs))
    subjects = [s.get("label", "") for s in work.get("subjects", [])]
    if subjects:
        extra["catalogue_subjects"] = " | ".join(filter(None, subjects))
    langs = [lang.get("label", "") for lang in work.get("languages", [])]
    if langs:
        extra["catalogue_languages"] = " | ".join(filter(None, langs))
    dates: list[str] = []
    for p in work.get("production", []):
        for d in p.get("dates", []):
            if d.get("label"):
                dates.append(d["label"])
    if dates:
        extra["catalogue_production_dates"] = " | ".join(dates)
    for ident in work.get("identifiers", []):
        idtype = ident.get("identifierType", {}).get("id", "")
        if idtype:
            extra[f"identifier:{idtype}"] = ident.get("value", "")

    return ManifestRef(
        manifest_url=f"{iiif_base}/presentation/{bnum}",
        provider_key="wellcome",
        extra_metadata=extra,
    )
