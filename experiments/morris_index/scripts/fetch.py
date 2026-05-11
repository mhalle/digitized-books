"""Fetch the Morris Anatomy 1914 manifest + every per-canvas ALTO XML.

Concurrent. Idempotent (cache hits skipped). Writes ../data/.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ALTO_DIR = DATA / "alto"
DATA.mkdir(exist_ok=True)
ALTO_DIR.mkdir(exist_ok=True)

MANIFEST_URL = "https://iiif.wellcomecollection.org/presentation/b21212600"
CATALOGUE_URL = "https://api.wellcomecollection.org/catalogue/v2/works/ad56hqjs"
UA = "iiif-utils-experiment/0"
CONCURRENCY = 16


def alto_seealso(canvas: dict) -> str | None:
    for s in canvas.get("seeAlso", []):
        fmt = (s.get("format") or "").lower()
        prof = (s.get("profile") or "").lower()
        if fmt in ("text/xml", "application/xml") and "alto" in prof:
            return s.get("id") or s.get("@id")
    return None


async def fetch_one(client: httpx.AsyncClient, url: str, dest: Path,
                    sem: asyncio.Semaphore) -> tuple[Path, str]:
    if dest.exists() and dest.stat().st_size > 0:
        return dest, "cached"
    async with sem:
        try:
            r = await client.get(url)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return dest, "ok"
        except Exception as e:
            return dest, f"error: {e}"


async def main() -> None:
    timeout = httpx.Timeout(60.0, connect=20.0)
    limits = httpx.Limits(max_connections=CONCURRENCY * 2,
                          max_keepalive_connections=CONCURRENCY * 2)
    async with httpx.AsyncClient(timeout=timeout, limits=limits,
                                 follow_redirects=True,
                                 headers={"User-Agent": UA}) as client:
        # Manifest
        manifest_path = DATA / "manifest.json"
        if not manifest_path.exists():
            print(f"GET {MANIFEST_URL}")
            r = await client.get(MANIFEST_URL); r.raise_for_status()
            manifest_path.write_text(r.text)
        manifest = json.loads(manifest_path.read_text())

        # Catalogue (for richer document metadata)
        cat_path = DATA / "catalogue.json"
        if not cat_path.exists():
            print(f"GET {CATALOGUE_URL}")
            r = await client.get(
                CATALOGUE_URL + "?include=identifiers,items,subjects,"
                "contributors,production,languages"
            )
            r.raise_for_status()
            cat_path.write_text(r.text)

        canvases = manifest.get("items", [])
        print(f"Manifest has {len(canvases)} canvases")

        tasks: list[asyncio.Task] = []
        skipped = 0
        sem = asyncio.Semaphore(CONCURRENCY)
        for idx, canvas in enumerate(canvases):
            alto_url = alto_seealso(canvas)
            if not alto_url:
                skipped += 1
                continue
            asset = alto_url.rstrip("/").rsplit("/", 1)[-1]
            dest = ALTO_DIR / f"{asset}.alto.xml"
            tasks.append(asyncio.create_task(fetch_one(client, alto_url, dest, sem)))
        print(f"Fetching {len(tasks)} ALTO files (skipped {skipped} canvases "
              "without ALTO seeAlso)")

        # Progress as tasks complete
        done = 0
        errors = 0
        cached = 0
        for fut in asyncio.as_completed(tasks):
            path, status = await fut
            done += 1
            if status == "cached":
                cached += 1
            elif status != "ok":
                errors += 1
                print(f"  {path.name}: {status}")
            if done % 100 == 0:
                print(f"  ... {done}/{len(tasks)}  (cached={cached} "
                      f"errors={errors})")
        print(f"\nDone: {done} total, {cached} cached, {errors} errors")
        # Stats
        sizes = [p.stat().st_size for p in ALTO_DIR.glob("*.alto.xml")]
        if sizes:
            print(f"  ALTO files on disk: {len(sizes)}, total "
                  f"{sum(sizes)/1024/1024:.1f} MB")


if __name__ == "__main__":
    asyncio.run(main())
