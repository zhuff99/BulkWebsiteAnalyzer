"""
extractor/html_parser.py
------------------------
Parses raw HTML and enriches a SiteData object with:
  - title
  - meta_description
  - body_text  (first N visible chars — used as AI prompt context)
  - cms        (CMS fingerprint: WordPress, Ghost, Webflow, etc.)

Also does a quick language detection pass using langdetect.

Usage:
    from extractor.html_parser import enrich_site_data
    site = enrich_site_data(site)  # mutates and returns the same object
"""

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

import config
from models import SiteData

logger = logging.getLogger(__name__)

# ── CMS fingerprinting rules ──────────────────────────────────────────────────
# Each tuple: (cms_name, list_of_patterns_to_search_in_html)
_CMS_SIGNATURES: list[tuple[str, list[str]]] = [
    ("WordPress",   ["/wp-content/", "/wp-includes/", 'generator" content="WordPress']),
    ("Ghost",       ["/ghost/", "ghost.io", 'generator" content="Ghost']),
    ("Webflow",     ["webflow.com", "data-wf-", 'generator" content="Webflow']),
    ("Squarespace", ["squarespace.com", "static.squarespace", 'generator" content="Squarespace']),
    ("Wix",         ["static.wixstatic.com", "wix.com/lpviral", "_wix_"]),
    ("Shopify",     ["cdn.shopify.com", "myshopify.com", "Shopify.theme"]),
    ("HubSpot",     ["hs-scripts.com", "hubspot.com/", "hbspt."]),
    ("Substack",    ["substack.com", "substackcdn.com"]),
    ("Medium",      ["medium.com/_/", "cdn-client.medium.com"]),
    ("Blogger",     ["blogger.com", "blogspot.com", "www.blogger.com/static"]),
]


def _detect_cms(html: str) -> Optional[str]:
    """Return the CMS name if we can fingerprint it, else None."""
    for cms_name, patterns in _CMS_SIGNATURES:
        for pattern in patterns:
            if pattern in html:
                return cms_name
    return None


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    """Extract page title, preferring og:title over <title>."""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    tag = soup.find("title")
    if tag and tag.string:
        return tag.string.strip()

    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    return None


def _extract_meta_description(soup: BeautifulSoup) -> Optional[str]:
    """Extract meta description, preferring og:description."""
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        return og_desc["content"].strip()

    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    return None


def _extract_body_text(soup: BeautifulSoup, limit: int) -> str:
    """
    Extract visible text from the page body, stripping scripts/styles/nav.
    Returns at most `limit` characters.
    """
    # Remove non-content tags
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "noscript", "iframe", "form"]):
        tag.decompose()

    # Prefer <main> or <article> if available, else use <body>
    content_tag = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id=re.compile(r"(content|main|post|article)", re.I))
        or soup.find(class_=re.compile(r"(content|main|post|article|entry)", re.I))
        or soup.body
    )

    if not content_tag:
        return ""

    text = content_tag.get_text(separator=" ", strip=True)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _detect_language(text: str) -> Optional[str]:
    """Use langdetect to identify the language. Returns ISO 639-1 code or None."""
    if not text or len(text) < 50:
        return None
    try:
        from langdetect import detect, LangDetectException
        return detect(text)
    except Exception:
        return None


def enrich_site_data(site: SiteData) -> SiteData:
    """
    Parse the HTML in `site` and populate:
      site.title, site.meta_description, site.body_text,
      site.cms, site.detected_language

    Returns the same SiteData object (mutated in place for convenience).
    Does nothing if site.html is None.
    """
    if not site.html:
        return site

    try:
        soup = BeautifulSoup(site.html, "html.parser")

        site.title            = _extract_title(soup)
        site.meta_description = _extract_meta_description(soup)
        site.body_text        = _extract_body_text(soup, config.BODY_TEXT_LIMIT)
        site.cms              = _detect_cms(site.html)
        site.detected_language = _detect_language(site.body_text or "")

        logger.debug(
            f"Parsed {site.url} | title={site.title!r} | "
            f"lang={site.detected_language} | cms={site.cms}"
        )

    except Exception as exc:
        logger.warning(f"HTML parsing failed for {site.url}: {exc}")

    return site
