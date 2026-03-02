# ShotockViz — Development Instructions

**Version:** 2.0
**Last Updated:** 2026-03-01
**Project:** ShotockViz — Self-hosted Stock Analysis Platform (Thai + US Markets)

---

## ⚠️ Critical Rules

1. **NEVER run any server directly on the host machine** — no `uvicorn`, `npm run dev`, `python`, `node` etc. executed bare. Everything runs inside Docker containers only.
2. **Development ONLY uses `docker-compose.dev.yml`** — never use prod compose for local work, never `docker run` individual containers manually
3. **After completing any task → update `changelog.md`** immediately
4. **Update `tasklist.md`** to mark completed items `[x]`
5. **Frontend changes require rebuilding the Docker image** — source edits alone don't affect the running production bundle. Run:
   ```bash
   docker-compose -f docker-compose.dev.yml build frontend
   docker-compose -f docker-compose.dev.yml up -d frontend
   ```

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

### ❌ Never Do These
```bash
uvicorn main:app              # ❌ direct server
python backend/main.py        # ❌ direct python
npm run dev                   # ❌ direct node
node server.js                # ❌ direct node
pip install <pkg>             # ❌ install on host (use exec backend pip install)
```

---

## Quick Start

### Prerequisites

- Docker & Docker Compose v2.0+
- Git
- 4GB+ RAM, 10GB+ free disk

### 1. Clone & Configure

```bash
git clone <repo-url>
cd ShotockViz
cp .env.example .env
# Edit .env with your secrets (JWT_SECRET_KEY required)
```

### 2. Start Dev Environment

```bash
docker-compose -f docker-compose.dev.yml up
```

**Dev Services:**

| Service | URL | Notes |
|---------|-----|-------|
| Frontend (Vite HMR) | http://localhost:5173 | Hot reload on save |
| Backend API | http://localhost:8000 | Auto-restart on save |
| API Docs | http://localhost:8000/docs | Swagger UI |
| Reverse Proxy | http://localhost | Caddy (routes to both) |
| pgAdmin | http://localhost:5050 | Optional DB GUI |

> **Note:** The running app at `http://localhost` is the **production build** served by the frontend container. For live frontend changes, use `http://localhost:5173` (Vite dev server) or rebuild the frontend image.

### 3. Create First User

```bash
docker-compose -f docker-compose.dev.yml exec backend python scripts/create_user.py
```

### 4. Seed Stock Metadata (Thai + US)

```bash
docker-compose -f docker-compose.dev.yml exec backend python scripts/seed_stocks.py
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
# Watch backend logs
docker-compose -f docker-compose.dev.yml logs -f backend

# Watch all
docker-compose -f docker-compose.dev.yml logs -f
```

### Frontend Changes (Requires Image Rebuild)

The frontend container runs a **Node.js production build** (TanStack Start / Nitro). Source file edits in `frontend/src/` do NOT auto-apply.

**For frontend changes:**

```bash
# Option 1: Use Vite dev server at http://localhost:5173 (HMR, instant)
docker-compose -f docker-compose.dev.yml logs -f frontend

# Option 2: Rebuild production bundle after changes
docker-compose -f docker-compose.dev.yml build frontend
docker-compose -f docker-compose.dev.yml up -d frontend
```

### After Any Task

```bash
# 1. Verify changes work
curl http://localhost/api/health

# 2. Update changelog.md (REQUIRED)
# Add entry under ## [Unreleased] section

# 3. Mark task complete in tasklist.md
# Change [ ] to [x]
```

---

## Project Structure

```
ShotockViz/
├── docker-compose.dev.yml       ← ✅ USE THIS FOR DEV
├── docker-compose.prod.yml      ← ⛔ PROD ONLY
├── .env                         ← Local secrets (not committed)
├── .env.example                 ← Template
├── .env.production              ← Prod template
│
├── frontend/                    ← React 19 + TanStack Start
│   ├── src/
│   │   ├── routes/              ← Pages (TanStack file-based routing)
│   │   ├── components/          ← UI components
│   │   │   ├── chart/           ← TradingChart, ChartToolbar, RightPanel
│   │   │   ├── common/          ← Sidebar, Navbar, AIChatPanel
│   │   │   ├── modals/          ← SearchModal, SettingsModal
│   │   │   └── pages/           ← Page-level components
│   │   ├── store/               ← Zustand (appStore, authStore, chartStore)
│   │   ├── services/            ← API clients (stockService, etc.)
│   │   ├── hooks/               ← Custom hooks
│   │   └── utils/               ← Formatters, validators, helpers
│   ├── .output/                 ← Production build output (auto-generated)
│   │   ├── server/              ← Nitro SSR server
│   │   └── public/              ← Static assets
│   └── vite.config.ts
│
├── backend/                     ← FastAPI + Python 3.13
│   ├── main.py                  ← App entry, routers, WebSocket
│   ├── api/routes/              ← 13 route modules
│   ├── services/                ← Business logic (stock_service.py key)
│   ├── workers/                 ← Celery tasks (price_fetcher, alert_checker)
│   ├── models/                  ← SQLAlchemy ORM models + Pydantic schemas
│   ├── core/                    ← Config, security, database, logger
│   └── scripts/                 ← create_user.py, seed_stocks.py
│
├── caddy/                       ← Reverse proxy config
├── master_plan.md               ← Feature roadmap & vision
├── tasklist.md                  ← Current sprint task breakdown
├── changelog.md                 ← What changed and when
└── INSTRUCTIONS.md              ← This file
```

---

## Environment Variables

