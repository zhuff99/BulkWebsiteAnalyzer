"""
output/csv_writer.py
--------------------
Writes a list of ResultRow objects to a timestamped CSV file.

Features:
  - Appends to existing file if it already exists (safe for resuming interrupted runs)
  - Writes a fresh file with headers if it does not exist
  - Creates the output directory automatically
  - Returns the final file path so callers can report it to the user

Usage:
    from output.csv_writer import write_results, open_output_file

    path = open_output_file("output/results.csv")
    # ... process sites ...
    write_results(results, path)
"""

import csv
import logging
import os
from datetime import datetime
from pathlib import Path

from models import ResultRow

logger = logging.getLogger(__name__)

# Column order in the output CSV (must match ResultRow.to_dict() keys)
CSV_COLUMNS = [
    "URL",
    "Niche/Topic",
    "Site Type",
    "Language",
    "Author/Editor",
    "Email",
    "Email Valid",
    "Conf. Niche (%)",
    "Conf. Type (%)",
    "Conf. Author (%)",
    "CMS",
    "Status",
    "Error",
]


def make_output_path(directory: str | None = None, prefix: str = "results") -> str:
    """
    Generate a timestamped output file path.
    Example: results/results_2026-04-10_143022.csv
    """
    import config
    out_dir = directory or config.OUTPUT_DIR
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return str(Path(out_dir) / f"{prefix}_{timestamp}.csv")


def write_results(results: list[ResultRow], filepath: str) -> int:
    """
    Write (or append) a list of ResultRow objects to a CSV file.

    If the file does not yet exist, it is created with a header row.
    If it already exists, rows are appended without repeating the header.

    Args:
        results:  List of ResultRow objects to write.
        filepath: Destination CSV path.

    Returns:
        Number of rows written.
    """
    if not results:
        logger.debug("write_results called with empty list — nothing to write.")
        return 0

    path        = Path(filepath)
    file_exists = path.exists() and path.stat().st_size > 0

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")

        if not file_exists:
            writer.writeheader()

        for row in results:
            writer.writerow(row.to_dict())
            rows_written += 1

    logger.info(f"Wrote {rows_written} rows to {filepath}")
    return rows_written


def write_summary(
    total: int,
    ok: int,
    failed: int,
    output_path: str,
    elapsed_seconds: float,
) -> None:
    """Print a summary table to stdout after a run completes."""
    print("\n" + "=" * 55)
    print("  BULK WEBSITE ANALYZER — RUN COMPLETE")
    print("=" * 55)
    print(f"  Total URLs processed : {total}")
    print(f"  Successful           : {ok}")
    print(f"  Failed / Skipped     : {failed}")
    print(f"  Time elapsed         : {elapsed_seconds:.1f}s")
    print(f"  Output file          : {output_path}")
    print("=" * 55 + "\n")
