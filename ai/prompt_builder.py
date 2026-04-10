"""
ai/prompt_builder.py
--------------------
Builds the structured prompt sent to the Claude API.

Design decisions:
  - Batches up to CLAUDE_BATCH_SIZE sites per API call to minimise per-call
    overhead and keep costs low.
  - Sends only the minimal context needed: URL, title, meta description,
    first N chars of body text, and any rule-based signals already extracted.
  - Requests a strict JSON response so we can parse it reliably.

Usage:
    from ai.prompt_builder import build_batch_prompt
    prompt = build_batch_prompt(sites)
"""

import json
from models import SiteData

# ── System prompt (sets Claude's role) ───────────────────────────────────────

SYSTEM_PROMPT = """You are a website classification expert. You will receive a JSON array of websites, each with metadata extracted from their HTML. Your job is to classify each website and return a JSON array with your analysis.

For each site you MUST return:
- "url": the original URL (unchanged)
- "niche": the primary topic/niche in 2-5 words (e.g. "Personal Finance", "SaaS Marketing", "Food & Recipes", "Travel Blog", "B2B Software")
- "site_type": exactly one of: "Blog", "News", "Business", "E-commerce", "Portfolio", "Unknown"
- "language": the full language name and ISO code (e.g. "English (en)", "Spanish (es)", "French (fr)")
- "author": the primary author or editor name if identifiable from the content, otherwise null
- "confidence": an object with integer scores 0-100 for each field: {"niche": 85, "site_type": 90, "language": 95, "author": 70}

Rules:
- Return ONLY valid JSON — no markdown, no code fences, no explanation.
- The response must be a JSON array with one object per input site, in the same order.
- If you cannot determine a field, use null (never omit the key).
- Confidence scores reflect how certain you are given the available context.
- For "author": only include a name if you are fairly confident it is a real person's name, not a brand or organisation.
"""

# ── Site context builder ──────────────────────────────────────────────────────

def _site_context(site: SiteData) -> dict:
    """
    Produce the minimal JSON-serialisable context dict for a single site.
    Truncates long fields so the prompt stays within token budget.
    """
    return {
        "url":         site.url,
        "title":       (site.title or "")[:200],
        "description": (site.meta_description or "")[:300],
        "body_text":   (site.body_text or "")[:2500],
        "cms":         site.cms,
        # Provide rule-based hints — Claude can use or override them
        "detected_language_hint": site.detected_language,
        "rule_based_author_hint": site.author,
    }


def build_batch_prompt(sites: list[SiteData]) -> str:
    """
    Build the user-turn content for a Claude API call covering multiple sites.

    Args:
        sites: List of SiteData objects to classify (should be <= CLAUDE_BATCH_SIZE).

    Returns:
        JSON string to send as the user message.
    """
    contexts = [_site_context(s) for s in sites]
    return json.dumps(contexts, ensure_ascii=False, indent=2)
