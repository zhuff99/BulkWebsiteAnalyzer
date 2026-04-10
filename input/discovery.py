"""
input/discovery.py
------------------
URL Discovery Engine — finds websites to analyse without needing a CSV.

Three providers supported (use any combination):

  1. SerpAPI         — queries Google Search. Best accuracy. ~$50/month for 5K searches.
                       Requires SERPAPI_KEY in .env
  2. Google CSE      — Google Custom Search Engine. 100 free/day, $5 per 1K after.
                       Requires GOOGLE_CSE_KEY + GOOGLE_CSE_ID in .env
  3. Common Crawl    — free, massive web index. No API key needed.
                       Slower but unlimited and great for broad discovery.

Usage:
    from input.discovery import discover_urls

    urls = asyncio.run(discover_urls(
        query="personal finance blog",
        num_results=50,
        provider="serpapi",  # or "google_cse" or "commoncrawl"
    ))
"""

import asyncio
import logging
from urllib.parse import urlparse, urlencode, quote_plus

import httpx

import config

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_domain_url(url: str) -> str:
    """Return just the scheme + netloc (homepage) from any URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        domain = _extract_domain_url(url)
        if domain not in seen and domain != "://":
            seen.add(domain)
            result.append(domain)
    return result


# ── Provider 1: SerpAPI ────────────────────────────────────────────────────────

async def _discover_serpapi(query: str, num_results: int) -> list[str]:
    """Use SerpAPI to search Google and return organic result URLs."""
    if not config.SERPAPI_KEY:
        raise ValueError(
            "SERPAPI_KEY is not set in your .env file. "
            "Get a key at https://serpapi.com"
        )

    urls: list[str] = []
    pages_needed = (num_results // 10) + 1

    async with httpx.AsyncClient(timeout=15) as client:
        for page in range(pages_needed):
            params = {
                "q":       query,
                "api_key": config.SERPAPI_KEY,
                "engine":  "google",
                "num":     10,
                "start":   page * 10,
                "hl":      "en",
            }
            try:
                resp = await client.get("https://serpapi.com/search", params=params)
                resp.raise_for_status()
                data = resp.json()

                for result in data.get("organic_results", []):
                    link = result.get("link", "")
                    if link:
                        urls.append(link)

                if len(urls) >= num_results:
                    break

            except Exception as exc:
                logger.error(f"SerpAPI error on page {page}: {exc}")
                break

    logger.info(f"SerpAPI discovered {len(urls)} URLs for query: {query!r}")
    return urls[:num_results]


# ── Provider 2: Google Custom Search Engine ───────────────────────────────────

async def _discover_google_cse(query: str, num_results: int) -> list[str]:
    """Use Google Custom Search API to find URLs."""
    if not config.GOOGLE_CSE_KEY or not config.GOOGLE_CSE_ID:
        raise ValueError(
            "GOOGLE_CSE_KEY and GOOGLE_CSE_ID are not set in your .env file. "
            "Set up a CSE at https://programmablesearchengine.google.com"
        )

    urls: list[str] = []
    # CSE returns max 10 results per call; index starts at 1
    pages_needed = min((num_results // 10) + 1, 10)  # max 100 results

    async with httpx.AsyncClient(timeout=15) as client:
        for page in range(pages_needed):
            params = {
                "key": config.GOOGLE_CSE_KEY,
                "cx":  config.GOOGLE_CSE_ID,
                "q":   query,
                "num": 10,
                "start": (page * 10) + 1,
            }
            try:
                resp = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("items", []):
                    link = item.get("link", "")
                    if link:
                        urls.append(link)

                if len(urls) >= num_results:
                    break

            except Exception as exc:
                logger.error(f"Google CSE error on page {page}: {exc}")
                break

    logger.info(f"Google CSE discovered {len(urls)} URLs for query: {query!r}")
    return urls[:num_results]


# ── Provider 3: Common Crawl ──────────────────────────────────────────────────

# Most recent available CC indexes to try in order
_CC_INDEXES = [
    "CC-MAIN-2024-51",
    "CC-MAIN-2024-42",
    "CC-MAIN-2024-18",
]


def _query_to_cc_patterns(query: str) -> list[str]:
    """
    Convert a keyword query into Common Crawl URL patterns.

    Common Crawl's CDX API matches URL patterns, not keywords.
    We derive domain-level patterns from the query words.

    Examples:
      "personal finance blog"  → ["*personal*finance*", "*finance*blog*", "*.personalfinance.*"]
      "travel blog"            → ["*travel*blog*", "*.travelblog.*"]
    """
    words = [w.lower().strip() for w in query.split() if len(w) > 3]
    patterns = []

    # Pattern 1: all words chained with wildcards in the domain
    if words:
        patterns.append("*" + "*".join(words) + "*")

    # Pattern 2: pairs of adjacent words as compound domain names
    for i in range(len(words) - 1):
        compound = words[i] + words[i + 1]
        patterns.append(f"*.{compound}.*")
        patterns.append(f"*{compound}*")

    # Pattern 3: each word individually in the domain
    for w in words:
        if w not in ("blog", "news", "site", "web"):  # too generic
            patterns.append(f"*{w}*blog*")
            patterns.append(f"*{w}*")

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    return unique[:6]  # Don't try too many


async def _query_cc_index(
    client: httpx.AsyncClient,
    index: str,
    pattern: str,
    limit: int,
) -> list[str]:
    """Query one Common Crawl index for a single URL pattern."""
    import json as _json

    url = (
        f"https://index.commoncrawl.org/{index}-index"
        f"?url={quote_plus(pattern)}&output=json"
        f"&limit={limit}&fl=url&filter=statuscode:200"
    )
    try:
        resp = await client.get(url)
        if resp.status_code == 504:
            return []
        resp.raise_for_status()
        results = []
        for line in resp.text.strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = _json.loads(line)
                u = record.get("url", "")
                if u:
                    results.append(u)
            except Exception:
                continue
        return results
    except Exception:
        return []


async def _discover_commoncrawl(query: str, num_results: int) -> list[str]:
    """
    Query the Common Crawl CDX API to find URLs.

    Common Crawl indexes URLs by pattern, not by keyword. This function
    automatically converts keyword queries into URL patterns and tries
    multiple recent indexes.

    For best results with Common Crawl, use URL patterns directly:
      "*.nerdwallet.com"     → all pages from NerdWallet
      "*personalfinance*"    → domains containing 'personalfinance'

    Keyword queries (e.g. "personal finance blog") are automatically
    converted to URL patterns.
    """
    urls: list[str] = []
    patterns = _query_to_cc_patterns(query)

    logger.info(f"Common Crawl patterns derived from {query!r}: {patterns}")

    async with httpx.AsyncClient(timeout=45) as client:
        for pattern in patterns:
            if len(urls) >= num_results * 2:
                break
            for index in _CC_INDEXES:
                batch = await _query_cc_index(client, index, pattern, limit=num_results)
                if batch:
                    urls.extend(batch)
                    logger.debug(f"CC {index} + {pattern!r}: {len(batch)} results")
                    break  # Got results from this index, move to next pattern

    logger.info(f"Common Crawl discovered {len(urls)} URLs for query: {query!r}")
    return urls[:num_results]


# ── Provider 4: DuckDuckGo (free, no API key) ─────────────────────────────────

async def _discover_duckduckgo(query: str, num_results: int) -> list[str]:
    """
    Use the duckduckgo-search library to find URLs for a keyword query.
    Completely free, no API key required.

    Install: pip install duckduckgo-search
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # fallback for older installs
        except ImportError:
            raise RuntimeError(
                "ddgs is not installed. Run: pip install ddgs"
            )

    urls: list[str] = []
    try:
        # Run sync DDG search in executor so we don't block the event loop
        def _search():
            with DDGS() as ddgs:
                return list(ddgs.text(
                    query,
                    max_results=num_results * 3,  # fetch extra, many will dedup
                    safesearch="off",
                    region="us-en",               # bias toward English results
                ))

        loop    = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _search)
        # Filter out results that look like search engine noise or social media
        noise_domains = {"youtube.com", "twitter.com", "x.com", "facebook.com",
                         "instagram.com", "linkedin.com", "reddit.com", "pinterest.com",
                         "tiktok.com", "wikipedia.org", "amazon.com"}
        urls = [
            r["href"] for r in results
            if r.get("href") and not any(nd in r["href"] for nd in noise_domains)
        ]

    except Exception as exc:
        logger.error(f"DuckDuckGo search error: {exc}")

    logger.info(f"DuckDuckGo discovered {len(urls)} URLs for query: {query!r}")
    return urls[:num_results]


