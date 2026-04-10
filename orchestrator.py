"""
orchestrator.py
---------------
The async engine that ties every layer together.

Pipeline per URL:
  1. Fetch HTML              (fetcher.http_fetcher)
  2. Parse & extract         (extractor.html_parser / email_extractor / author_parser)
  3. Batch for AI            (ai.claude_client — groups N sites per API call)
  4. Merge AI results        (models.ResultRow)
  5. Write to CSV            (output.csv_writer)

Concurrency model:
  - asyncio.Queue holds all pending URLs.
  - A pool of MAX_CONCURRENT_WORKERS coroutines drain the queue.
  - After every CLAUDE_BATCH_SIZE sites are fetched, they are sent to Claude together.
  - tqdm progress bar tracks completions in real time.

Usage (called by analyzer.py):
    import asyncio
    from orchestrator import run

    asyncio.run(run(urls, output_path="output/results.csv"))
"""

import asyncio
import logging
import time
from collections.abc import Sequence

from tqdm.asyncio import tqdm

import config
from ai.claude_client import classify_batch
from extractor.author_parser import extract_author
from extractor.email_extractor import extract_emails
from extractor.html_parser import enrich_site_data
from fetcher.http_fetcher import fetch_url
from models import FetchStatus, ResultRow, SiteData, ClassificationResult
from output.csv_writer import make_output_path, write_results, write_summary
from validation.email_validator import validate_emails_bulk

logger = logging.getLogger(__name__)


# ── Step 1+2: Fetch and extract a single URL ──────────────────────────────────

async def _fetch_and_extract(url: str) -> SiteData:
    """
    Fetch a URL and run all rule-based extraction.
    If the page body is suspiciously short after httpx (JS-heavy site),
    automatically retries with Playwright before extraction.
    """
    site = await fetch_url(url)

    # Proactive Playwright retry: if httpx returned HTML but almost no visible
    # text, the site is likely a JS SPA. Retry with Playwright to get full content.
    if (
        site.fetch_status == FetchStatus.OK
        and site.html
        and len(site.html) < 50_000  # small HTML is a strong JS-SPA signal
    ):
        from fetcher.playwright_fetcher import fetch_url_playwright, _check_playwright
        if _check_playwright():
            logger.info(f"Short HTML ({len(site.html):,} chars) — retrying with Playwright: {url}")
            pw_site = await fetch_url_playwright(url)
            if pw_site.fetch_status == FetchStatus.OK and pw_site.html:
                site = pw_site  # use the richer Playwright result

    if site.fetch_status == FetchStatus.OK and site.html:
        site = enrich_site_data(site)
        site.emails = extract_emails(site.html, base_url=url)
        site.author = extract_author(site.html)

    return site


# ── Step 4: Merge SiteData + ClassificationResult → ResultRow ─────────────────

def _merge(site: SiteData, classification: ClassificationResult) -> ResultRow:
    """Combine raw extraction + AI classification into a single output row."""
    # Prefer AI author over rule-based if AI has reasonable confidence
    author = classification.author
    if not author and classification.confidence.author < 50:
        author = site.author  # fall back to rule-based

    # Pick the best email (first one from our sorted/scored list)
    best_email = site.emails[0] if site.emails else None

    # If fetch failed, reflect that in the status
    status = site.fetch_status.value
    if classification.ai_error and site.fetch_status == FetchStatus.OK:
        status = "AI_ERROR"

    return ResultRow(
        url=site.url,
        niche=classification.niche,
        site_type=classification.site_type.value if classification.site_type else None,
        language=classification.language,
        author=author,
        email=best_email,
        email_valid=None,    # Phase 2: DNS/SMTP validation
        confidence_niche=classification.confidence.niche   or None,
        confidence_type=classification.confidence.site_type or None,
        confidence_author=classification.confidence.author  or None,
        cms=site.cms,
        status=status,
        error=site.fetch_error or classification.ai_error,
    )


# ── Step 3: Classify a batch with Claude ─────────────────────────────────────

async def _classify_and_merge(sites: list[SiteData]) -> list[ResultRow]:
    """Send a batch to Claude and merge results back into ResultRows."""
    # Only classify sites that were fetched successfully
    good_sites   = [s for s in sites if s.fetch_status == FetchStatus.OK]
    failed_sites = [s for s in sites if s.fetch_status != FetchStatus.OK]

    # Build error rows for sites that failed to fetch
    failed_rows = [
        ResultRow(
            url=s.url,
            status=s.fetch_status.value,
            error=s.fetch_error,
        )
        for s in failed_sites
    ]

    if not good_sites:
        return failed_rows

    classifications = await classify_batch(good_sites)
    class_map = {c.url: c for c in classifications}

    result_rows = []
    for site in good_sites:
        classification = class_map.get(
            site.url,
            ClassificationResult(url=site.url, ai_error="No classification returned"),
        )
        result_rows.append(_merge(site, classification))

    return result_rows + failed_rows


