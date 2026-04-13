"""
config.py
---------
Central configuration. All settings come from environment variables
(loaded from a .env file) with sensible defaults for local development.
"""

import os
from dotenv import load_dotenv

# Load .env file if present (silently ignored if not found)
load_dotenv()


# ── API Keys ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
SERPAPI_KEY:       str = os.getenv("SERPAPI_KEY", "")       # Phase 2: URL discovery
GOOGLE_CSE_KEY:    str = os.getenv("GOOGLE_CSE_KEY", "")    # Phase 2: URL discovery
GOOGLE_CSE_ID:     str = os.getenv("GOOGLE_CSE_ID", "")     # Phase 2: URL discovery


# ── Claude AI Settings ────────────────────────────────────────────────────────

# Model options:
#   "claude-haiku-4-5"    → cheap, fast, ~$0.25 per 500 sites  (recommended default)
#   "claude-sonnet-4-6"   → accurate, ~$3.00 per 500 sites
CLAUDE_MODEL:       str = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
CLAUDE_MAX_TOKENS:  int = int(os.getenv("CLAUDE_MAX_TOKENS", "2048"))
CLAUDE_BATCH_SIZE:  int = int(os.getenv("CLAUDE_BATCH_SIZE", "10"))  # Sites per API call


# ── Fetcher Settings ──────────────────────────────────────────────────────────

MAX_CONCURRENT_WORKERS: int   = int(os.getenv("MAX_WORKERS", "20"))
REQUEST_TIMEOUT:        float = float(os.getenv("REQUEST_TIMEOUT", "15"))   # seconds
PER_DOMAIN_DELAY:       float = float(os.getenv("PER_DOMAIN_DELAY", "2.0")) # seconds
MAX_RETRIES:            int   = int(os.getenv("MAX_RETRIES", "3"))

# Maximum characters of body text sent to the AI (keep costs down)
BODY_TEXT_LIMIT: int = int(os.getenv("BODY_TEXT_LIMIT", "3000"))

# Rotate user-agents to reduce bot detection
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]


# ── Proxy Settings (Phase 3: Apify residential proxies) ──────────────────────

# Set to True to route all requests through Apify proxy
USE_PROXY:         bool = os.getenv("USE_PROXY", "false").lower() in ("true", "1", "yes")

# Your Apify API token (Settings → Integrations → API token)
APIFY_API_TOKEN:   str  = os.getenv("APIFY_API_TOKEN", "")

# Proxy group: RESIDENTIAL (best for Cloudflare) or SHADER (cheaper datacenter)
APIFY_PROXY_GROUP: str  = os.getenv("APIFY_PROXY_GROUP", "RESIDENTIAL")


# ── Output Settings ───────────────────────────────────────────────────────────

OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "results")


# ── Validation ────────────────────────────────────────────────────────────────

def validate_config() -> list[str]:
    """
    Returns a list of warning strings for any missing/misconfigured settings.
    Call this at startup so the user knows what's not set before a long batch.
    """
    warnings = []
    if not ANTHROPIC_API_KEY:
        warnings.append("ANTHROPIC_API_KEY is not set — AI classification will be skipped.")
    if CLAUDE_BATCH_SIZE < 1 or CLAUDE_BATCH_SIZE > 20:
        warnings.append(f"CLAUDE_BATCH_SIZE={CLAUDE_BATCH_SIZE} is outside the 1-20 range. Defaulting to 10.")
    if USE_PROXY and not APIFY_API_TOKEN:
        warnings.append("USE_PROXY is enabled but APIFY_API_TOKEN is not set — proxy will be disabled.")
    return warnings
