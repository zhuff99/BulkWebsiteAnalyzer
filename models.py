"""
models.py
---------
All Pydantic data models used across the pipeline.
Every other module imports from here — never the other way around.
"""

from __future__ import annotations
from typing import Optional
from enum import Enum
from pydantic import BaseModel, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class SiteType(str, Enum):
    BLOG       = "Blog"
    NEWS       = "News"
    BUSINESS   = "Business"
    ECOMMERCE  = "E-commerce"
    PORTFOLIO  = "Portfolio"
    UNKNOWN    = "Unknown"

class FetchStatus(str, Enum):
    OK        = "OK"
    FAILED    = "FAILED"
    TIMEOUT   = "TIMEOUT"
    BLOCKED   = "BLOCKED"
    SKIPPED   = "SKIPPED"


# ── Stage 1: Raw scraped data ─────────────────────────────────────────────────

class SiteData(BaseModel):
    """Everything extracted from a single website before AI classification."""
    url:                str
    status_code:        Optional[int]   = None
    fetch_status:       FetchStatus     = FetchStatus.OK
    fetch_error:        Optional[str]   = None

    # HTML content
    html:               Optional[str]   = None

    # Extracted fields
    title:              Optional[str]   = None
    meta_description:   Optional[str]   = None
    body_text:          Optional[str]   = None   # First N chars of visible text
    detected_language:  Optional[str]   = None   # langdetect result
    emails:             list[str]       = []
    author:             Optional[str]   = None   # Rule-based author guess
    cms:                Optional[str]   = None   # WordPress, Ghost, etc.

    @field_validator("emails", mode="before")
    @classmethod
    def dedupe_emails(cls, v):
        seen = set()
        result = []
        for email in (v or []):
            email_lower = email.strip().lower()
            if email_lower not in seen:
                seen.add(email_lower)
                result.append(email.strip().lower())
        return result


# ── Stage 2: AI classification output ────────────────────────────────────────

class ConfidenceScores(BaseModel):
    niche:     int = 0   # 0-100
    site_type: int = 0
    language:  int = 0
    author:    int = 0

class ClassificationResult(BaseModel):
    """Structured output from the Claude API for a single site."""
    url:        str
    niche:      Optional[str]      = None
    site_type:  SiteType           = SiteType.UNKNOWN
    language:   Optional[str]      = None   # e.g. "English (en)"
    author:     Optional[str]      = None
    confidence: ConfidenceScores   = ConfidenceScores()
    ai_error:   Optional[str]      = None   # If Claude failed for this URL


# ── Stage 3: Email validation ─────────────────────────────────────────────────

class EmailResult(BaseModel):
    """Result of validating a single email address."""
    email:         str
    format_valid:  bool = False
    mx_valid:      bool = False
    is_valid:      bool = False   # True only if format + mx both pass


# ── Stage 4: Final output row ─────────────────────────────────────────────────

class ResultRow(BaseModel):
    """One row in the final CSV / Google Sheets output."""
    url:               str
    niche:             Optional[str]  = None
    site_type:         Optional[str]  = None
    language:          Optional[str]  = None
    author:            Optional[str]  = None
    email:             Optional[str]  = None
    email_valid:       Optional[bool] = None
    confidence_niche:  Optional[int]  = None
    confidence_type:   Optional[int]  = None
    confidence_author: Optional[int]  = None
    cms:               Optional[str]  = None
    status:            str            = FetchStatus.OK.value
    error:             Optional[str]  = None

    def to_dict(self) -> dict:
        return {
            "URL":               self.url,
            "Niche/Topic":       self.niche        or "",
            "Site Type":         self.site_type    or "",
            "Language":          self.language     or "",
            "Author/Editor":     self.author       or "",
            "Email":             self.email        or "",
            "Email Valid":       self.email_valid  if self.email_valid is not None else "",
            "Conf. Niche (%)":   self.confidence_niche  if self.confidence_niche  is not None else "",
            "Conf. Type (%)":    self.confidence_type   if self.confidence_type   is not None else "",
            "Conf. Author (%)":  self.confidence_author if self.confidence_author is not None else "",
            "CMS":               self.cms          or "",
            "Status":            self.status,
            "Error":             self.error        or "",
        }
