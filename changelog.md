# ShotockViz — Changelog

All notable changes to this project will be documented here.
Format: [version] · date · description
Rule: **Update this file after every completed task.**

---

## [Unreleased]

### bd:deps-2026-09 iter1 — Phase 3b FAIL fix pack (2026-09-03)

Chris (code review) and Quinn (integration/E2E/contract review) both
returned Phase 3b FAIL on the `/api/v1` + `{data,meta}` envelope
migration branch (`chore/deps-2026-09`). Full evidence/proof per finding:
`outputs/deps-2026-09/16-dave-iter1-fixes.md`. Reviews (never edited):
`outputs/deps-2026-09/14-chris-review.md`, `15-quinn-review.md`.

- **CHRIS-05** — `hash_password()` unconditionally broken (passlib 1.7.4 x
  bcrypt 5.0.0); replaced with direct `bcrypt.hashpw()`, dropped passlib.
- **CHRIS-01/Q-1/Q-3/Q-4/Q-5** — `tests/api/conftest.py` pytest-asyncio
  1.x rewrite (StaticPool, shared engine, `APP_ENV=test`), fixed the 17
  new test failures the S2 envelope flip owed (11 envelope-unwrap + 6
  auth-fixture). 3x-reproducible: 28 failed/208 passed, 0 errors.
- **CHRIS-02/Q-2** — rate-limiter's 429 was an unhandled non-JSON 500
  (`HTTPException` raised inside `BaseHTTPMiddleware.dispatch()`); now
  returns the real `{data,meta}` envelope.
- **CHRIS-03** — added `TRUSTED_PROXIES` allowlist so `X-Forwarded-For`
  is only honored from a configured trusted hop (default empty = safest,
  falls back to the raw socket peer) — closes an XFF-spoofing rate-limit
  bypass.
- **CHRIS-06** — `/openapi.json` now documents the real `{data,meta}`
  envelope + error shape (`app.openapi()` override) instead of each
  handler's raw `response_model` / FastAPI's stock validation-error shape.
  Regenerated `outputs/deps-2026-09/openapi-v1.json`.
- **CHRIS-07** — `.github/workflows/ci.yml` steps reconciled
  (`requirements-dev.txt`, Node 24, `.output/` artifact path, `APP_ENV`
  env var); trigger stays `workflow_dispatch`-only (unchanged, prior
  explicit decision).

### bd:deps-2026-09 iter2 — CHRIS-16/Q-10 fix (2026-09-03)

Chris's and Quinn's iter1 re-verify both surfaced the same new High
finding via live-`uvicorn`/`gunicorn` curl (not `TestClient`, which
structurally cannot see this class of bug): uvicorn/gunicorn's OWN
proxy-header trust (`forwarded_allow_ips` defaults to `'127.0.0.1'`)
rewrites `request.client.host` from a spoofed `X-Forwarded-For` BEFORE
the CHRIS-03/iter1 app-level `TRUSTED_PROXIES` allowlist ever runs, when
the connecting peer is loopback. Full evidence:
`outputs/deps-2026-09/16-dave-iter1-fixes.md` § iter 2.

- **NEW `backend/gunicorn.conf.py`** — derives `forwarded_allow_ips` from
  the same `TRUSTED_PROXIES` env var `core/config.py` reads. Auto-loaded
  by `gunicorn` (own-run confirmed: `gunicorn --help` defaults `-c` to
  `./gunicorn.conf.py`) — closes the gap for `docker-compose.prod.yml`/
  `docker-compose.ghcr.yml`'s existing `command:` lines with **zero
  compose edit**, live-curl-verified (6 spoofed XFF from loopback -> 1
  bucket, 429 on the 6th).
- **`backend/Dockerfile`** — added `CMD` wiring `-c gunicorn.conf.py`
  explicitly (for standalone `docker run`; the 3 compose files' own
  `command:` still wins over it, unaffected).
- **`api/middleware/rate_limit.py`** — `_client_ip()` now parses
  multi-hop `X-Forwarded-For` chains via rightmost-untrusted-hop (was
  leftmost-claimed), matching uvicorn's own `_TrustedHosts` algorithm;
  defense-in-depth for paths (e.g. `TestClient`) that never go through
  the real ASGI proxy-header middleware at all.
- **`.env.example` / `docs/deploy-gha.md`** — documented the two-layer
  (ASGI server + app) proxy-trust model and the still-open R1 gap:
  `docker-compose.dev.yml`'s plain `uvicorn` command has no equivalent
  auto-wiring in this repo yet (needs a 1-line compose edit, not applied
  — compose files are read-only on this branch).
- **NEW `backend/tests/test_rate_limit_proxy_boundary_live.py`** —
  subprocess-`uvicorn` integration tests (marked `integration`,
  deselected by default, run explicitly): reproduces the original bug as
  a negative control, then proves both directions of the fix (spoofed XFF
  collapses to one bucket when unset; distinct real users behind a
  correctly-configured trusted proxy do NOT collapse into one).

### Fix: Dashboard Top Holdings cross-currency sorting (2026-03-11)

- `api/routes/dashboard.py` — Top Holdings now sorts by THB-normalized value using USD/THB exchange rate from cache. Previously compared raw THB and USD values directly, causing Thai funds (~฿5,000) to rank above US stocks (~$4,000 = ฿130,000). Also fixes total portfolio value to show correct THB-normalized sum. Added float precision guard and currency field tracking per holding.

### Security Audit & Bug Fixes (2026-03-11)

**Critical:**
- `core/config.py` — Added `@field_validator` for `jwt_secret_key`: warns on default dev value, rejects keys < 16 chars
- `api/routes/portfolio.py` — Transaction update uses explicit field whitelist instead of blind `setattr()` (prevents privilege escalation)
- `api/routes/ai_chat.py` — SSE stream errors now return generic message instead of raw exception details (info disclosure fix)

**High:**
- `api/routes/portfolio.py` — Added float precision guard: zeroes qty/cost when residual < 1e-6 after SELL (prevents divide-by-zero)
- `api/middleware/auth.py` — Wrapped `int(user_id)` in try/except to return 401 instead of crashing on malformed JWT `sub`
- `workers/fund_fetcher.py` — Added symbol validation regex + URL encoding to prevent SSRF via crafted fund symbols
- `workers/on_demand_listener.py` — Added symbol regex validation at task entry to reject garbage/malicious inputs

**Medium:**
- `frontend/src/services/aiService.js` — Token now read from `useAuthStore.getState()` instead of direct `localStorage` access (prevents stale token usage)

### Sidebar: VIX + Fear & Greed Index (2026-03-10)

- `frontend/src/components/common/Sidebar.tsx` — Added VIX (`^VIX`) to market indices, added CNN Fear & Greed Index with color-coded score and label
- NEW `backend/workers/fgi_fetcher.py` — Celery worker fetches CNN FGI every 30 min, caches in Redis
- `backend/api/routes/system.py` — Added `GET /api/market/fgi` endpoint (pure-read from cache)
- `backend/workers/celery_app.py` — Registered `fgi_fetcher` worker + beat schedule

### Bug Fixes (2026-03-10)

- `api/routes/portfolio.py` — Removed fee from cost basis calculation; user-entered price already includes fee deduction
- `api/routes/dashboard.py` — Same fee removal fix for dashboard portfolio summary
- `frontend/src/components/portfolio/HoldingsTable.tsx` — Fixed currency symbol positioning: `-$4.23` instead of `$-4.23`
- `frontend/src/components/pages/PortfolioPage.tsx` — Fixed currency symbol positioning on P&L stat card
- `frontend/src/components/pages/DashboardPage.tsx` — Fixed currency symbol positioning on dashboard P&L

### V2 Phase 2.4-2.5 Implementation (2026-03-04)

**Phase 2.4 — AI/Observability (6 new files, 1 migration, 3 new API endpoints):**
- NEW `db/Dockerfile.dev` — Custom PostgreSQL image combining TimescaleDB + pgvector v0.8.0
- NEW `models/document_embedding.py` — `DocumentEmbedding` model: vector(768) embeddings for RAG search
- NEW `services/embedding_service.py` — Generate embeddings via Ollama (nomic-embed-text), cosine similarity search against pgvector
- NEW `workers/embedding_worker.py` — Celery worker: embeds news articles, earnings events, financial summaries (every 6h)
- `api/routes/ai_chat.py` — RAG context injection: `_fetch_rag_context()` searches top-3 similar docs before LLM streaming
- `docker-compose.dev.yml` — DB service changed from `image:` to `build:` (custom Dockerfile), Ollama pulls nomic-embed-text model
- Migration `20260304_0005` — Creates `document_embeddings` table with HNSW vector index
- NEW `api/routes/admin.py` — Data retention policy management:
  - `GET /api/admin/retention-policy` — Read policy + disk usage stats
  - `PUT /api/admin/retention-policy` — Update retention rules (stored in Redis)
  - `POST /api/admin/retention-policy/run-now` — Trigger housekeeping immediately
- `workers/housekeeping.py` — Rewritten to read retention policy from Redis config (no longer hardcoded)

**Phase 2.5 — Professional Tools (4 new files, 2 new API endpoints):**
- NEW `frontend/src/components/chart/VolumeProfile.tsx` — VPVR overlay: canvas-based horizontal volume bars with POC (gold) + Value Area (70%)
- NEW `frontend/src/components/chart/MultiChartLayout.tsx` — Split-view: 1x1/2x1/1x2/2x2 grid with independent chart instances
- NEW `services/backtesting_engine.py` — Strategy backtest engine: Golden Cross, RSI Reversal, MACD Crossover, BB Bounce. Computes win rate, Sharpe, max drawdown, profit factor.
- NEW `api/routes/backtesting.py` — Backtest API:
  - `GET /api/backtest/strategies` — List available strategies with default params
  - `POST /api/backtest/run` — Run simulation with custom params + period

**Registrations:**
- `celery_app.py` — embedding_worker registered + beat schedule (every 6h at :45)
- `models/__init__.py` — DocumentEmbedding exported
- `db/migrations/env.py` — document_embedding model imported
- `main.py` — admin + backtesting routers registered

### V2 Phase 2.1-2.3 Backend Implementation (2026-03-04)

