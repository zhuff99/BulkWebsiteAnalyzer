"""
fetcher/http_fetcher.py
-----------------------
Async HTTP fetcher with:
  - Per-domain rate limiting (configurable delay between requests to the same host)
  - Exponential back-off retry on transient failures
  - User-agent rotation to reduce bot detection
  - Automatic redirect following
  - Returns a SiteData object ready for the extractor layer

Usage:
    import asyncio
    from fetcher.http_fetcher import fetch_url

    async def main():
        site = await fetch_url("https://example.com")
        print(site.status_code, len(site.html or ""))

    asyncio.run(main())
"""

import asyncio
import logging
import random
import time
from urllib.parse import urlparse

import httpx

import config
from models import FetchStatus, SiteData

logger = logging.getLogger(__name__)

# ── Per-domain rate limiting ──────────────────────────────────────────────────
# Maps hostname -> asyncio.Lock + last-request timestamp
_domain_locks:      dict[str, asyncio.Lock]  = {}
_domain_last_call:  dict[str, float]         = {}
_lock_registry_lock = asyncio.Lock()          # Guards _domain_locks itself


async def _get_domain_lock(hostname: str) -> asyncio.Lock:
    """Return (creating if needed) the per-domain asyncio Lock."""
    async with _lock_registry_lock:
        if hostname not in _domain_locks:
            _domain_locks[hostname]     = asyncio.Lock()
            _domain_last_call[hostname] = 0.0
        return _domain_locks[hostname]


async def _rate_limited_get(
    client: httpx.AsyncClient,
    url: str,
    hostname: str,
) -> httpx.Response:
    """
    Acquire the domain lock, honour the per-domain delay, then issue the GET.
    This ensures we never hammer a single host.
    """
    lock = await _get_domain_lock(hostname)
    async with lock:
        elapsed = time.monotonic() - _domain_last_call.get(hostname, 0.0)
        wait    = config.PER_DOMAIN_DELAY - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

        response = await client.get(url, follow_redirects=True)
        _domain_last_call[hostname] = time.monotonic()
        return response


# ── Main fetch function ───────────────────────────────────────────────────────

async def fetch_url(url: str) -> SiteData:
    """
    Fetch a single URL and return a SiteData object.

    Retry logic:
      - Attempt up to config.MAX_RETRIES times.
      - Back-off: 1 s, 2 s, 4 s between attempts.
      - On timeout   → FetchStatus.TIMEOUT
      - On 403/429   → FetchStatus.BLOCKED (no retry)
      - On other 4xx → FetchStatus.FAILED  (no retry)
      - On 5xx       → retry

    Args:
        url: The fully-qualified URL to fetch.

    Returns:
        SiteData with html populated on success, fetch_status/error set on failure.
    """
    hostname = urlparse(url).hostname or url
    headers  = {
        "User-Agent": random.choice(config.USER_AGENTS),
        "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    last_error: str = ""

    # ── Proxy support (Phase 3: Apify residential proxies) ──────────
    proxy_url = None
    if config.USE_PROXY:
        from fetcher.proxy import get_proxy_url
        proxy_url = get_proxy_url()
        if proxy_url:
            logger.debug(f"Using Apify proxy for: {url}")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.REQUEST_TIMEOUT),
        headers=headers,
        verify=False,          # Some sites have self-signed certs; don't fail on them
        max_redirects=10,
        proxy=proxy_url,
    ) as client:

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                logger.debug(f"[Attempt {attempt}/{config.MAX_RETRIES}] GET {url}")
                response = await _rate_limited_get(client, url, hostname)
                status   = response.status_code

                # ── Blocked — try Playwright fallback ─────────────────────
                if status in (403, 429):
                    logger.warning(f"Blocked ({status}), trying Playwright fallback: {url}")
                    from fetcher.playwright_fetcher import fetch_url_playwright
                    return await fetch_url_playwright(url)

                # ── Other client errors ────────────────────────────────────
                if 400 <= status < 500:
                    logger.warning(f"Client error ({status}): {url}")
                    return SiteData(
                        url=url,
                        status_code=status,
                        fetch_status=FetchStatus.FAILED,
                        fetch_error=f"HTTP {status}",
                    )

                # ── Server errors — retry ──────────────────────────────────
                if status >= 500:
                    last_error = f"HTTP {status}"
                    logger.warning(f"Server error ({status}), attempt {attempt}: {url}")
                    if attempt < config.MAX_RETRIES:
                        await asyncio.sleep(2 ** (attempt - 1))
                    continue

                # ── Success ────────────────────────────────────────────────
                html = response.text
                logger.info(f"OK ({status}, {len(html):,} chars): {url}")
                return SiteData(
                    url=url,
                    status_code=status,
                    fetch_status=FetchStatus.OK,
                    html=html,
                )

            except httpx.TimeoutException:
                last_error = "Request timed out"
                logger.warning(f"Timeout, attempt {attempt}: {url}")
                if attempt < config.MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))

            except httpx.TooManyRedirects:
                logger.warning(f"Too many redirects: {url}")
                return SiteData(
                    url=url,
                    fetch_status=FetchStatus.FAILED,
                    fetch_error="Too many redirects",
                )

            except httpx.RequestError as exc:
                last_error = str(exc)
                logger.warning(f"Request error ({exc.__class__.__name__}), attempt {attempt}: {url}")
                if attempt < config.MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))

    # All retries exhausted
    is_timeout = "timed out" in last_error.lower()
    return SiteData(
        url=url,
        fetch_status=FetchStatus.TIMEOUT if is_timeout else FetchStatus.FAILED,
        fetch_error=last_error or "Unknown error after all retries",
    )
