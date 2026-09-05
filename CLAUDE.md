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
| Background | Celery 5.6 + Beat (price, names, fundamentals, fund NAV, history prefetch, alerts) |
| Data | Yahoo Finance + pythainav (Thai fund NAV) + Stooq (US fallback) |
| Proxy | Caddy 2 (reverse proxy + auto TLS) |

## Docker Commands

```bash
docker-compose -f docker-compose.dev.yml up -d          # Start all
docker-compose -f docker-compose.dev.yml build <service> # Rebuild
docker-compose -f docker-compose.dev.yml logs -f <svc>   # Logs
docker-compose -f docker-compose.dev.yml exec backend bash  # Shell into container
docker-compose -f docker-compose.dev.yml down            # Stop all
```

## Production Deployment

> **New standalone droplet (68.183.182.190) via GitHub Actions → GHCR → server pull** —
> see `docs/deploy-gha.md`, `.github/workflows/deploy.yml`, `docker-compose.ghcr.yml`.
> The section below still describes the OLD shared-droplet flow (`docs/deploy.md`,
> `scripts/deploy.sh`, `docker-compose.prod.yml`) — unchanged, kept for that droplet.
>
> **Resource limits on this droplet** (`docker-compose.ghcr.yml`, 2 vCPU / 2 GB / 1 GB
> swap box): backend 1 CPU/512M, celery-worker 0.5 CPU/**512M** (raised from 256M
> 2026-09-05, bd:shotockviz-3tr — the 2026-09-05 rebuild soak in `changelog.md` showed
> it pinned at 251/256 MiB even at idle once `celery-beat` started firing
> `fetch_prices` every 60s), celery-beat 0.5 CPU/256M, telegram-bot 0.25 CPU/128M,
> frontend 0.5 CPU/256M. Sum of hard limits = 1664M, leaving ~384M of the 2048M for
> db/redis/caddy/OS (uncapped); the soak observed ~820M free at the old 256M
> celery-worker limit, so ~564M free is the conservative expectation post-bump.
> **Pending until the next deploy runs** — this is a compose-file change only; the
> containers actually running on the droplet still have the old 256M limit.

**Server:** DigitalOcean droplet shared with ShoDe Town (`town.shode.dev`). Caddy is managed by ShoDe Town — ShotockViz does NOT run its own Caddy.

**Domain:** `stock.shode.dev` → A record to droplet IP. SSH via `Host do` alias.

```bash
# Deploy (rsync + build + up + migrate + healthcheck)
bash scripts/deploy.sh

# Check status
ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml ps'

# Backend logs
ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml logs backend --tail=50'

# Celery logs
ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml logs celery-worker --tail=30'

# DB shell
ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml exec db psql -U stockviz -d stockviz_prod'

# Run migrations
ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head'
```

**Architecture:**
```
Client → [ShoDe Town Caddy :443] (shared-proxy network)
  ├─ town.shode.dev  → ShoDe Town
  └─ stock.shode.dev → ShotockViz
      ├─ /api/ws/*    → stockviz-backend:8000 (WebSocket)
      ├─ /api/health  → stockviz-backend:8000 (unversioned, infra healthcheck)
      ├─ /api/v1/*    → stockviz-backend:8000 (REST, {data,meta} envelope)
      └─ /*           → stockviz-frontend:3000 (Nitro SSR)
```

> bd:deps-2026-09 S2 (ADR-001 r3) — REST moved under `/api/v1` with a
> `{data, meta}` response envelope (ADR-002) on all 13 route modules.
> `/api/ws/prices` and `/api/health` are the 2 deliberate
> unversioned exceptions (WS protocol, infra healthcheck contract).
> No legacy `/api` alias — frontend and backend flipped together in
> one commit.

**Prod `.env`:** `/root/shotockviz/.env` — must have `GOOGLE_CLIENT_ID`, `VITE_GOOGLE_CLIENT_ID`, `JWT_SECRET_KEY`, `DATABASE_URL` (asyncpg), etc. See `docs/deploy.md` for full list.

**⚠️ VITE_* vars are build-time only** — changing them requires `docker compose build frontend`, not just restart.

**Resource Limits:** Backend 1 CPU/512M, Celery 0.5 CPU/256M each, Frontend 0.5 CPU/256M. Total ~1.9GB RAM.

## Project Structure (Key Files)

```
ShotockViz/
├── backend/
│   ├── api/routes/          # 13 endpoint modules (auth, stocks, watchlist, portfolio, alerts, screener, etc.)
│   ├── models/              # SQLAlchemy ORM (User, Stock, StockPrice1m, Transaction, Alert, Drawing, Note, StockEvent)
│   ├── services/            # stock_service.py (47KB), cache_service.py
│   ├── workers/             # Celery: price_fetcher, name_fetcher, fundamentals_fetcher, fund_fetcher, history_prefetcher, on_demand_listener, alert_checker, housekeeping
│   ├── core/                # config, database, redis, security
│   └── main.py              # FastAPI app + WebSocket manager
├── frontend/
│   ├── src/routes/          # 8 pages (__root.tsx, chart, dashboard, portfolio, alerts, screener, news, login)
│   ├── src/components/      # 29 React components (chart/, common/, modals/, pages/)
│   ├── src/store/           # Zustand: appStore.js, authStore.js
│   ├── src/services/        # api.js
│   └── src/styles/          # Tailwind + glassmorphism CSS
├── docker-compose.dev.yml   # 8-service dev stack
├── caddy/                   # Caddyfile (prod, baked into the GHCR image), Caddyfile.dev
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
| `docs/engagements/<bd-id>.md` | Durable record of one engagement: ADRs, verification evidence, review outcome, follow-ups | When an engagement closes — process trail lives in gitignored `outputs/` and is consolidated here before that folder is removed |
| `bd` (beads) | **Single source of truth for open work.** `bd list` / `bd show <id>` | Every task — do not keep TODO lists in markdown |

## Current Status & Priorities

**Phase 1 (Stabilization):** ✅ Complete — critical fixes applied, fast-response pattern implemented.
**Phase 2 (CQRS Refactor):** ✅ Complete — API pure-read, 5 new Celery workers created.
**Phase 3 (Data Completeness):** 🔧 In progress — Thai fund NAV + data gaps.

### Current Priorities
1. **Frontend Docker rebuild** — compiled bundle outdated, source fixes not active
2. **Backend Docker rebuild** — new Celery workers need to be registered
3. **Verify CQRS flow** — API returns cache-only → Celery fetches → WS notifies → client re-fetches
4. **Thai Fund NAV** — pythainav integration via `fund_fetcher.py` (daily at 19:00 ICT)
5. **Fix sidebar names** — `name_fetcher.py` pre-populates all company names

### Completed
- ✅ All API endpoints respond < 5s (cache-only reads)
- ✅ WebSocket `data_ready` notification pattern
- ✅ PTT.BK retry logic fixed
- ✅ Cache key consistency fixed across 5 files
- ✅ Memory leak fixes in 4 frontend components
- ✅ 5 new Celery workers (name, fundamentals, fund, history, on-demand)

### See Also
- Full priority breakdown → `ShotockViz_Development_Plan.docx`
- Task checklist → `tasklist.md`
- Feature specs → `REQUIREMENTS.md`

## Key Architecture Decisions

- **CQRS (Command Query Responsibility Segregation)** — API endpoints are pure-read (Redis/PostgreSQL only). Celery workers are the sole data ingesters (Yahoo Finance, pythainav, Stooq). On cache miss, API triggers Celery task via `request_data_fetch()` → worker fetches → caches → publishes WS `data_ready` → frontend re-fetches automatically.
- **2-layer read cache (API side)** — Redis L1 (sub-ms) → PostgreSQL L2 (10-50ms). API never touches external services.
- **Celery write side** — 8 workers: `price_fetcher` (quotes), `name_fetcher` (company names), `fundamentals_fetcher` (PE/PB/EPS), `fund_fetcher` (Thai NAV via pythainav), `history_prefetcher` (OHLCV warm cache), `on_demand_listener` (API cache-miss handler), `alert_checker`, `housekeeping`
- **TimescaleDB hypertable** — `StockPrice1m` + `ohlcv_bars` for efficient time-series queries with auto-compression
- **WebSocket push** — Redis pub/sub `price_updates` channel → WebSocket broadcast: `price_update`, `data_ready`, `nav_update`, `alert_triggered`, `names_ready`
- **Google OAuth** — `@react-oauth/google` with `useGoogleOneTapLogin` in `__root.tsx` for seamless re-auth. **NO custom token management code on frontend.**
- **Thai Fund NAV** — `pythainav` library fetches from SEC Thailand / บลจ. websites. Daily at 19:00 ICT (T+1 delay acceptable).

## Market Hours (ICT timezone)

| Market | Hours | Notes |
|--------|-------|-------|
| SET | 10:00-12:30, 14:00-16:30 | Break 12:30-14:00 |
| US (NYSE/NASDAQ) | 21:30-04:00 (next day) | Pre-market from 20:00 |
| Celery price fetch | Every 1 min during market hours | via celery-beat schedule |
| Celery names | Every 6 hours | prefetch_names |
| Celery fundamentals | Every 4 hours | prefetch_fundamentals |
| Celery fund NAV | Daily 19:00 ICT | fetch_thai_fund_navs |
| Celery history | Every 30 min | prefetch_history |

## Environment Variables

See `.env.example` for full list. Key vars:
- `DATABASE_URL` — PostgreSQL connection
- `REDIS_URL` — Redis connection
- `JWT_SECRET_KEY` — Token signing
- `FINNHUB_API_KEY` — Free tier for enhanced data
- `TELEGRAM_BOT_TOKEN` — Alert notifications
- `GOOGLE_CLIENT_ID` — OAuth login

## Stakeholder Context

Primary user is an experienced Thai+US stock trader (8yr SET, 4yr US). Swing + position trading. Watchlist 40-60 symbols. Uses fundamentals + technical analysis. Trades during SET hours and monitors US pre-market at 20:00 ICT. The `stock-trader-stakeholder` skill in `.skills/` provides this persona for feature prioritization and UX feedback.

## Known Issues & Recent Fixes

- **CQRS refactor (2026-03-03)** — API endpoints no longer call external APIs. All data from cache/DB. Celery workers are sole data ingesters. 5 new workers created.
- **Fast-response pattern (2026-03-02)** — All API endpoints respond < 5s. Background fetch + WS `data_ready` notification.
- **Cache key mismatch** — Fixed for API endpoints: they now use `cache_keys.*()` functions (was hardcoded f-strings). **That pass missed `workers/alert_checker.py:70`, which still builds `cache:quote:{sym}` by hand while the cache writes `quote:{sym}` — so price alerts never fire at all.** Measured on the dev stack: 0 keys match `cache:quote:*`, 31 match `quote:*`. Tracked as `bd:shotockviz-983` (P0).
- **Memory leaks** — Fixed in source: setInterval leaks in Sidebar, Dashboard, TradingChart
- **Race condition** — Fixed: AbortController in RightPanel for stale XHR after symbol change
- **PTT.BK empty data** — Fixed: explicit `data_received` flag in retry loop
- **Alert field crash** — Fixed: `a.target_price` → `a.value` in dashboard.py
- **Hydration mismatch** — Harmless: browser extension `cz-shortcut-listen` attribute on body

## Celery Workers (CQRS Write Side)

| Worker | Schedule | Data Source | Cache Key |
|--------|----------|-------------|-----------|
| `price_fetcher` | 1min (market hours) | yfinance batch | `quote:{symbol}` |
| `name_fetcher` | 6h | yfinance info | `cache:name:{symbol}` |
| `fundamentals_fetcher` | 4h | yfinance info | `fundamentals:{symbol}` |
| `fund_fetcher` | Daily 19:00 ICT | pythainav (SEC) | `fund:{symbol}` |
| `history_prefetcher` | 30min | yfinance history | `ohlcv:{symbol}:{tf}` |
| `on_demand_listener` | On API cache miss | yfinance | varies |
| `alert_checker` | 60s | Redis cache read | — |
| `housekeeping` | Daily 03:00 ICT | PostgreSQL | — |


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
