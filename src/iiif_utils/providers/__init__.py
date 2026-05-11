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
    """Result of resolving a user-supplied reference to a manifest.

    `manifest_payload` lets a provider supply a synthesized manifest
    (a dict) instead of a URL to fetch. Used by the LoC adapter, which
    builds an in-memory IIIF v2 manifest from the LoC item-level JSON.
    When set, `create-index` uses the payload directly.
    """
    manifest_url: str
    provider_key: str           # 'wellcome' | 'generic' | 'loc' | ...
    extra_metadata: dict[str, str]
    manifest_payload: dict[str, Any] | None = None


def resolve(ref: str, *, cfg: dict[str, Any], explicit_provider: str | None = None,
            cache_dir: Any = None) -> ManifestRef:
    """Resolve a user input to a ManifestRef.

    Inputs accepted:
      - HTTPS URL — if hostname matches a configured provider, attribute to it
      - Wellcome b-number (b + 7 digits + digit-or-x) — Wellcome only
      - Wellcome work ID — resolves via catalogue to a b-number, then manifest
      - LoC item URL or LCCN — synthesizes a manifest from item JSON
    """
    cfg_http = cfg.get("http", {})

    if explicit_provider:
        provider_key = explicit_provider
    else:
        provider_key = _guess_provider(ref, cfg)

    # LoC has no real manifest URL — even URL inputs need synthesis.
    if provider_key == "loc":
        return _resolve_loc(ref, cfg=cfg, cfg_http=cfg_http, cache_dir=cache_dir)

    # MDZ has manifests but no in-manifest OCR URLs — we fetch and inject.
    if provider_key == "mdz":
        return _resolve_mdz(ref, cfg=cfg, cfg_http=cfg_http, cache_dir=cache_dir)

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
        # LoC item URLs need the loc provider (synthesizes the manifest)
        if host and host.endswith("loc.gov") and "/item/" in ref:
            return "loc"
        # MDZ manifest URLs need the mdz provider (injects hOCR seeAlso)
        if host and host.endswith("digitale-sammlungen.de"):
            return "mdz"
        # Hostname → provider key, if any configured provider declares an iiif_base
        for key, p in (cfg.get("providers") or {}).items():
            base = p.get("iiif_base")
            if base and host == urlparse(base).hostname:
                return str(key)
        return str(cfg.get("default_provider", "generic"))
    if B_NUMBER_RE.match(ref):
        return "wellcome"
    # BSB IDs (MDZ): 'bsb' + 8-10 digits.
    from iiif_utils.providers import mdz as mdz_mod  # lazy: avoid cycle
    if mdz_mod.looks_like_bsb(ref):
        return "mdz"
    # LoC LCCN: pure-digit (8-10) or letter-prefixed digit string.
    # Check before the Wellcome work-id heuristic since pure-digit
    # strings like '49043519' look like work-ids too.
    from iiif_utils.providers import loc as loc_mod  # lazy: avoid cycle
    if loc_mod.looks_like_lccn(ref):
        return "loc"
    # Wellcome work IDs are 8 lowercase alphanumeric containing at least
    # one letter — heuristic.
    if re.match(r"^[a-z0-9]{8}$", ref) and re.search(r"[a-z]", ref):
        return "wellcome"
    return str(cfg.get("default_provider", "generic"))


def _resolve_mdz(ref: str, *, cfg: dict[str, Any], cfg_http: dict[str, Any],
                  cache_dir: Any) -> ManifestRef:
    from iiif_utils.providers import mdz as mdz_mod
    bsb = mdz_mod.parse_ref(ref)
    if not bsb:
        raise ValueError(
            f"Cannot extract MDZ BSB id from {ref!r} — pass a BSB id like "
            f"'bsb00056329' or a manifest URL like "
            f"'https://api.digitale-sammlungen.de/iiif/presentation/v2/"
            f"bsb00056329/manifest'."
        )
    manifest = mdz_mod.fetch_and_augment(bsb, cfg_http=cfg_http,
                                          cache_dir=cache_dir)
    extra = mdz_mod.extra_metadata_for(manifest, bsb)
    return ManifestRef(
        manifest_url=mdz_mod.manifest_url_for(bsb),
        provider_key="mdz",
        extra_metadata=extra,
        manifest_payload=manifest,
    )


def _resolve_loc(ref: str, *, cfg: dict[str, Any], cfg_http: dict[str, Any],
                  cache_dir: Any) -> ManifestRef:
    from iiif_utils.providers import loc as loc_mod
    lccn = loc_mod.parse_ref(ref)
    if not lccn:
        raise ValueError(
            f"Cannot extract LoC LCCN from {ref!r} — pass an LCCN like "
            f"'49043519' or a full URL like "
            f"'https://www.loc.gov/item/49043519/'."
        )
    item_json = loc_mod.fetch_item_json(lccn, cfg_http=cfg_http,
                                         cache_dir=cache_dir)
    manifest = loc_mod.synthesize_manifest(lccn, item_json)
    extra = loc_mod.extra_metadata_from_item(item_json)
    return ManifestRef(
        manifest_url=manifest["@id"],
        provider_key="loc",
        extra_metadata=extra,
        manifest_payload=manifest,
    )


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
