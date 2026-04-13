# 🔍 Bulk Website Analyzer

> Classify 500–1,000+ websites at scale using AI. Feed it a CSV of URLs (or let it discover them automatically), and get back niche, site type, language, author, and contact email — exported to CSV or Google Sheets.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Claude AI](https://img.shields.io/badge/AI-Claude%20Haiku-purple?logo=anthropic)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker)
![License](https://img.shields.io/badge/license-MIT-green)
![Phase](https://img.shields.io/badge/phase-3%20complete-brightgreen)

---

## What It Does

| Field | Example Output |
|---|---|
| Niche / Topic | `Personal Finance` |
| Site Type | `Blog` / `News` / `Business` / `E-commerce` |
| Language | `English (en)` |
| Author / Editor | `Pat Flynn` |
| Contact Email | `neil@advanced.npdigital.com` |
| Email Valid | `True` (DNS MX verified) |
| Confidence Scores | `95% niche · 92% type · 88% author` |
| CMS Detected | `WordPress` / `Shopify` / `Ghost` |

---

## Demo

Real run across 20 diverse sites — authors detected, emails validated, all columns populated and auto-resized in Google Sheets:

![Google Sheets demo](Screenshots/google_sheets.jpg)

---

## Quick Start

There are two ways to run this — Docker (easier, no setup) or Python directly.

### Option A: Docker (recommended for most people)

You don't need Python, Playwright, or anything else installed. Just Docker.

**Step 1 — Install Docker Desktop**

Download it from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/). Open the `.dmg`, drag Docker to Applications, and launch it. Wait for the whale icon in your menu bar to say "Docker Desktop is running."

**Step 2 — Clone the repo and configure**

```bash
git clone https://github.com/zhuff99/BulkWebsiteAnalyzer.git
cd BulkWebsiteAnalyzer
cp .env.example .env
# Open .env and add your ANTHROPIC_API_KEY
```

**Step 3 — Build the image (one-time)**

```bash
docker build -t bulk-analyzer .
```

This downloads Python, installs all dependencies, and sets up Chromium inside a container. Takes a few minutes the first time, then it's cached.

**Step 4 — Run it**

```bash
docker compose run analyzer --input sample_data/sites.csv
```

Your results CSV will appear in the `results/` folder on your Mac. That's it.

> **Docker basics:** The image is like an app package — you build it once. A container is a running instance of that image. Docker Desktop is just the engine that has to be open in the background. You run everything from your terminal, not from the Docker Desktop GUI.

---

### Option B: Python directly

**Prerequisites:** Python 3.10+, an [Anthropic API key](https://console.anthropic.com)

```bash
# 1. Clone the repo
git clone https://github.com/zhuff99/BulkWebsiteAnalyzer.git
cd BulkWebsiteAnalyzer

# 2. Install dependencies
pip install -r requirements.txt
pip install playwright dnspython gspread google-auth ddgs
python -m playwright install chromium

# 3. Configure
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY at minimum

# 4. Run
python analyzer.py --input sample_data/sites.csv
```

Results land in a timestamped CSV under `results/`.

---

## Usage

### Analyse a CSV of URLs
```bash
# Python
python analyzer.py --input sites.csv

# Docker
docker compose run analyzer --input sites.csv
```

### Auto-discover URLs by keyword (no CSV needed)
```bash
python analyzer.py --discover "personal finance blog" --discover-count 50
```

### Discover + validate emails + export to Google Sheets
```bash
python analyzer.py \
  --input sites.csv \
  --validate-emails \
  --sheets --sheets-name "My Research"
```

### Run through Apify proxy (bypass Cloudflare)
```bash
python analyzer.py --input sites.csv --proxy
```

### Full-featured run
```bash
python analyzer.py \
  --input sites.csv \
  --discover "SEO tools" --discover-count 30 \
  --validate-emails \
  --sheets --sheets-name "SEO Tools Analysis" \
  --proxy \
  --model claude-sonnet-4-6 \
  --workers 30
```

---

## All CLI Options

```
Input / Output:
  --input  CSV_FILE        Input CSV with a 'url' column
  --output CSV_FILE        Output path (default: results/results_TIMESTAMP.csv)

AI Settings:
  --model  MODEL_ID        Claude model (default: claude-haiku-4-5-20251001)
  --batch-size N           Sites per API call (default: 10)

Performance:
  --workers N              Concurrent fetch workers (default: 20)

Phase 2 Features:
  --validate-emails        DNS MX validation on all extracted emails
  --sheets                 Push results to Google Sheets
  --sheets-name NAME       Spreadsheet name (default: 'Bulk Website Analysis')
  --discover QUERY         Keyword query for URL auto-discovery
  --discover-provider      duckduckgo | serpapi | google_cse | commoncrawl
  --discover-count N       URLs to discover (default: 50)

Phase 3 Features:
  --proxy                  Route requests through Apify residential proxy
  --proxy-group GROUP      RESIDENTIAL (default) or SHADER (cheaper datacenter)

Utility:
  --dry-run                Validate input without fetching
  --verbose                Debug-level logging
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```env
# Required
ANTHROPIC_API_KEY=your_key_here

# Model selection (haiku = cheap & fast, sonnet = most accurate)
CLAUDE_MODEL=claude-haiku-4-5-20251001

# Performance tuning
MAX_WORKERS=20
REQUEST_TIMEOUT=15
PER_DOMAIN_DELAY=2.0
CLAUDE_BATCH_SIZE=10
BODY_TEXT_LIMIT=3000

# Phase 2: Google Sheets export (optional)
GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service_account.json
SHARE_SHEET_WITH=you@gmail.com   # auto-shares new sheets to your Drive

# Phase 2: URL discovery (optional — DuckDuckGo is free, no key needed)
SERPAPI_KEY=
GOOGLE_CSE_KEY=
GOOGLE_CSE_ID=

# Phase 3: Apify proxy (optional — for Cloudflare-protected sites)
USE_PROXY=false
APIFY_API_TOKEN=
APIFY_PROXY_GROUP=RESIDENTIAL
```

### Google Sheets Setup (one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project
2. Enable **Google Sheets API** and **Google Drive API**
3. Go to **IAM & Admin → Service Accounts → Create Service Account**
4. Under **Keys → Add Key → JSON**, download the key file
5. Set `GOOGLE_SERVICE_ACCOUNT_FILE` in `.env` to point to that file
6. Set `SHARE_SHEET_WITH` to your personal Gmail
7. Create a blank Google Sheet, share it (Editor) with the service account email
8. Run with `--sheets --sheets-name "Your Sheet Name"`

### Apify Proxy Setup (Cloudflare bypass)

Some sites block scrapers with Cloudflare. Apify routes your requests through real residential IPs to get around this.

1. Sign up at [apify.com](https://apify.com)
2. Go to **Settings → Integrations** and copy your API token
3. Add to your `.env`:
   ```env
   USE_PROXY=true
   APIFY_API_TOKEN=your_token_here
   APIFY_PROXY_GROUP=RESIDENTIAL
   ```
4. Run with `--proxy`:
   ```bash
   python analyzer.py --input sites.csv --proxy
   ```

Use `--proxy-group SHADER` for cheaper datacenter proxies — works for most sites that aren't behind Cloudflare.

### Docker Cheat Sheet

```bash
# Build the image (first time, or after code changes)
docker build -t bulk-analyzer .

# Run via Docker Compose (simplest — env and volumes pre-configured)
docker compose run analyzer --input sample_data/sites.csv

# Run via docker run (manual — same result, more explicit)
docker run --env-file .env -v $(pwd)/results:/app/results bulk-analyzer --input sample_data/sites.csv

# Useful Docker commands
docker ps                  # see running containers
docker images              # see built images
docker system prune        # clean up old containers/images to free disk space
```

Results always land in your local `results/` folder — Docker writes inside the container but the volume mount pipes it straight to your Mac.

---

## Cost Estimate

Using Claude Haiku (default):

| Sites | API Calls | Approx. Cost |
|---|---|---|
| 100 | 10 | ~$0.03 |
| 500 | 50 | ~$0.15 |
| 1,000 | 100 | ~$0.30 |

Switch to `--model claude-sonnet-4-6` for higher accuracy (~10× cost).

---

## How It Works

```
URLs (CSV or --discover keyword search)
        ↓
  Async HTTP Fetcher (httpx, 20 concurrent workers)
        ↓  ← routes through Apify residential proxy if --proxy enabled
        ↓  ← auto-falls back on 403 / JS-heavy pages
  Playwright Headless Chromium
        ↓
  HTML Extraction
  ├── Title, meta description, body text
  ├── Email addresses (regex + contact page crawl)
  ├── Author name (JSON-LD, Open Graph, bylines)
  └── CMS fingerprint (WordPress, Shopify, Ghost…)
        ↓
  Claude AI — batched 10 sites per API call
  ├── Niche / topic classification
  ├── Site type (Blog / News / Business / E-commerce…)
  ├── Language detection
  └── Confidence scores (0–100)
        ↓
  Email DNS Validation (dnspython MX lookup)
        ↓
  CSV output  +  Google Sheets export (auto-resize, frozen header)
```

Full architecture diagram: [`website_analyzer_architecture.mermaid`](website_analyzer_architecture.mermaid)

---

## Project Structure

```
BulkWebsiteAnalyzer/
├── analyzer.py                       # CLI entry point
├── orchestrator.py                   # Async pipeline engine
├── models.py                         # Pydantic data schemas
├── config.py                         # Settings & .env loader
│
├── input/
│   ├── csv_loader.py                 # CSV parsing & URL validation
│   └── discovery.py                  # DuckDuckGo / SerpAPI / Common Crawl
│
├── fetcher/
│   ├── http_fetcher.py               # Async httpx with retry & rate limiting
│   ├── playwright_fetcher.py         # Headless Chromium fallback
│   └── proxy.py                      # Apify residential proxy integration
│
├── extractor/
│   ├── html_parser.py                # Title, body text, CMS detection
│   ├── email_extractor.py            # Email scraping
│   └── author_parser.py             # Author name extraction
│
├── ai/
│   ├── prompt_builder.py             # Claude prompt construction
│   └── claude_client.py             # Batched API calls with retry
│
├── validation/
│   └── email_validator.py            # Regex + DNS MX + optional SMTP
│
├── output/
│   ├── csv_writer.py                 # Timestamped CSV export
│   └── sheets_writer.py             # Google Sheets push with formatting
│
├── sample_data/
│   ├── sites.csv                     # 10 URLs — basic test
│   └── sites_with_contacts.csv       # 20 URLs — authors & emails demo
│
├── Screenshots/
│   └── google_sheets.jpg             # Demo output screenshot
│
├── Dockerfile                        # One-command Docker deployment
├── docker-compose.yml                # Docker Compose config
├── .dockerignore                     # Keep Docker image lean
├── requirements.txt
├── .env.example
└── website_analyzer_architecture.mermaid
```

---

## Input CSV Format

Minimum — just a `url` column:

```csv
url
https://www.example.com
https://www.another-site.com
```

The loader also accepts columns named `URL`, `website`, `domain`, or `link`. Extra columns are passed through to the output unchanged.

---

## Roadmap

- [x] **Phase 1** — CSV input, async HTTP fetching, Claude AI classification, CSV output
- [x] **Phase 2** — Playwright anti-bot fallback, email DNS validation, Google Sheets export with formatting, DuckDuckGo URL discovery
- [x] **Phase 3** — Docker container for one-command deployment, Apify residential proxy integration for Cloudflare-protected sites
- [ ] **Phase 4** — Scheduled runs, database persistence, webhook / Zapier notifications

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
