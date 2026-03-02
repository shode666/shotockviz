# ShotockViz — Changelog

All notable changes to this project will be documented here.
Format: [version] · date · description
Rule: **Update this file after every completed task.**

---

## [Unreleased]

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
