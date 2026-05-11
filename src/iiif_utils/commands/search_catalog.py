"""`iiif-utils search-catalog` (alias `search-cat`) — discovery via a
provider's catalog API.

Currently only Wellcome is wired. The generic provider has no
catalog endpoint and raises a clear error.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.utils import output as output_

ACCESS_CHOICES = ("open", "restricted", "safeguarded",
                  "licensed-resources", "permission-required")


def _parse_year(spec: str) -> tuple[str | None, str | None]:
    """Parse '1914' / '1900-1950' / '1900-' / '-1950' into Wellcome's
    YYYY-MM-DD form. Single year → Jan 1 → Dec 31.

    Returns (from, to). None means open-ended on that side.
    """
    spec = spec.strip()
    if not spec:
        return None, None

    def _from(year: str) -> str:
        return f"{year}-01-01"

    def _to(year: str) -> str:
        return f"{year}-12-31"

    if "-" not in spec:
        return _from(spec), _to(spec)
    a, b = spec.split("-", 1)
    return (_from(a) if a else None, _to(b) if b else None)


@click.command(name="search-catalog")
@click.option("-q", "--query", default=None, help="Full-text query string.")
@click.option("--year", default=None,
              help="Year or range: '1914', '1900-1950', '1900-', '-1950'.")
@click.option("--creator", default=None,
              help="contributors.agent.label substring.")
@click.option("--subject", default=None, help="subjects.label substring.")
@click.option("--language", "languages", multiple=True,
              help="ISO 639-3 code (repeatable): eng, ger, fre, ...")
@click.option("--work-type", "work_type", default=None,
              help="Single-letter format code: a=books, d=journals, "
                   "h=archives, ...")
@click.option("--license", "license_id", default=None,
              help="items.locations.license: pdm, cc-by, cc-by-nc, ...")
@click.option("--has-iiif", is_flag=True, default=False,
              help="Restrict to works with a IIIF Presentation location.")
@click.option("--access", "access_status",
              type=click.Choice(ACCESS_CHOICES), default=None,
              help="items.locations.accessConditions.status.")
@click.option("-l", "--limit", type=int, default=20, help="Page size (1-100).")
@click.option("--page", type=int, default=1, help="1-indexed page number.")
@click.option("--sort-by-date", "sort_by_date", is_flag=True, default=False,
              help="Sort by production.dates instead of relevance.")
@click.option("--sort-desc", is_flag=True, default=False,
              help="Descending sort (default: ascending).")
@click.option("-P", "--provider", default="wellcome",
              help="Provider key (only 'wellcome' wired in v1).")
@output_.format_option(default="table")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def search_catalog(query: str | None, year: str | None, creator: str | None,
                 subject: str | None, languages: tuple[str, ...],
                 work_type: str | None, license_id: str | None,
                 has_iiif: bool, access_status: str | None,
                 limit: int, page: int, sort_by_date: bool, sort_desc: bool,
                 provider: str, fmt: str,
                 config_path: Path | None) -> None:
    """Search a provider's catalogue for works."""
    if provider != "wellcome":
        raise click.ClickException(
            f"Provider {provider!r} has no catalogue search wired in v1. "
            "Use 'wellcome' or pass a manifest URL directly to "
            "`iiif-utils create-index`."
        )

    cfg = load_config(config_path)
    cfg_http = cfg.get("http", {})
    catalogue_api = cfg["providers"]["wellcome"]["catalogue_api"]

    params: list[tuple[str, str]] = [
        ("pageSize", str(max(1, min(100, limit)))),
        ("page", str(max(1, page))),
        ("include", "identifiers,items,production,contributors,languages"),
    ]
    if query:
        params.append(("query", query))
    if year:
        y_from, y_to = _parse_year(year)
        if y_from:
            params.append(("production.dates.from", y_from))
        if y_to:
            params.append(("production.dates.to", y_to))
    if creator:
        params.append(("contributors.agent.label", creator))
    if subject:
        params.append(("subjects.label", subject))
    for lang in languages:
        params.append(("languages", lang))
    if work_type:
        params.append(("workType", work_type))
    if license_id:
        params.append(("items.locations.license", license_id))
    if has_iiif:
        params.append(("items.locations.locationType", "iiif-presentation"))
    if access_status:
        params.append(("items.locations.accessConditions.status",
                        access_status))
    if sort_by_date:
        params.append(("sort", "production.dates"))
        params.append(("sortOrder", "desc" if sort_desc else "asc"))

    url = f"{catalogue_api}/works"
    # httpx builds the query string from params via the params= kwarg, but
    # our shared fetch helper takes a fully-built URL. Build it here.
    from urllib.parse import urlencode
    full = f"{url}?{urlencode(params)}"

    payload = http_.fetch_json(full, cfg_http=cfg_http)
    results = payload.get("results", [])

    rows = [_summarize(r) for r in results]
    output_.write_records(rows, fmt=fmt)

    if fmt in ("table", "records") and payload.get("totalResults"):
        total = payload["totalResults"]
        shown = len(rows)
        page_total = payload.get("totalPages", "?")
        click.echo(
            f"\n  page {page}/{page_total} — showing {shown} of {total} hits",
            err=True,
        )


def _summarize(work: dict[str, Any]) -> dict[str, Any]:
    """Pull the columns most useful for picking-a-work-to-index."""
    title = work.get("title", "")
    work_id = work.get("id", "")

    # b-number from sierra-system-number
    bnum = None
    for ident in work.get("identifiers", []):
        if ident.get("identifierType", {}).get("id") == "sierra-system-number":
            bnum = ident.get("value")
            break

    # year — first production date label
    year = None
    for p in work.get("production", []):
        for d in p.get("dates", []):
            if d.get("label"):
                year = d["label"]
                break
        if year:
            break

    contribs = " | ".join(
        c.get("agent", {}).get("label", "") for c in work.get("contributors", [])
    ) or None

    langs = " | ".join(
        lng.get("label", "") for lng in work.get("languages", [])
    ) or None

    # IIIF manifest URL (rewriting v2 path → v3 per WELLCOME_NOTES)
    manifest_url = None
    license_id = None
    access = None
    for it in work.get("items", []):
        for loc in it.get("locations", []):
            if loc.get("locationType", {}).get("id") == "iiif-presentation":
                raw = loc.get("url", "")
                manifest_url = re.sub(r"/presentation/v2/", "/presentation/", raw)
                lic = loc.get("license") or {}
                license_id = lic.get("id")
                for ac in loc.get("accessConditions", []):
                    ass = ac.get("status") or {}
                    if ass.get("id"):
                        access = ass["id"]
                        break
                break
        if manifest_url:
            break

    return {
        "id": work_id,
        "b_number": bnum,
        "year": year,
        "title": title[:60] + ("…" if len(title) > 60 else ""),
        "contributors": contribs,
        "languages": langs,
        "license": license_id,
        "access": access,
        "manifest_url": manifest_url,
    }
