"""`iiif-utils search-catalog` (alias `search-cat`) — discovery via a
provider's catalog API.

Wellcome, LoC and Internet Archive are wired. The generic provider has
no catalog endpoint and raises a clear error.
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
@click.option("--collection", "collections", multiple=True,
              help="Collection identifier (repeatable). Internet Archive "
                   "only; ignored by other providers.")
@click.option("-P", "--provider", default="wellcome",
              type=click.Choice(["wellcome", "loc", "ia"]),
              help="Provider key. wellcome | loc | ia.")
@output_.format_option(default="table")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def search_catalog(query: str | None, year: str | None, creator: str | None,
                 subject: str | None, languages: tuple[str, ...],
                 work_type: str | None, license_id: str | None,
                 has_iiif: bool, access_status: str | None,
                 limit: int, page: int, sort_by_date: bool, sort_desc: bool,
                 collections: tuple[str, ...], provider: str, fmt: str,
                 config_path: Path | None) -> None:
    """Search a provider's catalog for works."""
    cfg = load_config(config_path)
    cfg_http = cfg.get("http", {})

    if provider == "ia":
        _search_ia(
            query=query, year=year, creator=creator, subject=subject,
            languages=languages, collections=collections,
            work_type=work_type, has_iiif=has_iiif, limit=limit, page=page,
            sort_by_date=sort_by_date, sort_desc=sort_desc,
            fmt=fmt, cfg_http=cfg_http,
        )
        return

    if provider == "loc":
        _search_loc(
            query=query, year=year, creator=creator, subject=subject,
            languages=languages, work_type=work_type,
            license_id=license_id, has_iiif=has_iiif,
            access_status=access_status, limit=limit, page=page,
            sort_by_date=sort_by_date, sort_desc=sort_desc,
            fmt=fmt, cfg_http=cfg_http,
        )
        return

    # --- Wellcome branch ---------------------------------------------------
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


def _search_loc(*, query: str | None, year: str | None,
                  creator: str | None, subject: str | None,
                  languages: tuple[str, ...], work_type: str | None,
                  license_id: str | None, has_iiif: bool,
                  access_status: str | None, limit: int, page: int,
                  sort_by_date: bool, sort_desc: bool, fmt: str,
                  cfg_http: dict[str, Any]) -> None:
    """LoC search via `loc.gov/search/?fa=...&fo=json`.

    Filters not directly translatable (license_id, work_type,
    access_status) are silently ignored. `has_iiif` is implied because
    LoC's `online-format:online image` essentially means "has IIIF
    Image"; we apply it whenever `has_iiif` is True.
    """
    from urllib.parse import urlencode

    facets: list[str] = []
    # Books unless caller specifies otherwise (work_type ignored for now;
    # LoC doesn't have Wellcome's letter codes).
    facets.append("original-format:book")
    if has_iiif:
        facets.append("online-format:online image")
    if subject:
        facets.append(f"subject:{subject}")
    if creator:
        facets.append(f"contributor:{creator}")
    for lang in languages:
        facets.append(f"language:{lang}")

    params: list[tuple[str, str]] = [
        ("fo", "json"),
        ("c", str(max(1, min(100, limit)))),
        ("sp", str(max(1, page))),
    ]
    if query:
        params.append(("q", query))
    for f in facets:
        params.append(("fa", f))
    if year:
        # LoC dates= filter accepts YYYY/YYYY for ranges, YYYY for single
        y_from, y_to = _parse_year(year)
        # Use just year part of YYYY-MM-DD
        from_year = (y_from.split("-", 1)[0] if y_from else None)
        to_year = (y_to.split("-", 1)[0] if y_to else None)
        if from_year and to_year:
            params.append(("dates", f"{from_year}/{to_year}"))
        elif from_year:
            params.append(("dates", f"{from_year}/9999"))
        elif to_year:
            params.append(("dates", f"0001/{to_year}"))
    if sort_by_date:
        params.append(("sb", "date" + ("_desc" if sort_desc else "")))

    url = f"https://www.loc.gov/search/?{urlencode(params, doseq=True)}"
    payload = http_.fetch_json(url, cfg_http=cfg_http)
    results = payload.get("results") or []
    pagination = payload.get("pagination") or {}

    rows = [_summarize_loc(r) for r in results]
    output_.write_records(rows, fmt=fmt)

    if fmt in ("table", "records") and pagination:
        cur = pagination.get("current")
        total_pages = pagination.get("total") or pagination.get("totalPages")
        if cur and total_pages:
            click.echo(f"\n  page {cur}/{total_pages}", err=True)


