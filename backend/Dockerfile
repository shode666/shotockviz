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

# bd:shotockviz-18r — make /app importable for EVERY entrypoint, not just the
# ones launched as `python -m ...`.
#
# `celery -A workers.celery_app worker` is a console script, so `sys.path[0]`
# is `/usr/local/bin`, not the CWD. Celery puts the CWD on `sys.path` long
# enough to load the app module and then takes it back off, so the forked
# pool workers inherit `workers.*` already in `sys.modules` but cannot import
# anything new: every LAZY `from models... import` inside a task body raises
# `ModuleNotFoundError: No module named 'models'`. Reproduced on the droplet
# 2026-09-06 — `sr_proximity_digest` had never once delivered in production
# because of this, and every other task that lazy-imports `models` (that is
# most of them, including `alert_checker`) was one code path away from the
# same failure.
#
# `docker-compose.dev.yml` sets `PYTHONPATH: /app` on the celery services,
# which is exactly why this was invisible in dev. Setting it in the image
# removes the dev/prod divergence rather than adding a third place to keep
# in sync.
ENV PYTHONPATH=/app

USER stockviz

EXPOSE 8000

# bd:deps-2026-09 iter2 (CHRIS-16/Q-10) — default CMD for standalone
# `docker run`/no-compose-override use. NOTE: all 3 compose files in this
# repo (`docker-compose.dev.yml`, `docker-compose.prod.yml`,
# `docker-compose.ghcr.yml`) set their own backend `command:`, which
# replaces this CMD entirely (Docker semantics — compose `command:` always
# wins over image CMD) — so this line is NOT what actually closes
# CHRIS-16/Q-10 for those 3 topologies; `gunicorn.conf.py`'s CWD-relative
# auto-load (see that file's docstring) is what does. This CMD is kept
# correct/explicit anyway so a bare `docker run stockviz-backend` (no
# compose) gets the same safe-by-default proxy-header trust.
CMD ["gunicorn", "main:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "-c", "gunicorn.conf.py"]
