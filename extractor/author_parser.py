"""
extractor/author_parser.py
--------------------------
Extracts the author / editor name from a webpage using multiple strategies,
in order of reliability:

  1. schema.org JSON-LD  (most reliable — structured data)
  2. Open Graph / meta tags  (og:author, article:author, name="author")
  3. HTML byline elements  (<span class="author">, rel="author", etc.)
  4. Twitter card  (twitter:creator)

Returns the first name found, or None if nothing is detected.

Usage:
    from extractor.author_parser import extract_author
    name = extract_author(html)
"""

import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# CSS selectors and patterns commonly used for bylines
_BYLINE_SELECTORS = [
    # rel="author" anchor
    'a[rel="author"]',
    # Common class patterns
    '[class*="author"]',
    '[class*="byline"]',
    '[class*="writer"]',
    '[class*="journalist"]',
    # id patterns
    '[id*="author"]',
    '[id*="byline"]',
    # Microformat
    '.vcard .fn',
    '.p-author',
    # WordPress / common blog patterns
    '.entry-author',
    '.post-author',
    '.article-author',
]

# Pattern to sanity-check extracted names:
# Must look like a real person's name — letters, spaces, hyphens, apostrophes only
_NAME_RE = re.compile(r"^[A-Za-z\u00C0-\u024F\u0400-\u04FF'\-\. ]{2,50}$")

# Prefix words to strip (e.g. "By Jane Smith" → "Jane Smith")
_BY_PREFIX = re.compile(r"^(by|written by|posted by|author[:\s]?)\s+", re.I)

# Words that indicate we grabbed non-name adjacent text
_NON_NAME_WORDS = {
    "reader", "editor", "staff", "team", "contributor", "admin", "user",
    "member", "subscriber", "guest", "updated", "published", "posted",
    "comments", "shares", "views", "minutes", "hours", "days", "ago",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}


def _split_concatenated(text: str) -> str:
    """
    Detect and split names that got concatenated without a space.
    e.g. "BeltranIWT" → take only up to the second capital run
    Handles cases where a byline element contains "AuthorNameTag" merged together.
    """
    # Insert space before a capital letter that follows a lowercase letter
    # "BeltranIWT" → "Beltran IWT", then we take only the first part
    split = re.sub(r"([a-z\u00C0-\u024F])([A-Z\u00C0-\u024F])", r"\1 \2", text)
    return split


def _clean_name(raw: str) -> Optional[str]:
    """Strip noise from a candidate name string and validate it looks like a real name."""
    if not raw:
        return None

    name = raw.strip()
    name = _BY_PREFIX.sub("", name).strip()

    # Fix concatenated words (e.g. "Juan Pablo BeltranIWT Reader")
    name = _split_concatenated(name)
    name = re.sub(r"\s+", " ", name).strip()

    # Cap at 4 words — real author names are rarely longer
    words = name.split()
    if len(words) > 4:
        return None

    # Reject if any word is a known non-name token
    if any(w.lower() in _NON_NAME_WORDS for w in words):
        return None

    # Must match the name character pattern
    if not _NAME_RE.match(name):
        return None

    # Must have at least one word that looks like a capitalised name
    if not any(w[0].isupper() for w in words if w):
        return None

    return name


def _from_json_ld(soup: BeautifulSoup) -> Optional[str]:
    """
    Look for schema.org JSON-LD blocks and extract author name.
    Handles Article, NewsArticle, BlogPosting, Person types.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, AttributeError):
            continue

        # data can be a single object or a list
        items = data if isinstance(data, list) else [data]
        for item in items:
            author = item.get("author")
            if not author:
                continue

            # author can be a Person dict, a list, or a plain string
            if isinstance(author, str):
                name = _clean_name(author)
                if name:
                    return name

            if isinstance(author, dict):
                name = _clean_name(author.get("name", ""))
                if name:
                    return name

            if isinstance(author, list) and author:
                first = author[0]
                if isinstance(first, dict):
                    name = _clean_name(first.get("name", ""))
                    if name:
                        return name
                elif isinstance(first, str):
                    name = _clean_name(first)
                    if name:
                        return name

    return None


def _from_meta_tags(soup: BeautifulSoup) -> Optional[str]:
    """Check Open Graph and standard meta author tags."""
    candidates = [
        soup.find("meta", attrs={"property": "article:author"}),
        soup.find("meta", attrs={"property": "og:article:author"}),
        soup.find("meta", attrs={"name": "author"}),
        soup.find("meta", attrs={"name": "twitter:creator"}),
        soup.find("meta", attrs={"name": "sailthru.author"}),
    ]
    for tag in candidates:
        if tag and isinstance(tag, Tag):
            content = tag.get("content", "")
            if content:
                # og:article:author is sometimes a URL — skip it
                if content.startswith("http"):
                    continue
                name = _clean_name(str(content))
                if name:
                    return name
    return None


def _from_byline_elements(soup: BeautifulSoup) -> Optional[str]:
    """Scan HTML for common byline CSS selectors."""
    for selector in _BYLINE_SELECTORS:
        try:
            elements = soup.select(selector)
        except Exception:
            continue
        for el in elements:
            text = el.get_text(strip=True)
            if text:
                name = _clean_name(text)
                if name:
                    return name
    return None


def extract_author(html: str) -> Optional[str]:
    """
    Attempt to extract the author/editor name from a page's HTML.

    Tries four strategies in order of reliability. Returns the first
    non-None result, or None if nothing is found.

    Args:
        html: Raw HTML string.

    Returns:
        Author name string, or None.
    """
    if not html:
        return None

    try:
        soup = BeautifulSoup(html, "html.parser")

        # Strategy 1: schema.org JSON-LD (most reliable)
        name = _from_json_ld(soup)
        if name:
            logger.debug(f"Author found via JSON-LD: {name!r}")
            return name

        # Strategy 2: Meta tags
        name = _from_meta_tags(soup)
        if name:
            logger.debug(f"Author found via meta tag: {name!r}")
            return name

        # Strategy 3: Byline HTML elements
        name = _from_byline_elements(soup)
        if name:
            logger.debug(f"Author found via byline element: {name!r}")
            return name

    except Exception as exc:
        logger.warning(f"Author extraction error: {exc}")

    return None