**Phase 2.1 — Infrastructure:**
- `docker-compose.dev.yml` — Flower service updated with `--url_prefix=flower` for Caddy reverse proxy + `celery-worker` dependency
- `services/cache_orchestrator.py` — Hybrid fetching: `request_data_fetch()` now tries Celery first, falls back to asyncio direct fetch if broker unreachable. Fallback caches to Redis only (no DB persist) until Celery recovers.

**Phase 2.2 — Data Engine (4 new files, 1 migration):**
- NEW `models/symbol_mapping.py` — `SymbolMapping` model: maps internal symbols to Yahoo/Finnhub/pythainav formats
- NEW `models/corporate_action.py` — `CorporateAction` model: dividend/split/rights events with ex-dates
- NEW `services/symbol_mapper.py` — Centralized symbol translation (async + sync APIs, Redis-cached, DB-backed)
- NEW `services/price_adjuster.py` — Backward-adjusted OHLCV prices using corporate actions (never modifies raw DB data)
- NEW `workers/corporate_actions_fetcher.py` — Celery worker fetches dividends + splits from yfinance (daily 02:00 ICT)
- `api/routes/stocks.py` — History endpoint: added `?adjusted=true` query param for adjusted prices (default=false, backward compatible)
- Migration `20260304_0003` — Creates `symbol_mappings` + `corporate_actions` tables

**Phase 2.3 — Institutional Features (4 new files, 1 migration, 3 new API endpoints):**
- NEW `models/financial_history.py` — `FinancialHistory` model: 10-year annual financial metrics (revenue, profit, ROE, D/E, EPS, dividends, margins)
- NEW `models/earnings_event.py` — `EarningsEvent` model: EPS actual vs estimate with surprise % and price impact
- NEW `workers/financials_history_fetcher.py` — Celery worker fetches 10-year financial data from yfinance (daily 01:00 ICT)
- NEW `workers/earnings_events_fetcher.py` — Celery worker fetches earnings history with price impact (daily 06:00 ICT)
- `api/routes/stocks.py` — 3 new endpoints:
  - `GET /{symbol}/rs?benchmark=^SET.BK` — Relative Strength line data
  - `GET /{symbol}/financials?years=10` — Financial health scorecard
  - `GET /{symbol}/earnings?limit=8` — Earnings surprise tracker
- Migration `20260304_0004` — Creates `financial_history` + `earnings_events` tables

**Registrations:**
- `celery_app.py` — 3 new workers registered + 3 new beat schedules (corporate actions 19:00 UTC, financials 18:00 UTC, earnings 23:00 UTC)
- `models/__init__.py` — Exports: SymbolMapping, CorporateAction, FinancialHistory, EarningsEvent
- `db/migrations/env.py` — All 4 new model modules imported for Alembic autogenerate

### Refactor & Test Hardening (2026-03-04 — Pre-V2 Readiness)

**Bug Fixes:**
- `backend/api/routes/system.py` — Removed `.decode()` calls on Redis values (Redis uses `decode_responses=True`, returns strings not bytes). `/api/system/celery-stats` was crashing with `AttributeError: 'str' object has no attribute 'decode'`.
- `frontend/src/components/dashboard/AlertsNearTarget.tsx` — Fixed `key={i}` → `key={symbol-condition}` for stable React list rendering.

**New Test Coverage (101 new tests, all passing):**
- `tests/test_symbol_utils.py` — 39 tests: normalize_for_yahoo, denormalize, detect_market (16 markets), is_thai_stock, is_fund, partition_by_market, deduplicate
- `tests/test_cache_keys.py` — 13 tests: all 10 key builders, lock wrapping, key format consistency, no collisions
- `tests/test_screener_indicators.py` — 35 tests: RSI (6 edge cases), MACD (7 edge cases inc. IndexError regression), SMA, signals, all 4 filter matchers
- `tests/test_services.py` — 14 tests: stock_service facade (read_quote, read_fundamentals, search_stocks with cache hit/miss/error), cache key usage verification, TF_CONFIG completeness, facade re-exports

**Verification Completed:**
- All 10 API endpoints smoke tested via host gateway (health, ready, celery-stats, search, quote, batch quotes, history, fundamentals, screener, dashboard)
- Celery patterns verified: no `.apply().get()` inside tasks (only in comments as warnings)
- MarketType enum verified: 16 markets (SET, US, FUND, JP, CN, HK, UK, DE, FR, NL, KR, AU, CA, TW, SG, IT)
- Frontend static analysis: 0 memory leaks, 0 SSR issues, 0 circular imports, 0 stale request risks
- CQRS pattern confirmed: all API endpoints pure-read, Celery workers sole ingesters

### Added (2026-03-04 — V2 System Analysis & Handoff Documents)

**V2_DEV_SPEC.md** — Technical specification สำหรับ developer:
- Gap analysis V1 vs V2 requirements (12 features, 4 phases)
- Database schema สำหรับ 6 new tables (symbol_mappings, corporate_actions, financial_history, earnings_events, document_embeddings)
- New API endpoints (8 endpoints), New Celery workers (4 workers)
- Docker service changes (Flower + pgvector), breaking changes + migration plan
- 8-week implementation roadmap

**V2_QA_PLAN.md** — QA test plan:
- 60+ test cases ครอบคลุมทุก feature ใน 4 phases
- Acceptance criteria per feature
- Regression checklist สำหรับ V1 features
- Performance benchmarks (API, Frontend, Celery)
- Known risk areas + bug report template

### Fixed (2026-03-03 — Intraday timeframe full fix: end-to-end data flow)

**backend/api/routes/stocks.py — `timeframe` query param name mismatch:**
- ROOT CAUSE: history endpoint declared `tf: str = Query("1D")` but frontend sent `?timeframe=1h`. Backend always defaulted to `1D` regardless of the requested timeframe.
- FIX: Renamed parameter to `timeframe: str = Query("1D")` to match frontend convention.

**frontend/src/services/stockService.js — frontend sent wrong param key:**
- ROOT CAUSE: `getHistory()` used `{ params: { tf } }` → URL `?tf=1h`. Backend param was renamed so frontend needed to match.
- FIX: Changed to `{ params: { timeframe: tf } }` → URL `?timeframe=1h`.

**backend/models/ohlcv.py — `to_api_dict()` returned string timestamps for intraday (DB fallback):**
- ROOT CAUSE: `to_api_dict()` always returned `self.time_str` (string). For intraday bars stored in PostgreSQL, `time_str` is a numeric string like `"1759761000"`. TradingView v5 requires integer `UTCTimestamp` for intraday series.
- FIX: `is_intraday = self.time_str.isdigit()` — returns `self.time_unix` (int) for intraday rows, `self.time_str` (date string) for daily/weekly/monthly rows.

**backend/workers/on_demand_listener.py — 4h fetch used `period="120d"` (yfinance 1h limit exceeded):**
- ROOT CAUSE: 4h fetch config used `interval="1h", period="120d"`. yfinance silently returns empty data beyond 60d for 1h interval → `_fetch_history` returned False without error.
- FIX: Changed to `period="60d"` (confirmed working limit; yields ~250 aggregated 4h candles).

**backend/workers/price_fetcher.py — legacy alias tasks called `.apply().get()` inside Celery task:**
- ROOT CAUSE: `fetch_set_prices` and `fetch_us_prices` used `fetch_prices.apply().get(timeout=120)` which is forbidden inside a Celery task (raises `RuntimeError: Never call result.get() within a task!`).
- FIX: Changed to `fetch_prices.delay()` — fire-and-forget, no blocking.

**docker-compose.dev.yml — services not accessible from host for debugging:**
- FIX: Added `ports:` mappings to expose Redis (6379), PostgreSQL (5432), backend (8000), and Flower (5555) to the host machine for direct curl/redis-cli/psql debugging.

### Fixed (2026-03-03 — TradingChart time-type crash on timeframe switch)

**TradingChart.tsx — chart recreated when crossing intraday↔daily boundary:**
- ROOT CAUSE: chart creation `useEffect` had deps `[darkMode, chartType]` only. When user switched 1D→1h, the existing TradingView series was in "BusinessDay" (date string) mode from prior 1D data. Calling `setData([{ time: 1740000000 }])` threw a v5 error: cannot mix `UTCTimestamp` (integer) and `BusinessDay` (string) in the same series.
- FIX: Added `isIntradayMode = ['1m','5m','15m','1h','4h'].includes(timeframe)` boolean to the chart creation deps. Crossing the daily↔intraday boundary now triggers a full chart recreation with fresh series accepting the correct time type.
- Switching within same mode (1h↔4h, 1D↔1W) does NOT recreate — no unnecessary flicker.

### Fixed (2026-03-03 — Intraday timeframe display + WebSocket precision)

**useChartData.ts — normalizeBarTime: intraday bars no longer converted to date strings:**
- ROOT CAUSE: `normalizeBarTime()` converted ALL unix timestamps to `"yyyy-mm-dd"` strings, including 1m/5m/15m/1h/4h bars. Multiple same-day bars collapsed to the same string key → TradingView `data must be asc ordered by time` crash
- NEW: Daily/Weekly/Monthly timeframes → `"yyyy-mm-dd"` string (TradingView day series requirement)
- NEW: Intraday timeframes (1m/5m/15m/1h/4h) → integer unix timestamp (TradingView time series requirement)
- `sortBarsAsc()` now takes `isDaily` flag and uses numeric sort for intraday, string sort for daily

**useWebSocket.ts + appStore.js — precise data_ready handling:**
- ROOT CAUSE: `data_ready` handler called `bumpDataVersion()` unconditionally → any symbol's data_ready cancelled the active retry chain on the currently viewed chart
- NEW: Stores full `data_ready` payload as `dataReadyPayload` in Zustand (with `_key` timestamp for change detection) instead of incrementing a global counter
- `useChartData` subscribes to `dataReadyPayload` and only re-fetches when the payload matches the current symbol AND timeframe (history data_type only)
- Unrelated symbols or timeframes are filtered at the hook level → in-progress retries never cancelled by foreign notifications

**appStore.js:**
- Added `dataReadyPayload: null` state
- Added `setDataReadyPayload(payload)` action (creates new object reference each time for Zustand reactivity)

