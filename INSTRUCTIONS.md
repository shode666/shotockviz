# ShotockViz — Development Instructions

**Version:** 3.0
**Last Updated:** 2026-03-03
**Project:** ShotockViz — Self-hosted Stock Analysis Platform (10 International Markets)

---

## Critical Rules

1. **NEVER run any server directly on the host machine** — no `uvicorn`, `npm run dev`, `python`, `node` etc. Everything runs inside Docker containers only.
2. **Development ONLY uses `docker-compose.dev.yml`** — never use prod compose for local work
3. **After completing any task → update `changelog.md`** immediately
4. **Update `tasklist.md`** to mark completed items `[x]`
5. **Frontend changes require rebuilding the Docker image:**
   ```bash
   docker-compose -f docker-compose.dev.yml build frontend
   docker-compose -f docker-compose.dev.yml up -d frontend
   ```
6. **Auth uses Google OAuth (one-tap)** — NO custom token management on frontend. Tokens handled by `useGoogleOneTapLogin` in `__root.tsx`.

### Allowed Commands (Docker only)
```bash
# Start all services
docker-compose -f docker-compose.dev.yml up -d

# Start specific service
docker-compose -f docker-compose.dev.yml up -d backend

# Rebuild a service after source changes
docker-compose -f docker-compose.dev.yml build <service>
docker-compose -f docker-compose.dev.yml up -d <service>

# View logs
docker-compose -f docker-compose.dev.yml logs -f <service>

# Run one-off commands inside a container
docker-compose -f docker-compose.dev.yml exec backend bash
docker-compose -f docker-compose.dev.yml exec backend python -c "..."

# Stop everything
docker-compose -f docker-compose.dev.yml down
```

### Never Do These
```bash
uvicorn main:app              # direct server
python backend/main.py        # direct python
npm run dev                   # direct node
pip install <pkg>             # install on host (use exec backend pip install)
```

---

## Quick Start

### Prerequisites

- Docker & Docker Compose v2.0+
- Git
- 4GB+ RAM, 10GB+ free disk
- Google OAuth Client ID (from Google Cloud Console)

### 1. Clone & Configure

```bash
git clone <repo-url>
cd ShotockViz
cp .env.example .env
# Edit .env — set GOOGLE_CLIENT_ID (required for login)
```

### 2. Start Dev Environment

```bash
docker-compose -f docker-compose.dev.yml up -d
```

**Dev Services:**

| Service | URL | Notes |
|---------|-----|-------|
| App (via Caddy) | https://localhost | Reverse proxy to frontend + backend |
| API Docs | https://localhost/api/docs | Swagger UI |
| Vite HMR | http://localhost:5173 | Hot reload for frontend dev |
| Backend API | http://localhost:8000 | Direct backend access |

> **Note:** The app at `https://localhost` is the SSR build. For instant frontend changes, use `http://localhost:5173` (Vite dev server) or rebuild the frontend image.

### 3. First Login

Visit https://localhost — click Google Sign-In. First user is auto-created (no manual user creation needed).

### 4. Seed Stock Data

```bash
# Seed Thai + US base stocks
docker-compose -f docker-compose.dev.yml exec backend python scripts/seed_stocks.py

# Seed international markets (JP/HK/UK/DE/CN/FR/NL/KR) from Wikipedia
docker-compose -f docker-compose.dev.yml exec backend python scripts/fetch_real_constituents.py
```

### 5. Stop Services

```bash
docker-compose -f docker-compose.dev.yml down
```

---

## Development Workflow

### Backend Changes (Instant)

Backend uses `uvicorn --reload` — save any Python file and it auto-restarts:

```bash
docker-compose -f docker-compose.dev.yml logs -f backend
```

### Frontend Changes (Requires Image Rebuild)

The frontend container runs a TanStack Start / Nitro SSR build. Source file edits in `frontend/src/` do NOT auto-apply to the production bundle.

```bash
# Option 1: Use Vite dev server at http://localhost:5173 (HMR, instant)
# Option 2: Rebuild production bundle
docker-compose -f docker-compose.dev.yml build frontend
docker-compose -f docker-compose.dev.yml up -d frontend
```

