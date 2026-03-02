# CLAUDE.md — ShotockViz Project Context

## Project Overview

ShotockViz is a **self-hosted stock analysis platform** for Thai (SET/MAI) and US (NYSE/NASDAQ) markets. Docker Compose stack with 8 services. Version 0.1.3 BETA.

## Critical Rules

1. **NEVER run servers on host** — everything runs inside Docker containers only
2. **Use `docker-compose.dev.yml`** for all development — never use prod compose
3. **After any task** → update `changelog.md` + mark items in `tasklist.md`
4. **Frontend changes require Docker rebuild:**
   ```bash
   docker-compose -f docker-compose.dev.yml build frontend
   docker-compose -f docker-compose.dev.yml up -d frontend
   ```
5. **Auth uses Google OAuth (one-tap)** — NO custom token management on frontend. User explicitly demanded this 3 times. Tokens handled by `useGoogleOneTapLogin` in `__root.tsx`.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 + TanStack Start (SSR) + Vite 7 + Tailwind 4 + Zustand 5 |
| Charts | TradingView Lightweight Charts v5 |
| Backend | FastAPI (Python 3.13) + SQLAlchemy 2 + Pydantic 2 |
| Database | PostgreSQL 16 + TimescaleDB (time-series) |
| Cache | Redis 7 (caching + Celery broker + WebSocket pub/sub) |
| Background | Celery 5.6 + Beat (price fetching, alert checking) |
| AI | Ollama (llama3.2) — local LLM, no cloud |
| Data | Yahoo Finance + Finnhub (free tier) |
| Proxy | Caddy 2 (reverse proxy + auto TLS) |

## Docker Commands

```bash
docker-compose -f docker-compose.dev.yml up -d          # Start all
docker-compose -f docker-compose.dev.yml build <service> # Rebuild
docker-compose -f docker-compose.dev.yml logs -f <svc>   # Logs
docker-compose -f docker-compose.dev.yml exec backend bash  # Shell into container
docker-compose -f docker-compose.dev.yml down            # Stop all
```

## Project Structure (Key Files)

```
ShotockViz/
├── backend/
│   ├── api/routes/          # 13 endpoint modules (auth, stocks, watchlist, portfolio, alerts, screener, ai_chat, etc.)
│   ├── models/              # SQLAlchemy ORM (User, Stock, StockPrice1m, Transaction, Alert, Drawing, Note, StockEvent)
│   ├── services/            # stock_service.py (47KB), cache_service.py
│   ├── workers/             # Celery: price_fetcher, alert_checker, housekeeping
│   ├── core/                # config, database, redis, security
│   └── main.py              # FastAPI app + WebSocket manager
├── frontend/
│   ├── src/routes/          # 8 pages (__root.tsx, chart, dashboard, portfolio, alerts, screener, news, login)
│   ├── src/components/      # 33 React components (chart/, common/, modals/, pages/)
│   ├── src/store/           # Zustand: appStore.js, authStore.js
│   ├── src/services/        # api.js, aiService.js
│   └── src/styles/          # Tailwind + glassmorphism CSS
├── docker-compose.dev.yml   # 8-service dev stack
├── caddy/                   # Caddyfile.dev, Caddyfile.prod
├── REQUIREMENTS.md          # Canonical SRS (functional + non-functional specs)
├── INSTRUCTIONS.md          # Developer workflow guide
├── master_plan.md           # Strategic roadmap (Phase 1-6)
├── tasklist.md              # Live task tracking with [x]/[ ] status
├── changelog.md             # Version history
├── trade-prompt.md          # Pine Script strategy prompt library (15 strategies)
└── ShotockViz_Development_Plan.docx  # Comprehensive dev plan with stakeholder priorities
```

## Document Map (What Goes Where)