### Added (2026-03-03 — News Celery Worker + CQRS)

**workers/news_fetcher.py — NEW Celery worker for news:**
- `prefetch_news` task runs every 30 min via Celery Beat
- Fetches Google News RSS (Thai + English) for all watched symbols
- Deduplicates cleaned symbols (PTT.BK and PTT share same news cache)
- Skips symbols with fresh cache (avoids redundant fetches)
- Rate-limit friendly: 0.5s delay between symbols, max 30 per run
- `fetch_news_on_demand` task for symbols not in watchlists (triggered by API cache miss)
- Cache key: `news:{CLEAN_SYMBOL}`, TTL 30 minutes

**stocks.py — News endpoint now pure-read (CQRS):**
- Removed all feedparser/RSS logic from API endpoint
- API reads Redis cache only → returns cached or empty []
- On cache miss: triggers `fetch_news_on_demand` Celery task (non-blocking)
- News is NOT user-specific — all users share same cache per symbol

### Fixed (2026-03-03 — Intraday Timeframes + 4h Chart + News)

**on_demand_listener.py — intraday timeframes now work (1m/5m/15m/1h/4h):**
- ROOT CAUSE: `_fetch_history()` was hardcoded to fetch only `1D` bars regardless of requested timeframe
- `request_data_fetch()` now accepts optional `timeframe` parameter
- `process_fetch_request()` Celery task forwards timeframe to `_fetch_history()`
- `_fetch_history()` uses `TF_CONFIG` mapping to determine correct yfinance interval+period per timeframe
- Added `_aggregate_4h_sync()` for 4h aggregation inside Celery worker (sync context)
- DB upsert uses `ON CONFLICT DO UPDATE` instead of SELECT+INSERT (more efficient)
- Cache TTL is now timeframe-aware (1m=60s, 5m=300s, 1h=3600s, 1D=6h)

**db_helpers.py — 4h chart duplicate timestamp crash fixed:**
- OLD: chunked every 4 consecutive 1h bars → duplicate timestamps when data has gaps
- NEW: groups 1h bars by UTC 4-hour boundary (0:00/4:00/8:00/12:00/16:00/20:00)
- Deduplicates input bars by timestamp before grouping → guaranteed unique output timestamps
- Fixes TradingView error: "data must be asc ordered by time"

**stocks.py — News endpoint improved:**
- Added Redis caching (10 min TTL) for news results → no repeated RSS fetches
- Safer feedparser `source` field access (handles non-dict source gracefully)
- URL-encodes search query properly (`quote_plus`)
- Strips international market suffixes (.T, .HK, .SS, .SZ, .L, .DE, .PA, .AS, .KS)
- Increased RSS timeout from 4s to 6s
- Added error logging instead of silent `continue`

### Documentation (2026-03-03 — Full Docs Update)

- **REQUIREMENTS.md** — Major rewrite: 2→10 markets, email+password→Google OAuth, Nginx→Caddy, added CQRS architecture, round-robin price fetcher, 10 Celery workers, updated schema/API/milestones
- **INSTRUCTIONS.md** — Updated: Google OAuth setup, international market seeding, updated project structure, Celery worker commands, removed JWT env vars
- **PRODUCTION_DEPLOY.md** — Fixed: removed obsolete JWT config, added international market seeding step
- **DEVOPS_MONITORING.md** — Updated: round-robin price fetcher references, corrected log examples
- **README.md** — Complete rewrite (done earlier this session)

### Refactored (2026-03-03 — Round-Robin Price Fetcher)

**price_fetcher.py — unified round-robin across all markets:**
- Replaced 2 separate tasks (`fetch_set_prices` + `fetch_us_prices`) with 1 unified `fetch_prices` task
- 5 market slots rotate every 1 minute: SET → US → Asia (JP/HK/CN/KR) → Europe (UK/DE/FR/NL) → Overview
- Each market updates every ~5 min; closed markets auto-skip → open markets get more frequent updates
- Redis atomic counter (`price_fetcher:slot_idx`) tracks rotation across restarts
- Market-hours awareness: SET 09:30-16:30 ICT, US 09:30-16:00 ET, Asia 09:00-17:00 JST/HKT, EU 08:00-17:00 CET
- Fallback: if all markets closed (weekend) → still fetches overview (indices/FX/gold)
- Legacy aliases `fetch_set_prices` / `fetch_us_prices` kept for backward compat

**celery_app.py — simplified beat schedule:**
- Removed `fetch-set-prices` and `fetch-us-prices` crontab entries
- Added `fetch-prices` running every 60s (round-robin)
- `fetch-overview-prices` reduced to every 5 min (backup for indices)

**Scripts added:**
- `scripts/fetch_real_constituents.py` — fetch real index constituents from Wikipedia (Nikkei/HSI/FTSE/DAX/SSE/CAC/AEX)
- `scripts/seed_international.py` — direct DB seed for international symbols (no Celery dependency)
- `scripts/check_intl_symbols.py` — diagnostic query for international market data

### Enhanced (2026-03-03 — Symbol Autocomplete + Currency Display)

**AlertsPage.tsx — Symbol autocomplete with market/currency awareness:**
- Replaced plain text input with debounced search autocomplete (300ms, reuses `stockService.search`)
- Dropdown shows company name, market badge (SET/US/JP/etc.), and currency code
- Currency sign prefix on value input for price alerts (e.g., ฿ for SET, $ for US, ¥ for JP)
- Market badge + currency code on alert list items
- Direct ticker fallback when search returns no results

**AddTransactionModal.tsx — Same autocomplete pattern:**
- Replaced plain text input with search autocomplete dropdown
- Auto-detects currency from selected market (SET→THB, US/JP/HK/etc.→USD)
- Currency sign updates dynamically on price & fee inputs
- Market badge + currency code shown next to Symbol label
- Currency toggle still available for manual override

**formatters.js — New MARKET_CURRENCY mapping:**
- Added `MARKET_CURRENCY` export: maps market codes to `{ sign, code }` (e.g., SET→{฿,THB}, JP→{¥,JPY})
- Used by both AlertsPage and AddTransactionModal

### Refactored (2026-03-03 — Phase 6: Store & Hook Optimization)

**New custom hooks (SRP — extract data-fetching from components):**
- `hooks/usePriceUpdates.ts` (119 lines) — reusable price polling hook with configurable interval, auto-retry on partial data/network error, dataVersion reactivity. Replaces ~80 lines of inline logic in Sidebar.
- `hooks/usePortfolioData.ts` (90 lines) — portfolio analytics + transactions fetching with auto-retry for pending prices (6× every 5s), dataVersion reactivity. Replaces ~50 lines of inline logic in PortfolioPage.
- `hooks/useChartData.ts` (181 lines) — chart OHLCV data fetching with retry, normalization, timeout detection (created in Phase 4).

**Component simplification via hooks:**
- `Sidebar.tsx`: 402 → 326 lines — replaced inline price polling + indices fetching with 2× `usePriceUpdates()` calls
- `PortfolioPage.tsx`: 373 → 319 lines — replaced inline analytics/txns fetching + retry logic with `usePortfolioData()`

**Store named exports (tree-shaking):**
- `appStore.js`: added `export { useAppStore }` alongside default export
- `authStore.js`: added `export { useAuthStore }` alongside default export

### Refactored (2026-03-03 — Backend Route Refactoring: SOLID Principles + Guard Clauses)

**Dashboard.py (317 lines — was deeply nested):**
- Extracted `_fetch_indices_cached()` — pure helper for market index cards, returns (indices, misses)
- Extracted `_build_portfolio_summary()` — encapsulated portfolio aggregation + holdings calculation, returns (summary, misses)
- Extracted `_find_alerts_near_target()` — proximity-based alert detection, returns (count, triggered_alerts, misses)
- Extracted `_get_user_watchlist()` — watchlist fetching with guest default fallback
- Extracted `_get_top_movers()` — movers data aggregation sorted by change_pct
- Main `get_dashboard()` now an orchestrator calling 5 helpers (clean, readable, testable)
- All helpers follow SOLID: single responsibility, guard clauses, early returns, type hints
- File size reduction: nested blocks flattened, complexity moved to composable helpers

**Screener.py (345 lines — was monolithic _run_screener_db):**
- Extracted `_compute_sma()` — pure function for simple moving average (50/200 period)
- Extracted `_fetch_symbol_bars()` — database query with 30-bar minimum guard clause
- Extracted `_evaluate_symbol()` — pure function takes bars + filters, returns result or None (early exit on filter fail)
- All indicator helpers already existed (_compute_rsi, _compute_macd, _compute_signal)
- _run_screener_db now: iterate → fetch_bars (guard) → evaluate (pure, early return) → collect → sort
- Flattened try/except blocks using guard clauses (early continue on fetch/eval fail)

**AI Chat.py (408 lines — was deeply nested context builder):**
- Extracted `_fetch_quote_context()` — cache-first quote fetching, non-blocking fallback, returns formatted string or ""
- Extracted `_fetch_fundamentals_context()` — fundamentals retrieval + formatting, 3s timeout cap, returns "" on miss
- Extracted `_fetch_portfolio_context()` — user portfolio aggregation from transactions, returns "" if no holdings
- Extracted `_fetch_watchlist_context()` — watchlist retrieval, returns "" if empty
- Main `_build_context()` now: init base prompt → await 4 helpers → append non-empty results → join
- All helpers use guard clauses: `if not symbol: return ""` to skip processing on falsy input
- Context building is now linear, non-blocking (no nested try/except blocks)

**Refactoring Principles Applied:**
- Guard clauses: Early exit on falsy input, missing data, or filter failures
- Type hints: All helpers have full Callable signatures with Args and Returns docstrings
- Single responsibility: Each helper does ONE thing (fetch, compute, aggregate, or format)
- Pure functions: Indicator computation and evaluation have no side effects
- DRY: Eliminated code duplication across context building
- Error handling: Try/except flattened into guard clauses and helper boundaries
- Composability: Main endpoints now orchestrate simple, testable helpers

### Added (2026-03-03 — International Market Support + Symbol Display Cleanup)

