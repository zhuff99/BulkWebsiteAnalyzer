"""
output/sheets_writer.py
-----------------------
Pushes results to a Google Sheets spreadsheet using the gspread library.

Setup (one-time):
  1. Go to https://console.cloud.google.com
  2. Create a project → enable "Google Sheets API" and "Google Drive API"
  3. Create a Service Account → download the JSON key file
  4. Set GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json in your .env
  5. Share the target spreadsheet with the service account email (Editor access)

Usage:
    from output.sheets_writer import push_to_sheets
    push_to_sheets(results, spreadsheet_name="Website Analysis")
"""

import logging
from typing import Optional

from models import ResultRow
from output.csv_writer import CSV_COLUMNS

logger = logging.getLogger(__name__)

# How many rows to write per API call (Sheets API limit is 1000 values per call)
_BATCH_SIZE = 200


def _check_gspread() -> bool:
    try:
        import gspread  # noqa: F401
        return True
    except ImportError:
        logger.error(
            "gspread is not installed. Run: pip install gspread google-auth"
        )
        return False


def _get_client():
    """Authenticate with Google Sheets using a service account key file."""
    import os
    import gspread
    from google.oauth2.service_account import Credentials

    key_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if not key_file:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_FILE is not set in your .env file. "
            "Set it to the path of your Google service account JSON key."
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_file(key_file, scopes=scopes)
    return gspread.authorize(creds)


def push_to_sheets(
    results:           list[ResultRow],
    spreadsheet_name:  str  = "Bulk Website Analysis",
    worksheet_name:    str  = "Results",
    create_if_missing: bool = True,
) -> Optional[str]:
    """
    Write ResultRow objects to a Google Sheet.

    If the spreadsheet doesn't exist and create_if_missing=True, it will be
    created automatically. Existing data in the worksheet is cleared and
    replaced on each run.

    Args:
        results:           Rows to write.
        spreadsheet_name:  Name of the Google Spreadsheet to write to.
        worksheet_name:    Name of the tab/worksheet within the spreadsheet.
        create_if_missing: Create the spreadsheet if it doesn't exist.

    Returns:
        URL of the spreadsheet, or None on failure.
    """
    if not results:
        logger.warning("push_to_sheets called with empty results — nothing to write.")
        return None

    if not _check_gspread():
        return None

    try:
        client = _get_client()

        # Open or create the spreadsheet
        try:
            spreadsheet = client.open(spreadsheet_name)
            logger.info(f"Opened existing spreadsheet: {spreadsheet_name}")
        except Exception:
            if create_if_missing:
                spreadsheet = client.create(spreadsheet_name)
                logger.info(f"Created new spreadsheet: {spreadsheet_name}")
            else:
                raise

        # Get or create the worksheet
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except Exception:
            worksheet = spreadsheet.add_worksheet(
                title=worksheet_name, rows=len(results) + 10, cols=len(CSV_COLUMNS)
            )

        # Clear existing content
        worksheet.clear()

        # Build rows: header + data
        header = CSV_COLUMNS
        rows   = [header] + [
            [str(v) for v in row.to_dict().values()]
            for row in results
        ]

        # Write in batches to stay within Sheets API limits
        for i in range(0, len(rows), _BATCH_SIZE):
            chunk = rows[i : i + _BATCH_SIZE]
            start_row = i + 1
            worksheet.append_rows(chunk, value_input_option="USER_ENTERED")
            logger.debug(f"Wrote rows {start_row}-{start_row + len(chunk) - 1}")

        # Format the header row bold
        try:
            worksheet.format(
                f"A1:{chr(64 + len(CSV_COLUMNS))}1",
                {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.11, "green": 0.33, "blue": 0.55}},
            )
        except Exception:
            pass  # Formatting is best-effort

        url = spreadsheet.url
        logger.info(f"Results pushed to Google Sheets: {url}")
        print(f"\n  Google Sheets: {url}\n")
        return url

    except Exception as exc:
        logger.error(f"Failed to push to Google Sheets: {exc}")
        return None