# ── Public API ────────────────────────────────────────────────────────────────

async def discover_urls(
    query:       str,
    num_results: int  = 50,
    provider:    str  = "duckduckgo",
) -> list[str]:
    """
    Discover URLs using the specified search provider.

    Args:
        query:       Search query or domain pattern.
        num_results: How many URLs to return (de-duplicated to unique domains).
        provider:    One of "serpapi", "google_cse", "commoncrawl".

    Returns:
        List of de-duplicated homepage URLs.

    Raises:
        ValueError: If the provider is unknown or required keys are missing.
    """
    provider = provider.lower().strip()

    if provider == "serpapi":
        raw = await _discover_serpapi(query, num_results * 2)
    elif provider in ("google_cse", "cse"):
        raw = await _discover_google_cse(query, num_results * 2)
    elif provider in ("commoncrawl", "cc"):
        raw = await _discover_commoncrawl(query, num_results * 2)
    elif provider in ("duckduckgo", "ddg"):
        raw = await _discover_duckduckgo(query, num_results * 2)
    else:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            "Choose from: duckduckgo (free), serpapi, google_cse, commoncrawl"
        )

    deduped = _dedupe_urls(raw)
    logger.info(f"Discovery complete: {len(deduped)} unique domains found.")
    return deduped[:num_results]
