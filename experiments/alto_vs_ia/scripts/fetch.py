"""Cache Wellcome Spalteholz manifests + a sample of ALTO files.

Idempotent. Writes to ../data/. Subsequent runs hit the cache.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

COLLECTION_URL = "https://iiif.wellcomecollection.org/presentation/b31362126"
VOLUMES = [
    "https://iiif.wellcomecollection.org/presentation/b31362126_0001",
    "https://iiif.wellcomecollection.org/presentation/b31362126_0002",
    "https://iiif.wellcomecollection.org/presentation/b31362126_0003",
]
SAMPLES_PER_VOLUME = 10  # evenly spaced canvases per volume

UA = "iiif-utils-experiment/0 (+https://github.com/.../iiif)"


def fetch_json(client: httpx.Client, url: str, dest: Path) -> dict:
    if dest.exists():
        return json.loads(dest.read_text())
    print(f"GET {url}")
    r = client.get(url)
    r.raise_for_status()
    body = r.json()
    dest.write_text(json.dumps(body, indent=2))
    return body


def fetch_bytes(client: httpx.Client, url: str, dest: Path) -> bytes:
    if dest.exists():
        return dest.read_bytes()
    print(f"GET {url}")
    r = client.get(url)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return r.content


def alto_seealso(canvas: dict) -> str | None:
    """Return the ALTO seeAlso URL on a v3 canvas, if present."""
    for s in canvas.get("seeAlso", []):
        fmt = (s.get("format") or "").lower()
        prof = (s.get("profile") or "").lower()
        if fmt in ("text/xml", "application/xml") and "alto" in prof:
            return s.get("id") or s.get("@id")
    return None


def main() -> None:
    manifests_dir = DATA / "manifests"
    alto_dir = DATA / "alto"
    manifests_dir.mkdir(exist_ok=True)
    alto_dir.mkdir(exist_ok=True)

    samples: list[dict] = []

    with httpx.Client(timeout=60.0, follow_redirects=True,
                      headers={"User-Agent": UA}) as client:
        fetch_json(client, COLLECTION_URL, manifests_dir / "collection.json")

        for vol_url in VOLUMES:
            vol_id = vol_url.rsplit("/", 1)[-1]
            manifest = fetch_json(client, vol_url, manifests_dir / f"{vol_id}.json")
            canvases = manifest.get("items", [])
            n = len(canvases)
            if n == 0:
                print(f"!! {vol_id}: no canvases")
                continue
            # Evenly spaced canvas indexes
            if n <= SAMPLES_PER_VOLUME:
                idxs = list(range(n))
            else:
                step = n / SAMPLES_PER_VOLUME
                idxs = [int(i * step) for i in range(SAMPLES_PER_VOLUME)]

            print(f"{vol_id}: {n} canvases, sampling {len(idxs)}")
            for idx in idxs:
                canvas = canvases[idx]
                alto_url = alto_seealso(canvas)
                if not alto_url:
                    print(f"  canvas {idx}: no ALTO seeAlso")
                    samples.append({
                        "volume": vol_id, "canvas_index": idx,
                        "canvas_id": canvas.get("id"),
                        "alto_url": None, "alto_path": None,
                    })
                    continue
                # filename: e.g. b31362126_0001_0042.alto.xml
                asset = alto_url.rstrip("/").rsplit("/", 1)[-1]
                # asset like "b31362126_0001_0042.jp2"
                alto_path = alto_dir / f"{asset}.alto.xml"
                fetch_bytes(client, alto_url, alto_path)
                samples.append({
                    "volume": vol_id,
                    "canvas_index": idx,
                    "canvas_id": canvas.get("id"),
                    "alto_url": alto_url,
                    "alto_path": str(alto_path.relative_to(ROOT)),
                })

    (DATA / "samples.json").write_text(json.dumps(samples, indent=2))
    print(f"\n{len(samples)} samples cached to {DATA}/samples.json")
    print(f"  with ALTO:    {sum(1 for s in samples if s['alto_url'])}")
    print(f"  without ALTO: {sum(1 for s in samples if not s['alto_url'])}")


if __name__ == "__main__":
    main()
