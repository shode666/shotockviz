# ShotockViz — Master Plan

**Project:** Self-hosted Stock Analysis Platform (Thai + US Markets)
**Version:** 0.1.0 BETA → Target 1.0
**Last Updated:** 2026-03-01
**Stack:** FastAPI + React 19 + TanStack Start + TimescaleDB + Redis + Celery

---

## Vision

ShotockViz is a **self-hosted, privacy-first stock analysis platform** tailored for Thai retail investors who also trade US markets. It provides institutional-grade charting, real-time data, AI-assisted analysis, and portfolio management — all running locally with no external data leaks.

**Core Principles:**
- **Self-hosted first** — your data stays on your machine
- **Thai market first** — full .BK/.MAI support with Thai names
- **Speed** — sub-100ms chart loads via 4-layer cache
- **Intelligence** — local AI (Ollama) for sentiment & analysis, no cloud required
- **Production quality** — not a toy; built for daily professional use

---

## Current Status: Phase 1 (Stabilization)

**Status:** 🔴 In Progress — Core bugs being fixed
**Blockers:**
- Frontend production bundle outdated (missing interval-leak fixes, `dataVersion` hook, names in sidebar)
- PTT.BK Yahoo Finance returning empty bars (rate limiting)
- Celery workers not populating Redis (quotes all 202)
- Fundamentals 404 for US stocks (Yahoo Finance API version mismatch)

---

## Feature Roadmap

### Phase 1 — Stabilization & Core Fixes
> Goal: App is stable, reliable, default state is usable for new visitors

| Feature | Status | Priority |
|---------|--------|----------|
| Rebuild frontend Docker image with all source fixes | 🔴 TODO | P0 |
| Default stock: PTT.BK → NVDA (works without Celery) | 🔴 TODO | P0 |
| Interval memory leaks in Sidebar/Dashboard | 🟡 Fixed in src, not compiled | P0 |
| Quote 202 fallback: asyncio background fetch when Celery absent | 🟢 Fixed (backend) | P0 |
| Fundamentals 404: v11→v10→v8 chart API fallback chain | 🟢 Fixed (backend) | P0 |
| `avg_volume` field added to StockFundamentals schema | 🟢 Fixed (backend) | P1 |
| TradingChart retry (3× / 4s) on empty bars | 🟡 Fixed in src, not compiled | P1 |
| AIChatPanel timeout cleanup on unmount | 🟡 Fixed in src, not compiled | P1 |
| RightPanel AbortController race condition fix | 🟡 Fixed in src, not compiled | P1 |
| useBackendReady hook + dataVersion polling | 🟡 Fixed in src, not compiled | P1 |
| Company names in sidebar (batch /api/stocks/names) | 🟡 Fixed in src, not compiled | P1 |
| PTT.BK Yahoo Finance: increase timeout / retry | 🔴 TODO | P1 |
| WS://localhost/undefined error (TanStack devtools) | 🟡 Fixed in src | P2 |

### Phase 2 — Data Reliability & Real-time
> Goal: Prices update live, charts always have data, Thai stocks work

