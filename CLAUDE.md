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
6. **NEVER write a polling loop that waits on another task.** No
   `until grep ... ; do sleep N; done`, no `while [ ! -f x ]`, no "kick off
   a background run and watch for its output". Run the command in the
   foreground and read its exit status.

   This cost 15.5 hours on 2026-09-05: a loop was left watching a file for
   `passed|failed`, the wrapped job only ever wrote `PID:…` and `[exited
   with code 0]`, so the condition could never become true and it slept in
   a loop ~5,600 times until someone noticed it in the task panel. It also
   produced two agent hand-backs with no results at all, because the agent
   returned "waiting for the background run" instead of an answer.

   The long jobs here are known and bounded — the full E2E suite is ~5
   minutes, the backend suite ~25 seconds, a production image build ~1
   minute. All of them finish well inside a normal command timeout. If
   something genuinely must run detached, it is the caller's job to
   collect it, and a waiting condition that can never be satisfied is a
   hang, not a wait.

7. **Never run two agents on the same file in one working tree.** There is
   no `git worktree` isolation between concurrent agent sessions here — they
   share one checkout. Give each agent a disjoint file set up front, and
   before committing on behalf of one, check `git diff` for edits that
   belong to another.

   This produced a broken commit on 2026-09-06. `backend/api/routes/
   portfolio.py` and `backend/models/schemas.py` were each needed by two
   agents. Committing one agent's work captured the other's half-finished
   endpoint wiring, and the resulting commit was not importable —
   `ImportError: cannot import name 'PortfolioConcentration' from
   'models.schemas'`, because the schema it imported was still uncommitted
   in the other agent's file. Caught only by explicitly stashing the tree
   and importing at HEAD; the test suite was green the whole time, because
   the suite runs against the *working tree*, not against the commit.

   Two consequences worth keeping: a green suite is not evidence that a
   commit builds, and once edits are interleaved, splitting them back apart
   after the fact means hunk surgery — one honest commit naming every bead
   it contains beats three tidy ones that do not build.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 + TanStack Start (SSR) + Vite 7 + Tailwind 4 + Zustand 5 |
| Charts | TradingView Lightweight Charts v5 |
| Backend | FastAPI (Python 3.13) + SQLAlchemy 2 + Pydantic 2 |
| Database | PostgreSQL 16 + TimescaleDB (time-series) |
| Cache | Redis 7 (caching + Celery broker + WebSocket pub/sub) |
| Background | Celery 5.6 + Beat — **20** registered task modules (`backend/workers/celery_app.py:13-34`), not 8 — see § Celery Workers |
| Data | Yahoo Finance + SEC Open Data API (Thai fund NAV, Finnomena fallback — no `pythainav` dependency, `backend/requirements.txt:59`) + Stooq (US fallback) |
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

> This section describes the product **as of 2026-09-06** — it is a snapshot,
> not a running log. `bd:shotockviz-24c`/`8v9` rewrote it because the
> previous version listed 5 priorities that were all done or superseded, and
> Patrick was handed it as session context and got misrouted by it directly.

**Phase 1 (Stabilization) / Phase 2 (CQRS Refactor):** ✅ Complete and stable
— superseded by two production deploys since. The 5 priorities and 5
"Completed" items formerly listed here (frontend/backend Docker rebuild,
verify CQRS flow, Thai Fund NAV, fix sidebar names) are all done; see
`docs/engagements/backlog-2026-09.md` for the record.

**What is actually true today:**
- **Alerts**: all 7 types (Price Above/Below, RSI Overbought/Oversold,
  Golden/Death Cross, Volume Spike) are evaluated by `alert_checker.py`
  (`bd:shotockviz-06e`) — not just the 2 price types. Telegram is the only
  notification channel (`bd:shotockviz-675`).
- **Portfolio valuation**: current market-value totals + an allocation
  breakdown are implemented (`bd:shotockviz-916`,
  `backend/services/portfolio_service.py`). Sharpe Ratio, Beta, and Max
  Drawdown are struck from scope, not just unbuilt — no flow-adjusted
  portfolio return series exists to compute them from
  (`REQUIREMENTS.md` FR-PORT-003).
- **WebSocket auth + rate limiting**: `/api/ws/prices` requires an auth
  token (`backend/main.py:356`, `websocket_prices(ws, token)`); REST
  endpoints are rate-limited per IP/user
  (`backend/api/middleware/rate_limit.py`, exercised by
  `backend/tests/test_quotes_rate_limit.py` and
  `test_rate_limit_proxy_boundary_live.py`).
