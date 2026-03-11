# ShotockViz — Task List

**Format:** `[x]` = done · `[ ]` = pending · `[~]` = in progress
**Rule:** After completing any task → update `changelog.md`
**Dev command:** `docker-compose -f docker-compose.dev.yml up`

## Developer Guidance Legend

| Icon | Meaning |
|------|---------|
| 📁 **Files** | ไฟล์ที่ต้องแก้ — เริ่มอ่านจากไฟล์เหล่านี้ก่อน |
| ⚠️ **Pitfalls** | สิ่งที่ต้องระวัง — ข้อผิดพลาดที่เจอบ่อย |
| 🔗 **Reference** | ดูตัวอย่างจากโค้ดที่มีอยู่แล้วในโปรเจค |
| 📐 **Pattern** | Design pattern ที่ใช้ในโปรเจค — ทำตามเพื่อ consistency |

### Codebase Quick Map
```
frontend/src/
├── routes/          # TanStack Start pages: __root.tsx, index.tsx, dashboard.tsx, alerts.tsx, portfolio.tsx, screener.tsx, news.tsx, login.tsx
├── components/
│   ├── chart/       # TradingChart.tsx, ChartToolbar.tsx, DrawingToolbar.tsx, RightPanel.tsx, BottomPanel.tsx
│   ├── common/      # Navbar.tsx, Sidebar.tsx, StatusBar.tsx, AIChatPanel.tsx
│   ├── pages/       # DashboardPage.tsx, ChartPage.tsx, AlertsPage.tsx, PortfolioPage.tsx, ScreenerPage.tsx, NewsPage.tsx
│   └── modals/      # SearchModal.tsx, SettingsModal.tsx
├── store/           # Zustand: appStore.js (selectedStock, indicators), authStore.js (user, token)
├── services/        # API calls: api.js (axios base), stockService.js, watchlistService.js, portfolioService.js, alertService.js, aiService.js, notesService.js, dashboardService.js
├── hooks/           # useAuth.js, useWebSocket.ts, useBackendReady.ts
├── utils/           # formatters.js, indicators.js, marketStatus.ts
└── styles/          # Tailwind + glassmorphism CSS

backend/
├── main.py                  # FastAPI app, WebSocket manager, CORS, Redis broadcaster
├── api/routes/              # 13 modules: auth, stocks, watchlist, portfolio, portfolio_performance, alerts, screener, dashboard, ai_chat, drawings, notes, system
├── models/                  # SQLAlchemy ORM: user, stock, ohlcv, watchlist, portfolio, alert, drawing, note, schemas
├── services/                # stock_service.py (224-line facade), cache_orchestrator.py, db_helpers.py, providers/, generators/
├── workers/                 # Celery: 11 workers (price_fetcher, name_fetcher, fundamentals_fetcher, fund_fetcher, history_prefetcher, on_demand_listener, alert_checker, news_fetcher, symbol_registrar, index_populator, housekeeping)
├── core/                    # config.py, database.py, redis.py, security.py, logger.py, cache_keys.py, ttl_policy.py
├── schemas/                 # Pydantic: common.py
├── scripts/                 # seed_stocks.py, seed_history.py, create_user.py
└── utils/                   # timeframes.py
```

### Common Patterns (ทำตามเพื่อ consistency)
- **Frontend API call:** ใช้ `api.js` (axios instance) → สร้าง service file ใน `services/` → เรียกใน component
- **Backend route:** สร้างไฟล์ใน `api/routes/` → register ใน `api/routes/__init__.py` → prefix `/api/xxx`
- **State management:** Zustand store ใน `store/` → import `useAppStore()` ใน component
- **Celery task:** สร้าง function ใน `workers/` → register ใน `celery_app.py` beat schedule
- **Auth:** Google OAuth only — ห้ามสร้าง custom token logic ที่ frontend (ใช้ `useGoogleOneTapLogin` ใน `__root.tsx`)
- **Docker rebuild:** หลังแก้ frontend → `docker-compose -f docker-compose.dev.yml build frontend && docker-compose -f docker-compose.dev.yml up -d frontend`

---

# Phase 1: Stabilization — Fix What's Broken

## Frontend Bundle (Critical)
- [x] Fix interval memory leak in `Sidebar.tsx` — unstable deps on `setInterval` causing unbounded timer accumulation
- [x] Fix interval memory leak in `DashboardPage.tsx` — same pattern with `load` + `dataVersion` deps
- [x] Fix `setTimeout` not cleared in `TradingChart.tsx` on unmount during retry
- [x] Fix `setTimeout` not cleaned up in `AIChatPanel.tsx` Ollama polling
- [x] Fix `RightPanel.tsx` race condition — add `AbortController` on symbol change
- [x] Fix `RightPanel.tsx` 52W High/Low always "—" — `high_52week`/`low_52week` → `week_52_high`/`week_52_low` (field name mismatch with backend Pydantic schema)
- [x] Fix `RightPanel.tsx` quote never loading — removed dead 202-retry loop; `stockService.getQuote` now properly catches 404 (axios throws before the old `if (res.status === 404)` check was reached)
- [x] Fix `ws://localhost/undefined` WebSocket error (TanStack devtools WS injected even after plugin removed)
- [x] **Fix critical data display bugs (2026-03-02):**
  - [x] **Sidebar.tsx** — Filter out FUND symbols before API call to avoid wasting requests on unfetchable mutual funds
  - [x] **PortfolioPage.tsx** — Display "กองทุน" (Fund) badge and "ไม่มี NAV" label for mutual fund holdings instead of dash
  - [x] **ScreenerPage.tsx** — Fix pct field format: was duplicating `r.chg`, now formats correctly as percentage string `"±X.XX%"`
  - [x] **DashboardPage.tsx** — Add error state handling: capture error message, show retry button instead of infinite loading
- [ ] **Rebuild frontend Docker image** so all source fixes take effect in the running app
  - **Why:** Memory leak fixes, AbortController, WebSocket URL — all committed in source but compiled bundle still serves old code
  - **Steps:**
    - [ ] Run `docker-compose -f docker-compose.dev.yml build frontend`
    - [ ] Run `docker-compose -f docker-compose.dev.yml up -d frontend`
    - [ ] Verify NVDA loads as default stock on fresh page load
    - [ ] Verify no `setInterval` leak in browser DevTools Performance tab (record 60s, check heap)
    - [ ] Verify WebSocket connects to `/api/ws/prices` (not `/undefined`)
  - **Acceptance:** Fresh page → NVDA chart renders in <3s, no console errors, Performance tab shows stable memory over 60s
  - **Trader scenario:** เปิดเว็บมาแล้ว NVDA ขึ้นทันที ไม่ต้องกด refresh หรือเลือก stock ใหม่ ไม่มี memory leak ค้างจาก interval
  - 📁 **Files:** `docker-compose.dev.yml` (frontend service), `frontend/Dockerfile`
  - ⚠️ **Pitfalls:** ใช้ `docker-compose.dev.yml` เท่านั้น ห้ามใช้ prod compose, ตรวจ `frontend/.output/` ว่า build ใหม่จริง (ดู timestamp)

## Default Stock & First-Load Experience
- [x] Change `appStore.js` default `selectedStock` from `PTT.BK` → `NVDA`
- [x] Patch compiled SSR bundle (`router-wjxIC3wR.mjs`) — change PTT.BK default
- [x] Update `GUEST_SYMBOLS` in `Sidebar.tsx` — put US stocks first (NVDA, AAPL, TSLA) before Thai (.BK)
- [x] On chart empty bars after 3 retries: show "No data" message + suggest clicking a US stock

## Backend Data Fixes
- [x] Add asyncio fallback in `fetch_stock_quote` when Celery unavailable (`_cache_quote_background`)
- [x] Fix fundamentals 404 — upgrade `_fetch_fundamentals_direct` to try v11 → v10 → v8 chart API
- [x] Add `avg_volume` field to `StockFundamentals` Pydantic schema
- [x] Add `/api/stocks/names` batch endpoint for company name lookup
- [x] Add `useBackendReady` hook polling `/api/system/ready` → bumps `dataVersion`
- [x] Add `dataVersion` + `bumpDataVersion` to `appStore`
- [x] Fix `PTT.BK` Yahoo Finance empty bars — increase timeout from 6s → 15s for Thai stocks
- [x] Add retry with exponential backoff in `_fetch_yahoo_direct` for .BK symbols
- [x] Investigate Celery workers: verify they run in `docker-compose.dev.yml` stack

## Code Quality & Refactoring
- [x] **Refactor 3 backend route files to use guard clauses + extracted helpers (SOLID principles)**
  - [x] **dashboard.py (317 lines)** — Extracted 5 helpers: `_fetch_indices_cached()`, `_build_portfolio_summary()`, `_find_alerts_near_target()`, `_get_user_watchlist()`, `_get_top_movers()`
  - [x] **screener.py (345 lines)** — Extracted 2 helpers: `_fetch_symbol_bars()`, `_evaluate_symbol()` + added `_compute_sma()` utility
  - [x] **ai_chat.py (408 lines)** — Extracted 4 helpers: `_fetch_quote_context()`, `_fetch_fundamentals_context()`, `_fetch_portfolio_context()`, `_fetch_watchlist_context()`
  - All files < 500 lines, all compiled successfully
  - All helpers have type hints + docstrings with Args/Returns
  - Main endpoints now act as clean orchestrators
  - Flattened nested try/except blocks → guard clauses + early returns

## Fast-Response Pattern (ALL APIs < 5s)
- [x] Add `_notify_data_ready()` to stock_service.py — publishes WS notification via Redis pub/sub
- [x] Rewrite dashboard.py — cache-only reads + background fetch + WS `data_ready`
- [x] Fix batch quotes (`/quotes`) — return cached immediately, BG fetch for misses
- [x] Fix single quote (`/{symbol}/quote`) — 4s timeout + 202 + BG fetch
- [x] Fix history (`/{symbol}/history`) — 4.5s timeout + BG fetch + WS notify
- [x] Fix fundamentals (`/{symbol}/fundamentals`) — 4s timeout
- [x] Fix news (`/{symbol}/news`) — reduce feedparser timeout 8s → 4s
- [x] Fix portfolio analytics (`/analytics`) — replace 12s blocking gather with BG tasks
- [x] Fix portfolio performance (`/performance`) — 4.5s timeout on history gather
- [x] Fix AI chat context (`_build_context`) — cache-only quote read + 3s fundamentals cap
- [x] Fix Google OAuth — 5s timeout on verify_oauth2_token
- [x] Fix screener — 4s per-symbol timeout, 4.5s total timeout
- [x] Add `data_ready` message handling in main.py Redis broadcaster
- [x] Add `data_ready` handler in useWebSocket.ts → bumpDataVersion()
- [x] Add `has_pending_prices` to PortfolioAnalytics schema
- [x] **Pure-read refactor: NO external API calls from endpoints** (2026-03-03)
  - [x] Add 4 pure-read functions to stock_service.py: `read_quote()`, `read_history()`, `read_fundamentals()`, `request_data_fetch()`
  - [x] Refactor `/{symbol}/quote` — remove direct `_fetch_quote_direct()`, use `read_quote()` only
  - [x] Refactor `/quotes` batch — remove direct calls, use Redis pipeline + `request_data_fetch()` for misses
  - [x] Refactor `/{symbol}/history` — remove `fetch_stock_history()` call, use `read_history()` (Redis → PostgreSQL)
  - [x] Refactor `/{symbol}/fundamentals` — remove direct call, use `read_fundamentals()` (Redis only)
  - [x] Refactor screener.py — remove Yahoo Finance httpx.Client calls, implement `_run_screener_db()` reading from PostgreSQL ohlcv_bars table, compute indicators (RSI, MACD, MAs) in pure Python (no pandas)