**International market support (Japan, Hong Kong, UK, Germany, China, Korea, etc.):**
- **models/stock.py MarketType enum** — Added 13 new market types: JP, CN, HK, UK, DE, FR, NL, KR, AU, CA, TW, SG, IT
- **workers/index_populator.py** — Pre-populates DB with international index constituents:
  - Nikkei 225 (top 30 JP stocks), Hang Seng (top 26 HK stocks), FTSE 100 (top 24 UK stocks), DAX (top 20 DE stocks), SSE 50 (top 16 CN stocks)
  - Overview indices: ^N225, ^HSI, 000001.SS, ^FTSE, ^GDAXI, ^FCHI, ^KS11, ^TWII, ^STI, ^AEX, ^DJI
  - Auto-creates MarketType enum values in PostgreSQL via `ALTER TYPE ... ADD VALUE IF NOT EXISTS`
- **workers/price_fetcher.py FALLBACK_IDX** — Extended from 5 to 16 indices: added ^N225, ^HSI, 000001.SS, ^KS11, ^TWII, ^STI, ^FTSE, ^GDAXI, ^FCHI, ^AEX, ^DJI
- **services/stock_service.py `_search_yahoo_direct()`** — Auto-detects international market from Yahoo suffix (.T→JP, .HK→HK, .L→UK, .DE→DE, .SS→CN, etc.)
- **api/routes/screener.py** — Dynamic MarketType enum lookup instead of hardcoded SET/US only

**Symbol display cleanup — strip exchange suffixes, show market badge:**
- **utils/formatters.js** — New utilities: `parseSymbol(symbol)` strips suffix + detects market, `displaySymbol(symbol)` shorthand, `MARKET_COLORS` for badge colors
- **Sidebar.tsx** — Uses `parseSymbol()` for watchlist items + search results, shows colored market badge
- **ChartToolbar.tsx** — Shows clean symbol + market badge (e.g., "ADVANC" + green "SET" badge)
- **DashboardPage.tsx** — Updated Top Holdings, MoverRow, AlertNearTarget to use `displaySymbol()`
- **PortfolioPage.tsx** — Holdings + transactions tables use `displaySymbol()`
- **AlertsPage.tsx** — Alert list uses `displaySymbol()`
- **BottomPanel.tsx** — Portfolio tab + notes use `displaySymbol()`
- **SearchModal.tsx** — Uses `parseSymbol()` for display, added international MARKET_META colors (JP, CN, HK, UK, DE, FR, KR), updated popular stocks to include Toyota (.T) and Tencent (.HK)

### Added (2026-03-03 — Thai Fund NAV via SEC Open Data API)

**Thai mutual fund NAV data source — SEC API + Finnomena fallback:**
- **workers/fund_fetcher.py** — Complete rewrite:
  - Primary source: SEC Open Data API (api.sec.or.th) — Fund Factsheet for proj_id mapping + Fund Daily Info for daily NAV
  - Fallback: Finnomena public API (no auth required)
  - `_build_proj_id_map()`: Enumerates all Thai AMCs → all funds → builds `{fund_abbr_name → proj_id}` mapping (cached 24h in Redis)
  - `_resolve_proj_id()`: Fuzzy-matches user-entered symbols to SEC names (exact → suffix add/strip → prefix match → manual aliases)
  - `_fetch_nav_sec()`: Fetches daily NAV with share class matching (-A, -C, -D, -R) to get correct class
  - Dual-write: writes both `fund:{symbol}` (fund-specific) AND `quote:{symbol}` (same format as price_fetcher) so portfolio/sidebar read without special logic
- **core/config.py** — Added `sec_fund_factsheet_key` and `sec_fund_daily_info_key` settings
- **docker-compose.dev.yml** — Added `SEC_FUND_FACTSHEET_KEY` and `SEC_FUND_DAILY_INFO_KEY` env vars to celery-worker and celery-beat services
- **`_find_prev_nav()`** — Fetches previous day NAV from SEC API to calculate daily change/change_pct for fund quotes
- **`_fetch_nav_sec()`** — Share class matching: SEC returns multiple classes per proj_id (-A, -C, -D, -R), now matches by `class_abbr_name` to pick correct class

**Thai stock search fix:**
- **services/stock_service.py `_search_yahoo_direct()`** — Now searches both raw query AND query+".BK" to find Thai SET/MAI stocks. Detects Thai exchange from Yahoo `exchange` field and normalizes symbol with .BK suffix

**Data fixes:**
- Fixed ADVANC: market US → SET, symbol ADVANC → ADVANC.BK (stocks table + watchlist_items)

### Fixed (2026-03-03 — Portfolio ฿0.00, chart fund loading, symbol auto-registration)

**Critical fix — Portfolio มูลค่ารวม ฿0.00:**
- **portfolio.py analytics** — `StockQuote(**json)` failed silently because cached quote JSON (from on_demand_listener) is missing `open, high, low, prev_close, timestamp` fields. Changed to use raw dict parsing with `quote.get("price")` instead of `StockQuote` schema. All holdings now show correct current price and P&L.

**Critical fix — Chart loading forever for Thai funds:**
- **stocks.py `/history`** — Returns `is_fund: true` flag for non-Yahoo-fetchable symbols
- **schemas.py StockHistory** — Added `is_fund: bool = False` field
- **TradingChart.tsx** — Detects `is_fund` flag and immediately shows "กองทุนรวม — ไม่มีข้อมูลกราฟ" instead of retrying endlessly

**New feature — Symbol auto-registration (CQRS write side):**
- **workers/symbol_registrar.py** — New Celery worker with 2 tasks:
  - `register_symbol(symbol)`: fetches metadata from Yahoo Finance (name, sector, exchange), classifies market type (SET/US/FUND), upserts into `stocks` table
  - `scan_unregistered()`: periodic task (every 15 min) scans `watchlist_items` + `transactions` for symbols not yet in `stocks` table, dispatches `register_symbol` for each
- **watchlist.py `add_stock`** — fires `register_symbol.delay()` on stock add
- **portfolio.py `add_transaction`** — fires `register_symbol.delay()` on transaction add
- **celery_app.py** — registered `symbol_registrar` + beat schedule

**Portfolio performance 500 error:**
- **portfolio_performance.py** — Fixed: was calling `fetch_stock_history()` with unsupported `from_ts`/`to_ts` kwargs. Changed to CQRS-compliant `read_history()` (Redis/PostgreSQL only). Handles both dict and OHLCVBar bar formats.

**Dashboard TOP MOVERS layout:**
- **DashboardPage.tsx MoverRow** — Items without price data now show placeholder icon + "รอข้อมูล…" instead of bare "—" with no icon (was causing visual misalignment)

### Fixed (2026-03-03 — Data gaps: fund NAV, stock names, symbol mapping, chart reload)

**Frontend fixes:**
- **TradingChart.tsx** — Added `normalizeBarTime()` to convert unix timestamps to `yyyy-mm-dd` (fixes "Invalid date string" crash). Chart now re-fetches on `dataVersion` change (WS `data_ready` → chart auto-updates without page refresh).
- **Sidebar.tsx** — Thai mutual funds now display NAV with date label instead of "—". Names API returns `{name, market}` so sidebar knows which symbols are funds. Removed broken `searchResults`-based fund filter.
- **PortfolioPage.tsx** — Auto-retry timer (5s × 6 = 30s) fetches analytics when `has_pending_prices` is true. Also re-fetches on WS `data_ready` via `dataVersion` listener. Removed incorrect "กองทุน" badge that appeared for ALL null-price symbols. Now shows currency badge always, "รอข้อมูล..." for pending, "ไม่มีข้อมูล" for confirmed unavailable.
- **Caddyfile.dev** — Added Google OAuth domains to CSP (`accounts.google.com`, `apis.google.com`, `frame-src`).

