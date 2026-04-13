"""
fetcher/proxy.py
----------------
Apify residential proxy integration for bypassing Cloudflare and
other anti-bot protections.

Apify proxy URL format:
  http://<username>:<password>@proxy.apify.com:8000

Proxy groups:
  RESIDENTIAL  — rotating residential IPs (best for Cloudflare)
  SHADER       — datacenter proxies (cheaper, good for most sites)

Usage:
    from fetcher.proxy import get_proxy_url, get_playwright_proxy

    # For httpx
    proxy_url = get_proxy_url()
    async with httpx.AsyncClient(proxy=proxy_url) as client: ...

    # For Playwright
    proxy_config = get_playwright_proxy()
    browser = await pw.chromium.launch(proxy=proxy_config)

Setup:
    1. Sign up at https://apify.com
    2. Go to Settings → Integrations → API token
    3. Set APIFY_API_TOKEN in your .env
    4. Run with --proxy to enable

Docs: https://docs.apify.com/platform/proxy/residential-proxy
"""

import logging
from typing import Optional

import config

logger = logging.getLogger(__name__)


def is_proxy_configured() -> bool:
    """Check if Apify proxy credentials are available."""
    return bool(config.APIFY_API_TOKEN)


def get_proxy_url(
    country: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """
    Build the Apify residential proxy URL for httpx.

    Args:
        country:    Optional 2-letter country code (e.g. "US", "GB") to
                    pin exit IPs to a specific country.
        session_id: Optional session ID for sticky sessions (same IP
                    across multiple requests). Useful for multi-page crawls.

    Returns:
        Proxy URL string, or None if Apify token is not configured.
    """
    if not is_proxy_configured():
        return None

    group = config.APIFY_PROXY_GROUP

    # Build the username string
    # Format: groups-<GROUP>,country-<CC>,session-<ID>
    username_parts = [f"groups-{group}"]
    if country:
        username_parts.append(f"country-{country.upper()}")
    if session_id:
        username_parts.append(f"session-{session_id}")

    username = ",".join(username_parts)
    password = config.APIFY_API_TOKEN

    proxy_url = f"http://{username}:{password}@proxy.apify.com:8000"
    logger.debug(f"Proxy URL: http://{username}:****@proxy.apify.com:8000")
    return proxy_url


def get_playwright_proxy(
    country: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Build a Playwright-compatible proxy config dict.

    Returns:
        Dict with 'server', 'username', 'password' keys, or None if not configured.
    """
    if not is_proxy_configured():
        return None

    group = config.APIFY_PROXY_GROUP

    username_parts = [f"groups-{group}"]
    if country:
        username_parts.append(f"country-{country.upper()}")
    if session_id:
        username_parts.append(f"session-{session_id}")

    username = ",".join(username_parts)

    return {
        "server": "http://proxy.apify.com:8000",
        "username": username,
        "password": config.APIFY_API_TOKEN,
    }
