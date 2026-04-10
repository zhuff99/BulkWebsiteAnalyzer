"""
extractor/email_extractor.py
----------------------------
Extracts email addresses from raw HTML using regex.

Strategy:
  1. Scan visible HTML for email patterns (handles obfuscation like [at], (dot), etc.)
  2. Prioritise emails found near "contact", "editor", "author" keywords
  3. Filter out common false-positives (image filenames, example.com, etc.)
  4. De-duplicate and return sorted by likely relevance

Usage:
    from extractor.email_extractor import extract_emails
    emails = extract_emails(html)
"""

import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────────────────────

# Standard email regex (covers most real-world addresses)
_EMAIL_RE = re.compile(
    r"""(?<!\w)                   # Not preceded by a word char
        (                         # Capture group
            [a-zA-Z0-9._%+\-]+   # Local part
            @                     # @
            [a-zA-Z0-9.\-]+      # Domain
            \.[a-zA-Z]{2,}       # TLD (2+ chars)
        )
        (?!\w)                    # Not followed by a word char
    """,
    re.VERBOSE,
)

# Common obfuscation patterns — convert to real email, then re-run regex
_OBFUSCATION_SUBS = [
    (re.compile(r"\s*\[at\]\s*",      re.I), "@"),
    (re.compile(r"\s*\(at\)\s*",      re.I), "@"),
    (re.compile(r"\s+at\s+",          re.I), "@"),
    (re.compile(r"\s*\[dot\]\s*",     re.I), "."),
    (re.compile(r"\s*\(dot\)\s*",     re.I), "."),
]

# False-positive filters — skip any email matching these patterns
_BLOCKLIST_PATTERNS = [
    re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|css|js|json|xml|php|asp)$", re.I),
    re.compile(r"@example\.", re.I),
    re.compile(r"@domain\.", re.I),
    re.compile(r"@yourdomain\.", re.I),
    re.compile(r"@sentry\.", re.I),
    re.compile(r"noreply@", re.I),
    re.compile(r"no-reply@", re.I),
    re.compile(r"donotreply@", re.I),
    re.compile(r"@\d+\.\d+"),          # IP addresses as domain
    re.compile(r"\.{2,}"),              # Double dots in local part
]

# Keywords that suggest proximity to a contact email
_CONTACT_KEYWORDS = re.compile(
    r"(contact|editor|author|press|media|adverti|submit|pitch|tip|hello|info|reach)",
    re.I,
)


def _deobfuscate(text: str) -> str:
    """Replace common email obfuscation patterns."""
    for pattern, replacement in _OBFUSCATION_SUBS:
        text = pattern.sub(replacement, text)
    return text


def _is_blocked(email: str) -> bool:
    """Return True if the email matches any false-positive filter."""
    return any(p.search(email) for p in _BLOCKLIST_PATTERNS)


def _score_email(email: str, surrounding_text: str) -> int:
    """
    Assign a relevance score so we can sort results.
    Higher = more likely to be a real contact email.
    """
    score = 0
    local_part = email.split("@")[0].lower()

    # Reward contact-like local parts
    if re.match(r"^(contact|hello|info|press|editor|media|advertise|tips?)$", local_part):
        score += 20

    # Reward if found near a contact keyword
    if _CONTACT_KEYWORDS.search(surrounding_text):
        score += 15

    # Penalise very short local parts (likely noise)
    if len(local_part) < 4:
        score -= 10

    return score


def extract_emails(html: str, base_url: str = "") -> list[str]:
    """
    Extract all email addresses from HTML content.

    Args:
        html:      Raw HTML string.
        base_url:  The page URL (used to filter out self-referencing emails).

    Returns:
        De-duplicated list of email strings, sorted by relevance.
    """
    if not html:
        return []

    # Step 1: De-obfuscate
    text = _deobfuscate(html)

    # Step 2: Raw regex extraction + context window
    scored: dict[str, int] = {}
    for match in _EMAIL_RE.finditer(text):
        email = match.group(1).lower().strip(".")
        if _is_blocked(email):
            continue

        # Grab up to 200 chars around the match for context scoring
        start   = max(0, match.start() - 100)
        end     = min(len(text), match.end() + 100)
        context = text[start:end]

        existing = scored.get(email, 0)
        scored[email] = max(existing, _score_email(email, context))

    # Step 3: Sort by score descending, then alphabetically for stability
    sorted_emails = sorted(scored.items(), key=lambda x: (-x[1], x[0]))

    result = [email for email, _ in sorted_emails]
    logger.debug(f"Extracted {len(result)} email(s) from {base_url or 'page'}")
    return result