**Backend fixes:**
- **stocks.py `/names`** — Now returns `{symbol: {name, market}}` with market type so frontend can distinguish FUND vs stock.
- **stocks.py `/quotes`** — Now checks `fund:{symbol}` Redis cache for FUND symbols. Returns fund NAV as quote-like format with `type: "fund_nav"`. Added `_is_yahoo_fetchable()` filter + DB market=FUND check to prevent sending Thai mutual funds to Yahoo (avoids 20s timeout per symbol).
- **stocks.py `/{symbol}/quote`** — Added fund cache check (L1.5) before requesting background fetch. Only sends Yahoo-fetchable symbols to on_demand_listener.
- **stocks.py history/fundamentals** — Added `_is_yahoo_fetchable()` guard before requesting background fetch.
- **portfolio.py** — 3-stage price enrichment: Redis quote → Redis fund NAV → Celery `request_data_fetch()`. Only sends Yahoo-fetchable symbols to on_demand_listener. `has_pending_prices` flag enables frontend auto-retry.
- **Yahoo symbol mapping** — Added `BRK.B→BRK-B`, `BRK.A→BRK-A`, `BF.B→BF-B`, `BF.A→BF-A` in all 5 Celery workers + on_demand_listener.
- **fund_fetcher.py** — Removed `pythainav` dependency (incompatible with FastAPI's typing-extensions). Now fetches directly from SEC Open Data API + yfinance fallback.
- **workers/__init__.py** — Fixed `task_success_handler` signal signature (Celery `task_success` passes kwargs, not positional args).
- **requirements.txt** — Removed `pythainav` (dependency conflict with `typing-extensions>=4.8`).

### Refactored (2026-03-03 — Backend API: pure-read architecture, NO external API calls from endpoints)

**Major architecture refactor:** Every API endpoint is now "pure read" — NO endpoint calls external APIs (Yahoo Finance, Stooq, etc.). All data comes exclusively from Redis (L1) → PostgreSQL (L2). Missing data triggers a Celery background task via `request_data_fetch()`.

**Rationale:** Separates concerns cleanly. Data fetching is handled by Celery workers (background). API endpoints focus on fast reads + returning data status (empty/pending). This unblocks the event loop and prevents external API failures from blocking user responses.

- **stock_service.py** — Added 4 pure-read functions:
  - `async read_quote(symbol)` — Redis cache only, returns None on miss
  - `async read_history(symbol, tf)` — Redis → PostgreSQL ohlcv_bars table, returns list[dict] or []
  - `async read_fundamentals(symbol)` — Redis cache only, returns dict or None
  - `async request_data_fetch(symbol, data_type)` — Publishes to "fetch_requests" Redis channel (deduplicated 30s), triggers Celery worker to fetch + cache data asynchronously

- **stocks.py `/quotes` batch** — Refactored to pure-read:
  - Removed all calls to `_cache_quote_background()`
  - Now: 1. Redis pipeline all symbols (one round-trip) 2. Return cached immediately 3. Request background fetch for misses via `request_data_fetch()`

- **stocks.py `/{symbol}/quote`** — Simplified to pure-read:
  - Removed `_fetch_quote_direct()` direct call with 4s timeout
  - Now: 1. Read Redis cache (sub-ms) 2. Return 202 pending + request background fetch if miss

- **stocks.py `/{symbol}/history`** — Refactored to pure-read:
  - Removed `fetch_stock_history()` direct call with 4.5s timeout
  - Now: 1. Read from Redis → PostgreSQL via `read_history()` 2. Return empty bars + request background fetch if miss

- **stocks.py `/{symbol}/fundamentals`** — Refactored to pure-read:
  - Removed `fetch_stock_fundamentals()` direct call with 4s timeout
  - Now: 1. Read Redis cache only via `read_fundamentals()` 2. Return empty + request background fetch if miss

- **screener.py** — Complete rewrite, now pure-read from PostgreSQL:
  - Removed all httpx.Client calls to Yahoo Finance (was fetching live 6mo daily data per symbol)
  - Refactored `_run_screener()` → `_run_screener_db()`: accepts AsyncSession, queries ohlcv_bars table for daily bars, computes indicators (RSI, MACD, MA50/MA200) entirely from stored data
  - Replaced pandas Series `.ewm()/.diff()` with pure Python list comprehensions for RSI/MACD (no pandas dependency in screener logic)
  - EMA calculation implemented as helper function using standard Wilder smoothing
  - Endpoint now awaits `_run_screener_db()` directly (no executor thread needed) with 4.5s timeout

**Important:** Existing Celery worker code (`_fetch_quote_direct()`, `fetch_stock_history()`, `fetch_stock_fundamentals()`, `_cache_quote_background()`, etc.) is preserved unchanged. Workers still call these functions to populate Redis/PostgreSQL. Only the API layer changed.

### Added (2026-03-03 — CQRS Write Side: 5 new Celery workers for complete data ingestion)

**5 new Celery workers** created as the sole data ingesters (CQRS write side). API endpoints no longer fetch external data — these workers do it all.

- **`workers/name_fetcher.py`** — `prefetch_names()`: Fetches company names (Yahoo Finance `shortName`) for ALL active symbols in DB. Caches in Redis `cache:name:{symbol}` (24h TTL) + updates `stocks.name` in PostgreSQL. Schedule: every 6 hours.
- **`workers/fundamentals_fetcher.py`** — `prefetch_fundamentals()`: Fetches PE, PB, EPS, marketCap, dividendYield, beta, 52W high/low from yfinance `.info`. Caches in Redis `fundamentals:{symbol}` (4h TTL). Schedule: every 4 hours.
- **`workers/fund_fetcher.py`** — `fetch_thai_fund_navs()`: Fetches Thai mutual fund NAV via `pythainav` library (wraps SEC Thailand API + บลจ. websites). Caches in Redis `fund:{symbol}` (24h TTL). Schedule: daily at 19:00 ICT (12:00 UTC). Gracefully handles missing pythainav.
- **`workers/history_prefetcher.py`** — `prefetch_history()`: Pre-fetches 6-month 1D OHLCV history for all watched symbols with expired cache. Caches in Redis `ohlcv:{symbol}:1D` (6h TTL) + upserts to PostgreSQL `ohlcv_bars`. Schedule: every 30 minutes.
- **`workers/on_demand_listener.py`** — `process_fetch_request(symbol, data_type)`: Handles API cache-miss fetch requests. Triggered directly via Celery `.delay()` from `request_data_fetch()`. Supports: quote, history, fundamentals, all. Redis NX deduplication (30s lock).
- **`workers/celery_app.py`** — Added 5 new modules to `include=[]`, 4 new beat schedule entries.
- **`stock_service.py`** — Updated `request_data_fetch()` to use Celery `.delay()` instead of Redis pub/sub.
- **`requirements.txt`** — Added `pythainav==0.2.8` for Thai fund NAV.

### Fixed (2026-03-02 — ALL APIs < 5s: fast-response + WebSocket data_ready pattern)

**Architecture change:** Every API endpoint now responds within 5 seconds. External API calls (Yahoo Finance) that would block the response are moved to background tasks. When background data is ready, the server notifies the client via WebSocket `data_ready` message, and the client automatically re-fetches.

- **stock_service.py** — Added `_notify_data_ready(data_type, symbol)` function: publishes `{type: "data_ready", data_type, symbol}` on Redis pub/sub `price_updates` channel. Called after `_cache_quote_background()` completes.
- **dashboard.py** — Complete rewrite to cache-only pattern: all 4 sections (indices, portfolio, alerts, movers) use new `_fast_quote()` helper (Redis-only, sub-ms). Cache misses trigger `_ensure_quotes_cached()` background task which fetches then publishes WS `data_ready`. Response includes `has_pending_data` flag.
- **stocks.py `/quotes` batch** — Changed from blocking 12s gather to instant return: cached data returned immediately, cache misses fire individual `_cache_quote_background()` tasks (non-blocking).
- **stocks.py `/{symbol}/quote`** — 3-tier fast response: L1 Redis cache (sub-ms) → L2 quick fetch with 4s cap → L3 return 202 + trigger background fetch + WS notify.
- **stocks.py `/{symbol}/history`** — Added 4.5s timeout cap. On timeout: returns empty bars + fires background fetch + WS `data_ready` notification when bars are cached.
- **stocks.py `/{symbol}/fundamentals`** — Added 4s timeout cap. Returns empty fundamentals on timeout.
- **stocks.py `/{symbol}/news`** — Reduced feedparser timeout from 8s to 4s per feed.
- **stocks.py** — Added missing logger import (was referenced in history timeout handler).
- **portfolio.py `/analytics`** — Replaced blocking 12s `asyncio.gather(fetch_quote_now×N)` with non-blocking background tasks. Returns cached prices immediately, `has_pending_prices: true` flag tells frontend to expect updates.
- **portfolio_performance.py `/performance`** — Added 4.5s timeout cap on history gather.
- **ai_chat.py `_build_context()`** — Replaced blocking `fetch_quote_now()` (20s timeout) with Redis cache-only read (sub-ms). On cache miss: triggers background fetch (non-blocking). Fundamentals capped at 3s.
- **auth.py Google OAuth** — Wrapped `verify_oauth2_token` executor in `asyncio.wait_for(timeout=5.0)` to prevent 10-15s hangs on slow Google key fetch.
- **screener.py** — Reduced per-symbol Yahoo Finance timeout from 15s to 4s. Added 4.5s total timeout cap on the executor.
- **schemas.py `PortfolioAnalytics`** — Added `has_pending_prices: bool = False` field.
- **main.py** — Added `data_ready` message type handling in Redis pub/sub broadcaster: broadcasts to ALL connected WebSocket clients.
- **useWebSocket.ts** — Added `data_ready` message handler: calls `bumpDataVersion()` from `appStore` to trigger React re-renders in all data-dependent components.

### Fixed (2026-03-02 — Critical frontend bugs: stale closures, missing error UI, fund badge, pct format)
- **Sidebar.tsx** — Fixed stale closure in price refresh interval. The 60s interval was calling a stale reference of `refreshPrices`. Already using useRef pattern (`refreshPricesRef`) correctly, no change needed. Additionally added FUND symbol filter: before calling `getQuotesBatch`, filter out symbols with market type "FUND" to avoid wasting API calls on unfetchable mutual fund symbols.
- **PortfolioPage.tsx** — Fixed fund badge display. When a holding has `current_price == null` (mutual funds), now displays "กองทุน" (Fund) yellow badge instead of currency code, and shows "ไม่มี NAV" in price column instead of dash to clarify why price is missing.
- **ScreenerPage.tsx** — Fixed pct field format in `handleRowClick`. Was incorrectly setting `pct: r.chg` (duplicating change amount) instead of formatting the percentage. Now formats as `"±X.XX%"` string with proper sign prefix. Also added `.toFixed(2)` to price and chg fields for consistency.
- **DashboardPage.tsx** — Added error state handling. Previously when dashboard API failed, showed blank loading indefinitely. Now captures error message, displays centered error card with warning icon and "Retry" button. Error state checked before loading state, preventing infinite loading loop on persistent failures.

### Fixed (2026-03-02 — PTT.BK retry logic uses 'data' in locals() incorrectly)
- **stock_service.py `_fetch_yahoo_direct()`** — Fixed critical bug in Thai .BK stock fallback period retry logic. The code checked `if 'data' in locals()` to determine if fresh HTTP data was received, but after the first period iteration, the `data` variable persisted in local scope, causing subsequent period attempts to parse OLD data from the previous iteration instead of fresh data. Fixed with explicit `data_received = False` flag (initialized per period) set to `True` only after successful HTTP response + JSON parse. This ensures each fallback period (1y → 6mo → 3mo → 1mo → 5d) gets tested with fresh data.
- **stock_service.py `_fetch_yahoo_direct()`** — Improved logging throughout the period fallback flow: added debug logs showing which periods are being tried, warnings when a period returns 0 bars, debug logs showing transitions to next fallback period, and error logs when all periods are exhausted with the full list of attempted periods.

### Fixed (2026-03-02 — Alert field name bug: target_price → value)
- **dashboard.py** — Fixed crash in alert proximity check: references to non-existent `a.target_price` replaced with correct `a.value` field from Alert model (lines 140, 145, 148). Added null check for RSI/indicator alerts where `a.value` is None. Alert checker worker was already correct; dashboard was the only file with this bug.

### Fixed (2026-03-02 — Portfolio analytics slow + mutual fund symbols blocking Yahoo fetch)
- **portfolio.py `/analytics`** — Added `_is_yahoo_fetchable()` pre-filter: symbols with spaces, `&`, or other chars that Yahoo Finance rejects (Thai mutual funds: "SCBS&P500", "PRINCIPAL IPROP-D", "MPDIVMF") are immediately excluded from the Yahoo fetch pipeline. Previously each would wait the full 20 s httpx timeout on every cold-cache request, making the endpoint take 20+ s.
- **portfolio.py `/analytics`** — Added 12 s `asyncio.wait_for` guard around the entire `asyncio.gather` Yahoo batch. Endpoint now returns partial data (prices for whatever completed) within 12 s rather than potentially blocking for 20 s per slow symbol.
- **stocks.py `/quotes` batch** — Same 12 s `asyncio.wait_for` guard added for cold-cache Sidebar requests.
- **portfolioService.js** — Reduced frontend timeout 45 s → 20 s (backend now guarantees response within 12 s; 20 s gives 8 s buffer).

### Fixed (2026-03-02 — Portfolio analytics all current_price null)
- **portfolio.py `/analytics` endpoint** — Same semaphore starvation bug as the batch quotes endpoint: `asyncio.gather(fetch_quote_now×13)` competed for 8 semaphore slots simultaneously. Fixed with the same two-stage Redis pipeline strategy: (1) read all holdings from Redis in one pipeline round-trip; (2) only symbols missing from cache go to `fetch_quote_now()`. In steady state (Celery running), portfolio prices are served entirely from Redis cache in milliseconds.

### Fixed (2026-03-02 — Batch quotes all-null + company names missing for US stocks)
- **stocks.py `/quotes` batch endpoint** — Complete rewrite to two-stage strategy: (1) Redis pipeline checks ALL symbols in one round-trip — if Celery keeps cache warm this returns instantly with zero Yahoo requests; (2) only true cache misses go to `fetch_quote_now()` in parallel. Previously all 13 symbols hit `asyncio.gather(fetch_quote_now×13)` simultaneously, competing for 8 semaphore slots — the last 5 waited 4-6s for slots, leaving <3s for Yahoo, causing cascade timeouts and "all null" response.
- **stock_service.py `fetch_quote_now()`** — Raised hard cap from 7s → 20s to match the `httpx.Timeout(20.0)` inside `_fetch_quote_direct`. 7s was too tight when semaphore wait is included in the budget.
- **stock_service.py `_fetch_quote_direct()`** — Now caches `meta.shortName` from Yahoo chart API response into Redis `cache:name:{symbol}` (24h TTL). This populates company names for US stocks/ETFs not in the local PostgreSQL DB.
- **stocks.py `/names` endpoint** — Added Redis name cache fallback: for symbols not found in local DB (US ETFs like VOO, SCHD, BRK.B), reads from `cache:name:{symbol}` populated by `_fetch_quote_direct`. Sidebar now shows "Vanguard S&P 500 ETF" instead of "VOO" once the quote has been fetched at least once.

### Fixed (2026-03-02 — Not-found cache poisoning valid symbols like NVDA)
- **stock_service.py `fetch_quote_now()`** — Critical cache poisoning bug: `asyncio.TimeoutError` (7s hard cap exceeded) was treated identically to "symbol not found", setting `cache:quote:notfound:{sym}` for 5 minutes. So if Yahoo was slow once for NVDA, all `/quote/NVDA` requests returned 404 for 5 minutes. Fixed: only set not-found key when `_fetch_quote_direct()` returns `None` cleanly (Yahoo explicitly returned empty data) — not on `asyncio.TimeoutError` or any `Exception` (`is_transient_failure` flag). Timeouts and network errors now bypass the cache, allowing the next request to retry Yahoo immediately.

### Fixed (2026-03-02 — RightPanel quote & 52W data)
- **stockService.js `getQuote()`** — Dead-code bug: `if (res.status === 404)` was unreachable because axios throws on 4xx before returning. Fixed with try/catch: 404 now returns `{ data: null }` so the component sees "not found" cleanly; all other errors (timeout, network) are re-thrown for the caller's `.catch()` to handle
- **RightPanel.tsx `fetchQuote()`** — Removed obsolete 202-retry loop (6 retries × 5s = 30s of pointless polling). Backend `fetch_quote_now()` now blocks server-side for up to 7s and returns data or 404 — client-side polling is redundant and was masking the silent 404 failure
- **RightPanel.tsx `fetchQuote()`** — 404 from `getQuote` was silently swallowed: `.catch()` only set `timedOut` for ECONNABORTED, so quote stayed `null` forever with no error shown. Now handled cleanly: `{ data: null }` → quote stays null (panel shows "—"), real errors → setTimedOut
- **RightPanel.tsx stats** — Field name mismatch: `fundamentals?.high_52week` and `fundamentals?.low_52week` were referencing non-existent fields. Backend Pydantic schema exports `week_52_high` / `week_52_low`. Fixed to match — 52W High/Low now display actual data
- **RightPanel.tsx** — Removed unused `useRef` import and `quoteRetryRef` (only existed to support the now-deleted retry timer)

### Fixed (2026-03-02 — Quote timeouts + Vite HMR CSP)
- **stock_service.py `fetch_quote_now()`** — Added 7s hard cap via `asyncio.wait_for()`. Without this, batch calls block 20+ s waiting for invalid symbols (e.g. Thai mutual funds MPDIVMF, SCBS&P500 that don't exist on Yahoo Finance)
- **stock_service.py `fetch_quote_now()`** — Added "not-found" cache (Redis key `cache:quote:notfound:{sym}`, TTL 5 min): first miss fetches from Yahoo; subsequent calls return `None` instantly, preventing repeat hammering of Yahoo for invalid tickers
- **stock_service.py `_fetch_quote_direct()`** — Reduced .BK timeout from 20s → 8s, retries from 3 → 2 (faster fail, within the 7s fetch_quote_now hard cap)
- **caddy/Caddyfile.dev** — Removed strict CSP headers that blocked Vite HMR module injection (`(blocked:csp)` in network tab). Dev CSP now allows `blob:`, `https:`, `http:`, `worker-src blob:` so Vite hot-reload works properly. **Production Caddyfile unchanged.**

### Fixed (2026-03-02 — News page overhaul + backend async fix)
- **stocks.py `/news` endpoint** — Fixed sync-blocking `feedparser.parse()` running in async handler; now uses `asyncio.to_thread()` to prevent event loop stall
- **stocks.py `/news` endpoint** — Robust symbol sanitisation: strips `^`, `=X`, `=F`, `.BK`/`.MAI` and special chars; maps known index aliases to readable queries (GSPC → "S&P 500")
- **stocks.py `/news` endpoint** — 8s timeout per fetch + Thai-first / English-fallback dual-language strategy
- **NewsPage.tsx** — Full rewrite: search bar, tab-based symbol routing (SET/US/Watchlist), symbol validation (rejects garbage like "SCBS&P500"), sentiment summary counts, empty-state fallback button, refresh button

### Fixed (2026-03-02 — Dashboard prices & UI)
- **dashboard.py** — Replaced all `fetch_stock_quote()` (fire-and-forget → None on cache miss) with `fetch_quote_now()` (blocking, always returns data) for indices, portfolio summary, alert proximity checks, and movers
- **dashboard.py** — Alert proximity checks now run in parallel via `asyncio.gather` instead of sequential `for` loop (faster dashboard load)
- **dashboardService.js** — Increased timeout from 12s → 30s to accommodate parallel Yahoo Finance fetches
- **portfolioService.js** — Increased analytics timeout from 12s → 45s for portfolios with many holdings
- **DashboardPage.tsx** — Complete UI refresh:
  - `IndexCard`: added directional arrow icon (ArrowUpRight/ArrowDownRight), tighter spacing, % on own line
  - `MoverRow`: added colored TrendingUp/Down icon badge, better alignment, right-align % column
  - Portfolio card: side-by-side layout (value+sparkline left, top holdings right)
  - Market Status card: added trading hours text (10:00–16:30 / 21:30–04:00 ICT), divider between markets
  - Alerts section: horizontal layout (count left, content right) instead of stacked
  - Movers grid: sorted with data-available stocks first; xl:col-span-4 → md:col-span-3 xl:col-span-4

### Changed (2026-03-02 — Portfolio Tab Layout)
- **PortfolioPage.tsx** — Converted from stacked sections to tab-based layout
  - Tab bar with "Holdings" (BarChart2 icon + badge count) and "ประวัติธุรกรรม" (History icon + badge count)
  - Active tab shows accent underline indicator + accent-colored badge
  - Holdings tab: table with hover rows, empty state with CTA button
  - History tab: filter bar (ทั้งหมด/ซื้อ/ขาย) + transaction table + empty state
  - Removed collapsible toggle (ChevronUp/Down); tabs replace the show/hide mechanic

### Added (2026-03-02 — Frontend UI Design System)
- **frontend/src/styles/glass.css** — Global CSS design tokens & semantic color system
  - Color tokens: `--color-positive` (#10b981), `--color-negative` (#f43f5e), `--color-neutral`
  - Shimmer animation keyframe for skeleton loaders
  - Utility classes: `.text-positive`, `.text-negative`, `.bg-positive`, `.bg-negative`

- **frontend/src/components/common/Skeleton.tsx** — Reusable skeleton loading component
  - Main `<Skeleton>` with variants: 'text', 'rect', 'circle'
  - Pre-built layouts: `<SkeletonCard>`, `<SkeletonChart>`, `<SkeletonSidebarItem>`
  - Shimmer effect for better UX during data fetching

- **frontend/src/components/common/Badge.tsx** — Semantic badge component
  - Variants: positive, negative, neutral, warning, info
  - Sizes: sm, md
  - Convenience components: `<ChangeBadge>` for price changes, `<MarketStatusBadge>` for market status

- **frontend/src/components/pages/DashboardPage.tsx** — Bento grid dashboard redesign
  - New responsive grid layout (1 col mobile, 2 cols tablet, 4 cols desktop)
  - Portfolio Summary card spans 2 cols on XL (shows total value, P&L, sparkline, top holdings)
  - Market Status card shows SET and US market open/closed status
  - Top Movers spans full width (grid of 6 movers, 3 per row on XL)
  - Active Alerts card spans full width
  - Improved skeleton loading states with Skeleton components
  - Uses new Badge components for semantic styling

- **frontend/src/components/chart/BottomPanel.tsx** — Notes panel already fully implemented
  - Notes tab with markdown support
  - Auto-save debounced (1.5s) via notesService
  - Save status indicator (Saving... / Saved ✓)
  - Per-stock note persistence via `/api/notes/{symbol}`

### Added (2026-03-02 — Frontend Chart Indicators)
- **frontend/src/utils/indicators.js** — New `calculateVWAP()` function for Volume-Weighted Average Price
  - Resets per calendar day boundary (0-23:59 UTC)
  - Formula: VWAP = cumulative(typical_price × volume) / cumulative(volume)
  - Typical price = (H + L + C) / 3
  - Returns array of {time, value} points for charting

- **frontend/src/components/chart/TradingChart.tsx** — Volume indicator now toggleable
  - Added 'Volume' to ChartToolbar indicator list
  - Volume histogram shows/hides based on `activeIndicators.includes('Volume')`
  - Color: green (#34d39966) for up candles, red (#f8717166) for down candles

- **frontend/src/components/chart/TradingChart.tsx** — VWAP overlay for intraday timeframes
  - Rendered as dashed purple line (#9C27B0) when 'VWAP' toggle is ON
  - Only visible on 1m, 5m, 15m, 1h, 4h timeframes (resets daily)
  - Disabled on daily/weekly/monthly charts where VWAP has no practical use

- **frontend/src/components/chart/ChartToolbar.tsx** — Timeframe button active state styling
  - Active timeframe now has distinct appearance: accent background color, white text, border
  - Inactive timeframes show light gray text with hover effect on interaction
  - Clearer visual feedback for currently selected timeframe

### Fixed (2026-03-02 — OHLCV Crosshair Overlay Already Working)
- **frontend/src/components/pages/ChartPage.tsx** — Crosshair OHLCV overlay was already correctly implemented
  - Shows O/H/L/C/Volume values in top-left panel as user hovers over chart
  - Opacity 0.45 when no crosshair data, 1.0 when hovering
  - Color-coded: green for up moves, red for down moves

- **frontend/src/components/chart/RightPanel.tsx** — RSI gauge was already working correctly
  - Fetches 1D history bars, calculates RSI(14)
  - Displays as gradient gauge (green=oversold, yellow=neutral, red=overbought)
  - No changes needed; confirmed operational

### Added (2026-03-02 — Backend Data Improvements)
- **backend/services/stock_service.py** — Enhanced `_fetch_yahoo_direct()` for Thai .BK stocks:
  - Increased timeout to 20s (was 15s) for .BK symbols, keeping 1 retry attempt for US stocks
  - Added fallback period chain (3mo → 1mo → 5d) when initial fetch returns 0 bars — automatically retries with shorter periods before giving up
  - If all periods exhaust with 0 bars, logs warning and returns empty; frontend handles gracefully with "No data" message
  - Timeout/error retry logic already had exponential backoff [0, 2, 6]s for .BK symbols
  - Tested to verify ^SET.BK and Thai stocks now have better success rate on data fetching

- **backend/models/stock.py** — StockEvent model already existed with columns: id, symbol, event_type, event_date, value, description, created_at
  - Field names verified: uses `event_date` (not ex_date), `value` (dividend amount), `description` (Thai/English text)

- **backend/scripts/seed_events.py** — New seed script for corporate events (XD/XR dividends)
  - Seeded 7 sample XD events for SET50 stocks (PTT.BK, KBANK.BK, SCB.BK, AOT.BK, CPALL.BK, BTS.BK, BBL.BK) in Q1-Q2 2026
  - Each event includes: symbol, event_type, event_date, dividend amount, Thai description (ปันผล)
  - Run via: `docker-compose -f docker-compose.dev.yml exec backend python -m scripts.seed_events`

- **backend/api/routes/stocks.py** — New endpoint `/api/stocks/{symbol}/events`
  - GET with optional query params: `start_date` (YYYY-MM-DD), `end_date` (YYYY-MM-DD)
  - Defaults: 1 year back, 6 months forward from today
  - Returns: `{"symbol": "PTT.BK", "events": [{id, symbol, event_type, event_date, value, description}, ...]}`
  - Used by chart to display XD/XR markers with dividend amount on ex-date

- **backend/api/routes/stocks.py** — `/api/stocks/names` endpoint already returns `name_th` field
  - Prefers Thai names (name_th) for .BK/.MAI symbols, English (name) for others
  - Used by Sidebar and search to display "ปตท" instead of "PTT Public Company Limited"
  - Sample: `{"PTT.BK": "ปตท", "AAPL": "Apple Inc."}`

### Fixed (2026-03-01 — WebSocket + Real-time Prices + Alert Checker)
- **backend/main.py** — Added `_redis_price_broadcaster()` async background task: subscribes to Redis `price_updates` channel and forwards messages to WebSocket clients; `alert_triggered` messages go to `broadcast_all()`, price updates go to `broadcast_price()` (symbol subscribers only)
- **backend/main.py** — Added `ConnectionManager.broadcast_all()` method for broadcasting to all connected WS clients (used for alert notifications)
- **backend/workers/alert_checker.py** — Fixed Redis key mismatch: was reading `quote:{sym}`, corrected to `cache:quote:{sym}` to match `price_fetcher._cache_and_publish()` storage key — alerts were never evaluating because quotes were always empty
- **backend/workers/alert_checker.py** — Alert checker now publishes `alert_triggered` event to Redis `price_updates` channel on trigger, enabling real-time WS notifications to the browser
- **frontend/src/hooks/useWebSocket.ts** — Fixed WS URL: was connecting to `/api/ws/{user.id}?token=...` (non-existent route), corrected to `/api/ws/prices`
- **frontend/src/hooks/useWebSocket.ts** — Replaced flat 5s reconnect delay with exponential backoff: 2s → 4s → 8s → 16s → 30s (max)

### Fixed (2026-03-01 — Caddy + Frontend Access)
- **caddy/Caddyfile.dev** — Changed site address `http://localhost` → `:80` so Caddy binds to port 80 on all interfaces inside Docker (not just matching Host header "localhost")
- **caddy/Caddyfile.dev** — Fixed upstream from `frontend:3000` → `frontend:5173` (Vite dev server port)
- **frontend/vite.config.ts** — Fixed `server.port: 3000` → `5173`; added `hmr: { clientPort: 80 }` so HMR WebSocket connects through Caddy on port 80
- **docker-compose.dev.yml** — Added `ports: "5173:5173"` to frontend service as direct-access fallback

### Fixed (2026-03-01 — Startup noise + warm-up fix)
- **backend/main.py** — Replaced sync `apply_async()` warm-up (caused `[Errno 111] Connection refused` — sync broker connect conflicts with asyncio event loop) with async `_warmup_cache()` coroutine using `_cache_quote_background()` directly; waits 8s then warms 11 symbols in parallel
- **backend/api/routes/system.py** — `_check_celery_health()` now suppresses stdout/stderr during `inspect.ping()` — stops kombu/amqp printing function stubs (`def fetch_us_prices(self): return 1`) to Docker logs; timeout reduced to 2s, removed redundant `inspect.active()` call


### Fixed (2026-03-01 — Celery worker crash diagnosis)
- **backend/requirements.txt** — Added `yfinance==0.2.65` (missing package caused `No module named 'yfinance'` on every celery task) and `psycopg2-binary==2.9.10` (required by Celery sync SQLAlchemy in `alert_checker` and `housekeeping`)
- **docker-compose.dev.yml** — db healthcheck: added `-d ${POSTGRES_DB:-stockviz_db}` to `pg_isready` — without it Postgres tried connecting to DB named `stockviz` (= username) which didn't exist, flooding logs with `FATAL: database "stockviz" does not exist` every 5s
- **docker-compose.dev.yml** — Added `PYTHONPATH: /app` to `celery-worker` and `celery-beat` — fork-pool worker subprocesses were missing `/app` in `sys.path`, causing `No module named 'models'` on every alert-checker task

### Added
- **INSTRUCTIONS.md** — Rule: never run servers directly on host; all services must run via `docker-compose -f docker-compose.dev.yml` only; added allowed vs forbidden command reference table
- **PTT.BK Thai stock timeout** — `_fetch_yahoo_direct` now uses 15s timeout for .BK symbols (was 6s), addressing empty bars issue under slow network conditions
- **Yahoo Finance retry with exponential backoff** — Thai .BK symbols now retry up to 3 times with [0, 2, 6] second delays; US stocks use single attempt with 6s timeout
- **`/api/health` Celery status** — extended health check to include `celery: ok/fail` by inspecting active workers via `celery.control.inspect().active()` and `.ping()`
- **`/api/system/ready` US stock probes** — added `cache:quote:NVDA` and `cache:quote:AAPL` to probe keys; now checks 5 symbols (3 SET + 2 US) with threshold=3

### Completed
- **GUEST_SYMBOLS reorder** — US stocks now first (NVDA, AAPL, TSLA, MSFT, GOOGL, AMZN) followed by Thai stocks (PTT.BK, ADVANC.BK, KBANK.BK, SCB.BK, AOT.BK, CPALL.BK)
- **TradingChart "No data available" message** — when OHLCV returns empty after 3 retries, displays centered glass card with emoji + help text suggesting to try US stocks (NVDA/AAPL)
- **Global CSS design tokens file** (`frontend/src/styles/glass.css`) — 2026 glassmorphism system with CSS custom properties for backgrounds, borders, blur effects, shadows, colors, animations, and durations
- **Glassmorphism modal enhancements** — SearchModal and SettingsModal updated to use `.glass-search` and `.glass-panel` classes with `.glass-backdrop` overlay, `.glass-slide-up` animations, and `.glass-divider` borders; Sidebar autocomplete uses `.glass-dropdown`

### Planned
- Rebuild frontend Docker image with all Phase 1 source fixes
- Celery workers diagnosis and fix
- Modern 2026 UI overhaul (bento grid, micro-interactions)

---

## [0.1.3] — 2026-03-01

### Added
- **`/api/stocks/names`** batch endpoint — returns `{symbol: name}` for comma-separated symbols; used by Sidebar to show company names instead of tickers. Prefers `name_th` for `.BK`/`.MAI` symbols.
- **`useBackendReady` hook** (`frontend/src/hooks/useBackendReady.ts`) — polls `/api/system/ready` every 3 seconds after startup; calls `bumpDataVersion()` when backend cache is ready, triggering auto-refresh across all subscribed components.
- **`/api/system/ready`** endpoint — checks Redis probe keys (`cache:quote:PTT.BK`, `cache:quote:^GSPC`, `cache:quote:^IXIC`); returns `{ready: bool, cached: N, total: 3}`.
- **`dataVersion` + `bumpDataVersion`** to `appStore` — integer version counter used as useEffect dependency to trigger data refreshes when backend becomes ready.
- **`_cache_quote_background()`** coroutine — asyncio background task that fetches quote from Yahoo Finance and caches in Redis when Celery is unavailable. Triggered via `asyncio.create_task()` on cache miss.
- **`avg_volume` field** to `StockFundamentals` Pydantic schema — enables Avg Vol display in RightPanel stats.
- **`getNames()`** to `stockService.js` — calls `/api/stocks/names` endpoint.

### Fixed
- **Sidebar.tsx interval memory leak** — `setInterval` was recreated on every `dataVersion` or `refreshPrices` change. Fixed with stable ref pattern: interval set up once with empty deps, ref updated separately, immediate fetch triggered in separate effect.
- **DashboardPage.tsx interval memory leak** — same pattern as Sidebar. Fixed with `loadRef` stable ref.
- **TradingChart.tsx setTimeout not cleared** — retry `setTimeout` stored in `retryTimer` ref and properly cleared in cleanup function.
- **AIChatPanel.tsx setTimeout leak** — Ollama polling `setTimeout` now cleared on unmount via `cancelled` flag and `timer` ref.
- **RightPanel.tsx race condition** — rapid symbol changes left stale XHR promises updating state. Fixed with `AbortController` — aborted on symbol change.
- **`ws://localhost/undefined` WebSocket error** — caused by `@tanstack/devtools-vite` injecting WS client even after plugin removed. Fixed with `define` block in `vite.config.ts` setting `__TANSTACK_DEVTOOLS_WS__` to empty string.
- **Watchlist subtitle shows ticker instead of company name** — `displayList` was mapping `name: sym`. Fixed by adding `/api/stocks/names` batch lookup + `names` state in Sidebar.
- **Fundamentals 404** — `_fetch_fundamentals_direct` now tries Yahoo Finance v11 → v10 → v8 chart API meta in fallback chain. Extracts `fiftyTwoWeekHigh`, `fiftyTwoWeekLow`, `epsTrailingTwelveMonths`, `marketCap`, `trailingPE` from chart meta when quoteSummary fails.
- **Quote 202 (Celery unavailable)** — `fetch_stock_quote` now fires `asyncio.create_task(_cache_quote_background(symbol))` when Celery import fails, enabling quotes to populate via asyncio (~5s latency) instead of waiting indefinitely.
- **Default stock PTT.BK → NVDA** — changed `appStore.js` default `selectedStock` to NVDA (which has working chart data). Source changed; compiled bundle patch needed after Docker rebuild.

### Changed
- **Celery task priority** — on-demand and startup warm-up tasks now use `priority=9` (highest) to jump ahead of beat-scheduled tasks.
- **`_fetch_fundamentals_direct`** — upgraded to try `financialData` module alongside `summaryDetail` + `defaultKeyStatistics`; better EPS coverage.

---

## [0.1.2] — 2026-02-28

### Added
- **Watchlist company names** — added `/api/stocks/names` endpoint (must be registered BEFORE `/{symbol}/...` routes to avoid path conflict).
- **Celery priority=9** on `fetch_set_prices` and `fetch_us_prices` for on-demand triggers.
- **Startup warm-up tasks** in `main.py` lifespan — triggers `fetch_overview_prices`, `fetch_set_prices`, `fetch_us_prices` with `priority=9` and short countdown on first startup.

### Fixed
- **Frontend auto-refresh on backend ready** — implemented polling + `dataVersion` pattern. Components include `dataVersion` in their trigger `useEffect` deps to auto-refresh when cache warms up.

---

## [0.1.1] — 2026-02-24

### Added
- Initial project structure complete (frontend + backend + Docker)
- User authentication: JWT (15m access + 7d refresh rotation), bcrypt password hashing
- Google OAuth scaffolding
- Stock chart: TradingView Lightweight-Charts 5 with 8 timeframes
- Chart types: Candlestick, Line, Area
- Technical indicators: MA, EMA, Bollinger Bands, RSI, MACD
- Drawing tools: Trend, H-Line, Fib, Rect, Arrow, Pitchfork
- Watchlist CRUD (create, add, remove, reorder)
- Portfolio transactions (buy/sell with fee, date, note)
- Portfolio analytics: holdings, P&L, allocation
- Alerts system: PRICE_ABOVE, PRICE_BELOW, RSI, volume spike, MA cross
- Stock screener with preset filters
- News feed (Google RSS + Finnhub)
- AI Chat panel (Ollama local LLM)
- Stock notes (investment thesis per symbol)
- Dark mode (default) + light mode toggle
- WebSocket real-time price subscriptions
- Celery Beat scheduled workers:
  - `fetch-set-prices`: every 1 min (SET market hours)
  - `fetch-us-prices`: every 1 min (US market hours)
  - `fetch-overview-prices`: every 2 min (always-on for indices)
  - `check-all-alerts`: every 60 sec
  - `run-housekeeping`: daily @ 03:00 ICT
- TimescaleDB continuous aggregates for data compression
- Rate limiting: 30/min guests, 120/min users (Redis-backed)
- 4-layer OHLCV cache: Redis → PostgreSQL → Yahoo Finance/Stooq → Synthetic
- Synthetic intraday generator (Brownian bridge from daily data)
- SET stock name database (name_th for Thai names)
- `/api/health` and `/api/system/ready` endpoints
- Admin role scaffolding

### Known Issues at Release
- PTT.BK Yahoo Finance returns empty bars under rate limiting
- Celery worker not populating Redis in some dev environments
- Frontend production build outdated (interval leaks, names not showing)
- Fundamentals 404 due to Yahoo Finance quoteSummary API version changes
- Quote endpoint returns 202 when Celery offline

---

## [0.1.0] — 2026-02-15

### Added
- Initial project scaffolding
- Docker Compose setup (dev + prod)
- TimescaleDB + Redis + FastAPI + React 19 + TanStack Start
- Basic project structure, environment config
- README, REQUIREMENTS, INSTRUCTIONS documents

## [2026-03-02] — DevOps Session: Celery Monitoring + Flower UI

### Added — Celery task monitoring infrastructure
**Files:** `backend/workers/__init__.py`, `backend/workers/celery_app.py`, `backend/api/routes/system.py`, `backend/workers/price_fetcher.py`

- **`backend/workers/__init__.py`** — New module registering Celery signal handlers:
  - `@task_prerun.connect` → records task start time in `_task_start_times` dict
  - `@task_success.connect` → increments `celery:stats:success` counter, stores `celery:stats:last_success_at` timestamp, logs elapsed time (7-day TTL)
  - `@task_failure.connect` → increments `celery:stats:failure` counter, stores `celery:stats:last_failure_at` timestamp + exception in `celery:stats:last_error` (7-day TTL)
  - All handlers use sync Redis (required by signal handlers) and silently ignore errors to avoid crashing task execution

- **`backend/workers/celery_app.py`** — Updated to import `workers` module → registers signal handlers on startup; ensures task success/failure counters are populated in Redis

- **`backend/api/routes/system.py`** — Added `GET /api/system/celery-stats` endpoint:
  - Returns `{success_count, failure_count, last_success_at, last_failure_at, last_error, last_success_elapsed}`
  - Reads from Redis keys: `celery:stats:success`, `celery:stats:failure`, `celery:stats:last_success_at`, `celery:stats:last_failure_at`, `celery:stats:last_error`, `celery:task:last_success_elapsed`
  - Graceful fallback if Redis unavailable (returns zeros/nulls)

- **`backend/workers/price_fetcher.py`** — Enhanced logging in all three fetch tasks:
  - Added `start = time.time()` before yfinance calls
  - Logs `elapsed_sec` as formatted float (e.g., `"2.34"`) on success and failure
  - Enables visibility into task performance and latency patterns

### Added — Flower UI for Celery monitoring
**Files:** `docker-compose.dev.yml`, `caddy/Caddyfile.dev`

- **`docker-compose.dev.yml`** — New `flower` service:
  - Image: `mher/flower:2.0`
  - Command: `celery --broker=redis://redis:6379/0 flower --port=5555`
  - Depends on redis (broker)
  - Exposed on port 5555 (mapped directly and via Caddy)
  - Network: `stockviz-net`

- **`caddy/Caddyfile.dev`** — Added Flower reverse proxy rule:
  - Route `/flower*` → `flower:5555`
  - Placed before WebSocket routing to ensure proper rule matching
  - Enables access via `https://localhost/flower` in browser

### Manual Next Steps
1. **Rebuild Docker images** (required to activate Celery signal imports):
   ```bash
   docker-compose -f docker-compose.dev.yml build frontend backend celery-worker celery-beat
   docker-compose -f docker-compose.dev.yml up -d
   ```

2. **Restart backend to load new signals**:
   ```bash
   docker-compose -f docker-compose.dev.yml restart backend celery-worker
   ```

3. **Access monitoring endpoints**:
   - Flower UI: `https://localhost/flower` (live task queue, worker status, task history)
   - Celery stats: `GET /api/system/celery-stats` (JSON format, suitable for custom dashboards)

4. **Verify in logs**:
   - Backend should not error on import of `workers` module
   - Celery Beat should start scheduling tasks normally
   - Monitor `docker-compose -f docker-compose.dev.yml logs celery-worker` for task success/failure events

### Rationale
- **Signal handlers capture task metrics at execution time** → no need to pollute task code with logging
- **Redis storage (7-day TTL)** → lightweight, ephemeral metric store; stats auto-purge after 7 days
- **Flower UI** → visual task queue monitoring (active tasks, workers, task history, retry chains)
- **`/api/system/celery-stats` endpoint** → enables custom dashboards, alerting systems, and monitoring tools to pull stats in JSON format
- **Graceful error handling** → signal handlers never crash tasks even if Redis is temporarily unavailable
