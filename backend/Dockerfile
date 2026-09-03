FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# bd:deps-2026-09 WP-B1 — prod image installs ONLY requirements.txt (no
# pytest/pytest-asyncio/aiosqlite/pip-audit/ruff/mypy — those live in
# requirements-dev.txt so they never ship in this container). For local
# dev/CI: `uv pip install -r backend/requirements-dev.txt` (installs this
# file too via its `-r requirements.txt` line).
RUN uv pip install --system --no-cache -r requirements.txt

# --- Runtime ---
FROM python:3.13-slim

# Non-root user for security
RUN groupadd -r stockviz && useradd -r -g stockviz stockviz

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --chown=stockviz:stockviz . .

USER stockviz

EXPOSE 8000