- [ ] **Rebuild frontend Docker image** to activate useWebSocket.ts changes
- [ ] **Verify all endpoints < 5s** during live testing

## CQRS Write Side — Celery Workers (2026-03-03)
- [x] Create `workers/name_fetcher.py` — prefetch company names every 6h
- [x] Create `workers/fundamentals_fetcher.py` — prefetch PE/PB/EPS every 4h
- [x] Create `workers/fund_fetcher.py` — fetch Thai fund NAV daily 19:00 ICT via pythainav
- [x] Create `workers/history_prefetcher.py` — warm OHLCV cache every 30min
- [x] Create `workers/on_demand_listener.py` — handle API cache-miss via Celery .delay()
- [x] Update `celery_app.py` — register 5 new workers + 4 beat schedules
- [x] Update `stock_service.py request_data_fetch()` — Celery .delay() instead of Redis pub/sub
- [x] Add `pythainav==0.2.8` to requirements.txt
- [ ] **Rebuild backend Docker image** to register new workers
- [ ] **Verify Celery Beat picks up new schedules** (`celery inspect registered`)
- [ ] **Test on-demand flow**: clear cache → load page → verify 202 → verify WS data_ready → verify re-fetch

## System Health
- [x] Add `/api/system/ready` endpoint (checks Redis probe keys)
- [x] Backend `/api/health` → `{database: ok, redis: ok}`
- [x] Extend `/api/health` to include `celery: ok/fail` (inspect active workers)
- [x] Add `/api/system/ready` probe keys for US stocks in addition to SET

---

# Phase 2: Data Reliability & Real-time

## Celery Workers
- [x] Diagnose why `celery-worker` container isn't populating Redis quotes — confirmed working (check_all_alerts + fetch_overview_prices succeeding)
- [x] Fix `price_fetcher.py` yfinance batch signature — already uses `fast_info` correctly
- [ ] Add Celery task monitoring: log success/failure counts per run
  - **Why:** Celery failures are silent — worker crashes without alert, prices go stale, trader doesn't know
  - **Steps:**
    - [ ] Add `after_task_publish` / `task_failure` signals in `workers/__init__.py`
    - [ ] Create Redis keys `celery:stats:success`, `celery:stats:failure` with INCR per task
    - [ ] Add `/api/system/celery-stats` endpoint returning counts + last run timestamps
    - [ ] Log task name + duration + symbol count on each `price_fetcher` run
  - **Acceptance:** `/api/system/celery-stats` returns `{success_count, failure_count, last_success_at, last_failure_at}`, backend logs show `[price_fetcher] OK: 42 symbols in 3.2s`
  - **Trader scenario:** ถ้า Celery ตาย price sidebar จะไม่ update — ต้อง detect ได้ทันที ไม่ใช่รอจนสังเกตว่าราคาไม่ขยับ
  - **Effort:** 2-3 hours
  - 📁 **Files:** `backend/workers/__init__.py` (signals), `backend/workers/price_fetcher.py` (logging), `backend/api/routes/system.py` (endpoint), `backend/core/redis.py` (Redis client)
  - 🔗 **Reference:** ดู `/api/system/ready` ใน `system.py` เป็นตัวอย่าง endpoint pattern
  - ⚠️ **Pitfalls:** Redis INCR เป็น atomic — ใช้ได้ใน concurrent workers, แต่ต้องตั้ง TTL ด้วย (ไม่งั้น key อยู่ตลอด)
- [x] Add Flower UI for Celery task visibility
  - **Completed (V2):** Flower service in docker-compose.dev.yml with `--url_prefix=flower`, Caddy proxy at `/flower`, depends on celery-worker

## Real-time Price Updates
- [x] Fix WebSocket URL: `useWebSocket` was connecting to `/api/ws/{user.id}` — fixed to `/api/ws/prices`
- [x] Fix WebSocket reconnect on disconnect (exponential backoff: 2s, 4s, 8s, 16s, 30s max)
- [x] Broadcast price updates on Redis pub/sub → WebSocket → React state (added `_redis_price_broadcaster` task in `main.py`)
- [x] Fix alert checker reading wrong Redis key (`quote:{sym}` → `cache:quote:{sym}`)
- [x] Wire alert_triggered notifications via Redis pub/sub → broadcast_all() → WebSocket → frontend toast
- [ ] Verify live prices update in sidebar during US market hours (20:30–03:00 ICT)
  - **Why:** WebSocket pipeline (Celery → Redis pub/sub → WebSocket → React) not yet tested during live market
  - **Steps:**
    - [ ] During US market hours, open app and watch sidebar prices for NVDA, AAPL, TSLA
    - [ ] Verify prices change at least once per minute (Celery fetches every 60s)
    - [ ] Check Redis `cache:quote:NVDA` TTL is refreshed on each fetch
    - [ ] Verify WebSocket message received in browser DevTools Network → WS tab
    - [ ] Confirm sidebar sparkline updates on new price
  - **Acceptance:** Sidebar shows live bid/ask within 2 min of market data, prices auto-update without page refresh
  - **Trader scenario:** เปิดดู pre-market ตอน 20:00 ICT — ต้องเห็นราคา NVDA เปลี่ยนแบบ real-time ใน sidebar ไม่ต้อง F5
  - **Depends on:** Frontend Docker rebuild (Phase 1)
  - 📁 **Files:** `frontend/src/hooks/useWebSocket.ts` (client), `backend/main.py` (`_redis_price_broadcaster`), `backend/workers/price_fetcher.py` (source), `frontend/src/components/common/Sidebar.tsx` (display)
  - 🔗 **Reference:** ดู `useWebSocket.ts` — มี reconnect logic อยู่แล้ว, flow: price_fetcher → Redis pub/sub → main.py broadcaster → WebSocket → Sidebar
  - ⚠️ **Pitfalls:** US market hours เป็น ICT 21:30-04:00 — ต้อง test ช่วงนั้นจริง ๆ ไม่ใช่เวลาไทยปกติ, ดู `marketStatus.ts` สำหรับ market hours logic

## Thai Stock Data
- [ ] Research alternative data sources for SET market (.BK):
  - **Why:** Yahoo Finance .BK data is unreliable — frequent empty responses, slow timeouts, no intraday for Thai stocks
  - **Steps:**
    - [ ] SET official API (requires registration) — check rate limits, cost, data latency
    - [ ] Bisnews API (Thai financial data provider) — check free tier availability
    - [ ] Scrape from SET website as last resort — check robots.txt, legal implications
    - [ ] Evaluate Jitta API for Thai fundamental data
    - [ ] Document findings in `REQUIREMENTS.md` under Data Sources section
  - **Acceptance:** Written comparison table of 3+ sources with: cost, latency, coverage (SET50/SET100/MAI), rate limits
  - **Trader scenario:** ข้อมูล SET ต้อง reliable ถ้าจะดู PTT, KBANK, AOT ก่อนตลาดเปิด 10:00 แล้วข้อมูลไม่มา เสียโอกาส
  - **Effort:** 4-6 hours (research + documentation)
  - 📁 **Files:** `backend/services/stock_service.py` (ดู `_fetch_yahoo_direct`, `_fetch_fundamentals_direct` — logic ปัจจุบันที่ต้องเปลี่ยน)
  - ⚠️ **Pitfalls:** `stock_service.py` มี 47KB — ใหญ่มาก อ่าน function names ก่อน แล้วค่อย dive in, Yahoo Finance .BK ใช้ timeout 15s อยู่แล้ว (เพิ่มจาก 6s)
- [x] Fix `PTT.BK` and other .BK stocks returning empty history
  - **Why:** Yahoo Finance timeout + empty bars for Thai stocks makes SET analysis impossible
  - **Steps:**
    - [x] Increase yfinance timeout to 20s specifically for .BK symbols
    - [x] Add fallback: if yfinance returns 0 bars, try alternative period (3mo → 1mo → 5d)
    - [x] Cache last-known-good data in Redis with 24h TTL as stale fallback
    - [x] Test with PTT.BK, KBANK.BK, AOT.BK, CPALL.BK, TRUE.BK
    - [x] **Fix Bug #5: PTT.BK retry logic uses 'data' in locals() incorrectly (2026-03-02)** — The fallback period retry was reusing old `data` variable from previous period iteration instead of fresh data. Fixed with explicit `data_received` flag. Added detailed logging showing period chain traversal.
  - **Acceptance:** All 5 test symbols return ≥1 bar within 20s, stale data shown if live fetch fails
  - **Depends on:** Alternative data source research (ideally switch away from yfinance for .BK)
  - 📁 **Files:** `backend/services/stock_service.py` → `_fetch_yahoo_direct()`, `backend/services/cache_service.py` (stale fallback)
  - 🔗 **Reference:** ดู retry logic ที่มีอยู่ใน `_fetch_yahoo_direct` — มี exponential backoff สำหรับ .BK อยู่แล้ว
  - ⚠️ **Pitfalls:** อย่า cache data เก่าที่ราคาผิด — ใส่ flag `is_stale: true` ใน response ให้ frontend แสดง warning
- [ ] Verify `^SET.BK` index symbol works in Yahoo Finance
  - **Steps:**
    - [ ] Test `yfinance.download("^SET.BK", period="5d")` in Docker backend shell
    - [ ] If works: add to `GUEST_SYMBOLS` as market overview reference
    - [ ] If fails: try `^SET50.BK` or `SET.BK` variants
  - **Acceptance:** SET index chart renders on chart page with 1D candles
- [x] Implement `name_th` (Thai company names) display throughout UI
  - **Why:** Thai traders think in Thai names — "ปตท" not "PTT Public Company Limited"
  - **Steps:**
    - [x] Add `name_th` field to `Stock` model + migration
    - [x] Seed Thai company names from SET website or CSV
    - [x] Display `name_th` in sidebar, search results, chart header (with English fallback)
    - [x] Add locale toggle (TH/EN) in settings
  - **Acceptance:** PTT.BK shows "ปตท" in sidebar, KBANK.BK shows "กสิกรไทย"
  - **Effort:** 3-4 hours
  - 📁 **Files:** `backend/models/stock.py` (add column), `backend/scripts/seed_stocks.py` (seed data), `frontend/src/components/common/Sidebar.tsx` (display), `frontend/src/services/stockService.js` (fetch)
  - 🔗 **Reference:** ดู `/api/stocks/names` endpoint ใน `stocks.py` — มี batch name lookup อยู่แล้ว, เพิ่ม `name_th` field
  - ⚠️ **Pitfalls:** ต้อง migration (ดู Alembic task ใน Phase 5) — ถ้ายังไม่มี Alembic ใช้ `ALTER TABLE` manual ก่อน

## Indicators
- [ ] Verify all 5 indicator overlays render on chart: MA 20, EMA 50, BB, RSI 14, MACD
  - **Steps:**
    - [ ] Toggle each indicator one-by-one on NVDA 1D chart, screenshot result
    - [ ] Verify MA20 line (blue), EMA50 line (orange), BB bands (gray fill), RSI sub-chart, MACD sub-chart
    - [ ] Test indicator toggle off removes overlay cleanly (no ghost lines)
    - [ ] Test multi-indicator: MA20 + BB + RSI simultaneously
  - **Acceptance:** All 5 indicators render correctly, toggling on/off is instant (<200ms), no visual artifacts
  - **Trader scenario:** เปิด chart NVDA ดู MA20 + BB เทียบ price action ก่อนตัดสินใจ entry — indicator ต้องถูกต้อง 100%
  - 📁 **Files:** `frontend/src/components/chart/TradingChart.tsx` (render), `frontend/src/utils/indicators.js` (calculation logic), `frontend/src/components/chart/ChartToolbar.tsx` (toggle buttons)
  - 🔗 **Reference:** ดู `indicators.js` — มี calculation functions ทั้ง MA, EMA, BB, RSI, MACD อยู่แล้ว
  - ⚠️ **Pitfalls:** LightweightCharts v5 API — ใช้ `chart.addLineSeries()` สำหรับ overlay, `chart.addHistogramSeries()` สำหรับ sub-chart ห้ามใช้ deprecated v4 API