# ── Main run function ─────────────────────────────────────────────────────────

async def run(
    urls: list[str],
    output_path: str | None = None,
    max_workers: int | None = None,
    batch_size: int | None = None,
    validate_emails: bool = False,
    push_sheets: bool = False,
    sheets_name: str = "Bulk Website Analysis",
) -> str:
    """
    Run the full pipeline on a list of URLs.

    Args:
        urls:        List of URL strings to process.
        output_path: Where to write the CSV. Auto-generated if None.
        max_workers: Concurrent fetch workers (defaults to config.MAX_CONCURRENT_WORKERS).
        batch_size:  Sites per Claude API call (defaults to config.CLAUDE_BATCH_SIZE).

    Returns:
        Path to the output CSV file.
    """
    if not urls:
        raise ValueError("No URLs provided.")

    output_path = output_path or make_output_path()
    workers     = max_workers or config.MAX_CONCURRENT_WORKERS
    batch_sz    = batch_size  or config.CLAUDE_BATCH_SIZE
    start_time  = time.monotonic()

    logger.info(f"Starting run: {len(urls)} URLs | {workers} workers | batch={batch_sz}")
    logger.info(f"Output: {output_path}")

    # ── Queue setup ────────────────────────────────────────────────────────
    queue: asyncio.Queue[str] = asyncio.Queue()
    for url in urls:
        await queue.put(url)

    # Shared state
    pending_sites: list[SiteData]          = []
    pending_lock  = asyncio.Lock()
    flush_tasks:   list[asyncio.Task]      = []   # track all flush tasks so we can await them
    all_rows:      list[ResultRow]         = []
    rows_lock      = asyncio.Lock()

    async def flush_batch(sites_to_flush: list[SiteData]) -> None:
        """Classify a batch, write to CSV, and accumulate rows for summary."""
        rows = await _classify_and_merge(sites_to_flush)
        write_results(rows, output_path)
        async with rows_lock:
            all_rows.extend(rows)

    # ── Worker coroutine ───────────────────────────────────────────────────
    async def worker(progress_bar: tqdm) -> None:
        nonlocal pending_sites
        while True:
            try:
                url = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            try:
                site = await _fetch_and_extract(url)
            except Exception as exc:
                logger.error(f"Unhandled error processing {url}: {exc}")
                site = SiteData(
                    url=url,
                    fetch_status=FetchStatus.FAILED,
                    fetch_error=str(exc),
                )

            async with pending_lock:
                pending_sites.append(site)
                if len(pending_sites) >= batch_sz:
                    batch = pending_sites.copy()
                    pending_sites.clear()
                    # Schedule flush as a tracked task (not fire-and-forget)
                    flush_tasks.append(asyncio.create_task(flush_batch(batch)))

            progress_bar.update(1)
            queue.task_done()

    # ── Launch workers ─────────────────────────────────────────────────────
    with tqdm(total=len(urls), desc="Analysing", unit="site") as pbar:
        worker_tasks = [
            asyncio.create_task(worker(pbar))
            for _ in range(min(workers, len(urls)))
        ]
        await asyncio.gather(*worker_tasks)

    # Flush any remaining sites that didn't fill a full batch
    async with pending_lock:
        if pending_sites:
            flush_tasks.append(asyncio.create_task(flush_batch(pending_sites.copy())))
            pending_sites.clear()

    # Wait for ALL flush tasks to complete before printing the summary
    if flush_tasks:
        await asyncio.gather(*flush_tasks)

    # ── Email validation (Phase 2) ─────────────────────────────────────────
    if validate_emails:
        logger.info("Running email DNS validation...")
        all_emails = [r.email for r in all_rows if r.email]
        if all_emails:
            validation_map = await validate_emails_bulk(all_emails)
            for row in all_rows:
                if row.email and row.email in validation_map:
                    row.email_valid = validation_map[row.email].is_valid
            # Rewrite CSV with updated email_valid column
            from output.csv_writer import CSV_COLUMNS
            import csv
            from pathlib import Path
            rows_dicts = [r.to_dict() for r in all_rows]
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows_dicts)
            logger.info(f"Email validation complete for {len(all_emails)} addresses.")

    # ── Google Sheets export (Phase 2) ────────────────────────────────────
    if push_sheets:
        from output.sheets_writer import push_to_sheets
        push_to_sheets(all_rows, spreadsheet_name=sheets_name)

    total_ok     = sum(1 for r in all_rows if r.status in (FetchStatus.OK.value, "AI_ERROR"))
    total_failed = sum(1 for r in all_rows if r.status not in (FetchStatus.OK.value, "AI_ERROR"))

    elapsed = time.monotonic() - start_time
    write_summary(len(urls), total_ok, total_failed, output_path, elapsed)

    return output_path