def _ia_quote(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _ia_year_clause(spec: str) -> str | None:
    """Year spec → IA's Lucene date-range syntax."""
    y_from, y_to = _parse_year(spec)
    if not y_from and not y_to:
        return None
    return f"date:[{y_from or '*'} TO {y_to or '*'}]"


def build_ia_query(*, query: str | None, year: str | None,
                    creator: str | None, subject: str | None,
                    languages: tuple[str, ...], collections: tuple[str, ...],
                    mediatype: str | None, has_ocr: bool,
                    available_only: bool = True) -> str:
    """Compose an IA advancedsearch (Lucene) query.

    Ported from ia-utils' query builder, including its default of
    excluding print-disabled and removed items — without it a large
    share of hits are things you cannot actually fetch.
    """
    parts: list[str] = []
    if query and query.strip():
        parts.append(f"({query.strip()})")
    if not parts:
        parts.append("*:*")
    if available_only:
        parts.append("NOT collection:printdisabled")
        parts.append("NOT indexflag:removed")
    if mediatype:
        parts.append(f"mediatype:{_ia_quote(mediatype)}")
    for coll in collections:
        if coll:
            parts.append(f"collection:{_ia_quote(coll)}")
    for lang in languages:
        if lang:
            parts.append(f"language:{_ia_quote(lang)}")
    if creator:
        parts.append(f"creator:{_ia_quote(creator)}")
    if subject:
        parts.append(f"subject:{_ia_quote(subject)}")
    if year:
        clause = _ia_year_clause(year)
        if clause:
            parts.append(clause)
    if has_ocr:
        parts.append("ocr:*")
    return " AND ".join(parts)


_IA_FIELDS = ("identifier", "title", "creator", "date", "year", "language",
               "mediatype", "collection", "downloads", "ocr")


def _search_ia(*, query: str | None, year: str | None, creator: str | None,
                subject: str | None, languages: tuple[str, ...],
                collections: tuple[str, ...], work_type: str | None,
                has_iiif: bool, limit: int, page: int, sort_by_date: bool,
                sort_desc: bool, fmt: str, cfg_http: dict[str, Any]) -> None:
    """Internet Archive search via `archive.org/advancedsearch.php`.

    Filters with no IA equivalent (license_id, access_status) are
    ignored, as in the LoC branch. `has_iiif` maps to `ocr:*`: IA
    serves a IIIF manifest for every item, so "has IIIF" is not
    discriminating, whereas having OCR is what actually determines
    whether create-index can build a text index.

    `work_type` maps to IA's `mediatype`, defaulting to `texts`.
    """
    from urllib.parse import urlencode

    q = build_ia_query(
        query=query, year=year, creator=creator, subject=subject,
        languages=languages, collections=collections,
        mediatype=work_type or "texts", has_ocr=has_iiif,
    )
    params: list[tuple[str, str]] = [("q", q), ("output", "json"),
                                      ("rows", str(max(1, min(100, limit)))),
                                      ("page", str(max(1, page)))]
    for f in _IA_FIELDS:
        params.append(("fl[]", f))
    if sort_by_date:
        params.append(("sort[]", f"date {'desc' if sort_desc else 'asc'}"))

    url = f"https://archive.org/advancedsearch.php?{urlencode(params)}"
    payload = http_.fetch_json(url, cfg_http=cfg_http)
    resp = payload.get("response") or {}
    docs = resp.get("docs") or []

    rows = [_summarize_ia(d) for d in docs]
    output_.write_records(rows, fmt=fmt)

    if fmt in ("table", "records"):
        total = resp.get("numFound")
        if total is not None:
            click.echo(f"\n  {len(rows)} of {total} results "
                       f"(page {max(1, page)})", err=True)


def _summarize_ia(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one IA search hit.

    `ref` is what you hand to create-index / get-page — a details URL,
    since bare identifiers are never provider-guessed.
    """
    def _joined(key: str) -> str | None:
        v = item.get(key)
        if isinstance(v, list):
            return " | ".join(str(x) for x in v if x)
        return str(v) if v else None

    ident = item.get("identifier") or ""
    title = str(item.get("title") or "")
    date = str(item.get("date") or item.get("year") or "")
    return {
        "id": ident,
        "year": date[:4] if date else None,
        "title": title[:60] + ("…" if len(title) > 60 else ""),
        "creator": _joined("creator"),
        "languages": _joined("language"),
        "has_ocr": bool(item.get("ocr")),
        "downloads": item.get("downloads"),
        "ref": f"https://archive.org/details/{ident}" if ident else None,
    }


def _summarize_loc(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one LoC search hit."""
    title = item.get("title") or ""
    item_url = item.get("id") or ""
    # LCCN: last path segment of item URL https://www.loc.gov/item/{lccn}/
    lccn = item_url.rstrip("/").rsplit("/", 1)[-1] if item_url else None

    year = None
    dates = item.get("dates") or item.get("date")
    if isinstance(dates, list) and dates:
        year = str(dates[0])
    elif isinstance(dates, str):
        year = dates

    def _joined(key: str) -> str | None:
        v = item.get(key)
        if isinstance(v, list):
            return " | ".join(str(x) for x in v if x)
        return str(v) if v else None

    fmts = item.get("online_format") or []
    if isinstance(fmts, list):
        online_format = " | ".join(str(x) for x in fmts)
    else:
        online_format = str(fmts) if fmts else None

    return {
        "id": lccn,
        "year": year,
        "title": title[:60] + ("…" if len(title) > 60 else ""),
        "contributors": _joined("contributor_names"),
        "languages": _joined("language"),
        "online_format": online_format,
        "item_url": item_url,
    }


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
