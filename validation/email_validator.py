"""
validation/email_validator.py
------------------------------
Three-stage email validation pipeline:

  Stage 1 — Format check   : RFC-5322 regex (free, instant)
  Stage 2 — DNS MX lookup  : confirms the domain can receive email (free, ~50ms)
  Stage 3 — SMTP probe     : connects to MX server to verify deliverability
                             (optional, disabled by default — can trigger spam filters)

Usage:
    from validation.email_validator import validate_email, validate_emails_bulk

    result = asyncio.run(validate_email("contact@example.com"))
    print(result.is_valid, result.mx_valid)
"""

import asyncio
import logging
import re
import smtplib
import socket
from typing import Optional

from models import EmailResult

logger = logging.getLogger(__name__)

# ── Stage 1: Format validation ────────────────────────────────────────────────

_EMAIL_FORMAT_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _is_format_valid(email: str) -> bool:
    return bool(_EMAIL_FORMAT_RE.match(email.strip()))


# ── Stage 2: DNS MX lookup ────────────────────────────────────────────────────

async def _has_mx_record(domain: str, timeout: float = 5.0) -> bool:
    """
    Check if a domain has MX records using dnspython.
    Returns False if dnspython is not installed or the lookup fails.
    """
    try:
        import dns.asyncresolver
        import dns.exception

        resolver = dns.asyncresolver.Resolver()
        resolver.lifetime = timeout

        records = await resolver.resolve(domain, "MX")
        return len(records) > 0

    except ImportError:
        logger.debug("dnspython not installed — skipping MX lookup. Run: pip install dnspython")
        return False

    except Exception as exc:
        logger.debug(f"MX lookup failed for {domain}: {exc}")
        return False


# ── Stage 3: SMTP probe (optional) ───────────────────────────────────────────

def _smtp_probe(email: str, domain: str, timeout: float = 5.0) -> bool:
    """
    Connect to the domain's MX server and issue RCPT TO without sending mail.
    This is the most accurate validation but can be flagged as suspicious by
    mail servers. Disabled by default.
    """
    try:
        import dns.resolver
        records = dns.resolver.resolve(domain, "MX")
        mx_host = str(sorted(records, key=lambda r: r.preference)[0].exchange)

        with smtplib.SMTP(timeout=timeout) as smtp:
            smtp.connect(mx_host, 25)
            smtp.helo(socket.getfqdn())
            smtp.mail("verify@example.com")
            code, _ = smtp.rcpt(email)
            return code == 250

    except Exception as exc:
        logger.debug(f"SMTP probe failed for {email}: {exc}")
        return False


# ── Main validate function ────────────────────────────────────────────────────

async def validate_email(
    email: str,
    smtp_probe: bool = False,
) -> EmailResult:
    """
    Validate a single email address through up to three stages.

    Args:
        email:      The email address to validate.
        smtp_probe: If True, also run SMTP verification (slower, more accurate).

    Returns:
        EmailResult with format_valid, mx_valid, and is_valid fields populated.
    """
    email = email.strip().lower()
    result = EmailResult(email=email)

    # Stage 1: Format
    result.format_valid = _is_format_valid(email)
    if not result.format_valid:
        logger.debug(f"Invalid format: {email}")
        return result

    # Stage 2: MX record
    domain = email.split("@")[1]
    result.mx_valid = await _has_mx_record(domain)

    # Stage 3: SMTP (optional)
    if smtp_probe and result.mx_valid:
        smtp_ok = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _smtp_probe(email, domain)
        )
        result.is_valid = smtp_ok
    else:
        result.is_valid = result.format_valid and result.mx_valid

    logger.debug(
        f"Email {email}: format={result.format_valid} mx={result.mx_valid} valid={result.is_valid}"
    )
    return result


async def validate_emails_bulk(
    emails: list[str],
    smtp_probe: bool = False,
    concurrency: int = 20,
) -> dict[str, EmailResult]:
    """
    Validate multiple emails concurrently.

    Args:
        emails:      List of email strings to validate.
        smtp_probe:  Enable SMTP stage for all emails.
        concurrency: Max simultaneous DNS lookups.

    Returns:
        Dict mapping each email string to its EmailResult.
    """
    if not emails:
        return {}

    semaphore = asyncio.Semaphore(concurrency)

    async def _limited(email: str) -> tuple[str, EmailResult]:
        async with semaphore:
            return email, await validate_email(email, smtp_probe=smtp_probe)

    results = await asyncio.gather(*[_limited(e) for e in emails])
    return dict(results)