| Feature | Status | Priority |
|---------|--------|----------|
| Celery workers: diagnose and fix not running in dev | 🔴 TODO | P0 |
| WebSocket real-time price stream (subscribe by symbol) | 🟡 Partial (infra exists) | P1 |
| PTT.BK: alternative data source (Stooq doesn't support .BK) | 🔴 TODO | P1 |
| SET index quotes via Yahoo Finance `^SET.BK` | 🔴 TODO | P1 |
| Indicators on chart: all 5 (MA, EMA, BB, RSI, MACD) rendered correctly | 🟡 Partial | P1 |
| XD/XR event markers on chart (dividend/rights dates) | 🔴 TODO | P2 |
| Financial data: earnings dates, revenue, net profit | 🔴 TODO | P2 |
| Stock comparison mode (overlay 2+ symbols) | 🔴 TODO | P2 |
| Intraday bars (1m/5m/15m): fix timezone for Thai stocks | 🟡 Partial | P2 |

### Phase 3 — UX & Feature Completeness
> Goal: Every page is fully functional and polished

#### UI Design System (2026 Modern Trends)

**Required Design Principles:**
- **Glassmorphism modals** — ALL pop-up modals (notifications, alerts, confirmations, drawers) must use `backdrop-filter: blur(16px)` + semi-transparent background (`rgba(255,255,255,0.08)` dark / `rgba(255,255,255,0.72)` light) + subtle border (`1px solid rgba(255,255,255,0.15)`)
- **2026 UI trends** — Apply throughout the app:
  - Fluid micro-animations (Framer Motion or CSS transitions ≤ 300ms)
  - Bento grid layout for dashboard cards
  - Gradient accent borders on active/hover states
  - Frosted glass sidebar panels
  - Monochrome base with selective color accents (emerald for positive, rose for negative)
  - Subtle noise/grain texture overlay for depth
  - Large, bold typography for key numbers (price, P&L)
  - Pill-shaped badges and tags
  - Smooth skeleton loading states instead of spinners

| Feature | Status | Priority |
|---------|--------|----------|
| **Modern UI overhaul** — apply 2026 design system across all pages | 🔴 TODO | P1 |
| **Glassmorphism modals** — all pop-up overlays (alerts, confirm, drawer, notifications) | 🔴 TODO | P1 |
| Search modal (Ctrl+K): fix result ordering & UI | 🟡 Partial | P1 |
| News feed: display Finnhub + Google RSS articles with sentiment | 🟡 Partial | P1 |
| Portfolio page: buy/sell transactions, holdings table | 🟡 Partial | P1 |
| Portfolio: P&L chart (equity curve over time) | 🟡 Partial | P1 |
| Alerts page: create/edit/delete alerts UI | 🟡 Partial | P1 |
| Screener page: filter stocks by PE, RSI, volume, etc. | 🟡 Partial | P1 |
| AI Chat: stock-aware context (current symbol, price) | 🟡 Partial | P2 |
| Drawing tools: save/load per user per symbol | 🟡 Partial | P2 |
| Stock notes: investment thesis editor per symbol | 🟡 Partial | P2 |
| Settings modal: timezone, theme, default symbol | 🔴 TODO | P2 |
| Mobile responsive: stack layout for small screens | 🔴 TODO | P3 |
| Dark/Light mode: persist, smooth transition | 🟢 Done | - |
| Status bar: live market status, last update time | 🟢 Done | - |

### Phase 4 — Advanced Intelligence
> Goal: AI-powered analysis that actually adds value

| Feature | Status | Priority |
|---------|--------|----------|
| AI Sentiment on news articles (Ollama) | 🔴 TODO | P2 |
| AI chart pattern recognition (support/resistance auto-detect) | 🔴 TODO | P3 |
| AI portfolio suggestions ("rebalance recommendation") | 🔴 TODO | P3 |
| Backtesting: run strategy on historical data | 🔴 TODO | P3 |
| Strategy builder UI (visual rule editor) | 🔴 TODO | P3 |
| Alert: MACD signal, Golden Cross, Death Cross auto-detect | 🟡 Partial | P2 |
| Telegram notification delivery (need user chat_id storage) | 🟡 Infra ready | P2 |
| Email notifications (SMTP) | 🔴 TODO | P3 |
| Price target + analyst rating aggregation | 🔴 TODO | P3 |

### Phase 5 — Scale & Operations
> Goal: Production-ready for 50+ concurrent users, easy to maintain

| Feature | Status | Priority |
|---------|--------|----------|
| Admin dashboard: user management, system metrics | 🔴 TODO | P2 |
| Alembic migrations: proper DB schema versioning | 🔴 TODO | P2 |
| Frontend build pipeline: CI auto-rebuild on push | 🔴 TODO | P2 |
| Structured logging dashboard (Grafana / Loki) | 🔴 TODO | P3 |
| API rate limit tuning: authenticated users get more | 🟢 Done | - |
| Health checks: /api/health covers DB + Redis + Celery | 🟢 Done | - |
| Test coverage: backend pytest ≥ 70% | 🔴 TODO | P2 |
| Frontend e2e tests: Playwright critical paths | 🔴 TODO | P3 |
| Docker health checks & auto-restart policies | 🟡 Partial | P2 |
| Horizontal scaling: stateless backend behind load balancer | 🔴 TODO (future) | P4 |

### Phase 6 — Future Expansion
> Nice-to-have after v1.0

| Feature | Status |
|---------|--------|
| Crypto market support (BTC, ETH via Binance API) | 🔴 TODO |
| Forex support (USD/THB, EUR/USD) | 🔴 TODO |
| Broker integration: SETTRADE / IB API auto-trade | 🔴 TODO |
| Social trading: share watchlists / ideas publicly | 🔴 TODO |
| Mobile app: React Native iOS/Android | 🔴 TODO |
| Multi-language: full EN/TH toggle | 🔴 TODO |
| White-label API: expose data endpoint for other apps | 🔴 TODO |
| Fundamental screening: filter by financial ratios, earnings growth | 🔴 TODO |
| Sector rotation heatmap | 🔴 TODO |
| Options chain viewer | 🔴 TODO |

---

## Architecture Decisions

### Data Flow

```
External APIs → Celery Workers → Redis Cache → API Endpoint → Frontend
     Yahoo Finance                    L1 (hot)    FastAPI
     Stooq                                        ↑
     Finnhub              PostgreSQL ──────────────┘
                           L2 (warm)
```

**4-Layer Cache (OHLCV history):**
1. **Redis** (L1, 60s–6h TTL) — fastest, shared across users
2. **PostgreSQL/TimescaleDB** (L2, persistent) — survives Redis restart
3. **Yahoo Finance / Stooq** (L3, live) — fetched on cache miss
4. **Synthetic intraday** (L4, generated) — Brownian bridge from daily bars

**Quote Flow:**
- Celery writes quotes to Redis every 60s (market hours)
- Asyncio fallback: `_cache_quote_background()` fires when Celery unavailable
- Frontend polls with exponential backoff on 202

**Fundamentals Flow:**
- Live fetch from Yahoo Finance quoteSummary v11 → v10 → v8 chart meta
- Cached in Redis for 5 minutes

### Frontend State Architecture

```
Zustand Stores:
  appStore   → selectedStock, theme, searchOpen, dataVersion
  authStore  → user, tokens, isAuthenticated
  chartStore → timeframe, indicators, chartType

dataVersion bump triggers:
  - useBackendReady: polls /api/system/ready, bumps on ready
  - Components subscribe: [dataVersion] in useEffect deps
  - Sidebar: re-fetches prices on bump
  - DashboardPage: re-loads overview on bump
```

### Market Hours

| Market | Hours (ICT) | Notes |
|--------|-------------|-------|
| SET Thailand | Mon–Fri 10:00–12:30, 14:30–17:00 | Lunch break |
| US Markets | Mon–Fri 20:30–03:00+1 (ICT) | Pre/post market ±2h |
| Data latency | 15 min delay | Free API tier limitation |

### Tech Constraints

- **Yahoo Finance**: Rate limited (~100 req/min), crumb auth required, .BK unreliable
- **Stooq**: US stocks only, daily/weekly/monthly only, reliable
- **Finnhub**: Free tier = 60 calls/min, US stocks + fundamentals
- **Ollama**: Local inference, no network required, model must be pulled first
- **TimescaleDB**: ~10GB/year storage for 500 symbols at 1m resolution

---

## Key Files to Know

### Backend Critical Files

| File | Purpose |
|------|---------|
| `backend/services/stock_service.py` | Core data fetching, 4-layer cache, Yahoo Finance auth |
| `backend/workers/price_fetcher.py` | Celery task — fetch all watchlist prices |
| `backend/workers/alert_checker.py` | Celery task — check alert conditions |
| `backend/api/routes/stocks.py` | REST endpoints: search, quote, history, fundamentals |
| `backend/api/routes/system.py` | Health check, backend readiness probe |
| `backend/core/config.py` | All settings from .env |
| `backend/main.py` | FastAPI app setup, router registration, WebSocket |

### Frontend Critical Files

| File | Purpose |
|------|---------|
| `frontend/src/store/appStore.js` | Global state: selectedStock, dataVersion, theme |
| `frontend/src/components/common/Sidebar.tsx` | Watchlist, price refresh, stock select |
| `frontend/src/components/chart/TradingChart.tsx` | Main chart (Lightweight-Charts) |
| `frontend/src/components/chart/RightPanel.tsx` | Stats, fundamentals, quick alert |
| `frontend/src/hooks/useBackendReady.ts` | Polls /api/system/ready → bumps dataVersion |
| `frontend/src/services/stockService.js` | All stock API calls |
| `frontend/.output/` | **Production build** — what actually runs in Docker |

---

## Contacts & Links

- **Docs**: README.md, REQUIREMENTS.md
- **Tasks**: tasklist.md
- **Changes**: changelog.md
- **API Docs**: http://localhost:8000/docs (when running)
