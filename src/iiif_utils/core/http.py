"""HTTP client helpers — sync + async, with file caching."""
from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

import httpx

# Retry on anything transport-level. The earlier tuple listed
# RemoteProtocolError / ReadError / ConnectError and so missed
# ReadTimeout, which is a *sibling* under TransportError rather than a
# subclass of any of them — and is the failure archive.org actually
# produces. A single timeout escaped the whole max_retries budget,
# which for `create-index` meant silently falling back from hOCR to
# DjVu and building a poorer index that still reported success.
_RETRYABLE = httpx.TransportError


def _timeout(cfg_http: dict[str, Any]) -> httpx.Timeout:
    """Connect and read budgets, not one number for both.

    A single scalar applied the same value to connect/read/write/pool.
    Against archive.org the variable part is time-to-first-byte — it
    spins large derivatives up from storage, and that wait is unbounded
    and unrelated to how long a connection should take to establish.
    Measured: a 12.4 MB hOCR transfers in ~1.7s once bytes flow, but
    TTFB ranged from 1.1s to over 45s on the same file.
    """
    total = float(cfg_http.get("timeout_seconds", 60))
    connect = float(cfg_http.get("connect_timeout_seconds", 15))
    read = float(cfg_http.get("read_timeout_seconds", max(total, 180)))
    return httpx.Timeout(total, connect=min(connect, total), read=read)


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
    timeout = _timeout(cfg_http)
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
    timeout = _timeout(cfg_http)
    max_retries = int(cfg_http.get("max_retries", 8))
    base_backoff = float(cfg_http.get("retry_base_seconds", 0.5))
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers=headers) as client:
        for attempt in range(max_retries + 1):
            try:
                r = client.get(url)
            except _RETRYABLE:
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
            # Never cache an empty body: the read guard is `exists() and
            # size > 0`, so a zero-length write would be re-fetched, but
            # writing it at all is pointless and a truncated one would
            # be served forever.
            if cache_dir is not None and not content:
                return content
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
    """Concurrent fetch with file cache + 429/5xx retry. Returns {url: bytes}.

    Honors three pacing knobs in `cfg_http`:
      - `max_concurrency` (default 8) — semaphore-bounded parallelism
      - `request_interval_seconds` (default 0) — minimum delay between
        the *start* of consecutive uncached requests. Use this for hosts
        that rate-limit on requests-per-second rather than concurrent
        connections (e.g. Gallica).
      - `max_retries` / `retry_base_seconds` — exponential-backoff retry
        budget on 429 / 5xx
    """
    headers = {"User-Agent": cfg_http.get("user_agent", "iiif-utils/0.1")}
    timeout = _timeout(cfg_http)
    concurrency = int(cfg_http.get("max_concurrency", 8))
    max_retries = int(cfg_http.get("max_retries", 8))
    base_backoff = float(cfg_http.get("retry_base_seconds", 0.5))
    interval = float(cfg_http.get("request_interval_seconds", 0.0))
    # Retry classes: 429 = rate-limited; 5xx = any server-side hiccup,
    # covering Cloudflare-specific 520-527 codes that LoC's edge emits.
    sem = asyncio.Semaphore(concurrency)
    # Single global pacing lock — when set, requests serialize through it
    # so that `interval` actually paces wall-clock request starts.
    pacer_lock = asyncio.Lock() if interval > 0 else None
    last_request_time = [0.0]  # mutable cell for the closure
    out: dict[str, bytes] = {}

    async def pace() -> None:
        if pacer_lock is None:
            return
        loop = asyncio.get_event_loop()
        async with pacer_lock:
            wait = last_request_time[0] + interval - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            last_request_time[0] = loop.time()

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
                await pace()
                try:
                    r = await client.get(url)
                except _RETRYABLE:
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