| File | Purpose | When to Update |
|------|---------|----------------|
| `CLAUDE.md` (this file) | AI agent quick reference | When project structure or rules change |
| `REQUIREMENTS.md` | Canonical spec (features, schema, API) | When requirements change |
| `INSTRUCTIONS.md` | Developer how-to (commands, workflow, standards) | When dev process changes |
| `master_plan.md` | Strategic roadmap (phases, vision) | When roadmap evolves |
| `tasklist.md` | Sprint task tracking | After every completed task |
| `changelog.md` | Version history | After every change |
| `trade-prompt.md` | Pine Script strategy library | When adding new strategies |
| `ShotockViz_Development_Plan.docx` | Stakeholder-reviewed dev plan | Major planning milestones |

## Current Status & Priorities

**Phase 1 (Stabilization):** In progress — critical fixes applied but frontend Docker rebuild pending.

### Immediate Blockers (Week 1)
1. **Frontend Docker rebuild** — compiled bundle outdated, source fixes not active
2. **Verify live WebSocket prices** during market hours (20:30-03:00 ICT for US)
3. **Fix Thai .BK stock data** — PTT.BK returning empty history
4. **System health monitoring** — Celery failures are silent

### High Value (Week 2-3)
5. XD/XR corporate event markers on chart
6. Price alerts + Telegram delivery
7. Portfolio page (transactions + P&L)
8. Indicator verification (RSI gauge broken)

### See Also
- Full priority breakdown → `ShotockViz_Development_Plan.docx`
- Task checklist → `tasklist.md`
- Feature specs → `REQUIREMENTS.md`

## Key Architecture Decisions

- **SSE for AI Chat** — `ai_chat.py` streams via Server-Sent Events with `asyncio.wait_for` keepalive heartbeat every 15s
- **4-layer cache** — Redis → PostgreSQL → Yahoo Finance → synthetic Brownian bridge
- **TimescaleDB hypertable** — `StockPrice1m` for efficient time-series queries with auto-compression
- **WebSocket prices** — Redis pub/sub `price_updates` channel → WebSocket broadcast to frontend
- **Google OAuth** — `@react-oauth/google` with `useGoogleOneTapLogin` in `__root.tsx` for seamless re-auth. **NO custom token management code on frontend.**

## Market Hours (ICT timezone)

| Market | Hours | Notes |
|--------|-------|-------|
| SET | 10:00-12:30, 14:00-16:30 | Break 12:30-14:00 |
| US (NYSE/NASDAQ) | 21:30-04:00 (next day) | Pre-market from 20:00 |
| Celery price fetch | Every 1 min during market hours | via celery-beat schedule |

## Environment Variables

See `.env.example` for full list. Key vars:
- `DATABASE_URL` — PostgreSQL connection
- `REDIS_URL` — Redis connection
- `JWT_SECRET_KEY` — Token signing
- `FINNHUB_API_KEY` — Free tier for enhanced data
- `TELEGRAM_BOT_TOKEN` — Alert notifications
- `OLLAMA_URL` — Local LLM endpoint (default: `http://ollama:11434`)
- `GOOGLE_CLIENT_ID` — OAuth login

## Stakeholder Context

Primary user is an experienced Thai+US stock trader (8yr SET, 4yr US). Swing + position trading. Watchlist 40-60 symbols. Uses fundamentals + technical analysis. Trades during SET hours and monitors US pre-market at 20:00 ICT. The `stock-trader-stakeholder` skill in `.skills/` provides this persona for feature prioritization and UX feedback.

## Known Issues & Recent Fixes

- **AI chat freeze** — Fixed: immediate SSE flush + keepalive heartbeat + frontend error propagation
- **Memory leaks** — Fixed in source: setInterval leaks in Sidebar, Dashboard, TradingChart, AIChatPanel
- **Race condition** — Fixed: AbortController in RightPanel for stale XHR after symbol change
- **SyntaxError ai_chat.py** — Fixed: missing `try:` before `async with httpx.AsyncClient` block
- **Hydration mismatch** — Harmless: browser extension `cz-shortcut-listen` attribute on body
