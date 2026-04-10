# 🔍 Bulk Website Analyzer

> Classify 500–1,000+ websites at scale using AI. Feed it a CSV of URLs (or let it discover them automatically), and get back niche, site type, language, author, and contact email — all in one CSV or Google Sheet.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Claude AI](https://img.shields.io/badge/AI-Claude%20Haiku-purple?logo=anthropic)
![License](https://img.shields.io/badge/license-MIT-green)
![Phase](https://img.shields.io/badge/phase-2%20complete-brightgreen)

---

## What It Does

| Field | Example Output |
|---|---|
| Niche / Topic | `Personal Finance` |
| Site Type | `Blog` / `News` / `Business` / `E-commerce` |
| Language | `English (en)` |
| Author / Editor | `J.D. Roth` |
| Contact Email | `support@getrichslowly.org` |
| Email Valid | `True` (DNS MX verified) |
| Confidence Scores | `95% niche · 92% type · 88% author` |
| CMS Detected | `WordPress` / `Shopify` / `Ghost` |

**Sample output** from a real run on `--discover "personal finance blog"`:

```
https://www.getrichslowly.org  →  Personal Finance | Blog | J.D. Roth | support@getrichslowly.org
https://www.ramseysolutions.com  →  Personal Finance | Business | Dave Ramsey | help@ramseysolutions.com
https://finmasters.com  →  Personal Finance Education | Blog | Steve Rogers | hi@finmasters.com
```

---

## Quick Start

**Prerequisites:** Python 3.10+, an [Anthropic API key](https://console.anthropic.com)

```bash
# 1. Clone the repo
git clone https://github.com/yourusername/BulkWebsiteAnalyzer.git
cd BulkWebsiteAnalyzer

# 2. Install dependencies
pip install -r requirements.txt
pip install langdetect ddgs        # required extras

# 3. Configure
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 4. Run on the sample CSV
python analyzer.py --input sample_data/sites.csv
```

Results land in a timestamped CSV in the `results/` folder. That's it.

---

## Installation

### Core dependencies
```bash
pip install -r requirements.txt
pip install langdetect ddgs
```

### Optional: Playwright (for JS-heavy / bot-protected sites)
```bash
pip install playwright
python -m playwright install chromium
```

### Optional: Email DNS validation
```bash
pip install dnspython
```

### Optional: Google Sheets export
```bash
pip install gspread google-auth
```

---

## Usage

### Analyse a CSV of URLs
```bash
python analyzer.py --input sites.csv
```

### Auto-discover URLs by niche (no CSV needed)
```bash
python analyzer.py --discover "personal finance blog" --discover-count 50
```

### Combine discovery + your own CSV
```bash
python analyzer.py --input existing.csv --discover "SEO tools" --discover-count 30
```

### Full-featured run
```bash
python analyzer.py \
  --input sites.csv \
  --discover "personal finance blog" --discover-count 50 \
  --validate-emails \
  --model claude-sonnet-4-6 \
  --workers 30 \
  --output results/my_run.csv
```

### Push results to Google Sheets
```bash
python analyzer.py --input sites.csv --sheets --sheets-name "My Research"
```

---

## All CLI Options

```
Input / Output:
  --input  CSV_FILE      Input CSV with a 'url' column
  --output CSV_FILE      Output path (default: results/results_TIMESTAMP.csv)

AI Settings:
  --model  MODEL_ID      Claude model (default: claude-haiku-4-5-20251001)
  --batch-size N         Sites per API call (default: 10)

Performance:
  --workers N            Concurrent fetch workers (default: 20)

Phase 2 Features:
  --validate-emails      DNS MX validation on all extracted emails
  --sheets               Push results to Google Sheets
  --sheets-name NAME     Spreadsheet name (default: 'Bulk Website Analysis')
  --discover QUERY       Keyword query for URL auto-discovery
  --discover-provider    duckduckgo | serpapi | google_cse | commoncrawl
  --discover-count N     URLs to discover (default: 50)

Utility:
  --dry-run              Validate input without fetching
  --verbose              Debug-level logging
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```env
# Required
ANTHROPIC_API_KEY=your_key_here

# Model (haiku = cheap & fast, sonnet = accurate)
CLAUDE_MODEL=claude-haiku-4-5-20251001

# Performance tuning
MAX_WORKERS=20
REQUEST_TIMEOUT=15
PER_DOMAIN_DELAY=2.0
CLAUDE_BATCH_SIZE=10
BODY_TEXT_LIMIT=3000

# Phase 2: URL discovery (optional)
SERPAPI_KEY=
GOOGLE_CSE_KEY=
GOOGLE_CSE_ID=

# Phase 2: Google Sheets (optional)
GOOGLE_SERVICE_ACCOUNT_FILE=path/to/key.json
```

---

## Cost Estimate

Using Claude Haiku (default):

| Sites | API Calls | Cost |
|---|---|---|
| 100 | 10 | ~$0.03 |
| 500 | 50 | ~$0.15 |
| 1,000 | 100 | ~$0.30 |

Switch to `--model claude-sonnet-4-6` for higher accuracy (~10× cost).

---

## How It Works

```
URLs (CSV or discovery)
        ↓
  Async HTTP Fetcher  ←──── Playwright fallback (auto on 403 or JS-heavy)
        ↓
  HTML Extraction
  ├── Title, meta, body text
  ├── Email addresses (regex + contact page)
  ├── Author name (JSON-LD, meta tags, bylines)
  └── CMS fingerprint
        ↓
  Claude AI (batched, 10 sites/call)
  ├── Niche classification
  ├── Site type
  ├── Language
  └── Confidence scores
        ↓
  Email DNS Validation (optional)
        ↓
  CSV / Google Sheets output
```

Full architecture diagram: [`website_analyzer_architecture.mermaid`](website_analyzer_architecture.mermaid)

---

## Project Structure

```
BulkWebsiteAnalyzer/
├── analyzer.py           # CLI entry point
├── orchestrator.py       # Async engine
├── models.py             # Pydantic data schemas
├── config.py             # Settings & env vars
├── input/
│   ├── csv_loader.py     # CSV parsing & URL validation
│   └── discovery.py      # DuckDuckGo / SerpAPI / Common Crawl
├── fetcher/
│   ├── http_fetcher.py   # Async httpx fetcher with retry
│   └── playwright_fetcher.py  # Headless Chromium fallback
├── extractor/
│   ├── html_parser.py    # Title, text, CMS detection
│   ├── email_extractor.py
│   └── author_parser.py
├── ai/
│   ├── prompt_builder.py
│   └── claude_client.py
├── validation/
│   └── email_validator.py  # Regex + DNS MX + optional SMTP
├── output/
│   ├── csv_writer.py
│   └── sheets_writer.py
├── sample_data/
│   └── sites.csv         # 10 test URLs to get started
├── requirements.txt
└── .env.example
```

---

## Input CSV Format

Minimum required — just a `url` column:
```csv
url
https://www.example.com
https://www.another.com
```

The loader also accepts columns named `URL`, `website`, `domain`, or `link`. Extra columns are passed through to the output unchanged.

---

## Roadmap

- [x] **Phase 1** — CSV input, async fetching, Claude AI classification, CSV output
- [x] **Phase 2** — Playwright fallback, email validation, Google Sheets, URL discovery
- [ ] **Phase 3** — Docker container, Apify proxy integration, web UI (Streamlit)
- [ ] **Phase 4** — Scheduled runs, database persistence, webhook notifications

---

## Contributing

Pull requests welcome. For major changes please open an issue first.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Open a pull request

---

## License

MIT
