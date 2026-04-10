"""
input/csv_loader.py
-------------------
Reads a CSV file and returns a validated list of URL strings.

Expected CSV format (flexible):
  - Must contain at least one column with URLs.
  - Column can be named: url, URL, urls, URLs, website, Website, domain, Domain
  - Extra columns (name, notes, etc.) are ignored — they don't affect processing.

Usage:
    from input.csv_loader import load_urls
    urls = load_urls("sites.csv")
"""

import logging
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

logger = logging.getLogger(__name__)

# Column names we'll look for (in priority order)
_URL_COLUMN_CANDIDATES = [
    "url", "URL", "urls", "URLs",
    "website", "Website", "websites", "Websites",
    "domain", "Domain", "domains", "Domains",
    "link", "Link", "links", "Links",
]


def _find_url_column(df: pd.DataFrame) -> str:
    """Find the URL column in a DataFrame, case-insensitively."""
    # Exact match first
    for candidate in _URL_COLUMN_CANDIDATES:
        if candidate in df.columns:
            return candidate

    # Case-insensitive fallback
    lower_map = {col.lower(): col for col in df.columns}
    for candidate in _URL_COLUMN_CANDIDATES:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]

    # Last resort: take the first column and warn
    first_col = df.columns[0]
    logger.warning(
        f"No recognised URL column found. Using first column: '{first_col}'. "
        f"Rename it to 'url' to suppress this warning."
    )
    return first_col


def _normalize_url(raw: str) -> str | None:
    """
    Ensure the URL has a scheme. Returns None if the value looks invalid.
    Examples:
        "example.com"        -> "https://example.com"
        "http://example.com" -> "http://example.com"
        "not a url"          -> None
    """
    raw = str(raw).strip()
    if not raw or raw.lower() in ("nan", "none", "null", ""):
        return None

    # Add scheme if missing
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
        # Must have both scheme and a netloc with at least one dot
        if parsed.scheme in ("http", "https") and "." in parsed.netloc:
            return raw
    except Exception:
        pass

    return None


def load_urls(filepath: str | Path) -> list[str]:
    """
    Load and validate URLs from a CSV file.

    Args:
        filepath: Path to the CSV file.

    Returns:
        Deduplicated list of validated URL strings.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file is empty or has no usable URL column.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {filepath}")

    logger.info(f"Loading URLs from: {filepath}")

    # Try to auto-detect the delimiter (comma, tab, semicolon)
    try:
        df = pd.read_csv(path, sep=None, engine="python", dtype=str)
    except Exception as e:
        raise ValueError(f"Could not parse CSV file '{filepath}': {e}") from e

    if df.empty:
        raise ValueError(f"CSV file '{filepath}' is empty.")

    url_col = _find_url_column(df)
    raw_urls = df[url_col].tolist()

    valid_urls: list[str] = []
    skipped = 0

    for raw in raw_urls:
        normalized = _normalize_url(str(raw))
        if normalized:
            valid_urls.append(normalized)
        else:
            skipped += 1
            logger.debug(f"Skipping invalid URL: '{raw}'")

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for url in valid_urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)

    duplicates_removed = len(valid_urls) - len(deduped)

    logger.info(
        f"Loaded {len(deduped)} unique URLs "
        f"({skipped} invalid, {duplicates_removed} duplicates removed)."
    )

    if not deduped:
        raise ValueError(
            f"No valid URLs found in '{filepath}'. "
            "Check that the file has a column named 'url' containing valid web addresses."
        )

    return deduped
