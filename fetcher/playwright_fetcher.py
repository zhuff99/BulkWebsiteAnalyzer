"""
fetcher/playwright_fetcher.py
-----------------------------
Headless Chromium fallback fetcher using Playwright.

Used when httpx returns 403 (blocked) or a JS-heavy SPA returns little/no
visible text. Playwright renders the full page including JavaScript before
returning the HTML, so we get the same content a real browser would see.

Install deps (one-time setup):
    pip install playwright
    playwright install chromium

Usage:
    from fetcher.playwright_fetcher import fetch_url_playwright
    site = asyncio.run(fetch_url_playwright("https://www.allrecipes.com"))
"""

import asyncio
import logging
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import config
from models import FetchStatus, SiteData

# Thread pool for running Playwright in its own ProactorEventLoop on Windows
# (avoids conflict with the SelectorEventLoop used by httpx)
_playwright_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="playwright")

logger = logging.getLogger(__name__)

# Lazy import — only load Playwright if it's installed
_playwright_available: bool | None = None


def _check_playwright() -> bool:
    global _playwright_available
    if _playwright_available is None:
        try:
            from playwright.async_api import async_playwright  # noqa: F401
            _playwright_available = True
        except ImportError:
            _playwright_available = False
            logger.warning(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )
    return _playwright_available


def _run_playwright_sync(url: str, user_agent: str, timeout_ms: int) -> SiteData:
    """
    Synchronous Playwright fetch that runs in its own event loop.
    This avoids the SelectorEventLoop vs ProactorEventLoop conflict on Windows.
    """
    import asyncio

    # On Windows, use ProactorEventLoop inside this thread so Playwright works
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
    else:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(_playwright_fetch(url, user_agent, timeout_ms))
    finally:
        loop.close()


async def _playwright_fetch(url: str, user_agent: str, timeout_ms: int) -> SiteData:
    """Inner async Playwright logic, called inside a dedicated event loop."""
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

    try:
        async with async_playwright() as pw:
            # Phase 3: Apify residential proxy support
            proxy_config = None
            if config.USE_PROXY:
                from fetcher.proxy import get_playwright_proxy
                proxy_config = get_playwright_proxy()
                if proxy_config:
                    logger.debug(f"Using Apify proxy for Playwright: {url}")

            launch_args = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            }
            if proxy_config:
                launch_args["proxy"] = proxy_config

            browser = await pw.chromium.launch(**launch_args)

            context = await browser.new_context(
                user_agent=user_agent,
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/New_York",
            )

            # Block images/fonts/media to speed up loads
            await context.route(
                "**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,mp4,mp3,avi}",
                lambda route: route.abort(),
            )

            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            try:
                response = await page.goto(
                    url,
                    timeout=timeout_ms,
                    wait_until="domcontentloaded",
                )
                await asyncio.sleep(1.5)  # Let JS settle

                status_code = response.status if response else 0
                html        = await page.content()
                await browser.close()

                if status_code in (403, 429):
                    return SiteData(
                        url=url,
                        status_code=status_code,
                        fetch_status=FetchStatus.BLOCKED,
                        fetch_error=f"HTTP {status_code} — blocked even with Playwright",
                    )

                return SiteData(
                    url=url,
                    status_code=status_code,
                    fetch_status=FetchStatus.OK,
                    html=html,
                )

            except PlaywrightTimeout:
                await browser.close()
                return SiteData(
                    url=url,
                    fetch_status=FetchStatus.TIMEOUT,
                    fetch_error="Playwright page load timed out",
                )

    except Exception as exc:
        return SiteData(
            url=url,
            fetch_status=FetchStatus.FAILED,
            fetch_error=f"Playwright error: {type(exc).__name__}: {exc}",
        )


async def fetch_url_playwright(url: str) -> SiteData:
    """
    Fetch a URL using headless Chromium via Playwright.

    Runs Playwright in a dedicated thread with its own ProactorEventLoop
    to avoid conflicts with the main SelectorEventLoop used by httpx on Windows.

    Args:
        url: Fully-qualified URL to fetch.

    Returns:
        SiteData with html populated on success, or fetch_status=FAILED on error.
    """
    if not _check_playwright():
        return SiteData(
            url=url,
            fetch_status=FetchStatus.FAILED,
            fetch_error="Playwright not installed — run: pip install playwright && playwright install chromium",
        )

    user_agent = random.choice(config.USER_AGENTS)
    timeout_ms = int(config.REQUEST_TIMEOUT * 1000)

    logger.info(f"Playwright fetching: {url}")

    try:
        # Run in thread pool so it gets its own ProactorEventLoop on Windows
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _playwright_executor,
            _run_playwright_sync,
            url,
            user_agent,
            timeout_ms,
        )

        if result.fetch_status == FetchStatus.OK:
            logger.info(f"Playwright OK ({result.status_code}, {len(result.html or ''):,} chars): {url}")
        else:
            logger.warning(f"Playwright {result.fetch_status.value}: {url} — {result.fetch_error}")

        return result

    except Exception as exc:
        logger.error(f"Playwright executor error for {url}: {type(exc).__name__}: {exc}")
        return SiteData(
            url=url,
            fetch_status=FetchStatus.FAILED,
            fetch_error=f"Playwright executor error: {type(exc).__name__}: {exc}",
        )