- **Quality gates are green**: `npx tsc --noEmit -p .` is clean under
  `"strict": true` (flipped 2026-09-06, `bd:shotockviz-9z0`,
  `frontend/tsconfig.json:36`), and the Playwright E2E suite passed
  226/226 the same day (`changelog.md`, "TypeScript strict mode enabled —
  type gate is finally honest" entry, "Gates:" line).
- **Migrations**: Alembic head is `20260906_0008_alert_value_as_of`, 8
  migrations on disk (`backend/db/migrations/versions/`) — this is not a
  TODO, it is the schema-versioning mechanism in active use.

**Known, currently-true documentation gaps:** `REQUIREMENTS.md` carries 11
FR/NFR claims that describe features not actually built as written
(Ichimoku, Stochastic, indicator parameter/colour controls, Compare Mode,
"1D → 1 year" history range, RSI min/max screener filter, multi-watchlist
creation UI, aggregate-then-delete + auto-compression housekeeping) — each
is now marked `Status: Deferred` in place with what is actually there
instead, per `bd:shotockviz-24c`.

### See Also
- Full priority breakdown → `ShotockViz_Development_Plan.docx`
- Task checklist → `tasklist.md`
- Feature specs → `REQUIREMENTS.md`

## Key Architecture Decisions

- **CQRS (Command Query Responsibility Segregation)** — API endpoints are pure-read (Redis/PostgreSQL only). Celery workers are the sole data ingesters (Yahoo Finance, pythainav, Stooq). On cache miss, API triggers Celery task via `request_data_fetch()` → worker fetches → caches → publishes WS `data_ready` → frontend re-fetches automatically.
- **2-layer read cache (API side)** — Redis L1 (sub-ms) → PostgreSQL L2 (10-50ms). API never touches external services.
- **Celery write side** — **20** registered task modules
  (`backend/workers/celery_app.py:13-34`, not 8; this was stale at **18** —
  `pipeline_health` (landed 2026-09-06, `bd:shotockviz-5e7`) was already
  missing from this count before `gap_list_digest` below added a 20th):
  `price_fetcher` (quotes),
  `alert_checker`, `alert_symbol_refresher`, `housekeeping`, `name_fetcher`,
  `fundamentals_fetcher`, `fund_fetcher`, `history_prefetcher`,
  `on_demand_listener`, `symbol_registrar`, `index_populator`,
  `news_fetcher`, `sr_auto_pivot`, `sr_proximity_digest`, `pipeline_health`,
  `corporate_actions_fetcher`, `financials_history_fetcher`,
  `earnings_events_fetcher`, `fgi_fetcher`, `gap_list_digest`
  (`bd:shotockviz-06z`). Full schedule → § Celery Workers below.
- **TimescaleDB hypertable** — `StockPrice1m` + `ohlcv_bars` for efficient time-series queries with auto-compression
- **WebSocket push** — Redis pub/sub `price_updates` channel → WebSocket broadcast: `price_update`, `data_ready`, `nav_update`, `alert_triggered`, `names_ready`
- **Google OAuth** — `@react-oauth/google` with `useGoogleOneTapLogin` in `__root.tsx` for seamless re-auth. **NO custom token management code on frontend.**
- **Thai Fund NAV** — fetched directly from the SEC Open Data API
  (`api.sec.or.th`), with a Finnomena public-API fallback
  (`backend/workers/fund_fetcher.py:1-48`; `backend/requirements.txt:59`
  states explicitly "no pythainav dep" — that library is not installed and
  not used). Daily at 19:00 ICT (T+1 delay acceptable). Note: the same task
  also writes the NAV into `quote:{symbol}` (the same Redis key
  `price_fetcher` uses for live prices, `fund_fetcher.py:428-440`) with an
  86400s TTL vs. `price_fetcher`'s 120s — a fund symbol carrying a
  PRICE_ABOVE/BELOW alert will read a stale NAV as if it were a live quote.

## Market Hours (ICT timezone)

> **SET hours below are confirmed against the primary source**,
> [set.or.th "Trading Procedure — Trading Hours"](https://www.set.or.th/en/market/information/trading-procedure/trading-hours)
> (extended hours effective 2026-03-25): Pre-Open I 09:30-10:00, Trading
> Session I 10:00-12:30, Pre-Open II 13:30-14:00, Trading Session II
> 14:00-16:30, Pre-Close 16:30-close. `REQUIREMENTS.md:81` agrees
> (`10:00-16:30, break 12:30-14:00`). `master_plan.md` previously said
> `14:30-17:00` for the afternoon session — that was wrong (stale
> pre-extension figure that doesn't even match the pre-extension schedule)
> and has been corrected there to match this row.
> Separately: `backend/workers/price_fetcher.py:86` (`_set_hours`) gates
> fetching on a single continuous `02:30-09:45 UTC` (09:30-16:45 ICT)
> window with **no lunch-break gap** — this is a known, deliberate superset
> (extra polling 12:30-14:00 costs a few no-op yfinance calls, no
> trader-visible effect; not a doc/code mismatch worth fixing).

| Market | Hours | Notes |
|--------|-------|-------|
| SET | 10:00-12:30, 14:00-16:30 | Break 12:30-14:00 (source above) |
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
- `TELEGRAM_DRY_RUN` — leave unset. Outbound Telegram is real only when
  `APP_ENV=production`; anywhere else every notification is logged in full
  (`TELEGRAM DRY RUN — message NOT sent`) instead of being sent, even with a
  real token and a real chat id in the DB (`bd:shotockviz-4d9`,
  `backend/services/telegram_notify.py`). Set it to `false` to send for real
  from a non-production environment — a deliberate act, not a default. **This
  replaces the old instruction telling agents "do not send a real Telegram
  message": it is now enforced by code, and a test asserts that no module
  builds the Telegram API URL itself.**
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

> 20 modules registered in `backend/workers/celery_app.py:13-34`, not 8
> (`pipeline_health` and `gap_list_digest` were the two missing from the
> previously-stated 18 — see § Key Architecture Decisions above).
> Schedules below are from `celery_app.py` (`beat_schedule`).
>
> **⚠️ Every `crontab()` in `beat_schedule` is ICT, not UTC.** `conf.timezone`
> is `settings.tz` = `Asia/Bangkok`, and Celery evaluates crontab against
> `conf.timezone`; `enable_utc=True` only affects message headers. Until
> 2026-09-06 (`bd:shotockviz-rwq`) all 8 crontab entries were written as UTC
> with a `# = HH:MM ICT` comment, so every one of them fired **7 hours
> early** — the S/R digest reached the user at 02:30 and 12:30 ICT on a
> Sunday, and `housekeeping` was deleting rows at 20:00 ICT (US pre-market)
> instead of 03:00. Write the ICT wall-clock time you want; do not convert.
> `backend/tests/test_beat_schedule_ict.py` asserts the intended ICT time of
> each job.

| Worker | Schedule | Data Source | Cache Key |
|--------|----------|-------------|-----------|
| `price_fetcher` | 1min, round-robin across 6 market slots | yfinance batch | `quote:{symbol}` |
| `alert_symbol_refresher` | 60s | yfinance batch (active-alert symbols only) | `quote:{symbol}` |
| `alert_checker` | 60s | Redis cache read | — |
| `housekeeping` | Daily 03:00 ICT | PostgreSQL (delete-only past age cutoff, see REQUIREMENTS.md §3.2) | — |
| `name_fetcher` | 6h | yfinance info | `cache:name:{symbol}` |
| `fundamentals_fetcher` | 4h | yfinance info | `fundamentals:{symbol}` |
| `fund_fetcher` | Daily 19:00 ICT | SEC Open Data API + Finnomena fallback (no pythainav) | `fund:{symbol}` **and** `quote:{symbol}` (dual-write, 86400s TTL — see note above) |
| `history_prefetcher` | 30min (fills cold keys only; effective refresh is 6h per key TTL) | yfinance history | `ohlcv:{symbol}:{tf}` |
| `on_demand_listener` | On API cache miss | yfinance | varies |
| `symbol_registrar` | 15min (`scan-unregistered-symbols`) | yfinance (market classification) | `cache:name:{symbol}` |
| `index_populator` | Weekly, Sunday 00:00 ICT | Wikipedia (S&P 500, NASDAQ 100 constituent tables) | — (writes PostgreSQL) |
| `news_fetcher` | 30min | Google News RSS (`feedparser`) | `cache:news:{symbol}` |
| `sr_auto_pivot` | Daily 18:00 ICT | OHLCV bars → computed pivot levels | — (writes `sr_levels` table, `source='auto_pivot'`) |
| `sr_proximity_digest` | 2x/day: 09:30 ICT + 19:30 ICT, **weekdays only** | Reads `sr_levels` + quote cache → Telegram | — (read-only, sends Telegram) |
| `pipeline_health` | Every 5 min, plain-interval (not a crontab, no ICT/UTC concern) | Reads `quote:{symbol}` freshness for `price_fetcher`'s always-on canaries | — (read-only, sends Telegram on stale/recovered edge only) |
| `corporate_actions_fetcher` | Daily 02:00 ICT | yfinance (dividends/splits) | — (writes `stock_events` table) |
| `financials_history_fetcher` | Daily 01:00 ICT | yfinance (10y financial statements) | — (writes financials table) |
| `earnings_events_fetcher` | Daily 06:00 ICT | yfinance (EPS actual vs. estimate) | — (writes earnings_events table) |
| `fgi_fetcher` | 30min | CNN Fear & Greed Index | `fgi:current` |
| `gap_list_digest` | Daily 20:00 ICT, **US trading days only** (`bd:shotockviz-06z`) | Reads `quote:{symbol}`/`fund:{symbol}` for each user's watchlist ∪ open holdings → Telegram | — (read-only, sends Telegram) |


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
