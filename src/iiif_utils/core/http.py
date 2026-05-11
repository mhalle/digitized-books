"""HTTP client helpers — sync + async, with file caching."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import httpx


def cache_path(cache_dir: Path, url: str, suffix: str = "") -> Path:
    """Stable per-URL cache filename."""
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{h}{suffix}"


def fetch_json(url: str, *, cfg_http: dict[str, Any],
               cache_dir: Path | None = None) -> dict[str, Any]:
    """Sync JSON fetch with optional file cache. Idempotent."""
    if cache_dir is not None:
        cp = cache_path(cache_dir, url, ".json")
        if cp.exists():
            import json
            return json.loads(cp.read_text())  # type: ignore[no-any-return]
    headers = {"User-Agent": cfg_http.get("user_agent", "iiif-utils/0.1")}
    timeout = httpx.Timeout(float(cfg_http.get("timeout_seconds", 60)))
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers=headers) as client:
        r = client.get(url)
        r.raise_for_status()
        body = r.json()
    if cache_dir is not None:
        import json
        cp = cache_path(cache_dir, url, ".json")
        cp.write_text(json.dumps(body, indent=2))
    return body  # type: ignore[no-any-return]


def fetch_bytes(url: str, *, cfg_http: dict[str, Any],
                cache_dir: Path | None = None,
                suffix: str = "") -> bytes:
    """Sync bytes fetch with optional file cache."""
    if cache_dir is not None:
        cp = cache_path(cache_dir, url, suffix)
        if cp.exists() and cp.stat().st_size > 0:
            return cp.read_bytes()
    headers = {"User-Agent": cfg_http.get("user_agent", "iiif-utils/0.1")}
    timeout = httpx.Timeout(float(cfg_http.get("timeout_seconds", 60)))
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers=headers) as client:
        r = client.get(url)
        r.raise_for_status()
        content = r.content
    if cache_dir is not None:
        cp = cache_path(cache_dir, url, suffix)
        cp.write_bytes(content)
    return content


async def fetch_many_bytes(
    urls: list[str],
    *,
    cfg_http: dict[str, Any],
    cache_dir: Path | None = None,
    suffix: str = "",
    on_progress: Any = None,
) -> dict[str, bytes]:
    """Concurrent fetch with file cache. Returns {url: bytes}."""
    headers = {"User-Agent": cfg_http.get("user_agent", "iiif-utils/0.1")}
    timeout = httpx.Timeout(float(cfg_http.get("timeout_seconds", 60)))
    concurrency = int(cfg_http.get("max_concurrency", 8))
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, bytes] = {}

    async def one(client: httpx.AsyncClient, url: str) -> None:
        if cache_dir is not None:
            cp = cache_path(cache_dir, url, suffix)
            if cp.exists() and cp.stat().st_size > 0:
                out[url] = cp.read_bytes()
                if on_progress:
                    on_progress(url, "cached")
                return
        async with sem:
            r = await client.get(url)
            r.raise_for_status()
            content = r.content
        out[url] = content
        if cache_dir is not None:
            cp = cache_path(cache_dir, url, suffix)
            cp.write_bytes(content)
        if on_progress:
            on_progress(url, "ok")

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 headers=headers,
                                 limits=httpx.Limits(
                                     max_connections=concurrency * 2,
                                     max_keepalive_connections=concurrency * 2,
                                 )) as client:
        await asyncio.gather(*(one(client, u) for u in urls))
    return out
