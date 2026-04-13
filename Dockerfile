# ─────────────────────────────────────────────────────────────────
#  Bulk Website Analyzer — Docker Image
#  One-command deployment with all dependencies pre-installed.
#
#  Build:   docker build -t bulk-analyzer .
#  Run:     docker run --env-file .env bulk-analyzer --input sample_data/sites.csv
#  Compose: docker compose run analyzer --input sample_data/sites.csv
# ─────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# Playwright system dependencies (Chromium needs these)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser
RUN python -m playwright install chromium

# Copy application code
COPY . .

# Create results directory
RUN mkdir -p results

# Default entrypoint — pass CLI args via docker run
ENTRYPOINT ["python", "analyzer.py"]

# Default command shows help if no args given
CMD ["--help"]
