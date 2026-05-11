"""For each ★ pick in CORPUS.md, resolve Wellcome work-id → manifest →
count canvases with vs without per-canvas ALTO seeAlso.

Also flag: 0-canvas (bibliographic-only) and Collection manifests.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

# (work_id, short_label, date) — ★ picks from CORPUS.md
PICKS: list[tuple[str, str, str]] = [
    # Tier 1
    ("ad56hqjs", "Morris Anatomy 5e",                    "1914"),
    ("cfn934u3", "Cunningham Textbook 4e",               "1914"),
    ("kw6vt8gv", "Cunningham Manual 6e",                 "1914"),
    ("mvaqfjxm", "Piersol Human Anatomy",                "1918"),
    ("dsgx7nzq", "Gerrish Textbook",                     "1899"),
    ("gw75hbbr", "Quain Elements 11e",                   "1908"),
    # Tier 2
    ("cafpy896", "Holden Manual",                        "1880s"),
    ("dzmjbt9h", "Ellis Demonstrations",                 "1887"),
    ("jev9kze2", "Gray UK 11e",                          "1883"),
    # Tier 3 (atlases — the suspected ALTO-less ones live here)
    ("d8quuwxg", "Spalteholz English (late)",            "1929-30"),
    ("kdckv24y", "Sobotta English (McMurrich)",          "1927-28"),
    ("dy48h43b", "Sobotta German",                       "1926-28"),
    ("tgekje3p", "Toldt latest",                         "1919-20"),
    ("p747b7vs", "Bourgery & Jacob",                     "1831-54"),
    # Tier 4 (early modern)
    ("g6b6smge", "Vesalius Epitome",                     "1543"),
    ("nrtzmcfn", "Valverde Historia",                    "1556"),
    ("resfyxts", "Crooke Mikrokosmographia",             "1618"),
    ("jfkydvqm", "Cheselden Osteographia",               "1733"),
    ("r3thaf6m", "Albinus Tabulae sceleti (Eng)",        "1754"),
    ("ugz833qz", "Albinus Tabulae ossium",               "1753"),
    ("t6hqn97a", "Albinus Tabulae VII uteri",            "1748-51"),
    ("wc7gxkcu", "Hunter Gravid Uterus",                 "1815"),
    # Tier 5 (neuroanatomy)
    ("cfbxq8k8", "Cajal Histologie v1",                  "1909"),
    ("akfqm42j", "Cajal Histologie v2",                  "1911"),
    ("gsfwgf65", "Cajal Nouvelles idées v1",             "1894"),
    ("n3hcmcax", "Cajal Nouvelles idées v2",             "1894"),
    ("z8w4cbad", "Edinger Vorlesungen",                  "1911"),
    ("bjsh27ua", "Ranson Anatomy NS 3e",                 "1927"),
    ("vrnkkxtj", "Brodmann Lokalisationslehre",          "1909"),
    # Tier 6 (histology / embryology)
    ("b69dh6vk", "Schäfer Essentials Histo 11e",         "1920"),
    ("n8dz65uv", "Bailey Textbook Histology",            "1913"),
    ("v43geect", "Sobotta Histologie",                   "1929"),
    ("w8yhh68k", "Keith Embryology 3e",                  "1913"),
    ("g9my2acs", "McMurrich Human Body",                 "1910"),
    # Tier 7 (continental)
    ("h9n43hma", "Sappey Traité descriptive 5e",         "1888-89"),
    ("dnbmq5p3", "Sappey Traité générale",               "1894"),
    ("xugmyg7r", "Hyrtl Lehrbuch",                       "1889"),
    ("h8cwyqvx", "Rauber-Kopsch 1912",                   "1912"),
    ("z3ny6kad", "Bardeleben Holl",                      "1897"),
    ("wcjvv3n2", "Bardeleben Krause",                    "1909"),
    ("f3xd4cyt", "Bardeleben Tandler",                   "1913"),
    ("yd8qmy94", "Poirier-Cunéo Lymphatics",             "1903"),
    # Henle six-volume
    ("e5pwrbf9", "Henle Knochen",                        "1855"),
    ("xs8jejsy", "Henle Bänder",                         "1856"),
    ("cz73pq6c", "Henle Muskel",                         "1858"),
    ("veuxugxf", "Henle Eingeweide",                     "1862-66"),
    ("ywgnwrfg", "Henle Gefäss",                         "1868"),
    ("g84rzrx7", "Henle Nerven",                         "1879"),
]

UA = {"User-Agent": "iiif-utils-experiment/0"}


def alto_seealso(canvas: dict) -> bool:
    for s in canvas.get("seeAlso", []):
        fmt = (s.get("format") or "").lower()
        prof = (s.get("profile") or "")
        if isinstance(prof, list):
            prof = " ".join(prof)
        prof = prof.lower()
        if fmt in ("text/xml", "application/xml") and "alto" in prof:
            return True
    return False


async def resolve_to_manifest_urls(
    client: httpx.AsyncClient, work_id: str,
) -> list[str]:
    """Resolve a work ID to one-or-more manifest URLs.

    Catalogue → b-number → presentation manifest. If the manifest is a
    Collection, dive once into its children.
    """
    cache = DATA / f"work_{work_id}.json"
    if cache.exists():
        w = json.loads(cache.read_text())
    else:
        r = await client.get(
            f"https://api.wellcomecollection.org/catalogue/v2/works/{work_id}"
            "?include=identifiers,items",
        )
        if r.status_code != 200:
            return []
        w = r.json()
        cache.write_text(json.dumps(w))

    bnum = None
    for it in w.get("items", []):
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
        return []
    base = f"https://iiif.wellcomecollection.org/presentation/{bnum}"

    cache_m = DATA / f"manifest_{bnum}.json"
    if cache_m.exists():
        m = json.loads(cache_m.read_text())
    else:
        r = await client.get(base)
        if r.status_code != 200:
            return [base]  # we'll catch the error at fetch time
        m = r.json()
        cache_m.write_text(json.dumps(m))
    if (m.get("type") or m.get("@type")) == "Collection":
        return [c.get("id") or c.get("@id") for c in m.get("items", [])
                 if c.get("id") or c.get("@id")]
    return [base]


async def stats_for_manifest(client: httpx.AsyncClient,
                              url: str) -> dict:
    cache = DATA / f"manifest_{url.rsplit('/', 1)[-1]}.json"
    if cache.exists():
        m = json.loads(cache.read_text())
    else:
        r = await client.get(url)
        if r.status_code != 200:
            return {"url": url, "status": r.status_code,
                    "canvases": 0, "with_alto": 0}
        m = r.json()
        cache.write_text(json.dumps(m))
    canvases = m.get("items", [])
    with_alto = sum(1 for c in canvases if alto_seealso(c))
    return {
        "url": url,
        "type": m.get("type") or m.get("@type"),
        "canvases": len(canvases),
        "with_alto": with_alto,
    }


async def main() -> None:
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=8)
    timeout = httpx.Timeout(60.0, connect=20.0)
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=timeout, limits=limits,
                                  follow_redirects=True,
                                  headers=UA) as client:
        for i, (wid, name, date) in enumerate(PICKS):
            print(f"[{i+1:>2}/{len(PICKS)}] {wid} {name}")
            try:
                manifest_urls = await resolve_to_manifest_urls(client, wid)
            except Exception as e:
                rows.append({"work_id": wid, "name": name, "date": date,
                             "error": str(e)[:100]})
                continue
            if not manifest_urls:
                rows.append({"work_id": wid, "name": name, "date": date,
                             "error": "no IIIF location"})
                continue
            for mu in manifest_urls:
                stats = await stats_for_manifest(client, mu)
                rows.append({
                    "work_id": wid, "name": name, "date": date,
                    "manifest": mu.rsplit("/", 1)[-1],
                    **stats,
                })

    # Sort: items with no ALTO first, then partial, then full
    def sort_key(r):
        if "error" in r:
            return (0, r["work_id"])
        if r.get("canvases", 0) == 0:
            return (1, r["work_id"])
        ratio = r["with_alto"] / max(1, r["canvases"])
        return (2 if ratio == 0 else 3 if ratio < 1 else 4, ratio,
                r["work_id"])
    rows.sort(key=sort_key)

    # Markdown report
    out = ["# Wellcome ALTO coverage — ★ picks from CORPUS.md", ""]
    out.append("| work_id  | name                            | date    "
                "| manifest                | canvases | w/ALTO | ratio |")
    out.append("|----------|---------------------------------|---------"
                "|-------------------------|---------:|-------:|------:|")
    for r in rows:
        if "error" in r and "canvases" not in r:
            out.append(f"| {r['work_id']} | {r['name'][:30]:<30} | "
                        f"{r['date']:<7} | _{r['error'][:30]}_         "
                        f"|       0 |      0 |   —   |")
            continue
        ratio = r['with_alto'] / max(1, r['canvases'])
        out.append(f"| {r['work_id']} | {r['name'][:30]:<30} | "
                    f"{r['date']:<7} | {r['manifest'][:23]:<23} | "
                    f"{r['canvases']:>8} | {r['with_alto']:>6} | "
                    f"{ratio:>4.1%} |")

    out.append("")
    out.append("## Summary")
    out.append("")
    full = sum(1 for r in rows if "canvases" in r and r["canvases"] > 0
                and r["with_alto"] == r["canvases"])
    none = sum(1 for r in rows if "canvases" in r and r["canvases"] > 0
                and r["with_alto"] == 0)
    partial = sum(1 for r in rows if "canvases" in r and r["canvases"] > 0
                   and 0 < r["with_alto"] < r["canvases"])
    empty = sum(1 for r in rows if "canvases" in r and r["canvases"] == 0)
    errored = sum(1 for r in rows if "error" in r and "canvases" not in r)
    out.append(f"- full ALTO coverage:    **{full}** manifests")
    out.append(f"- zero ALTO:             **{none}** manifests")
    out.append(f"- partial:               **{partial}** manifests")
    out.append(f"- zero-canvas:           **{empty}** manifests")
    out.append(f"- could not resolve:     **{errored}** items")

    text = "\n".join(out) + "\n"
    (ROOT / "results.md").write_text(text)
    print(f"\nWrote {ROOT / 'results.md'}")
    print("\n" + "\n".join(out[-7:]))


if __name__ == "__main__":
    asyncio.run(main())