### Celery Worker Changes

After modifying any `workers/*.py` file:

```bash
docker-compose -f docker-compose.dev.yml build backend
docker-compose -f docker-compose.dev.yml up -d celery celery-beat
```

### After Any Task

1. Verify changes work: `curl https://localhost/api/health`
2. Update `changelog.md`
3. Mark task complete in `tasklist.md`

---

## Project Structure

```
ShotockViz/
├── docker-compose.dev.yml       ← USE THIS FOR DEV
├── docker-compose.prod.yml      ← PROD ONLY
├── .env                         ← Local secrets (not committed)
├── .env.example                 ← Template
│
├── frontend/                    ← React 19 + TanStack Start (SSR)
│   ├── src/
│   │   ├── routes/              ← Pages (TanStack file-based routing)
│   │   ├── components/          ← UI components
│   │   │   ├── chart/           ← TradingChart, ChartToolbar, RightPanel
│   │   │   ├── common/          ← Sidebar, WatchlistSearch, Navbar, AIChatPanel
│   │   │   ├── modals/          ← SearchModal, SettingsModal, DrawingModal
│   │   │   ├── pages/           ← AlertsPage, ScreenerPage, NewsPage
│   │   │   ├── portfolio/       ← HoldingsTable, AddTransactionModal
│   │   │   ├── dashboard/       ← IndexCards, TopMovers, AlertsNearTarget
│   │   │   └── ui/              ← ErrorState, EmptyState, LoadingState
│   │   ├── store/               ← Zustand (appStore, authStore)
│   │   ├── services/            ← API clients (stockService, portfolioService, etc.)
│   │   ├── hooks/               ← useChartData, usePortfolioData, usePriceUpdates
│   │   └── utils/               ← formatters (parseSymbol, MARKET_COLORS, MARKET_CURRENCY)
│   └── vite.config.ts
│
├── backend/                     ← FastAPI + Python 3.13
│   ├── main.py                  ← App entry, routers, WebSocket manager
│   ├── api/routes/              ← 13 route modules
│   ├── services/                ← Business logic
│   │   ├── stock_service.py     ← Facade (re-exports from sub-modules)
│   │   ├── providers/           ← yahoo_provider, stooq_provider
│   │   ├── generators/          ← synthetic_bars
│   │   └── cache_orchestrator.py ← 4-layer cache logic
│   ├── workers/                 ← Celery tasks (10 workers)
│   │   ├── helpers/             ← symbol_loader, cache_publisher, task_timing
│   │   ├── price_fetcher.py     ← Round-robin across 5 market slots
│   │   ├── alert_checker.py
│   │   ├── name_fetcher.py
│   │   ├── fundamentals_fetcher.py
│   │   ├── fund_fetcher.py      ← Thai mutual fund NAV
│   │   ├── history_prefetcher.py
│   │   ├── on_demand_listener.py
│   │   ├── symbol_registrar.py
│   │   ├── index_populator.py
│   │   └── housekeeping.py
│   ├── models/                  ← SQLAlchemy ORM models + Pydantic schemas
│   ├── core/                    ← config, database, redis, cache_keys, symbol_utils
│   └── scripts/                 ← seed_stocks, fetch_real_constituents, check_intl_symbols
│
├── caddy/                       ← Reverse proxy config (Caddyfile.dev, Caddyfile.prod)
├── CLAUDE.md                    ← AI agent quick reference
├── REQUIREMENTS.md              ← Canonical SRS (features, schema, API)
├── INSTRUCTIONS.md              ← This file
├── master_plan.md               ← Strategic roadmap
├── tasklist.md                  ← Sprint task tracking
├── changelog.md                 ← Version history
└── trade-prompt.md              ← Pine Script strategy library
```

---

## Environment Variables

```env
# Required
DATABASE_URL=postgresql://stockviz:password@db:5432/stockviz_db
REDIS_URL=redis://redis:6379/0
JWT_SECRET_KEY=<generate: openssl rand -hex 32>
GOOGLE_CLIENT_ID=<your-google-client-id>.apps.googleusercontent.com

# Optional — enhances features
FINNHUB_API_KEY=<free tier at finnhub.io>
TELEGRAM_BOT_TOKEN=<for alert notifications>
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2
TZ=Asia/Bangkok
```

