# ShotockViz

> Self-hosted stock analysis platform for Thai (SET/MAI), US (NYSE/NASDAQ), and 8 international markets. Advanced charting, portfolio tracking, alerts, AI chat, and real-time price updates. Zero monthly fees — runs entirely on Docker.

![Version](https://img.shields.io/badge/version-0.1.3-blue)
![Python](https://img.shields.io/badge/python-3.13-blue)
![React](https://img.shields.io/badge/react-19-61dafb)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-Beta-orange)

---

## Features

**Charts & Analysis** — Candlestick / Line / Area / Bar charts with 8 timeframes (1m to 1M). Drawing tools (trend lines, Fibonacci, H-lines, rectangles, arrows, pitchfork). Technical indicators: MA, EMA, RSI, MACD, Bollinger Bands, Volume, Stochastic, Ichimoku. Compare mode to overlay 2 stocks. XD/XR dividend markers for Thai stocks.

**Portfolio Tracking** — Record Buy/Sell transactions with fees and currency. Real-time analytics: current value, P&L, allocation breakdown. Risk metrics: Sharpe Ratio, Max Drawdown, Beta. Fundamental overlay: P/E, P/BV, Dividend Yield, Market Cap. Symbol autocomplete with market badge and currency auto-detection.

**Alerts** — Price Above/Below, RSI, MACD Golden/Death Cross, Volume Spike. Channels: In-app and Telegram Bot. Symbol autocomplete with currency-aware value display.

**Stock Screener** — Filter by market, price range, P/E, RSI, MACD signal, volume. Save presets for quick re-use.

**News Feed** — Multi-source aggregation: Google News RSS + Finnhub. AI sentiment analysis via local Ollama (llama3.2). Filter by market, symbol, or watchlist.

**AI Chat** — SSE-streamed chat with local LLM (Ollama). Context-aware stock analysis. No cloud dependency.

**10 Markets Supported** — SET, US, Japan, Hong Kong, China, UK, Germany, France, Netherlands, Korea. Round-robin price fetching across all markets.

---

## Supported Markets

| Market | Suffix | Exchange | Trading Hours (ICT) | Currency |
|--------|--------|----------|---------------------|----------|
| SET | `.BK` | Stock Exchange of Thailand | Mon-Fri 10:00-16:30 (break 12:30-14:00) | THB ฿ |
| US | — | NYSE / NASDAQ | Mon-Fri 21:30-04:00 (next day) | USD $ |
| Japan | `.T` | Tokyo Stock Exchange | Mon-Fri 08:00-14:00 | JPY ¥ |
| Hong Kong | `.HK` | HKEX | Mon-Fri 09:30-16:00 | HKD HK$ |
| China | `.SS` `.SZ` | Shanghai / Shenzhen | Mon-Fri 09:30-15:00 | CNY ¥ |
| UK | `.L` | London Stock Exchange | Mon-Fri 15:00-23:30 | GBP £ |
| Germany | `.DE` | XETRA / Frankfurt | Mon-Fri 14:00-22:30 | EUR € |
| France | `.PA` | Euronext Paris | Mon-Fri 14:00-22:30 | EUR € |
| Netherlands | `.AS` | Euronext Amsterdam | Mon-Fri 14:00-22:30 | EUR € |
| Korea | `.KS` | Korea Exchange | Mon-Fri 09:00-15:30 | KRW ₩ |

Indices tracked: ^SET.BK, ^GSPC (S&P 500), ^IXIC (NASDAQ), ^DJI, ^N225 (Nikkei), ^HSI (Hang Seng), ^FTSE, ^GDAXI (DAX), ^FCHI (CAC 40), ^AEX, ^KS11 (KOSPI), plus THBUSD=X and GC=F (Gold).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 + TanStack Start (SSR) + Vite 7 + Tailwind 4 + Zustand 5 |
| Charts | TradingView Lightweight Charts v5 |
| Backend | FastAPI (Python 3.13) + SQLAlchemy 2 + Pydantic 2 |
| Database | PostgreSQL 16 + TimescaleDB (hypertable for time-series) |
| Cache | Redis 7 (L1 cache + Celery broker + WebSocket pub/sub) |
| Background | Celery 5.6 + Beat (8 workers: price, names, fundamentals, fund NAV, history, on-demand, alerts, housekeeping) |
| AI | Ollama (llama3.2) — 100% local, no cloud |
| Data | Yahoo Finance + pythainav (Thai fund NAV) + Finnhub (free tier) |
| Auth | Google OAuth one-tap (`@react-oauth/google`) |
| Proxy | Caddy 2 (reverse proxy + auto TLS) |

All open source and free. No paid dependencies.

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │────▶│    Caddy      │────▶│   FastAPI     │
│  React 19    │◀────│  (reverse    │◀────│  (pure-read   │
│  TanStack    │ WS  │   proxy)     │     │   CQRS)       │
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                                    ┌────────────┼────────────┐
                                    ▼            ▼            ▼
                              ┌──────────┐ ┌──────────┐ ┌──────────┐
                              │  Redis   │ │ Postgres │ │  Celery  │
                              │  (L1     │ │ +Timescale│ │ Workers  │
                              │  cache)  │ │  (L2)    │ │ (write)  │
                              └──────────┘ └──────────┘ └────┬─────┘
                                                              │
                                                    ┌─────────┼─────────┐
                                                    ▼         ▼         ▼
                                              Yahoo Finance  pythainav  Finnhub
```

**CQRS pattern**: API endpoints are pure-read (Redis L1 → PostgreSQL L2). Celery workers are the sole data ingesters. On cache miss, API triggers a Celery task → worker fetches → caches → publishes WebSocket `data_ready` → frontend re-fetches automatically.

**Round-robin price fetcher**: Single Celery task runs every 1 minute, rotating through 5 market slots (SET → US → Asia → Europe → Overview). Each market updates every ~5 min. Closed markets are auto-skipped so open markets get more frequent updates.

---

## Quick Start

### Requirements

- Docker & Docker Compose v2+
- 4GB+ RAM, 10GB free disk
- Internet connection (for stock data)
- Google OAuth Client ID (for login)

### 1. Clone & Configure

```bash
git clone https://github.com/yourusername/ShotockViz.git
cd ShotockViz
cp .env.example .env
# Edit .env — set GOOGLE_CLIENT_ID, JWT_SECRET_KEY, etc.
```

### 2. Start (Dev Mode)

```bash
docker-compose -f docker-compose.dev.yml up -d
```

8 services will start: frontend, backend, postgres, redis, celery, celery-beat, ollama, caddy.

### 3. Access

| Service | URL |
|---------|-----|
| App | https://localhost |
| API Docs | https://localhost/api/docs |
| Caddy Admin | http://localhost:2019 |

### 4. Seed Data

```bash
# Seed Thai + US base stocks
docker-compose -f docker-compose.dev.yml exec backend python scripts/seed_stocks.py

# Seed international markets (JP/HK/UK/DE/CN/FR/NL) from Wikipedia
docker-compose -f docker-compose.dev.yml exec backend python scripts/fetch_real_constituents.py
```

### 5. Login

Visit https://localhost — click Google Sign-In. First user is auto-created.

---

## Celery Workers

| Worker | Schedule | What it does |
|--------|----------|-------------|
| `fetch_prices` | Every 1 min | Round-robin price fetch across 5 market slots |
| `fetch_overview_prices` | Every 5 min | Indices, USD/THB, Gold (backup) |
| `check_all_alerts` | Every 60s | Check active alerts against cached prices |
| `prefetch_names` | Every 6h | Company names for all watched symbols |
| `prefetch_fundamentals` | Every 4h | P/E, P/BV, EPS, dividend yield |
| `fetch_thai_fund_navs` | Daily 19:00 ICT | Thai mutual fund NAVs via pythainav |
| `prefetch_history` | Every 30 min | Warm OHLCV cache for charts |
| `scan_unregistered` | Every 15 min | Auto-register new user-added symbols |
| `populate_index_constituents` | Weekly (Sun) | Refresh S&P 500, NASDAQ 100, SET 100, international indices |
| `run_housekeeping` | Daily 03:00 ICT | Compress old 1m → 5m → 1d → 1w data |

---

## Project Structure

```
ShotockViz/
├── backend/
│   ├── api/routes/            # 13 endpoint modules
│   ├── models/                # SQLAlchemy ORM models
│   ├── services/              # Business logic + cache orchestrator
│   ├── workers/               # Celery tasks (10 workers)
│   │   └── helpers/           # Shared: symbol_loader, cache_publisher, task_timing
│   ├── core/                  # Config, database, redis, cache_keys, symbol_utils
│   ├── scripts/               # Seed data, diagnostics
│   └── main.py                # FastAPI app + WebSocket manager
├── frontend/
│   ├── src/routes/            # 8 pages (TanStack Router)
│   ├── src/components/        # 33 React components
│   │   ├── chart/             # TradingView chart + controls
│   │   ├── common/            # Sidebar, Header, WatchlistSearch
│   │   ├── modals/            # Settings, Drawing, Alert modals
│   │   ├── pages/             # AlertsPage, ScreenerPage, NewsPage
│   │   └── portfolio/         # HoldingsTable, AddTransactionModal
│   ├── src/hooks/             # usePriceUpdates, usePortfolioData, useChartData
│   ├── src/store/             # Zustand: appStore, authStore
│   ├── src/services/          # API clients
│   └── src/utils/             # formatters (parseSymbol, MARKET_COLORS, MARKET_CURRENCY)
├── caddy/                     # Caddyfile.dev + Caddyfile.prod
├── docker-compose.dev.yml     # 8-service dev stack
├── docker-compose.prod.yml    # Production stack
├── CLAUDE.md                  # AI agent context
├── REQUIREMENTS.md            # Feature specs + API reference
├── INSTRUCTIONS.md            # Developer workflow guide
├── master_plan.md             # Strategic roadmap (Phase 1-6)
├── tasklist.md                # Sprint task tracking
├── changelog.md               # Version history
└── trade-prompt.md            # Pine Script strategy library
```

---

## Data Sources

| Source | Coverage | Lag | Free |
|--------|----------|-----|------|
| Yahoo Finance (yfinance) | 10 markets + indices + FX + commodities | ~15 min | Unlimited |
| pythainav | Thai mutual fund NAVs | T+1 day | Unlimited |
| Finnhub | US stocks + news | ~15 min | 60 req/min |
| Google News RSS | News articles | Near real-time | Unlimited |

---

## Database Housekeeping

Automatically compresses old price data to reduce storage:

| Age | Resolution | Action |
|-----|-----------|--------|
| < 7 days | 1-minute | Raw storage |
| 7-90 days | 5-minute | Aggregate + delete 1m |
| 90 days - 2 years | 1-day | Aggregate + delete 5m |
| > 2 years | 1-week | Aggregate + delete 1d |

Runs daily at 03:00 ICT via Celery Beat. Uses TimescaleDB hypertables with auto-compression.

---

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `JWT_SECRET_KEY` | Token signing key |
| `GOOGLE_CLIENT_ID` | Google OAuth login |
| `TELEGRAM_BOT_TOKEN` | Alert notifications via Telegram |
| `OLLAMA_URL` | Local LLM endpoint (default: `http://ollama:11434`) |
| `FINNHUB_API_KEY` | Optional — enhanced US data |

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|------------|
| RAM | 4GB | 8GB+ |
| CPU | 2 cores | 4 cores |
| Disk | 10GB | 50GB+ |
| Docker | v20.10 | v24+ |
| Docker Compose | v2.0 | v2.20+ |

---

## Development

```bash
# Start all services
docker-compose -f docker-compose.dev.yml up -d

# Rebuild after code changes
docker-compose -f docker-compose.dev.yml build frontend backend
docker-compose -f docker-compose.dev.yml up -d frontend backend celery celery-beat

# View logs
docker-compose -f docker-compose.dev.yml logs -f backend
docker-compose -f docker-compose.dev.yml logs -f celery

# Shell into container
docker-compose -f docker-compose.dev.yml exec backend bash

# Run diagnostics
docker-compose -f docker-compose.dev.yml exec backend python scripts/check_intl_symbols.py
```

---

## Troubleshooting

**Backend won't start** — Check `docker-compose logs backend`. Common: missing env vars or DB not ready yet. Backend waits for postgres via `depends_on`.

**No price data** — Celery workers may not have run yet. Check `docker-compose logs celery`. Trigger manually: `docker-compose exec backend celery -A workers.celery_app call workers.price_fetcher.fetch_prices`.

**International symbols missing** — Run `docker-compose exec backend python scripts/fetch_real_constituents.py` to seed from Wikipedia.

**WebSocket errors** — Usually Caddy proxy config. Check `docker-compose logs caddy`. Ensure `wss://` upgrade is configured in Caddyfile.

**Alert creation fails** — Frontend sends display names ("Price Above"), backend normalizes to enum ("PRICE_ABOVE") automatically. Check backend logs for the actual error.

---

## Changelog

See [changelog.md](changelog.md) for full version history.

### v0.1.3 (2026-03-03) — Current

- CQRS architecture: API pure-read, Celery sole data ingesters
- Round-robin price fetcher across 10 international markets
- Symbol autocomplete with market badges and currency display
- 8 Celery workers (price, names, fundamentals, fund NAV, history, on-demand, alerts, housekeeping)
- Google OAuth one-tap authentication
- Extreme Refactor: SOLID principles, 500-line file cap, custom React hooks

### v0.1.0 (2026-02-24) — Initial Beta

- Stock charts with TradingView Lightweight Charts
- Technical indicators and drawing tools
- Watchlist and portfolio management
- Basic alerts (price, RSI)
- Dark mode UI

---

## License

MIT License — free for personal and commercial use.

---

## Disclaimer

ShotockViz is for educational and analysis purposes only. It is not financial advice. Always do your own research before making investment decisions.