- [x] Fix RSI gauge not showing in RightPanel when indicator active
  - **Why:** RSI gauge in RightPanel designed to show current RSI value as dial — **VERIFIED WORKING** already
  - **Status:** RightPanel already calculates RSI(14) from 1D history (lines 40-54 in RightPanel.tsx) and displays gauge (lines 152-174)
  - **Evidence:** RSI value computed via `calculateRSI(barsData, 14)` and rendered as gradient gauge with 0-100 scale
  - No changes needed
- [x] Add Volume indicator (already in chart data, add toggle)
  - **Status:** COMPLETED 2026-03-02
  - **Changes:**
    - Added 'Volume' to indicator list in ChartToolbar (line 9)
    - Volume histogram now toggles ON/OFF based on `activeIndicators.includes('Volume')` in TradingChart (lines 269-280)
    - Color: green (#34d39966) for up candles, red (#f8717166) for down candles
  - **Files modified:** `frontend/src/components/chart/ChartToolbar.tsx`, `frontend/src/components/chart/TradingChart.tsx`
- [x] Add VWAP overlay for intraday timeframes (1m, 5m, 15m)
  - **Status:** COMPLETED 2026-03-02
  - **Changes:**
    - Added `calculateVWAP()` function to `frontend/src/utils/indicators.js` (lines 134-159)
      - Resets per calendar day boundary
      - Formula: VWAP = cumulative(TP×V) / cumulative(V) where TP = (H+L+C)/3
    - Added 'VWAP' to indicator list in ChartToolbar (line 9)
    - VWAP renders as dashed purple line (#9C27B0) only on intraday timeframes (1m,5m,15m,1h,4h) in TradingChart (lines 328-337)
    - Hides automatically on daily/weekly/monthly charts
  - **Files modified:** `frontend/src/utils/indicators.js`, `frontend/src/components/chart/ChartToolbar.tsx`, `frontend/src/components/chart/TradingChart.tsx`

## Chart UI Polish
- [x] Fix chart toolbar timeframe active state styling
  - **Status:** COMPLETED 2026-03-02
  - **Changes:** Timeframe buttons now have distinct active styling:
    - Active button: accent background color, white text, accent border
    - Inactive buttons: light gray text, transparent background, hover effect
  - **File modified:** `frontend/src/components/chart/ChartToolbar.tsx` (lines 47-72)
  - **Visual feedback:** User now clearly sees which timeframe is selected

- [x] Verify OHLCV crosshair overlay working
  - **Status:** VERIFIED WORKING — no changes needed
  - **Evidence:** ChartPage.tsx (lines 65-80) shows crosshair overlay when hovering chart, TradingChart.tsx (lines 156-181) has proper subscription
  - **Features:** Shows O/H/L/C/Volume with color-coding (green up, red down)

## Corporate Events
- [x] Seed `stock_events` table with XD/XR dates from SET API
  - **Why:** XD/XR dates cause sudden price drops — trader ต้องรู้ก่อนเข้าซื้อ ไม่งั้นเจ็บ
  - **Steps:**
    - [x] Scrape XD/XR calendar from SET website or use SET API
    - [x] Parse event type (XD = ex-dividend, XR = ex-rights, XW = ex-warrant)
    - [x] Insert into `stock_events` table: symbol, event_type, ex_date, record_date, payment_date, amount
    - [x] Create Celery task to refresh monthly
  - **Acceptance:** `stock_events` table has ≥50 rows for current quarter's SET50 stocks
  - **Effort:** 4 hours
  - 📁 **Files:** `backend/models/stock.py` (StockEvent model มีอยู่แล้ว — ตรวจ schema), `backend/workers/` (สร้าง Celery task ใหม่), `backend/scripts/` (seed script)
  - 🔗 **Reference:** ดู `seed_stocks.py` เป็นตัวอย่าง seed script pattern
- [x] Display XD/XR markers on chart as vertical lines or icons
  - **Steps:**
    - [x] Query `stock_events` for current symbol + visible date range
    - [x] Render vertical dashed line on ex-date using LightweightCharts markers API
    - [x] Add tooltip on hover: "XD: ปันผล 0.50 บาท/หุ้น, จ่าย 15 พ.ค."
    - [x] Color: XD = green marker, XR = blue marker, XW = yellow marker
  - **Acceptance:** KBANK.BK chart shows XD marker on correct date with dividend amount tooltip
  - **Trader scenario:** กำลังจะซื้อ KBANK แล้วเห็น XD marker อีก 3 วัน — ตัดสินใจได้ว่าจะรอหลัง XD หรือเข้าก่อน
  - 📁 **Files:** `frontend/src/components/chart/TradingChart.tsx` (markers), `backend/api/routes/stocks.py` (add `/api/stocks/{symbol}/events` endpoint)
  - 🔗 **Reference:** LightweightCharts markers API: `series.setMarkers([{time, position, color, shape, text}])`
  - ⚠️ **Pitfalls:** Markers ต้อง sort by time — ถ้าไม่ sort จะ throw error, ใช้ `position: 'aboveBar'` สำหรับ XD/XR
- [ ] Earnings date markers for US stocks (from Finnhub)
  - **Steps:**
    - [ ] Use Finnhub `/stock/earnings` endpoint (free tier: 60 calls/min)
    - [ ] Store in `stock_events` table with event_type = "EARNINGS"
    - [ ] Add Celery task to fetch quarterly for watchlist symbols
    - [ ] Display as orange marker on chart with tooltip: "Earnings: 2026-04-25 AMC" (After Market Close)
  - **Acceptance:** NVDA chart shows next earnings date marker, tooltip shows date + timing (BMO/AMC)
  - **Trader scenario:** ไม่เข้า position ก่อน earnings ถ้าไม่มั่นใจ — ต้องเห็น earnings marker บน chart เลย
  - **Effort:** 3 hours
  - 📁 **Files:** `backend/core/config.py` (FINNHUB_API_KEY), `backend/workers/` (new Celery task), `backend/models/stock.py` (StockEvent model)
  - ⚠️ **Pitfalls:** Finnhub free tier = 60 calls/min — ใช้ rate limiter, batch fetch for watchlist symbols only (ไม่ fetch all stocks)

---

# V2: Institutional-Grade Features (2026-03-04)

## Phase 2.1 — Infrastructure
- [x] Flower Monitoring Dashboard — `--url_prefix=flower`, Caddy proxy, celery-worker dependency
- [x] Hybrid Fetching Logic — `request_data_fetch()` tries Celery → asyncio fallback on broker failure

## Phase 2.2 — Data Engine
- [x] Symbol Mapping — `SymbolMapping` model + `symbol_mapper.py` service (async/sync, Redis-cached, DB-backed)
- [x] Corporate Action Adjustments — `CorporateAction` model + `corporate_actions_fetcher.py` worker + `price_adjuster.py` + `?adjusted=true` history param
- [x] Migration `20260304_0003` — `symbol_mappings` + `corporate_actions` tables

## Phase 2.3 — Institutional Features
- [x] Relative Strength (RS) Line — `GET /{symbol}/rs?benchmark=^SET.BK` endpoint
- [x] Financial Health Scorecard — `FinancialHistory` model + `financials_history_fetcher.py` worker + `GET /{symbol}/financials?years=10`
- [x] Earnings Surprise Tracker — `EarningsEvent` model + `earnings_events_fetcher.py` worker + `GET /{symbol}/earnings?limit=8`
- [x] Migration `20260304_0004` — `financial_history` + `earnings_events` tables

## Phase 2.4 — AI/Observability
- [x] pgvector Integration (RAG) — custom PostgreSQL image (TimescaleDB + pgvector), `DocumentEmbedding` model, `embedding_service.py`, `embedding_worker.py`, RAG context injection in `ai_chat.py`, migration `20260304_0005`
- [x] Data Retention UI — `api/routes/admin.py` with GET/PUT/POST retention-policy endpoints, `housekeeping.py` reads policy from Redis config

## Phase 2.5 — Professional Tools
- [x] Volume Profile (VPVR) — `VolumeProfile.tsx` canvas overlay with POC + Value Area (70%)
- [x] Multi-Chart Layout — `MultiChartLayout.tsx` split view (1x1, 2x1, 1x2, 2x2) with independent chart instances
- [x] Strategy Backtesting — `backtesting_engine.py` (Golden Cross, RSI Reversal, MACD Crossover, BB Bounce) + `api/routes/backtesting.py` (GET strategies, POST run)

---

# Phase 3: UX & Feature Completeness

## Modern UI Design System (2026)
- [x] Create global CSS design tokens: glassmorphism vars, gradient palette, animation durations
  - **Completed:** Enhanced glass.css with semantic color tokens
    - [x] Color tokens: `--color-positive` (#10b981), `--color-negative` (#f43f5e), `--color-neutral`
    - [x] Muted color variants for backgrounds: `--color-positive-muted`, `--color-negative-muted`
    - [x] Typography scale: `--text-price` (2rem), `--text-price-secondary` (1.25rem), `--font-mono`
    - [x] Utility classes: `.text-positive`, `.text-negative`, `.bg-positive`, `.bg-negative`
    - [x] Shimmer animation for skeleton loaders
  - 📁 **Files:** `frontend/src/styles/glass.css`
- [~] Apply glassmorphism to ALL modals: `backdrop-filter: blur(16px)` + semi-transparent bg + border
  - [~] Alert trigger modal / notification toast
  - [~] Confirmation dialogs (delete watchlist, remove stock)
  - [~] Search modal (Ctrl+K)
  - [~] Settings modal
  - [~] Add stock / add alert drawer
- [x] Bento grid layout for dashboard overview cards
  - **Why:** Dashboard ต้อง glanceable — เห็น portfolio, top movers, alerts รวดเดียว
  - **Completed:** Dashboard now uses responsive CSS Grid layout (1 col mobile, 2 cols tablet, 4 cols desktop)
    - [x] Portfolio Summary card spans 2 cols on XL (with P&L, sparkline, top holdings)
    - [x] Market Status card shows SET/US market open/closed badges
    - [x] Top Movers spans full width with 6-mover grid (3 per row on XL)
    - [x] Active Alerts card spans full width at bottom
    - [x] Skeleton loading states integrated with new Skeleton component
    - [x] Responsive breakpoints: md (tablet), xl (desktop)
  - 📁 **Files:** `frontend/src/components/pages/DashboardPage.tsx`
- [ ] Fluid micro-animations (≤300ms) on hover, click, route change
  - **Steps:**
    - [ ] Add `transition: all 0.2s ease` to interactive elements globally
    - [ ] Route change: fade-in content with `opacity 0→1` over 200ms
    - [ ] Button hover: subtle scale(1.02) + shadow elevation
    - [ ] Card hover: lift shadow + border glow
  - **Acceptance:** All interactions feel smooth, no janky transitions, total animation budget ≤300ms
  - **Effort:** 2-3 hours
- [ ] Gradient accent borders on active sidebar items and timeframe buttons
  - **Steps:** CSS `border-image: linear-gradient(...)` on `.active` state
  - **Effort:** 1 hour
- [ ] Frosted glass sidebar panel (semi-transparent dark bg + blur)
  - **Steps:** `backdrop-filter: blur(16px); background: rgba(15,23,42,0.85)` on sidebar container
  - **Effort:** 1 hour
- [ ] Monochrome base — emerald (#10b981) for positive, rose (#f43f5e) for negative
  - **Steps:**
    - [ ] Define CSS custom properties: `--color-positive`, `--color-negative`
    - [ ] Replace all hardcoded green/red with CSS vars
    - [ ] Apply to: price change %, P&L, candle colors, sparklines
  - **Acceptance:** Consistent color language across entire app
  - **Effort:** 2 hours
- [ ] Subtle noise texture overlay for depth on card backgrounds
  - **Steps:** SVG noise filter as `::before` pseudo-element with low opacity (0.03-0.05)
  - **Effort:** 30 min
- [ ] Large bold typography for price, P&L key numbers
  - **Steps:** `font-size: 2rem; font-weight: 700` for primary price, `1.25rem` for secondary metrics
  - **Effort:** 1 hour
- [x] Pill-shaped badges for market status, alert type, change %
  - **Completed:** Created Badge component system with semantic variants
    - [x] Main `<Badge>` component with 5 variants: positive, negative, neutral, warning, info
    - [x] Sizes: sm, md for flexible use cases
    - [x] Convenience components: `<ChangeBadge>` (formats price %) + `<MarketStatusBadge>` (with pulse indicator)
    - [x] Integrated into Dashboard Market Status card
  - 📁 **Files:** `frontend/src/components/common/Badge.tsx` (new), `frontend/src/components/pages/DashboardPage.tsx`
- [x] Skeleton loading states (animated shimmer) replace all spinners
  - **Completed:** Created comprehensive Skeleton component system
    - [x] Main `<Skeleton>` component with variants: text, rect, circle
    - [x] Pre-built layouts: `<SkeletonCard>`, `<SkeletonChart>`, `<SkeletonSidebarItem>`
    - [x] CSS shimmer animation in glass.css with `@keyframes shimmer`
    - [x] Integrated into DashboardPage loading states
    - [x] Support for dynamic width/height props and multiple text lines
  - 📁 **Files:** `frontend/src/components/common/Skeleton.tsx` (new), `frontend/src/styles/glass.css` (shimmer keyframe), `frontend/src/components/pages/DashboardPage.tsx` (integrated)

## Chart Page
- [ ] Chart toolbar: fix timeframe buttons active state highlight
  - **Steps:** Add `bg-white/10 border-emerald-400` class to active timeframe button via state comparison
  - **Acceptance:** Clicking "1D" highlights it, clicking "1W" moves highlight — only one active at a time
  - **Effort:** 30 min
- [ ] Fix crosshair OHLCV overlay (shows correct values on hover)
  - **Steps:**
    - [ ] Subscribe to LightweightCharts `crosshairMove` event
    - [ ] Extract OHLCV from `param.seriesData` map for candlestick series
    - [ ] Display formatted values in overlay div: O: 185.20 H: 187.50 L: 184.80 C: 186.90 V: 12.3M
  - **Acceptance:** Hovering over any candle shows accurate OHLCV, overlay disappears when cursor leaves chart
  - **Trader scenario:** ดู exact high/low ของแท่งเทียนเมื่อวาน เพื่อหา support/resistance — ต้องเห็นค่า precise
  - **Effort:** 2 hours
  - 📁 **Files:** `frontend/src/components/chart/TradingChart.tsx` (subscribe event + overlay div)
  - 🔗 **Reference:** LightweightCharts API: `chart.subscribeCrosshairMove(param => { param.seriesData.get(candleSeries) })` → ได้ `{open, high, low, close}`
  - 📐 **Pattern:** ใช้ `formatters.js` สำหรับ number formatting (existing `formatPrice`, `formatVolume` functions)
- [ ] Chart comparison mode: overlay 2nd symbol as line chart
  - **Why:** เปรียบเทียบ NVDA vs AAPL performance แบบ overlay — ดู correlation
  - **Steps:**
    - [ ] Add "Compare" button in chart toolbar → opens symbol search dropdown
    - [ ] Fetch 2nd symbol OHLC data, normalize to % change from start
    - [ ] Add as `addLineSeries` on right price scale (separate axis)
    - [ ] Legend shows both symbols with toggle visibility
  - **Acceptance:** Select AAPL as comparison → line chart overlays on NVDA candles, both have price axis
  - **Effort:** 6 hours
  - 📁 **Files:** `frontend/src/components/chart/TradingChart.tsx` (add line series), `frontend/src/components/chart/ChartToolbar.tsx` (add Compare button), `frontend/src/services/stockService.js` (fetch 2nd symbol data)
  - ⚠️ **Pitfalls:** Normalize ด้วย % change (ไม่ใช่ raw price) — NVDA $180 vs AAPL $150 เทียบไม่ได้ ต้อง normalize from start, ใช้ right price scale (`priceScaleId: 'right'`) สำหรับ 2nd symbol
- [ ] Drawing tools: verify all 6 tools work (Trend, H-Line, Fib, Rect, Arrow, Pitchfork)
  - **Steps:**
    - [ ] Test each tool on NVDA 1D chart: draw → save → reload page → verify persistence
    - [ ] Fix any tool that doesn't render or save correctly
    - [ ] Verify drawings are symbol-specific (PTT.BK drawings don't show on NVDA)
  - **Acceptance:** All 6 tools draw correctly, persist across page reloads, scoped per symbol
  - **Trader scenario:** วาด trendline บน KBANK 1D chart → ปิดเว็บ → เปิดวันรุ่งขึ้นต้องเห็นเส้นเดิม
  - **Effort:** 4 hours
  - 📁 **Files:** `frontend/src/components/chart/DrawingToolbar.tsx` (tools), `frontend/src/components/chart/TradingChart.tsx` (render drawings), `backend/api/routes/drawings.py` (CRUD API), `backend/models/drawing.py` (DB model)
  - 🔗 **Reference:** `drawings.py` API มีอยู่แล้ว — GET/POST/DELETE per user per symbol, ดูว่า frontend เรียกถูก endpoint ไหม
- [ ] Drawing save/load: verify per-user per-symbol persistence via `/api/drawings`
  - **Steps:**
    - [ ] Test: create drawing → `GET /api/drawings?symbol=NVDA` returns saved drawings
    - [ ] Test: different user doesn't see other user's drawings
    - [ ] Auto-save on draw complete (not manual save button)
  - **Acceptance:** Drawings persist per-user per-symbol via API, auto-saved on creation
- [ ] Right-click context menu on chart (add alert, add note, etc.)
  - **Steps:**
    - [ ] Intercept `contextmenu` event on chart area
    - [ ] Show custom menu with: "Add Price Alert at $X", "Add Note", "Draw Horizontal Line"
    - [ ] Price pre-filled from cursor Y position
    - [ ] Menu closes on click outside or Escape
  - **Acceptance:** Right-click on chart → menu appears with price-aware options
  - **Trader scenario:** เห็น support ที่ $180 → right-click → "Add Alert at $180" → ได้ alert ทันทีไม่ต้องไปหน้า alerts
  - **Effort:** 4 hours
  - 📁 **Files:** `frontend/src/components/chart/TradingChart.tsx` (contextmenu event), `frontend/src/services/alertService.js` (create alert API call)
  - ⚠️ **Pitfalls:** ต้อง `e.preventDefault()` เพื่อ block browser default context menu, cursor Y → price ใช้ `chart.coordinateToPrice(y)` ของ LightweightCharts

## Sidebar & Watchlist
- [ ] Company names display in sidebar (names from `/api/stocks/names`)
  - **Steps:**
    - [ ] Call `/api/stocks/names` on sidebar mount with all watchlist symbols
    - [ ] Display company name below ticker in smaller gray text
    - [ ] Cache names in Zustand store to avoid re-fetching
  - **Acceptance:** Sidebar shows "NVDA" with "NVIDIA Corporation" below it
  - **Effort:** 1 hour
- [ ] Drag-and-drop reorder watchlist items
  - **Steps:**
    - [ ] Add `@dnd-kit/core` or use native HTML5 drag API
    - [ ] Persist order via `PATCH /api/watchlist/reorder` with position array
    - [ ] Visual feedback: dragging item has shadow, drop target has highlight line
  - **Acceptance:** Drag NVDA above AAPL → reload page → order persists
  - **Trader scenario:** จัดเรียง watchlist ตาม priority — หุ้นที่กำลัง monitor ใกล้ entry ไว้บนสุด
  - **Effort:** 4 hours
  - 📁 **Files:** `frontend/src/components/common/Sidebar.tsx` (drag UI), `frontend/src/services/watchlistService.js` (API), `backend/api/routes/watchlist.py` (reorder endpoint), `backend/models/watchlist.py` (add `position` column)
  - ⚠️ **Pitfalls:** `@dnd-kit/core` ดีกว่า HTML5 drag API (smoother + mobile support) แต่ต้อง `npm install` ใน Docker build
- [ ] Multiple watchlists: tabs or dropdown to switch between lists
  - **Why:** Trader มี watchlist แยก: "SET Blue Chip", "US Tech", "Potential Entry", "Holdings"
  - **Steps:**
    - [ ] Add `watchlist_group` field to watchlist model (or separate `WatchlistGroup` table)
    - [ ] UI: tabs at top of sidebar showing watchlist names
    - [ ] CRUD: create/rename/delete watchlist group
    - [ ] Default groups: "Favorites", "SET", "US"
  - **Acceptance:** Create 3 watchlists, switch between them, each has different symbols
  - **Trader scenario:** แยก watchlist "SET Entry" กับ "US Holdings" — เปิดดูแต่ละกลุ่มตามช่วงเวลาตลาด
  - **Effort:** 6 hours
  - 📁 **Files:** `backend/models/watchlist.py` (add group model), `backend/api/routes/watchlist.py` (CRUD groups), `frontend/src/components/common/Sidebar.tsx` (tabs UI), `frontend/src/services/watchlistService.js` (API calls)
  - 📐 **Pattern:** ดู `watchlist.py` model + route เป็นฐาน — extend ด้วย group_id field, ใหม่ต้อง register route ใน `api/routes/__init__.py`
- [ ] GUEST_SYMBOLS: reorder to put US stocks first, add AAPL, TSLA
  - **Steps:** Edit `GUEST_SYMBOLS` array in `Sidebar.tsx`: `['NVDA', 'AAPL', 'TSLA', 'MSFT', 'PTT.BK', 'KBANK.BK']`
  - **Effort:** 15 min
- [ ] Watchlist import: paste CSV of tickers
  - **Steps:**
    - [ ] Add "Import" button in sidebar → opens modal with textarea
    - [ ] Parse comma/newline separated tickers: "NVDA, AAPL, PTT.BK"
    - [ ] Validate each symbol exists via `/api/stocks/search`
    - [ ] Add valid symbols to current watchlist, show errors for invalid ones
  - **Acceptance:** Paste "NVDA,AAPL,FAKE123" → NVDA & AAPL added, "FAKE123 not found" error shown
  - **Effort:** 2 hours

## Portfolio Page
- [ ] Transaction form: add buy/sell with symbol, qty, price, fee, date
  - **Steps:**
    - [ ] Create `TransactionForm` component with fields: type (BUY/SELL), symbol (autocomplete), quantity, price, fee, date
    - [ ] POST to `/api/portfolio/transactions` → inserts into `transactions` table
    - [ ] Validate: qty > 0, price > 0, can't sell more than held
    - [ ] After submit: recalculate holdings + refresh portfolio view
  - **Acceptance:** Add BUY NVDA 10 shares @ $185 → appears in holdings, avg cost correct
  - **Trader scenario:** ซื้อ NVDA 10 หุ้น @ $185 + ค่า fee $1.50 → บันทึกเข้าระบบ → เห็น cost basis ถูกต้อง
  - **Effort:** 4 hours
  - 📁 **Files:** `frontend/src/components/pages/PortfolioPage.tsx` (form UI), `frontend/src/services/portfolioService.js` (API), `backend/api/routes/portfolio.py` (POST endpoint), `backend/models/portfolio.py` (Transaction model)
  - 🔗 **Reference:** `portfolioService.js` + `portfolio.py` มีอยู่แล้ว — ดู existing CRUD pattern
  - ⚠️ **Pitfalls:** Validate server-side: ห้าม SELL มากกว่าที่ถืออยู่, fee ต้อง optional (default 0), date ต้อง ≤ today
- [ ] Holdings table: symbol, avg cost, current price, qty, value, P&L %
  - **Steps:**
    - [ ] Calculate avg cost = total_cost / total_qty per symbol (FIFO or avg)
    - [ ] Fetch current price from Redis cache
    - [ ] P&L % = (current - avg_cost) / avg_cost × 100
    - [ ] Color: green if positive, red if negative
    - [ ] Sortable columns: click header to sort by P&L, value, symbol
  - **Acceptance:** Holdings table shows accurate P&L matching manual calculation
  - **Trader scenario:** เปิดมาเห็น NVDA +12.5%, KBANK -3.2% ทันที — รู้ว่าตัวไหนกำไร ตัวไหนขาดทุน
  - **Effort:** 4 hours
  - 📁 **Files:** `frontend/src/components/pages/PortfolioPage.tsx` (table), `backend/api/routes/portfolio.py` (holdings endpoint), `backend/api/routes/portfolio_performance.py` (P&L calc)
  - 🔗 **Reference:** ดู `portfolio_performance.py` — มี P&L calculation logic อยู่แล้ว
  - ⚠️ **Pitfalls:** Current price ดึงจาก Redis cache (fast) ไม่ใช่ Yahoo (slow) — ใช้ `cache:quote:{symbol}` key, SET + US ใช้คนละ currency — ต้อง separate display
- [ ] Portfolio summary card: total value, total cost, unrealized P&L
  - **Steps:**
    - [ ] Sum all holdings: total_value = Σ(qty × current_price), total_cost = Σ(qty × avg_cost)
    - [ ] Display: "Portfolio: ฿1,250,000 (+฿125,000 / +10.0%)"
    - [ ] Separate display for SET (THB) and US (USD) portfolios
  - **Acceptance:** Summary card at top of portfolio page shows aggregate P&L, currency-separated
  - **Effort:** 2 hours
- [ ] Sector allocation pie chart
  - **Steps:**
    - [ ] Map each holding to sector (from fundamentals data or manual mapping)
    - [ ] Use Recharts `PieChart` component with sector labels + %
    - [ ] Top 5 sectors labeled, rest grouped as "Other"
  - **Acceptance:** Pie chart shows "Technology 45%, Financials 20%, Energy 15%, ..." based on holdings
  - **Effort:** 3 hours
- [ ] Equity curve (P&L over time) sparkline/chart
  - **Why:** ดู performance ของ portfolio เทียบกับ benchmark (SET50, S&P500)
  - **Steps:**
    - [ ] Calculate daily portfolio value from transactions + historical prices
    - [ ] Store snapshots in `portfolio_snapshots` table (Celery daily job)
    - [ ] Render as line chart using Recharts `AreaChart`
    - [ ] Optional: overlay SET50/SPY benchmark line
  - **Acceptance:** Equity curve shows portfolio growth over 30 days, benchmark comparison toggle
  - **Effort:** 8 hours (most complex portfolio feature)
  - 📁 **Files:** `backend/workers/` (new daily snapshot task), `backend/models/portfolio.py` (add PortfolioSnapshot model), `frontend/src/components/pages/PortfolioPage.tsx` (chart)
  - ⚠️ **Pitfalls:** Daily snapshot ต้อง run หลังตลาดปิด (16:30 ICT for SET, 04:00 ICT for US), ใช้ Celery Beat schedule, chart ใช้ Recharts `AreaChart` (ไม่ใช่ LightweightCharts — ง่ายกว่าสำหรับ simple line chart)
- [ ] Export holdings as CSV
  - **Steps:**
    - [ ] "Export" button → generates CSV: Symbol, Qty, Avg Cost, Current Price, Value, P&L, P&L%
    - [ ] Use `Blob` + `URL.createObjectURL` for client-side download
  - **Acceptance:** Click Export → CSV downloaded with all holdings data
  - **Effort:** 1 hour

## Alerts Page
- [ ] Create alert form: symbol + type (PRICE_ABOVE, PRICE_BELOW, RSI, MA cross)
  - **Steps:**
    - [ ] Form fields: symbol (autocomplete), alert_type (dropdown), threshold value, note (optional)
    - [ ] Alert types: PRICE_ABOVE, PRICE_BELOW, RSI_ABOVE, RSI_BELOW, MA_CROSS_UP, MA_CROSS_DOWN
    - [ ] POST to `/api/alerts` → Celery `alert_checker` evaluates every 60s
    - [ ] Validation: threshold must be positive number, symbol must exist
  - **Acceptance:** Create "NVDA > $200" alert → shows in active alerts list → triggers when price crosses
  - **Trader scenario:** ตั้ง alert "KBANK > 165" — ถ้า breakout resistance จะได้รู้ทันที ไม่พลาด entry
  - **Effort:** 3 hours
  - 📁 **Files:** `frontend/src/components/pages/AlertsPage.tsx` (form UI), `frontend/src/services/alertService.js` (API), `backend/api/routes/alerts.py` (POST endpoint), `backend/models/alert.py` (Alert model), `backend/workers/alert_checker.py` (evaluation logic)
  - 🔗 **Reference:** `alertService.js` + `alerts.py` + `alert_checker.py` ทั้งหมดมีอยู่แล้ว — ดู flow เดิม: create alert → Celery checks every 60s → trigger → WebSocket notification
  - 📐 **Pattern:** Alert types ใน `alert.py` model — extend enum: เพิ่ม RSI_ABOVE, RSI_BELOW, MA_CROSS_UP, MA_CROSS_DOWN
- [ ] Alerts list: show status (active/triggered), edit/delete
  - **Steps:**
    - [ ] Table: symbol, type, threshold, status (🟢 Active / 🔴 Triggered / ⏸ Paused), created date
    - [ ] Edit: click row → inline edit threshold value
    - [ ] Delete: swipe or delete button with confirmation
    - [ ] Re-arm: triggered alerts can be reset to active
  - **Acceptance:** Alerts page shows all alerts, can edit threshold, delete, and re-arm triggered alerts
  - **Effort:** 3 hours
- [ ] Triggered alerts: notification badge in navbar
  - **Steps:**
    - [ ] WebSocket delivers `alert_triggered` event → increment badge counter in Zustand
    - [ ] Red badge with count on bell icon in navbar
    - [ ] Click badge → navigates to alerts page filtered by triggered
    - [ ] Toast notification on trigger with sound (optional, mutable)
  - **Acceptance:** Alert triggers → red badge "1" appears in navbar within 60s of price crossing threshold
  - **Trader scenario:** กำลังดู chart อยู่ → เห็น badge ขึ้น → รู้ว่า NVDA ทะลุ $200 แล้ว → ตัดสินใจ action
  - **Effort:** 3 hours
  - 📁 **Files:** `frontend/src/components/common/Navbar.tsx` (badge UI), `frontend/src/hooks/useWebSocket.ts` (receive event), `frontend/src/store/appStore.js` (badge count state), `backend/main.py` (`broadcast_all` sends alert_triggered)
  - 🔗 **Reference:** WebSocket alert_triggered event ส่งอยู่แล้วจาก `main.py` → ดู `useWebSocket.ts` ว่า handle message type ยังไง
- [ ] Telegram alert delivery: store user chat_id, send on trigger
  - **Why:** ไม่ได้เปิดเว็บตลอด — Telegram notification เข้ามือถือทันที
  - **Steps:**
    - [ ] Settings page: "Connect Telegram" → show bot link + instruction to send `/start`
    - [ ] Bot webhook receives chat_id → store in `users.telegram_chat_id`
    - [ ] On alert trigger: `alert_checker` calls Telegram Bot API `sendMessage`
    - [ ] Message format: "🚨 NVDA hit $200.50 (Alert: PRICE_ABOVE $200)"
  - **Acceptance:** Alert triggers → Telegram message received within 2 min
  - **Depends on:** `TELEGRAM_BOT_TOKEN` env var configured
  - **Effort:** 4 hours
  - 📁 **Files:** `backend/workers/alert_checker.py` (send on trigger), `backend/models/user.py` (add telegram_chat_id), `backend/core/config.py` (TELEGRAM_BOT_TOKEN)
  - ⚠️ **Pitfalls:** Telegram Bot API ใช้ httpx POST `https://api.telegram.org/bot{token}/sendMessage` — simple HTTP call, ไม่ต้อง install library เพิ่ม, ใช้ `httpx.AsyncClient` ที่มีอยู่แล้ว

## Screener Page
- [ ] Screener filter UI: PE, RSI, price range, volume, market
  - **Steps:**
    - [ ] Filter panel with dropdowns/sliders: Market (SET/US/All), PE range (0-50+), RSI range (0-100), Price range, Min volume
    - [ ] Backend `/api/screener` endpoint with query params for all filters
    - [ ] Query joins `stocks` + latest `stock_fundamentals` + computed RSI
    - [ ] Debounce filter changes (500ms) before API call
  - **Acceptance:** Filter PE < 15, RSI < 30, Market = SET → returns matching SET stocks
  - **Trader scenario:** หา SET stocks ที่ PE < 15 และ RSI oversold — สำหรับ value + technical entry
  - **Effort:** 6 hours
  - 📁 **Files:** `frontend/src/components/pages/ScreenerPage.tsx` (UI), `backend/api/routes/screener.py` (endpoint มีอยู่แล้ว), `backend/models/stock.py` (fundamentals), `backend/models/schemas.py` (Pydantic)
  - 🔗 **Reference:** `screener.py` route มีอยู่แล้ว — ดู current implementation แล้ว extend ด้วย query params
  - ⚠️ **Pitfalls:** RSI ต้อง compute real-time จาก OHLCV data (ไม่ store ใน DB) — อาจ slow ถ้า compute for all stocks, ใช้ pre-computed RSI cache ใน Redis
- [ ] Results table: sortable columns, click to chart
  - **Steps:**
    - [ ] Columns: Symbol, Name, Price, Change%, PE, RSI, Volume, Market Cap
    - [ ] Click column header → sort ASC/DESC
    - [ ] Click row → navigate to chart page with that symbol
    - [ ] Highlight rows where RSI < 30 (green) or RSI > 70 (red)
  - **Acceptance:** Table renders ≤100 results, sortable, click navigates to chart
  - **Effort:** 3 hours
- [ ] Save preset filters per user
  - **Steps:**
    - [ ] "Save Filter" button → name the preset → store in `screener_presets` table
    - [ ] Dropdown to load saved presets
    - [ ] Default presets seeded for new users
  - **Acceptance:** Save "Oversold SET" preset → reload page → load preset → same filters applied
  - **Effort:** 3 hours
- [ ] Export results as CSV
  - **Steps:** "Export" button → client-side CSV download of current results
  - **Effort:** 1 hour
- [ ] Preset screener templates: "Oversold SET", "High Volume US", "Dividend Thai"
  - **Steps:**
    - [ ] "Oversold SET": Market=SET, RSI<30, Volume>1M
    - [ ] "High Volume US": Market=US, Volume>10M, Change%>2%
    - [ ] "Dividend Thai": Market=SET, DivYield>3%, PE<20
    - [ ] Seed as system presets visible to all users
  - **Acceptance:** 3 preset buttons at top of screener, clicking loads filters instantly
  - **Effort:** 1 hour

## News Page
- [ ] News list: title, source, published time, thumbnail
  - **Steps:**
    - [ ] Use Finnhub `/company-news` endpoint (free tier) for US stocks
    - [ ] Use RSS feed from SET/Bangkokpost for Thai market news
    - [ ] Display as card list: thumbnail (if available), title, source, time ago
    - [ ] Infinite scroll or paginate (20 per page)
  - **Acceptance:** News page shows ≥10 recent articles, sorted by date
  - **Effort:** 4 hours
- [ ] Filter by: all markets, SET, US, specific symbol
  - **Steps:**
    - [ ] Tab bar: All | SET | US | [Symbol search]
    - [ ] Symbol filter: type symbol → show only news mentioning that stock
    - [ ] Cache news per symbol in Redis (TTL: 15 min)
  - **Acceptance:** Click "US" tab → only US market news shown, search "NVDA" → NVDA news only
  - **Effort:** 2 hours
- [ ] AI sentiment badge (Positive/Neutral/Negative via Ollama)
  - **Why:** อ่านข่าวเยอะไม่ไหว — ให้ AI สรุป sentiment แทน
  - **Steps:**
    - [ ] On news fetch: send title + snippet to Ollama with prompt "Classify sentiment: Positive/Neutral/Negative"
    - [ ] Cache sentiment result in Redis per article URL
    - [ ] Display colored badge: 🟢 Positive, ⚪ Neutral, 🔴 Negative
    - [ ] Batch process in Celery to avoid blocking UI
  - **Acceptance:** Each news article has sentiment badge, ≥80% accuracy on manual review
  - **Trader scenario:** scan ข่าวเร็ว ๆ — เห็น 🔴 ติดกัน 3 อัน → ระวัง sentiment ตลาดลบ
  - **Effort:** 4 hours
  - 📁 **Files:** `backend/api/routes/ai_chat.py` (ดู Ollama call pattern), `backend/workers/` (new Celery task), `backend/core/config.py` (OLLAMA_URL)
  - 🔗 **Reference:** ดู `ai_chat.py` สำหรับ Ollama HTTP call pattern — ใช้ `httpx.AsyncClient` POST to `{OLLAMA_URL}/api/generate`
  - ⚠️ **Pitfalls:** Ollama response time ช้า (2-10s per article) — ต้อง batch ใน Celery ไม่ใช่ sync, cache result per article URL ใน Redis
- [ ] Click article → open in new tab
  - **Steps:** `<a href={url} target="_blank" rel="noopener noreferrer">` on article card
  - **Effort:** 15 min
- [ ] Watchlist-filtered news: only show news for stocks in watchlist
  - **Steps:**
    - [ ] Fetch watchlist symbols → batch query news for all symbols
    - [ ] "My Watchlist" tab in news filters
    - [ ] Highlight news for stocks currently in portfolio (bold or badge)
  - **Acceptance:** "My Watchlist" tab shows news only for watchlist symbols
  - **Trader scenario:** เปิด news tab "My Watchlist" → เห็นข่าว NVDA earnings beat ก่อนคนอื่น (ใน watchlist ของเรา)
  - **Effort:** 2 hours

## AI Chat Panel
- [ ] Stock context injection: current symbol + price in system prompt
  - **Steps:**
    - [ ] Inject `{symbol: "NVDA", price: 186.50, change: +2.3%, PE: 35, RSI: 62}` into system prompt
    - [ ] Update context when user switches symbol
    - [ ] Backend `ai_chat.py` prepends context to user message before sending to Ollama
  - **Acceptance:** Ask "should I buy?" → AI responds referencing NVDA's current price and RSI
  - **Trader scenario:** เปิด NVDA chart → ถาม AI "RSI สูงไปไหม" → AI ตอบโดยอ้างอิง RSI จริง ไม่ใช่ hallucinate
  - **Effort:** 2 hours
  - 📁 **Files:** `backend/api/routes/ai_chat.py` (inject context into system prompt), `frontend/src/components/common/AIChatPanel.tsx` (send current symbol), `frontend/src/store/appStore.js` (selectedStock state)
  - 🔗 **Reference:** `ai_chat.py` มี SSE streaming อยู่แล้ว — แค่เพิ่ม context object ใน system prompt, ดู existing `aiService.js` สำหรับ frontend call pattern
- [ ] "Analyze this chart" button → pass OHLCV data to AI
  - **Steps:**
    - [ ] Button in AI chat panel: "📊 Analyze Chart"
    - [ ] Sends last 30 candles OHLCV as structured data to AI
    - [ ] Prompt: "Analyze this price action. Identify trend, support/resistance, and potential entry/exit."
    - [ ] Stream response via SSE as usual
  - **Acceptance:** Click "Analyze Chart" → AI identifies trend direction, key levels, pattern if present
  - **Effort:** 3 hours
- [ ] Chat history: persist per session (localStorage)
  - **Steps:**
    - [ ] Store messages array in `localStorage` key `ai_chat_history_{symbol}`
    - [ ] Load on mount, save on each new message
    - [ ] "Clear Chat" button to reset
    - [ ] Max 50 messages per symbol (FIFO eviction)
  - **Acceptance:** Close tab → reopen → previous chat messages still visible
  - **Effort:** 1 hour
- [ ] Suggested questions: auto-populated from current symbol context
  - **Steps:**
    - [ ] Show 3-4 pill buttons below chat input: "PE ratio?", "Support levels?", "Compare to sector?"
    - [ ] Questions dynamically generated based on symbol type (SET vs US) and available data
    - [ ] Click pill → auto-fills chat input and sends
  - **Acceptance:** NVDA shows "What's NVDA's PE?", PTT.BK shows "XD date เมื่อไหร่?"
  - **Effort:** 2 hours
- [ ] Model selector: show available Ollama models
  - **Steps:**
    - [ ] Call `GET /api/ai/models` (proxy to Ollama `/api/tags`)
    - [ ] Dropdown in chat panel header showing available models
    - [ ] Default: llama3.2, allow switching to other installed models
  - **Acceptance:** Dropdown shows installed Ollama models, switching model changes AI behavior
  - **Effort:** 1 hour

## Stock Notes
- [x] Notes panel in BottomPanel tab
  - **Completed:** Notes feature fully implemented in BottomPanel
    - [x] Notes tab integrated alongside News, Portfolio, Fundamentals tabs
    - [x] Fetch notes via `notesService.get(symbol)` endpoint
    - [x] Auto-save with 1.5s debounce → `PUT /api/notes/{symbol}`
    - [x] Save status indicator: "Saving..." → "✓ บันทึกแล้ว" (Thai locale)
    - [x] Per-stock note persistence with markdown support in textarea
    - [x] Auth-gated: requires login to create/edit notes
  - 📁 **Files:** `frontend/src/components/chart/BottomPanel.tsx`, `frontend/src/services/notesService.js`
  - **Already Working:** Notes backend API at `/api/notes/{symbol}` with GET/PUT/DELETE methods
  - 📁 **Files:** `frontend/src/components/chart/BottomPanel.tsx` (add Notes tab), `frontend/src/services/notesService.js` (API — มีอยู่แล้ว), `backend/api/routes/notes.py` (CRUD — มีอยู่แล้ว), `backend/models/note.py` (model — มีอยู่แล้ว)
  - 🔗 **Reference:** Backend notes API + model ครบแล้ว! แค่ต้อง wire frontend — ดู `notesService.js` สำหรับ existing API calls
  - 📐 **Pattern:** Debounce pattern: `useEffect(() => { const timer = setTimeout(() => saveFn(), 1000); return () => clearTimeout(timer); }, [content])`
- [ ] Display last edit time
  - **Steps:** Show "Last edited: 2 hours ago" below textarea using `updated_at` from API
  - **Effort:** 15 min

## Settings
- [ ] Settings modal: timezone, default symbol, default timeframe
  - **Steps:**
    - [ ] Create `SettingsModal` component with form sections
    - [ ] Timezone: dropdown with common zones (ICT, UTC, EST, JST)
    - [ ] Default symbol: autocomplete input → stored in user preferences
    - [ ] Default timeframe: radio buttons (1D, 1W, 1M)
    - [ ] Persist via `PUT /api/user/settings`
  - **Acceptance:** Change default symbol to AAPL → refresh → chart loads AAPL
  - **Effort:** 3 hours
  - 📁 **Files:** `frontend/src/components/modals/SettingsModal.tsx` (UI — มีอยู่แล้ว ดู current content), `backend/models/user.py` (add preferences JSON field), `frontend/src/store/appStore.js` (load default from user prefs)
- [ ] Theme toggle (already works)
  - **Steps:** Verify dark/light toggle persists across sessions
  - **Effort:** 30 min (verification only)
- [ ] API key management (Finnhub, Telegram bot token)
  - **Steps:**
    - [ ] Encrypted storage: API keys stored encrypted in DB (not plaintext)
    - [ ] Settings form: masked input fields showing `****` with "Reveal" button
    - [ ] Validation: test Finnhub key by calling `/quote?symbol=AAPL` on save
  - **Acceptance:** Save Finnhub key → key stored encrypted → API calls use new key
  - **Effort:** 3 hours
- [ ] Account: display name (Google OAuth — no password change needed)
  - **Steps:**
    - [ ] Display: Google profile name + email (read-only from OAuth)
    - [ ] Optional: custom display name override
    - [ ] Show: account creation date, last login
  - **Acceptance:** Settings shows Google name + email, optional display name editable
  - **Note:** No password management — auth is Google OAuth only (per project rules)
  - **Effort:** 1 hour

---

# Phase 4: Advanced Intelligence

## Backtesting
- [ ] Strategy builder: define rules (IF RSI < 30 THEN BUY)
  - **Why:** Trader ต้อง validate strategy ก่อนเอาเงินจริงไปเสี่ยง
  - **Steps:**
    - [ ] UI: drag-and-drop or form-based rule builder
    - [ ] Conditions: price crosses MA, RSI above/below threshold, MACD cross, volume spike
    - [ ] Actions: BUY, SELL, position size (% of capital or fixed qty)
    - [ ] Store strategy as JSON in `backtest_strategies` table
  - **Acceptance:** Create "Buy when RSI < 30 and price > MA50, Sell when RSI > 70" → strategy saved
  - **Trader scenario:** มี strategy ในหัว "ซื้อตอน RSI < 30 + price above MA50" → อยากรู้ว่า backtest ได้ผลจริงไหม
  - **Effort:** 8 hours
  - 📁 **Files:** สร้าง `frontend/src/components/pages/BacktestPage.tsx` (new page), สร้าง `backend/api/routes/backtest.py` (new route), register ใน `api/routes/__init__.py`
  - 📐 **Pattern:** Strategy JSON format: `{conditions: [{indicator: "RSI", operator: "<", value: 30}], action: "BUY", position_size: "10%"}`
  - ⚠️ **Pitfalls:** อย่า build UI ที่ซับซ้อนเกินไป — เริ่มจาก form-based (dropdown + input) ก่อน, drag-and-drop เพิ่มทีหลัง
- [ ] Backtest engine: run strategy on historical OHLCV
  - **Steps:**
    - [ ] Python backtest engine in `services/backtest_service.py`
    - [ ] Input: strategy JSON + symbol + date range + initial capital
    - [ ] Iterate through OHLCV candles, evaluate conditions, simulate trades
    - [ ] Track: entry/exit prices, position size, cash, equity per day
    - [ ] Run as Celery task (can take 10-30s for large datasets)
  - **Acceptance:** Backtest NVDA 1Y with RSI strategy → returns trade list + performance metrics
  - **Effort:** 12 hours
  - 📁 **Files:** สร้าง `backend/services/backtest_service.py` (new), `backend/workers/celery_app.py` (register as async task), `backend/models/ohlcv.py` (query historical data)
  - 🔗 **Reference:** ดู `stock_service.py` → `get_stock_history()` สำหรับ OHLCV query pattern
  - ⚠️ **Pitfalls:** Backtest อาจใช้เวลานาน (10-30s) — ต้อง run เป็น Celery task + return task_id → frontend polls for result, ห้าม run sync ใน API route
- [ ] Results: Sharpe ratio, max drawdown, win rate, equity curve
  - **Steps:**
    - [ ] Calculate: total return, CAGR, Sharpe ratio, Sortino ratio, max drawdown, win rate, profit factor
    - [ ] Display as summary cards + equity curve chart
    - [ ] Trade list: date, type, price, P&L per trade
    - [ ] Drawdown chart: show underwater equity periods
  - **Acceptance:** Results page shows all metrics + interactive equity curve
  - **Effort:** 6 hours
- [ ] Compare strategies side-by-side
  - **Steps:**
    - [ ] Run 2+ strategies on same symbol/period → overlay equity curves
    - [ ] Comparison table: metrics side-by-side
  - **Acceptance:** Compare "RSI Mean Reversion" vs "MACD Trend Follow" → see which performs better
  - **Effort:** 4 hours

## AI Features
- [ ] Sentiment analysis on news articles (Ollama local)
  - **Steps:**
    - [ ] Celery task: process new articles batch → classify via Ollama
    - [ ] Store result in `news_sentiment` table: article_url, sentiment, confidence, processed_at
    - [ ] Aggregate: daily sentiment score per symbol (avg of article sentiments)
  - **Acceptance:** ≥80% accuracy on manually verified sample of 20 articles
  - **Effort:** 4 hours
- [ ] Chart pattern auto-detection (Head & Shoulders, Cup & Handle)
  - **Why:** ตา trader จับ pattern ได้ แต่ไม่ได้จ้องจอตลอด — ให้ AI หาแทน
  - **Steps:**
    - [ ] Implement pattern detection in Python: pivot point detection → pattern matching
    - [ ] Patterns: Double Top/Bottom, Head & Shoulders, Cup & Handle, Triangle, Wedge
    - [ ] Send OHLCV data to detection function → return pattern type + key points
    - [ ] Draw detected pattern on chart as highlighted region with label
  - **Acceptance:** Feed known H&S pattern data → correctly identifies it, draws neckline
  - **Trader scenario:** เปิด chart แล้วระบบ highlight "Double Bottom detected at $175-180 zone" → เห็นโอกาส entry
  - **Effort:** 16 hours (complex algorithm + UI)
  - 📁 **Files:** สร้าง `backend/services/pattern_detector.py` (new), `frontend/src/components/chart/TradingChart.tsx` (draw highlights)
  - ⚠️ **Pitfalls:** Pattern detection เป็น advanced topic — เริ่มจาก pivot point detection (local min/max) ก่อน แล้วค่อย match patterns, อาจใช้ library `ta-lib` หรือ implement custom, ระวัง false positive — ควร require minimum confidence threshold
- [ ] Support/Resistance level auto-draw
  - **Steps:**
    - [ ] Algorithm: find price levels where price touched ≥3 times (within 0.5% tolerance)
    - [ ] Draw horizontal lines at S/R levels with strength indicator (more touches = stronger)
    - [ ] Toggle on/off in indicator toolbar
  - **Acceptance:** NVDA 1D chart shows 2-4 horizontal S/R lines at historically significant levels
  - **Effort:** 6 hours
  - 📁 **Files:** สร้าง `backend/services/sr_detector.py` (new) หรือ เพิ่มใน `pattern_detector.py`, `frontend/src/components/chart/TradingChart.tsx` (draw horizontal lines)
  - 📐 **Pattern:** Algorithm: scan OHLCV → find price levels where high/low touched ≥3 times within 0.5% band → sort by touch count → return top 4-5 levels
- [ ] Portfolio review: AI commentary on holdings
  - **Steps:**
    - [ ] "Review Portfolio" button → sends all holdings + current metrics to Ollama
    - [ ] Prompt: analyze concentration risk, sector exposure, P&L outliers, suggestions
    - [ ] Stream response in AI chat panel
  - **Acceptance:** AI identifies "portfolio heavy in tech (65%), KBANK is only Thai stock, consider diversifying"
  - **Effort:** 3 hours
- [ ] Risk scoring per stock (volatility + beta)
  - **Steps:**
    - [ ] Calculate: 30-day historical volatility, beta vs market (SET50 for .BK, SPY for US)
    - [ ] Risk score 1-10: combine volatility + beta + drawdown metrics
    - [ ] Display as badge in sidebar + detail in RightPanel
  - **Acceptance:** TSLA shows risk 8/10 (high volatility), KBANK shows 4/10 (low volatility)
  - **Effort:** 4 hours

## Advanced Alerts
- [ ] MACD signal cross alert
  - **Steps:** Add `MACD_CROSS` type in `alert_checker` → evaluate MACD line crossing signal line
  - **Acceptance:** Alert triggers when MACD crosses above signal line (bullish) or below (bearish)
  - **Effort:** 2 hours
- [ ] Golden/Death Cross alert (MA50 × MA200)
  - **Steps:** Add `GOLDEN_CROSS` / `DEATH_CROSS` type → evaluate MA50 vs MA200 crossover
  - **Acceptance:** Golden Cross alert on NVDA triggers when MA50 crosses above MA200
  - **Trader scenario:** Golden Cross = strong bullish signal → ต้องรู้ทันที เพราะเกิดไม่บ่อย
  - **Effort:** 2 hours
- [ ] Volume spike alert (3× average)
  - **Steps:** Add `VOLUME_SPIKE` type → compare current volume vs 20-day average × multiplier
  - **Acceptance:** Alert fires when NVDA volume exceeds 3× its 20-day average
  - **Trader scenario:** Volume spike = institutional activity → ต้องเช็คว่าเกิดอะไรขึ้น
  - **Effort:** 2 hours
- [ ] Fibonacci retracement level touch alert
  - **Steps:**
    - [ ] User draws Fib levels on chart → option to "Set Alert" on each level
    - [ ] Backend stores Fib high/low + target level (23.6%, 38.2%, 50%, 61.8%)
    - [ ] Alert checker evaluates price vs Fib level
  - **Acceptance:** Draw Fib on NVDA, set alert at 61.8% → triggers when price touches that level
  - **Effort:** 4 hours
- [ ] Email notification channel (SMTP)
  - **Steps:**
    - [ ] Add SMTP config in settings (host, port, username, password)
    - [ ] User settings: notification preference (Telegram / Email / Both)
    - [ ] On alert trigger: send email via `aiosmtplib`
    - [ ] Email template: HTML with stock info, chart snapshot link
  - **Acceptance:** Alert triggers → email received within 2 min with formatted stock info
  - **Effort:** 4 hours

---

# Phase 5: Operations & Scale

## Admin Dashboard
- [ ] User list: email, role, last login, created date
  - **Steps:**
    - [ ] Admin-only route `/admin` with role guard (redirect non-admins)
    - [ ] Table: email, display_name, role, last_login, created_at, active alerts count
    - [ ] Search/filter by email
  - **Acceptance:** Admin sees all registered users with their activity metadata
  - **Effort:** 3 hours
- [ ] Promote/demote user role (guest → user → admin)
  - **Steps:**
    - [ ] Dropdown in user row: Guest / User / Admin
    - [ ] `PATCH /api/admin/users/{id}/role` with role validation
    - [ ] Prevent self-demotion (can't remove own admin)
  - **Acceptance:** Change user from Guest to User → user gains full feature access
  - **Effort:** 2 hours
- [ ] System metrics: Redis memory, DB size, Celery queue depth
  - **Steps:**
    - [ ] Redis: `INFO memory` → used_memory, connected_clients, keyspace_hits
    - [ ] DB: `pg_database_size('stockviz_db')`, row counts for key tables
    - [ ] Celery: `inspect().active()` → queue depth, active tasks
    - [ ] Display as metric cards with sparklines (24h trend)
  - **Acceptance:** Admin dashboard shows live Redis/DB/Celery metrics, auto-refreshes every 30s
  - **Effort:** 4 hours
- [ ] API usage stats: top endpoints, error rates
  - **Steps:**
    - [ ] Add middleware to log request: endpoint, status_code, response_time, user_id
    - [ ] Store in `api_logs` table (or Redis with 24h TTL for lightweight option)
    - [ ] Admin dashboard: bar chart of top 10 endpoints, error rate %, avg response time
  - **Acceptance:** Admin sees "/api/stocks/history — 1,200 calls/day, avg 120ms, 2% error rate"
  - **Effort:** 6 hours

## Database & Migrations
- [ ] Add Alembic for proper schema versioning
  - **Why:** Currently using `create_all()` — no way to migrate existing data when schema changes
  - **Steps:**
    - [ ] `pip install alembic` in backend container
    - [ ] `alembic init migrations` → configure `env.py` with async SQLAlchemy
    - [ ] `alembic revision --autogenerate -m "initial"` → baseline migration
    - [ ] Add `alembic upgrade head` to Docker entrypoint
  - **Acceptance:** `alembic upgrade head` runs on container start, `alembic history` shows migration chain
  - **Effort:** 3 hours
  - 📁 **Files:** `backend/core/database.py` (SQLAlchemy engine config — ใช้ same connection), `backend/models/__init__.py` (import all models for autogenerate), `docker-compose.dev.yml` (add alembic command to entrypoint)
  - ⚠️ **Pitfalls:** Async SQLAlchemy ต้อง configure `env.py` ด้วย `run_async()` — ดู alembic async migration docs, ต้อง import ALL models ใน `env.py` target_metadata ไม่งั้น autogenerate จะ miss tables
- [ ] Migration: add `avg_volume` column to `StockFundamentals` (already in Pydantic, not DB)
  - **Steps:** `alembic revision -m "add avg_volume"` → `ALTER TABLE stock_fundamentals ADD COLUMN avg_volume BIGINT`
  - **Depends on:** Alembic setup
  - **Effort:** 30 min
- [ ] Migration: `stock_notes` table (`note.py` model created, no migration yet)
  - **Steps:** `alembic revision -m "add stock_notes"` → create table: id, user_id, symbol, content, created_at, updated_at
  - **Depends on:** Alembic setup
  - **Effort:** 30 min
- [ ] TimescaleDB continuous aggregates: verify compression running daily
  - **Steps:**
    - [ ] Check `timescaledb_information.compression_settings` for `stock_price_1m` hypertable
    - [ ] Verify compression policy: compress chunks older than 7 days
    - [ ] Check `timescaledb_information.jobs` for scheduled compression job
    - [ ] Test: query 30-day range → response time <500ms
  - **Acceptance:** Compression active, 30-day query returns in <500ms, storage efficient
  - **Effort:** 2 hours

## CI/CD & Testing
- [ ] GitHub Actions: run pytest on every push
  - **Steps:**
    - [ ] Create `.github/workflows/test.yml` with: checkout, setup Python, install deps, run pytest
    - [ ] Use Docker Compose for test DB (PostgreSQL + TimescaleDB + Redis)
    - [ ] Cache pip dependencies between runs
  - **Acceptance:** Push to any branch → CI runs tests → green check or red X on PR
  - **Effort:** 3 hours
  - 📁 **Files:** สร้าง `.github/workflows/test.yml` (new), `backend/requirements.txt` (deps for CI), `docker-compose.dev.yml` (reference for test services)
  - 📐 **Pattern:** CI workflow: checkout → setup-python → pip install → docker-compose up db redis → pytest → docker-compose down
- [ ] GitHub Actions: build frontend on push, cache node_modules
  - **Steps:**
    - [ ] Add frontend build step to CI workflow
    - [ ] Cache `node_modules` and `.vinxi` build cache
    - [ ] Fail if build has TypeScript errors
  - **Acceptance:** Frontend build completes in CI without errors
  - **Effort:** 2 hours
- [x] Backend test coverage: 101 new unit/service tests added (2026-03-04)
  - [x] `test_symbol_utils.py` — 39 tests: normalize, detect_market, partition, deduplicate
  - [x] `test_cache_keys.py` — 13 tests: all key builders, consistency, no collisions
  - [x] `test_screener_indicators.py` — 35 tests: RSI, MACD, SMA, signals, filters
  - [x] `test_services.py` — 14 tests: stock_service facade, cache key usage, re-exports
  - [x] API smoke test: 10 endpoints verified via host gateway
  - [x] Frontend static analysis: 0 memory leaks, 0 SSR issues, 0 circular imports
  - [ ] Remaining: increase to ≥70% overall coverage (need auth, websocket, celery tests)
  - **Effort remaining:** 6-8 hours
- [ ] Playwright e2e: chart loads, watchlist add, login flow
  - **Steps:**
    - [ ] Install Playwright + configure for Docker test environment
    - [ ] Test cases: page loads, NVDA chart renders, add stock to watchlist, Google login mock
    - [ ] Screenshot on failure for debugging
  - **Acceptance:** 4+ e2e tests pass against running Docker stack
  - **Effort:** 8 hours

## Performance
- [ ] Redis memory usage audit: review TTLs, eviction policy
  - **Steps:**
    - [ ] `redis-cli INFO memory` → check used_memory vs maxmemory
    - [ ] Review all key patterns + TTLs: `cache:quote:*`, `cache:history:*`, `celery-*`
    - [ ] Set eviction policy to `allkeys-lru` if not set
    - [ ] Document Redis memory budget in INSTRUCTIONS.md
  - **Acceptance:** Redis memory < 256MB, all keys have appropriate TTLs, no unbounded growth
  - **Effort:** 2 hours
- [ ] DB query profiling: find slow queries in TimescaleDB
  - **Steps:**
    - [ ] Enable `pg_stat_statements` extension
    - [ ] Query: `SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10`
    - [ ] Add indexes for slow queries (likely: history queries by symbol + timeframe)
    - [ ] Verify hypertable chunk size is optimal (7 days default)
  - **Acceptance:** Top 10 queries all < 100ms avg execution time
  - **Effort:** 3 hours
- [ ] Frontend bundle size: analyze with `vite-bundle-analyzer`
  - **Steps:**
    - [ ] Run `npx vite-bundle-analyzer` in frontend container
    - [ ] Target: main bundle < 500KB gzipped
    - [ ] Identify large dependencies for lazy loading (chart library, markdown parser)
    - [ ] Code-split: chart page, portfolio page, admin page as separate chunks
  - **Acceptance:** Main bundle < 500KB gzipped, chart library lazy-loaded
  - **Effort:** 4 hours
- [ ] CDN for static assets (if deploying publicly)
  - **Steps:** Configure Caddy to serve `/assets/*` with cache-control headers, optionally proxy to Cloudflare
  - **Effort:** 2 hours

---

# Phase 6: Future Expansion

## New Markets
- [ ] Crypto: BTC, ETH, BNB via Binance API (no auth required for public data)
  - **Steps:**
    - [ ] Add `binance` data source in `stock_service.py` alongside yfinance
    - [ ] Binance public API: `GET /api/v3/klines` for OHLCV, `/api/v3/ticker/price` for quotes
    - [ ] Symbol format: "BTCUSDT", "ETHUSDT" → map to display as "BTC/USD"
    - [ ] 24/7 market hours — update Celery schedule (no market hours filter for crypto)
  - **Acceptance:** BTC chart renders with 1D candles, live price updates in sidebar
  - **Trader scenario:** เช็ค BTC correlation กับ NVDA — ถ้า BTC dump หนัก อาจกระทบ tech stocks
  - **Effort:** 6 hours
  - 📁 **Files:** `backend/services/stock_service.py` (add Binance data source alongside yfinance), `backend/workers/price_fetcher.py` (add crypto schedule — 24/7), `backend/core/config.py` (Binance doesn't need API key for public data)
  - ⚠️ **Pitfalls:** Binance API ไม่ต้อง auth สำหรับ public data แต่มี rate limit (1200 req/min), crypto market 24/7 — ต้อง adjust Celery schedule ให้ fetch ตลอด ไม่ filter by market hours
- [ ] Forex: USD/THB, EUR/USD via Yahoo Finance (`THBUSD=X`)
  - **Steps:**
    - [ ] Use yfinance with symbols: `THBUSD=X`, `EURUSD=X`, `USDJPY=X`
    - [ ] Display as "USD/THB" not "THBUSD=X" in UI
    - [ ] Add to watchlist as optional category "Forex"
  - **Acceptance:** USD/THB chart renders, shows current exchange rate in sidebar
  - **Trader scenario:** ดู USD/THB ก่อนตัดสินใจซื้อ US stocks — ถ้าบาทอ่อนมากอาจรอ
  - **Effort:** 3 hours
- [ ] SET50 ETF and mutual funds (.FUND symbols)
  - **Steps:**
    - [ ] Research fund symbol format in Yahoo Finance (e.g., `BBLSF.BK`, `KFSDIV.BK`)
    - [ ] Add fund type flag in `stocks` table to differentiate from equities
    - [ ] Display NAV instead of market price where applicable
  - **Acceptance:** Search "BBLSF" → shows fund with NAV data
  - **Effort:** 4 hours

## Social & Collaboration
- [ ] Public watchlists: share via URL
  - **Steps:**
    - [ ] Add `is_public` flag + `share_token` (UUID) to watchlist model
    - [ ] Public URL: `/shared/watchlist/{share_token}` → read-only view
    - [ ] "Share" button generates link, copyable to clipboard
  - **Acceptance:** Share link → anyone can view watchlist without login (read-only)
  - **Effort:** 4 hours
- [ ] Idea feed: post chart + comment publicly
  - **Steps:**
    - [ ] New `ideas` table: user_id, symbol, chart_snapshot_url, comment, created_at
    - [ ] "Post Idea" button on chart → captures chart screenshot + markdown comment
    - [ ] Feed page: chronological list of ideas with chart thumbnails
  - **Acceptance:** Post idea with NVDA chart + comment → visible in feed by other users
  - **Effort:** 8 hours
- [ ] Follow other users' watchlists
  - **Steps:** Follow model linking follower → followed watchlist, notification on watchlist update
  - **Effort:** 4 hours

## Mobile
- [ ] Responsive design: portrait phone layout (stacked sidebar + chart)
  - **Steps:**
    - [ ] Mobile breakpoint: `@media (max-width: 768px)` → sidebar collapses to bottom drawer
    - [ ] Chart takes full width, toolbar becomes scrollable horizontal strip
    - [ ] RightPanel becomes slide-up sheet (swipe up to reveal)
    - [ ] BottomPanel tabs at bottom of screen
  - **Acceptance:** Open on iPhone 14 viewport → chart visible full-width, sidebar accessible via hamburger
  - **Trader scenario:** ดูราคาผ่านมือถือตอนไม่ได้อยู่หน้าจอ — ต้อง glanceable, ไม่ต้องซูม
  - **Effort:** 12 hours
  - 📁 **Files:** `frontend/src/routes/__root.tsx` (layout wrapper), `frontend/src/components/common/Sidebar.tsx` (collapse to drawer), `frontend/src/components/chart/TradingChart.tsx` (responsive), `frontend/src/styles/` (media queries)
  - ⚠️ **Pitfalls:** TanStack Start SSR — ระวัง `window` access ใน mobile detection (ต้อง wrap ใน `ClientOnly` หรือ `useEffect`), LightweightCharts auto-resize: ใช้ `chart.applyOptions({width: containerWidth})`
- [ ] PWA: installable on mobile home screen
  - **Steps:**
    - [ ] Add `manifest.json` with app name, icons, theme_color
    - [ ] Register service worker for offline shell caching
    - [ ] Add `<meta name="apple-mobile-web-app-capable">` for iOS
  - **Acceptance:** Chrome shows "Install App" prompt, app icon appears on home screen
  - **Effort:** 3 hours
- [ ] Touch-friendly chart: pinch zoom, swipe to pan
  - **Steps:**
    - [ ] LightweightCharts has built-in touch support — verify it works on mobile viewport
    - [ ] Add touch gesture hints on first mobile visit
    - [ ] Increase touch target size for timeframe buttons (min 44×44px)
  - **Acceptance:** Pinch to zoom on mobile works smoothly, swipe to scroll through candles
  - **Effort:** 2 hours

## Integrations
- [ ] SETTRADE API: auto-import Thai portfolio
  - **Why:** ไม่อยากกรอก transaction manual — sync จาก broker โดยตรง
  - **Steps:**
    - [ ] Research SETTRADE Open API: auth flow, endpoints, rate limits
    - [ ] Implement OAuth flow for SETTRADE account linking
    - [ ] Celery task: sync portfolio daily → insert into transactions table
    - [ ] Conflict resolution: skip duplicate transactions
  - **Acceptance:** Link SETTRADE account → Thai portfolio auto-imported with buy/sell history
  - **Effort:** 12 hours
- [ ] Interactive Brokers API: auto-import US portfolio
  - **Steps:**
    - [ ] Use IBKR Client Portal API or TWS API
    - [ ] Sync: positions, trades, P&L from IBKR
    - [ ] Map IBKR symbols to app's symbol format
  - **Acceptance:** Link IBKR → US holdings appear in portfolio page
  - **Effort:** 12 hours
- [ ] LINE Notify: alternative to Telegram for Thai users
  - **Why:** คนไทยใช้ LINE มากกว่า Telegram — alert เข้า LINE สะดวกกว่า
  - **Steps:**
    - [ ] Register LINE Notify service → get access token
    - [ ] User settings: "Connect LINE" button → OAuth flow
    - [ ] On alert trigger: send via LINE Notify API alongside/instead of Telegram
  - **Acceptance:** Alert triggers → LINE notification received on phone
  - **Effort:** 4 hours
- [ ] Google Sheets export: portfolio → Google Sheets via API
  - **Steps:**
    - [ ] Google Sheets API v4: create/update spreadsheet
    - [ ] "Export to Sheets" button → creates new sheet with holdings data
    - [ ] Optional: auto-sync daily via Celery task
  - **Acceptance:** Click Export → Google Sheet created with all holdings, values, P&L
  - **Effort:** 6 hours