> **Google OAuth setup:** Create an OAuth 2.0 Client ID in Google Cloud Console. Add `https://localhost` to Authorized JavaScript origins (dev) and your production domain for prod.

---

## Database Management

```bash
# Access DB shell
docker-compose -f docker-compose.dev.yml exec db psql -U stockviz -d stockviz_db

# Initialize schema (first time)
docker-compose -f docker-compose.dev.yml exec backend python -c \
  "import asyncio; from core.database import init_db; asyncio.run(init_db())"

# Backup
docker-compose -f docker-compose.dev.yml exec db \
  pg_dump -U stockviz stockviz_db > backup_$(date +%Y%m%d).sql

# Restore
docker-compose -f docker-compose.dev.yml exec -T db \
  psql -U stockviz stockviz_db < backup.sql

# Check international market data
docker-compose -f docker-compose.dev.yml exec backend python scripts/check_intl_symbols.py
```

---

## Celery Workers

```bash
# Check worker status
docker-compose -f docker-compose.dev.yml exec celery \
  celery -A workers.celery_app inspect active

# View worker logs
docker-compose -f docker-compose.dev.yml logs -f celery
docker-compose -f docker-compose.dev.yml logs -f celery-beat

# Trigger specific task manually
docker-compose -f docker-compose.dev.yml exec backend \
  celery -A workers.celery_app call workers.price_fetcher.fetch_prices

# Trigger index populator (seed international markets)
docker-compose -f docker-compose.dev.yml exec backend \
  celery -A workers.celery_app call workers.index_populator.populate_index_constituents
```

---

## Testing

```bash
# Backend tests
docker-compose -f docker-compose.dev.yml exec backend pytest tests/ -v

# Quick API smoke test
curl https://localhost/api/health
curl https://localhost/api/stocks/NVDA/history?tf=1D | python3 -m json.tool | head -20
```

---

## Coding Standards

### Python (Backend)

- Max **500 lines per file**, **40 lines per function**
- **Type hints** on all function signatures
- **Docstrings** (Google format) on all public functions
- Import order: stdlib → third-party → local
- Use `structlog` / `get_logger(__name__)` for logging
- Prefer `async def` for I/O-bound operations
- Never bare `except:` — catch specific exceptions

### JavaScript/TypeScript (Frontend)

- Use **TypeScript** for new files (`.tsx`/`.ts`)
- Custom hooks for all non-trivial logic (no inline `useEffect` soup)
- All API calls go through `services/` — never `fetch()` directly in components
- Use **AbortController** on fetch calls in `useEffect` to prevent race conditions
- Clean up **all** side effects: `clearInterval`, `clearTimeout`, `abort()` in `useEffect` return
- **Zustand stores** for cross-component state; local `useState` for UI-only state
- **Named exports** preferred (tree-shaking friendly)

---

## Troubleshooting

### Frontend shows old data after source edit
The frontend at `https://localhost` is a production build. Use `http://localhost:5173` for HMR dev server, or rebuild: `docker-compose -f docker-compose.dev.yml build frontend`

### No price data showing
Celery workers populate the Redis quote cache. Check if workers are running:
```bash
docker-compose -f docker-compose.dev.yml ps
docker-compose -f docker-compose.dev.yml logs celery
```

### International symbols missing
Run the real constituents seeder:
```bash
docker-compose -f docker-compose.dev.yml exec backend python scripts/fetch_real_constituents.py
```

### Google Login not working
Verify `GOOGLE_CLIENT_ID` is set in `.env` and `https://localhost` is added to authorized origins in Google Cloud Console.

### AI Chat not responding
Ollama must be running and a model pulled:
```bash
docker-compose -f docker-compose.dev.yml exec ollama ollama pull llama3.2
```

### WebSocket errors
Check Caddy proxy config: `docker-compose -f docker-compose.dev.yml logs caddy`. Ensure WebSocket upgrade is configured in Caddyfile.

---

*See `REQUIREMENTS.md` for feature specs. See `master_plan.md` for roadmap. See `tasklist.md` for current sprint.*
