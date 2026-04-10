"""
analyzer.py
-----------
Command-line entry point for the Bulk Website Analyzer.

Usage examples:
  # Analyse a CSV of URLs
  python analyzer.py --input sites.csv

  # Specify output file and model
  python analyzer.py --input sites.csv --output results/run1.csv --model claude-sonnet-4-6

  # Use faster/cheaper Haiku with 30 concurrent workers
  python analyzer.py --input sites.csv --workers 30 --model claude-haiku-4-5-20251001

  # Override batch size (sites per Claude API call)
  python analyzer.py --input sites.csv --batch-size 5

Run `python analyzer.py --help` for the full option list.
"""

import argparse
import asyncio
import logging
import sys
import platform
from pathlib import Path

# Windows requires SelectorEventLoop for httpx compatibility
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import config
from config import validate_config
from input.csv_loader import load_urls
from orchestrator import run

# ── Logging setup ─────────────────────────────────────────────────────────────

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Quieten noisy third-party loggers unless in verbose mode
    if not verbose:
        for noisy in ("httpx", "httpcore", "hpack", "charset_normalizer"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


# ── CLI argument parser ───────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analyzer",
        description=(
            "Bulk Website Analyzer — classify websites at scale using AI.\n"
            "Reads URLs from a CSV, scrapes each site, and outputs niche,\n"
            "type, language, author, and contact email to CSV."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyzer.py --input sample_data/sites.csv
  python analyzer.py --input sites.csv --output output/results.csv --model claude-sonnet-4-6
  python analyzer.py --input sites.csv --workers 30 --batch-size 5 --verbose
        """,
    )

    # Input / Output
    io_group = parser.add_argument_group("Input / Output")
    io_group.add_argument(
        "--input", "-i",
        required=False,
        default=None,
        metavar="CSV_FILE",
        help="Path to input CSV file containing URLs (must have a 'url' column).",
    )
    io_group.add_argument(
        "--output", "-o",
        metavar="CSV_FILE",
        default=None,
        help="Path for output CSV. Defaults to output/results_<timestamp>.csv",
    )

    # AI settings
    ai_group = parser.add_argument_group("AI Settings")
    ai_group.add_argument(
        "--model", "-m",
        default=config.CLAUDE_MODEL,
        metavar="MODEL_ID",
        help=(
            f"Claude model to use. Default: {config.CLAUDE_MODEL}\n"
            "  claude-haiku-4-5-20251001    → cheapest/fastest (~$0.25 per 500 sites)\n"
            "  claude-sonnet-4-6  → most accurate (~$3.00 per 500 sites)"
        ),
    )
    ai_group.add_argument(
        "--batch-size", "-b",
        type=int,
        default=config.CLAUDE_BATCH_SIZE,
        metavar="N",
        help=f"Number of sites per Claude API call. Default: {config.CLAUDE_BATCH_SIZE}",
    )

    # Performance
    perf_group = parser.add_argument_group("Performance")
    perf_group.add_argument(
        "--workers", "-w",
        type=int,
        default=config.MAX_CONCURRENT_WORKERS,
        metavar="N",
        help=f"Number of concurrent fetch workers. Default: {config.MAX_CONCURRENT_WORKERS}",
    )

    # Phase 2 features
    p2_group = parser.add_argument_group("Phase 2 Features")
    p2_group.add_argument(
        "--validate-emails",
        action="store_true",
        help="Run DNS MX validation on extracted emails (requires dnspython).",
    )
    p2_group.add_argument(
        "--sheets",
        action="store_true",
        help="Push results to Google Sheets (requires gspread + service account key).",
    )
    p2_group.add_argument(
        "--sheets-name",
        default="Bulk Website Analysis",
        metavar="NAME",
        help="Name of the Google Spreadsheet to write to. Default: 'Bulk Website Analysis'",
    )
    p2_group.add_argument(
        "--discover",
        metavar="QUERY",
        help="Auto-discover URLs for a niche query instead of (or in addition to) --input.",
    )
    p2_group.add_argument(
        "--discover-provider",
        default="duckduckgo",
        choices=["duckduckgo", "serpapi", "google_cse", "commoncrawl"],
        help="URL discovery provider. Default: duckduckgo (free, no API key needed)",
    )
    p2_group.add_argument(
        "--discover-count",
        type=int,
        default=50,
        metavar="N",
        help="Number of URLs to discover. Default: 50",
    )

    # Misc
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug-level logging.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and validate URLs, print summary, then exit without fetching.",
    )

    return parser


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = build_parser()
    args   = parser.parse_args()

    setup_logging(verbose=args.verbose)
    logger = logging.getLogger("analyzer")

    # ── Config warnings ────────────────────────────────────────────────────
    warnings = validate_config()
    for w in warnings:
        logger.warning(f"Config: {w}")

    # Override config with CLI flags
    config.CLAUDE_MODEL      = args.model
    config.CLAUDE_BATCH_SIZE = args.batch_size

    # ── Load URLs (CSV and/or discovery) ──────────────────────────────────
    urls: list[str] = []

    if args.input:
        logger.info(f"Loading URLs from: {args.input}")
        try:
            urls = load_urls(args.input)
        except (FileNotFoundError, ValueError) as exc:
            logger.error(str(exc))
            return 1

    if args.discover:
        logger.info(f"Discovering URLs for query: {args.discover!r} via {args.discover_provider}")
        from input.discovery import discover_urls
        try:
            discovered = asyncio.run(discover_urls(
                query=args.discover,
                num_results=args.discover_count,
                provider=args.discover_provider,
            ))
            logger.info(f"Discovered {len(discovered)} URLs.")
            # Merge with CSV URLs, deduplicating
            existing = set(urls)
            urls += [u for u in discovered if u not in existing]
        except Exception as exc:
            logger.error(f"URL discovery failed: {exc}")
            if not urls:
                return 1

    if not urls:
        logger.error("No URLs to process. Provide --input and/or --discover.")
        return 1

    print(f"\n  Input file : {args.input}")
    print(f"  URLs found : {len(urls)}")
    print(f"  Model      : {args.model}")
    print(f"  Workers    : {args.workers}")
    print(f"  Batch size : {args.batch_size}")
    print(f"  Output     : {args.output or 'auto-generated'}\n")

    if args.dry_run:
        logger.info("Dry run — exiting without processing.")
        return 0

    # ── Run pipeline ───────────────────────────────────────────────────────
    try:
        output_path = asyncio.run(
            run(
                urls=urls,
                output_path=args.output,
                max_workers=args.workers,
                batch_size=args.batch_size,
                validate_emails=args.validate_emails,
                push_sheets=args.sheets,
                sheets_name=args.sheets_name,
            )
        )
        logger.info(f"Done. Results saved to: {output_path}")
        return 0

    except KeyboardInterrupt:
        logger.warning("\nInterrupted by user. Partial results may have been saved.")
        return 130

    except Exception as exc:
        logger.error(f"Fatal error: {exc}", exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
