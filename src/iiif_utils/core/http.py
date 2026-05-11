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
    """Sync JSON fetch with optional file cache. Idempotent.

    On HTTP error, augments the exception with the response body — IIIF
    providers (Wellcome especially) return a JSON `description` field
    that pinpoints which parameter is wrong.
    """
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
        if r.is_error:
            detail = ""
            try:
                err = r.json()
                if isinstance(err, dict):
                    detail = err.get("description") or err.get("error") or ""
            except Exception:
                detail = r.text[:200]
            raise httpx.HTTPStatusError(
                f"HTTP {r.status_code} for {url}"
                + (f" — {detail}" if detail else ""),
                request=r.request, response=r,
            )
        body = r.json()
    if cache_dir is not None:
        import json
        cp = cache_path(cache_dir, url, ".json")
        cp.write_text(json.dumps(body, indent=2))
    return body  # type: ignore[no-any-return]


def fetch_bytes(url: str, *, cfg_http: dict[str, Any],
                cache_dir: Path | None = None,
                suffix: str = "") -> bytes:
    """Sync bytes fetch with optional file cache and 429/5xx retry."""
    if cache_dir is not None:
        cp = cache_path(cache_dir, url, suffix)
        if cp.exists() and cp.stat().st_size > 0:
            return cp.read_bytes()
    headers = {"User-Agent": cfg_http.get("user_agent", "iiif-utils/0.1")}
    timeout = httpx.Timeout(float(cfg_http.get("timeout_seconds", 60)))
    max_retries = int(cfg_http.get("max_retries", 8))
    base_backoff = float(cfg_http.get("retry_base_seconds", 0.5))
    import time
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers=headers) as client:
        for attempt in range(max_retries + 1):
            try:
                r = client.get(url)
            except (httpx.RemoteProtocolError, httpx.ReadError,
                     httpx.ConnectError):
                if attempt == max_retries:
                    raise
                time.sleep(base_backoff * (2 ** attempt))
                continue
            if r.status_code == 429 or 500 <= r.status_code < 600:
                ra = r.headers.get("retry-after")
                delay = (float(ra) if ra and ra.isdigit()
                         else base_backoff * (2 ** attempt))
                if attempt == max_retries:
                    r.raise_for_status()
                time.sleep(delay)
                continue
            r.raise_for_status()
            content = r.content
            if cache_dir is not None:
                cp = cache_path(cache_dir, url, suffix)
                cp.write_bytes(content)
            return content
    # Unreachable — the loop returns or raises.
    raise RuntimeError("fetch_bytes: retry loop exited without result")


async def fetch_many_bytes(
    urls: list[str],
    *,
    cfg_http: dict[str, Any],
    cache_dir: Path | None = None,
    suffix: str = "",
    on_progress: Any = None,
) -> dict[str, bytes]:
    """Concurrent fetch with file cache + 429/5xx retry. Returns {url: bytes}."""
    headers = {"User-Agent": cfg_http.get("user_agent", "iiif-utils/0.1")}
    timeout = httpx.Timeout(float(cfg_http.get("timeout_seconds", 60)))
    concurrency = int(cfg_http.get("max_concurrency", 8))
    max_retries = int(cfg_http.get("max_retries", 8))
    base_backoff = float(cfg_http.get("retry_base_seconds", 0.5))
    # Retry classes: 429 = rate-limited; 5xx = any server-side hiccup,
    # covering Cloudflare-specific 520-527 codes that LoC's edge emits.
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
        for attempt in range(max_retries + 1):
            async with sem:
                try:
                    r = await client.get(url)
                except (httpx.RemoteProtocolError, httpx.ReadError,
                         httpx.ConnectError):
                    if attempt == max_retries:
                        raise
                    await asyncio.sleep(base_backoff * (2 ** attempt))
                    continue
            if r.status_code == 429 or 500 <= r.status_code < 600:
                # Respect Retry-After if present, else exponential backoff.
                ra = r.headers.get("retry-after")
                delay = (float(ra) if ra and ra.isdigit()
                         else base_backoff * (2 ** attempt))
                if attempt == max_retries:
                    r.raise_for_status()
                await asyncio.sleep(delay)
                continue
            r.raise_for_status()
            out[url] = r.content
            if cache_dir is not None:
                cp = cache_path(cache_dir, url, suffix)
                cp.write_bytes(r.content)
            if on_progress:
                on_progress(url, "ok")
            return

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 headers=headers,
                                 limits=httpx.Limits(
                                     max_connections=concurrency * 2,
                                     max_keepalive_connections=concurrency * 2,
                                 )) as client:
        await asyncio.gather(*(one(client, u) for u in urls))
    return out