```env
# Required
DATABASE_URL=postgresql://stockviz:password@db:5432/stockviz_db
REDIS_URL=redis://redis:6379/0
JWT_SECRET_KEY=<generate: openssl rand -hex 32>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Optional — enhances features
FINNHUB_API_KEY=<free tier at finnhub.io>
TELEGRAM_BOT_TOKEN=<for alert notifications>
GOOGLE_CLIENT_ID=<for Google OAuth>
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2

# App
APP_ENV=development
DEBUG=True
TZ=Asia/Bangkok
```

Generate JWT secret:
```bash
openssl rand -hex 32
```

---

## Database Management

```bash
# Access DB shell
docker-compose -f docker-compose.dev.yml exec db psql -U stockviz -d stockviz_db

# Run migrations (create tables)
docker-compose -f docker-compose.dev.yml exec backend python -c \
  "import asyncio; from core.database import init_db; asyncio.run(init_db())"

# Backup
docker-compose -f docker-compose.dev.yml exec db \
  pg_dump -U stockviz stockviz_db > backup_$(date +%Y%m%d).sql

# Restore
docker-compose -f docker-compose.dev.yml exec -T db \
  psql -U stockviz stockviz_db < backup.sql

# Check health
curl http://localhost/api/health
```

---

## Celery Workers

```bash
# Check worker status
docker-compose -f docker-compose.dev.yml exec celery-worker \
  celery -A workers.celery_app inspect active

# Check scheduled tasks
docker-compose -f docker-compose.dev.yml exec celery-beat \
  celery -A workers.celery_app inspect scheduled

# Monitor via Flower (if configured)
curl http://localhost:5555

# View worker logs
docker-compose -f docker-compose.dev.yml logs -f celery-worker
docker-compose -f docker-compose.dev.yml logs -f celery-beat
```

---

## Testing

```bash
# Backend tests
docker-compose -f docker-compose.dev.yml exec backend pytest tests/ -v

# With coverage
docker-compose -f docker-compose.dev.yml exec backend pytest tests/ --cov=. --cov-report=html

# Frontend e2e
docker-compose -f docker-compose.dev.yml exec frontend npm run test:e2e

# Quick API smoke test
curl http://localhost/api/health
curl http://localhost/api/stocks/NVDA/history?tf=1D | python3 -m json.tool | head -20
```

---

## Coding Standards

### Python (Backend)

- Max **300 lines per file**, **40 lines per function**
- **Type hints** on all function signatures
- **Docstrings** (Google format) on all public functions
- Import order: stdlib → third-party → local
- Use `structlog` / `get_logger(__name__)` for logging
- Prefer `async def` for I/O-bound operations
- Never bare `except:` — catch specific exceptions

```python
# ✅ Good pattern
async def fetch_stock_quote(symbol: str) -> Optional[StockQuote]:
    """Fetch current stock quote from cache.

    Args:
        symbol: Uppercase ticker symbol (e.g. "NVDA", "PTT.BK")

    Returns:
        StockQuote if cached, None if pending background fetch.
    """
    cache_key = f"cache:quote:{symbol}"
    try:
        r = await get_redis()
        cached = await r.get(cache_key)
        return StockQuote(**json.loads(cached)) if cached else None
    except Exception as e:
        logger.error("Redis quote cache read failed", error=str(e))
        return None
```

### JavaScript/TypeScript (Frontend)

- Use **TypeScript** for new files (`.tsx`/`.ts`)
- Custom hooks for all non-trivial logic (no inline `useEffect` soup)
- All API calls go through `services/` — never `fetch()` directly in components
- Use **AbortController** on fetch calls in `useEffect` to prevent race conditions
- Clean up **all** side effects: `clearInterval`, `clearTimeout`, `abort()` in `useEffect` return
- **Zustand stores** for cross-component state; local `useState` for UI-only state

```tsx
// ✅ Stable interval pattern (prevents memory leaks)
const refreshRef = useRef(refreshFn);
useEffect(() => { refreshRef.current = refreshFn; }, [refreshFn]);

useEffect(() => {
  const t = setInterval(() => refreshRef.current(), 15_000);
  return () => clearInterval(t);          // cleanup
}, []);  // mount once only

useEffect(() => { refreshRef.current(); }, [dataVersion]);  // trigger on version bump
```

---

## Troubleshooting

### Frontend shows old data after source edit

The frontend at `http://localhost` is a production build. Use:
- `http://localhost:5173` for HMR dev server, OR
- `docker-compose -f docker-compose.dev.yml build frontend` to rebuild

### PTT.BK chart is empty

Yahoo Finance occasionally rate-limits Thai stock requests. The backend returns `bars: []` and the chart retries up to 3× every 4 seconds. If still empty after 15 seconds, click NVDA or another US stock.

### All quotes show `—` (202 responses)

Celery workers populate the Redis quote cache. If workers aren't running:
```bash
docker-compose -f docker-compose.dev.yml ps  # verify celery-worker is Up
docker-compose -f docker-compose.dev.yml logs celery-worker
```
The backend also has an asyncio fallback that caches quotes in ~5 seconds.

### Fundamentals show `—`

Fundamentals are fetched live from Yahoo Finance quoteSummary API. First call may take 8–12 seconds. Check `/api/stocks/NVDA/fundamentals` — if it returns 404, Yahoo Finance auth may have expired (auto-retries on next request).

### AI Chat not responding

Ollama must be running and a model pulled:
```bash
docker-compose -f docker-compose.dev.yml exec ollama ollama pull llama3.2
docker-compose -f docker-compose.dev.yml logs ollama
```

---

*See `master_plan.md` for feature roadmap. See `tasklist.md` for current sprint.*
