# ShotockViz Test Suite
# =====================
# Tests live here, NOT inside frontend/ or backend/, so they are excluded from Docker images.
#
# Prerequisites:
#   Docker stack running: docker compose -f ../docker-compose.dev.yml up -d
#
# Usage:
#   make e2e           — run all Playwright e2e tests (headless)
#   make e2e-ui        — run Playwright in interactive UI mode
#   make e2e-headed    — run Playwright with visible browser
#   make api           — run all backend API tests (pytest)
#   make all           — run both e2e and api tests
#   make install       — install all test dependencies
#   make install-e2e   — install Playwright + browsers
#   make install-api   — install Python test deps

.PHONY: all e2e e2e-ui e2e-headed api install install-e2e install-api

# ── Install ──────────────────────────────────────────────────────────────────

install: install-e2e install-api

install-e2e:
	cd e2e && npm install && npx playwright install chromium

install-api:
	pip install -r api/requirements.txt

# ── E2E ─────────────────────────────────────────────────────────────────────

e2e:
	cd e2e && npx playwright test

e2e-ui:
	cd e2e && npx playwright test --ui

e2e-headed:
	cd e2e && npx playwright test --headed

e2e-chart:
	cd e2e && npx playwright test chart-timeframes.spec.ts

e2e-watchlist:
	cd e2e && npx playwright test watchlist-autocomplete.spec.ts

e2e-quote:
	cd e2e && npx playwright test quote-fetch.spec.ts

e2e-ai:
	cd e2e && npx playwright test ai-chat.spec.ts

e2e-search:
	cd e2e && npx playwright test search.spec.ts

e2e-auth:
	cd e2e && npx playwright test auth.spec.ts

# ── API (pytest) ──────────────────────────────────────────────────────────────

api:
	cd api && pytest -v

api-auth:
	cd api && pytest -v -k "TestAuth or TestRegister or TestLogin"

api-stocks:
	cd api && pytest -v -k "TestStock"

api-watchlist:
	cd api && pytest -v -k "TestWatchlist"

api-ai:
	cd api && pytest -v -k "TestAI"

api-security:
	cd api && pytest -v -k "TestInput or TestConcurrent"

# ── All ───────────────────────────────────────────────────────────────────────

all: api e2e
