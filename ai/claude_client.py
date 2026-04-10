"""
ai/claude_client.py
-------------------
Thin wrapper around the Anthropic Python SDK.

Responsibilities:
  - Send a batch of SiteData objects to the Claude API.
  - Parse the JSON response into a list of ClassificationResult objects.
  - Handle API errors gracefully (never crash the whole pipeline on one bad batch).
  - Respect rate limits with exponential back-off.

Usage:
    import asyncio
    from ai.claude_client import classify_batch

    results = asyncio.run(classify_batch(sites))
"""

import asyncio
import json
import logging
from typing import Optional

import anthropic

import config
from models import ClassificationResult, ConfidenceScores, SiteData, SiteType
from ai.prompt_builder import SYSTEM_PROMPT, build_batch_prompt

logger = logging.getLogger(__name__)

# ── Client singleton ──────────────────────────────────────────────────────────
# Instantiated once per process; the SDK handles connection pooling internally.
_client: Optional[anthropic.Anthropic] = None

def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file or environment variables."
            )
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


# ── Response parser ───────────────────────────────────────────────────────────

def _safe_site_type(raw: Optional[str]) -> SiteType:
    """Convert a raw string to SiteType, defaulting to UNKNOWN."""
    if not raw:
        return SiteType.UNKNOWN
    for member in SiteType:
        if member.value.lower() == str(raw).lower():
            return member
    return SiteType.UNKNOWN


def _parse_confidence(raw: Optional[dict]) -> ConfidenceScores:
    """Parse confidence dict from Claude, clamping values to 0-100."""
    if not raw or not isinstance(raw, dict):
        return ConfidenceScores()

    def clamp(v) -> int:
        try:
            return max(0, min(100, int(v)))
        except (TypeError, ValueError):
            return 0

    return ConfidenceScores(
        niche=clamp(raw.get("niche",     0)),
        site_type=clamp(raw.get("site_type", 0)),
        language=clamp(raw.get("language",  0)),
        author=clamp(raw.get("author",    0)),
    )


def _strip_code_fences(text: str) -> str:
    """
    Remove markdown code fences that Claude sometimes wraps JSON in.
    e.g. ```json ... ``` or ``` ... ```
    """
    text = text.strip()
    # Strip opening fence (```json or ```)
    if text.startswith("```"):
        text = text[text.index("\n") + 1:] if "\n" in text else text[3:]
    # Strip closing fence
    if text.endswith("```"):
        text = text[: text.rfind("```")].strip()
    return text.strip()


def _parse_response(raw_json: str, sites: list[SiteData]) -> list[ClassificationResult]:
    """
    Parse Claude's JSON response into ClassificationResult objects.
    Falls back gracefully if individual entries are malformed.
    """
    # Always log what we got back so bugs are easy to diagnose
    logger.debug(f"Raw Claude response ({len(raw_json)} chars): {raw_json[:600]}")

    if not raw_json.strip():
        logger.error("Claude returned an empty response.")
        return [
            ClassificationResult(url=s.url, ai_error="Claude returned empty response")
            for s in sites
        ]

    cleaned = _strip_code_fences(raw_json)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(f"Claude response was not valid JSON: {exc}")
        logger.error(f"Cleaned response snippet: {cleaned[:600]}")
        # Return error results for every site in the batch
        return [
            ClassificationResult(url=s.url, ai_error=f"JSON parse error: {exc}")
            for s in sites
        ]

    if not isinstance(data, list):
        logger.error("Claude response was not a JSON array.")
        return [
            ClassificationResult(url=s.url, ai_error="Response was not a JSON array")
            for s in sites
        ]

    results: list[ClassificationResult] = []
    site_url_map = {s.url: s for s in sites}

    for item in data:
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        results.append(ClassificationResult(
            url=url,
            niche=item.get("niche"),
            site_type=_safe_site_type(item.get("site_type")),
            language=item.get("language"),
            author=item.get("author"),
            confidence=_parse_confidence(item.get("confidence")),
        ))

    # If Claude returned fewer items than we sent, fill the gaps
    result_urls = {r.url for r in results}
    for site in sites:
        if site.url not in result_urls:
            logger.warning(f"Claude did not return a result for: {site.url}")
            results.append(ClassificationResult(
                url=site.url,
                ai_error="Missing from Claude response",
            ))

    return results


# ── Main classify function ────────────────────────────────────────────────────

async def classify_batch(
    sites: list[SiteData],
    max_retries: int = 3,
) -> list[ClassificationResult]:
    """
    Classify a batch of sites using the Claude API.

    Args:
        sites:       List of SiteData objects (should be <= config.CLAUDE_BATCH_SIZE).
        max_retries: How many times to retry on rate-limit or server errors.

    Returns:
        List of ClassificationResult objects in the same order as input.
        On total failure, returns error results rather than raising.
    """
    if not sites:
        return []

    # Skip AI if no API key — return empty classifications
    if not config.ANTHROPIC_API_KEY:
        logger.warning("No ANTHROPIC_API_KEY — skipping AI classification.")
        return [ClassificationResult(url=s.url, ai_error="No API key configured") for s in sites]

    client = _get_client()
    user_content = build_batch_prompt(sites)

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                f"Calling Claude ({config.CLAUDE_MODEL}) for batch of "
                f"{len(sites)} sites [attempt {attempt}/{max_retries}]"
            )

            # Run the synchronous SDK call in a thread so we don't block the event loop
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=config.CLAUDE_MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_content}],
                )
            )

            raw_text = response.content[0].text
            logger.debug(f"Claude response ({len(raw_text)} chars): {raw_text[:300]}")

            results = _parse_response(raw_text, sites)
            logger.info(f"Classified {len(results)} sites successfully.")
            return results

        except anthropic.RateLimitError:
            wait = 2 ** attempt
            logger.warning(f"Rate limited by Claude API. Waiting {wait}s before retry.")
            await asyncio.sleep(wait)

        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                wait = 2 ** attempt
                logger.warning(f"Claude server error {exc.status_code}. Waiting {wait}s.")
                await asyncio.sleep(wait)
            else:
                logger.error(f"Claude API error {exc.status_code}: {exc.message}")
                break

        except Exception as exc:
            logger.error(f"Unexpected error calling Claude API: {exc}")
            break

    # All retries exhausted
    error_msg = f"Claude API failed after {max_retries} attempts"
    logger.error(error_msg)
    return [ClassificationResult(url=s.url, ai_error=error_msg) for s in sites]
