# 01 — Sara ADR: deps-2026-09 migration (target matrix + breaking map + API decisions)

bd: deps-2026-09 · phase 1a · iter 0 · author: Sara (SA) · date 2026-09-03
Repo evidence @ `73fac00` (read-only clone `/home/claude/shotockviz-ro`). Baseline numbers per `outputs/deps-2026-09/00-oliver-discover.md`.
⚠️ Tooling note (honesty): this session has **no Bash tool** → could not run `uv pip index` in `.venv` as instructed. Python "latest" values below therefore come from (a) discover-doc registry query of 2026-09-03 (lower bounds, marked `≥`), (b) upstream changelog/release pages fetched today (exact, cited). Where only a floor is known, the pin rule is explicit (see §1.4) — no invented patch numbers.

---

## 0. Strategy record (user decision — not re-litigated)

**Big-bang**: all bumps on one branch `chore/deps-2026-09`, fix until green (user decision 2026-09-03, discover doc L7; Oliver dissent recorded there).
**Risk recorded (Sara)**: single branch carries ~30 simultaneous majors (yfinance, redis, pytest-asyncio, gunicorn, vite, TS, nitro, lucide, TanStack). Failure attribution cost is the main risk — a red build has ~30 suspects. Mitigation inside big-bang (not staging): commit **per-package-group commits** on the one branch (frontend-core / frontend-tanstack-nitro / backend-runtime / backend-test) so `git bisect` within the branch stays cheap, and run the two spikes in §2.7/§2.8 first. Reversibility: R1 — branch never merges without user (pre-merge gate, discover L11).

---

## 1. Target version matrix

### 1.1 frontend/package.json (current values cite: `frontend/package.json:13-41`)

| Package | Current | Target pin | Evidence |
|---|---|---|---|
| vite | ^7.1.7 | **8.2.2** | registry 2026-09-03 (discover L22); Vite 8.0 GA blog: Node 20.19+/22.12+, rolldown bundler |
| typescript | ^5.7.2 | **7.0.2** (fallback **6.0.3**, R1) | pkgpulse tsgo guide: stable `typescript@7.0.2` ships native `tsc`; fallback JS line 6.0.3 |
| @vitejs/plugin-react | ^5.0.4 | **6.1.1** | discover L22; Vite 8 blog: v6 uses Oxc, v5 still functional |
| vite-tsconfig-paths | ^5.1.4 | **6.1.1** | discover L22. Note: Vite 8 has built-in tsconfig `paths` → dep removable later (R2, out of big-bang scope) |
| @tanstack/react-start | ^1.132.0 | **1.168.49** | discover L22 |
| @tanstack/react-router | ^1.132.0 | **1.170.32** | discover L22 |
| @tanstack/react-router-devtools | ^1.132.0 | **1.170.32** (align router) | lockstep with react-router |
| @tanstack/router-plugin | ^1.132.0 | **1.168.35** | discover L22 |
| @tanstack/react-router-ssr-query | ^1.131.7 | **1.167.2** | discover L22 |
| @tanstack/react-devtools | ^0.7.0 | **0.10.12** | discover L22 |
| @tanstack/devtools-vite | ^0.3.11 | latest at install (UNVERIFIED — not in registry query) | resolve + lock on branch |
| nitro | `npm:nitro-nightly@latest` (🔴 floating) | **`"nitro": "3.0.260610-beta"`** — drop the `npm:` alias; real `nitro` pkg dist-tag `latest = 3.0.260610-beta` | [output: WebFetch registry.npmjs.org/-/package/nitro/dist-tags] |
| lucide-react | ^0.545.0 | **1.39.0** | discover L22; lucide.dev/guide/version-1 |
| react / react-dom | ^19.2.0 | **19.2.8** | discover L22 |
| @types/react / @types/react-dom | ^19.2.0 | 19.2.x latest at install | low risk |
| axios | ^1.13.5 | **1.20.0** | discover L22 |
| lightweight-charts | ^5.1.0 | **5.2.1** | discover L22 |
| tailwindcss + @tailwindcss/vite | ^4.1.18 | **4.3.3** | discover L22 |
| zustand | ^5.0.11 | **5.0.15** | discover L22 |
| @types/node | ^22.10.2 | **^24 line** (NOT 26.4.1 — see ADR-006) | dist-tags: latest=26.4.1 [output: WebFetch registry.npmjs.org/-/package/@types/node/dist-tags] |
| @react-oauth/google | ^0.13.4 | latest at install (UNVERIFIED) | touches auth one-tap (CLAUDE.md rule 5) — bump patch/minor only, no major without spike |
| react-hot-toast | ^2.6.0 | latest 2.x at install | low risk |

Pin style: convert to **exact pins (no `^`)** on this branch — big-bang rollback needs deterministic diffs; `package-lock.json` exists (`frontend/package-lock.json`) but exact pins make the manifest itself the rollback artifact.

### 1.2 tests/e2e/package.json (cite `tests/e2e/package.json:13-16`)

| Package | Current | Target |
|---|---|---|
| @playwright/test | ^1.44.0 | **1.62.1** [output: WebFetch registry.npmjs.org/-/package/@playwright/test/dist-tags → latest=1.62.1] |
| typescript | ^5.4.5 | **7.0.2** (align frontend; Playwright transpiles itself — TS pkg here is editor-only) |

### 1.3 backend/requirements.txt (current cite `backend/requirements.txt:1-54`)

| Package | Current | Target | Evidence class |
|---|---|---|---|
| fastapi | 0.131.0 | ≥0.141.1 → pin exact at lock | discover L23 floor |
| uvicorn[standard] | 0.41.0 | **0.52.4** | uvicorn.dev/release-notes (exact, 2026-08-18) |
| gunicorn | 23.0.0 | ≥26.2 → pin exact at lock (breaking notes from 26.0.0 release) | discover L23 floor + GH release 26.0.0 |
| **uvicorn-worker** (NEW) | — | latest at lock | ADR-005 (uvicorn.workers deprecated since 0.30.0, uvicorn.dev) |
| asyncpg | 0.30.0 | ≥0.31 → exact at lock | discover L23 |
| sqlalchemy[asyncio] | 2.0.46 | ≥2.0.52 → exact at lock | discover L23 |
| alembic | 1.14.1 | ≥1.19.1 → exact at lock | discover L23 |
| redis | 7.1.0 | ≥8.1 → exact at lock | discover L23; breaking notes from redis-py 8.0 release |
| celery | 5.6.2 | ≥5.6.3 → exact at lock | discover L23 |
| PyJWT | 2.10.1 | ≥2.13 → exact at lock | discover L23 |
| google-auth | 2.38.0 | ≥2.57 → exact at lock | discover L23 |
| python-multipart | 0.0.20 | ≥0.0.32 → exact at lock | discover L23 |
| pandas / numpy | 2.2.3 / 2.2.3 | floor kept; let resolver satisfy yfinance 1.4.1, then pin | discover L23 shows `?` (unresolved) |
| requests | 2.32.3 | ≥2.34 → exact at lock | discover L23 |
| httpx | 0.28.1 | keep 0.28.x | already current; but see §2.3 conftest breakage |
| yfinance | 0.2.65 | **1.4.1** | GH CHANGELOG.rst (latest = 1.4.1) |
| psycopg2-binary | 2.9.10 | keep (no registry data) | NO MAGIC — unverified, unchanged |
| pydantic | 2.12.5 | ≥2.13.5 → exact at lock | discover L23 |
| pydantic-settings | 2.8.1 | ≥2.15 → exact at lock | discover L23 |
| bcrypt / passlib / email-validator / feedparser / structlog / python-telegram-bot | as pinned | structlog ≥26.1, ptb ≥22.8 per discover; rest unchanged (no data). ⚠️ passlib 1.7.4 unmaintained w/ bcrypt 5 — pre-existing, out of scope, flag to Stan | discover L23 |
| pytest | 8.3.5 | ≥9.1 → exact at lock; **if pytest-asyncio 1.4 declares no pytest 9 support at resolve time, hold pytest 8.4.x** (record in lock commit) | discover L23 |
| pytest-asyncio | 0.25.3 | **1.4.0** | pytest-asyncio.readthedocs changelog (latest 1.4.0, 2026-05-26) |
| **pytest-cov** (NEW) | — (missing!) | add + pin | ci.yml:55 runs `--cov=.` but requirements.txt has no pytest-cov → CI job cannot pass as written |
| aiosqlite | 0.20.0 | ≥0.22 → exact at lock | discover L23 |
| pip-audit | 2.9.0 | ≥2.10 → exact at lock | discover L23 |

**§1.4 Pin rule for `≥` rows (binding on Dave):** first commit on the branch = run `uv pip install -r requirements.txt` (updated floors) in the py3.13 venv, then freeze the resolved versions back into `requirements.txt` as `==` pins and paste `uv pip freeze` output into the PR. No floating specifiers may land.

### 1.5 Dockerfiles + CI

| File | Change | Cite |
|---|---|---|
| frontend/Dockerfile | `node:22-alpine` → **`node:24-alpine`** (both stages) | frontend/Dockerfile:1,21 |
| frontend/Dockerfile.dev | same | frontend/Dockerfile.dev:1 |
| backend/Dockerfile(.dev) | **unchanged** `python:3.13-slim` | backend/Dockerfile:1,17; Dockerfile.dev:1 |
| .github/workflows/ci.yml | `node-version: '20'` → `'24'` | ci.yml:69 |
| .github/workflows/ci.yml | artifact path `frontend/dist/` → **`frontend/.output/`** (nitro output; pre-existing bug — build never produced `dist/`) | ci.yml:86 vs frontend/Dockerfile:28 (`COPY /app/.output`) |
| .github/workflows/ci.yml | add pytest-cov to reqs OR drop `--cov` flags | ci.yml:55 |
| .github/workflows/ci.yml | redis service stays `redis:7-alpine` — **server upgrade to 8 is NOT in this branch** (client redis-py 8.x ↔ server 7.x compatible per redis-py release notes); separate R1 later | ci.yml:26; docker-compose.ghcr.yml:33 |
| docker-compose.prod.yml / docker-compose.ghcr.yml | gunicorn command worker class change (ADR-005) | prod.yml:65, ghcr.yml:76 |
| deploy.yml | no node/python version pinned (builds via Docker) — no change | [output: Grep node-version deploy.yml → no matches] |

---

## 2. Breaking-change map (evidence-cited)

### 2.1 yfinance 0.2.65 → 1.4.1 — 🟡 lower risk than feared
Upstream: 1.0 release notes state **"No breaking changes, but some deprecation warnings"**; 1.4.0 made `curl_cffi` optional with requests fallback (GH CHANGELOG.rst).
**Scope containment (key finding):** `services/providers/yahoo_*.py` and `services/stock_service.py` do **NOT** use yfinance — they call Yahoo v8 HTTP directly with cookie/crumb (`stock_service.py:13`, `yahoo_provider.py:50`, `yahoo_auth.py:66`; [output: Grep "import yfinance" in stock_service.py → no matches]). yfinance blast radius = Celery workers + one API route:

| Call site | API used | Risk |
|---|---|---|
| workers/price_fetcher.py:128,137,144 | `yf.Tickers` batch, `t.fast_info` | fast_info key coverage — verify in spike |
| workers/name_fetcher.py:29,56,78,81 | `Tickers`, `fast_info.short_name`, `.info` | `short_name` attr on fast_info is undocumented-ish — verify |
| workers/fundamentals_fetcher.py:29,56,67 | `Tickers`, `.info` | .info dict keys restored/camelCase changes in 1.x — verify keys used |
| workers/history_prefetcher.py:96-100 | `Ticker.history(period="6mo", interval="1d")` | low |
| workers/on_demand_listener.py:124-128,171-188,339-343 | `fast_info`, `.history`, `.info` | note L31: 60d limit assumption for 1h bars — re-verify against 1.x |
| workers/financials_history_fetcher.py:83-98,134-150 | `.financials`, `.balance_sheet`, `.info`, **`.earnings` (L137)**, `.dividends` | 🔴 `ticker.earnings` was already deprecated/broken in late 0.2.x era — **spike must confirm it exists in 1.4.1**; fallback = income_stmt-derived |
| workers/earnings_events_fetcher.py:82-93 | `.earnings_dates`, `.history` | earnings_dates refactored to API fetching in 1.x (changelog) — shape check |
| workers/corporate_actions_fetcher.py:91-126 | `.dividends`, `.splits` | dividend-repair behavior changed (changelog) — values may shift; DB upsert keyed on ex_date OK |
| workers/symbol_registrar.py:115-122 | `.info` | low |
| api/routes/backtesting.py:150-157 | `Ticker.history` **inside API process** | works, but violates CQRS (CLAUDE.md: API never touches external services) — hand to Stan as refactor input, not fixed on this branch |

Docker note: keep `curl_cffi` OUT of requirements (1.4.0 falls back to requests) — avoids new build deps in `python:3.13-slim`.

### 2.2 redis-py 7.1 → 8.x — 🟡
From redis-py 8.0 release notes (GH releases): RESP3 default on wire (legacy-shaped responses preserved; `protocol=2` escape hatch), new defaults `socket_timeout=5s`, `socket_connect_timeout=5s`, TCP keepalive on, `max_connections=100`; typing overloads changed.
- `core/redis.py:38-45` — sets explicit 3s timeouts + `decode_responses=True` → unaffected by new defaults.
- **`await aioredis.from_url(...)` pattern** at core/redis.py:38, api/routes/system.py:120, api/middleware/rate_limit.py:25, main.py:125 — relies on `Redis.__await__` auto-init; spike must confirm retained in 8.x (deprecation candidate).
- Bare `from_url` without timeouts: services/stock_service.py:91, services/cache_orchestrator.py:45, services/providers/yahoo_provider.py:129 → inherit new 5s defaults = behavior change (previously unbounded). Beneficial, but note for triage if quote paths start timing out.
- Pub/sub under RESP3: main.py:120-133 (WS broadcast subscriber) + sync `import redis` publishers in 20+ worker files (workers/price_fetcher.py:181 etc.) — RESP3 push-message path is the highest-risk area; smoke: publish → WS receive. Rollback lever without version rollback: `protocol=2`.
- Tests: `tests/api/test_pr3_cache_service.py` 92 errors already redis-dependent (baseline) — do not count as regression.

### 2.3 pytest-asyncio 0.25 → 1.4.0 — 🔴 mandatory conftest rewrite
Changelog (readthedocs stable): **`event_loop` fixture removed in 1.0.0**; `loop_scope` replaces marker `scope`; scoped loops created once; `asyncio_mode` config remains in 1.x.
- backend/tests/conftest.py:24-29 — session `event_loop` fixture → **delete**; set `asyncio_default_fixture_loop_scope` (ini) instead.
- tests/api/conftest.py:32-36 — same deletion; session-scoped async fixtures `test_engine` (tests/api/conftest.py:39-46) need `loop_scope="session"` semantics → ini `asyncio_default_fixture_loop_scope = session` for that suite (it shares one in-memory engine per session).
- `asyncio_mode = auto` stays: backend/pytest.ini:17, tests/api/pytest.ini:2.
- **Pre-existing breakage to fix in the same pass**: backend/tests/conftest.py:110 `AsyncClient(app=app, ...)` — httpx 0.28 (already pinned, requirements.txt:26) removed the `app=` shortcut → must become `AsyncClient(transport=ASGITransport(app=app), ...)`. Counts as fixing pre-existing red, not regression.
- backend/pytest.ini:23 `--disable-warnings` hides all deprecation signals → recommend dropping the flag on this branch (visibility during migration), restore after.

### 2.4 gunicorn 23 → 26.x — 🟢 low, one decision
26.0.0 release: eventlet worker class **dropped** (not used here); RFC 9112 strict request validation + smuggling protections; fast C parser (`gunicorn_h1c`).
- Worker class used: `-k uvicorn.workers.UvicornWorker` (docker-compose.prod.yml:65, docker-compose.ghcr.yml:76). `uvicorn.workers` deprecated since uvicorn 0.30.0, still present at 0.52.4 (uvicorn.dev release notes) → ADR-005: switch to `uvicorn_worker.UvicornWorker` now.
- Strict header validation risk mitigated by Caddy fronting all traffic (caddy/Caddyfile:20-56).

### 2.5 pydantic 2.13 + pydantic-settings 2.15 — 🟢 mechanical
v1-style `class Config` (deprecated since pydantic 2.0; removal targeted v3) at **8 sites**:
- core/config.py:72-74 (BaseSettings) → `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")`
- api/routes/notes.py:24-25 → `model_config = ConfigDict(from_attributes=True)`
- models/schemas.py:52,140,151,189,242,269 → same.
Warnings currently invisible due to pytest.ini:23. No other v1 remnants found ([output: Grep "class Config:" backend → 8 matches above]).

### 2.6 Vite 7 → 8.2.2 — 🟡
Vite 8.0 blog: rolldown replaces rollup+esbuild; Node 20.19+/22.12+ (node:24 OK); "most plugins work out of the box"; plugin-react v6 = Oxc; built-in tsconfig paths.
Repo-specific checkpoints:
- vite.config.ts:19-28 — nitro plugin `rollupConfig: { external: [/^@sentry\//] }` passed into rolldown world: nitro v3 beta owns this mapping — spike-verify the `@sentry/*` external still applies to server bundle.
- Known ecosystem issue: `$RefreshReg$` HMR error with TanStack + Vite 8 (GH TanStack/router #7059) — verify fixed at pinned versions (dev-mode only; build gate is prod build).
- vite.config.ts:15-16 devtools `define` workaround — re-test under Vite 8 (may be obsolete or still needed).

### 2.7 TypeScript 5.7 → 7.0.2 — 🟡, small surface **in this repo** (SPIKE #1)
Build chain fact: `npm run build` = `vite build` only (frontend/package.json:10) — **tsc is not in the build path**. Only CI runs `npx tsc --noEmit` and it's `continue-on-error: true` (ci.yml:75-78). tsconfig: `noEmit`, `strict: false`, `allowJs` (tsconfig.json:30-34).
Tooling audit for typescript-API dependency (the task's question):
- `vite-tsconfig-paths` — parses tsconfig via tsconfck, not the TS compiler API → unaffected by tsgo (verify in spike, cited as belief not fact).
- `@tanstack/router-plugin` codegen — generates `routeTree.gen.ts` textually (routeTree.gen.ts:7 header), no tsc dependency.
- `@vitejs/plugin-react` 6 — Oxc transform, no tsc.
→ TS7 risk in this repo ≈ `tsc --noEmit` diagnostic parity + editor. pkgpulse guide: compiler API/custom transformers "not ready", language service "in progress" — neither is load-bearing here.
**Spike #1 (before any other frontend commit):** install matrix §1.1, run `npx tsc --noEmit` + `vite build`. Fail → fallback pin `typescript@6.0.3` (R1; supersedes discover doc's "5.9 fallback" — 6.0.3 is the last JS-based line per pkgpulse) and record.

### 2.8 TanStack Start 1.132 → 1.168.49 + nitro beta (SPIKE #2)
react-start CHANGELOG findings for the range:
- 1.167.44: plugin split into explicit Vite/Rsbuild subpaths — repo already imports the Vite subpath `@tanstack/react-start/plugin/vite` (vite.config.ts:3) → expected no-op, verify.
- 1.168.25: `validator()` canonical, `inputValidator()` deprecated — repo has **no server functions** ([output: Grep createServerFn|inputValidator frontend/src → no files]) → irrelevant.
- router.tsx:1-20 (`createRouter`, `Register` interface) and __root.tsx:2,47 (`createRootRoute`, `HeadContent`, `Scripts`) — no breaking change found in range; routeTree.gen.ts regenerated by router-plugin 1.168.35 at build.
- **Version skew risk**: 5 TanStack packages at 3 different minor lines (1.167.x/1.168.x/1.170.x are each package's latest) — anchor = react-start; if peer-dep conflict at install, downgrade router to react-start's declared peer range and record.
- nitro `3.0.260610-beta`: v3 blog — pkg rename nitropack→nitro (repo already on the new name via nightly alias), `nitro/vite` plugin (already used, vite.config.ts:6), Node ≥20 (OK), `eventHandler`→`defineHandler` (no server handlers in repo → config-only exposure: `routeRules` proxy + `devProxy`, vite.config.ts:22-27 — verify both under the beta pin).
**Spike #2 = prod build + `node .output/server/index.mjs` boot + `/api` proxy smoke** on Node 24 before other frontend work.

### 2.9 lucide-react 0.545 → 1.39.0 — 🟢 mechanical worst-case
lucide.dev/guide/version-1: brand icons removed; UMD dropped (ESM fine); `aria-hidden` default on icons; context providers added. **No rename list published; deprecated-alias removal UNCONFIRMED.**
- 20 importing files (grep evidence). No brand icons used.
- Legacy alias names present: `Loader2` (ChartToolbar.tsx:1, AlertsPage.tsx:2, NewsPage.tsx:11, ScreenerPage.tsx:3, AddTransactionModal.tsx:3, Sidebar.tsx:4, WatchlistSearch.tsx:2), `CandlestickChart`+`AreaChart` (ChartToolbar.tsx:1), `BarChart2` (BottomPanel.tsx:2, DashboardPage.tsx:8, PortfolioPage.tsx:3). If v1 dropped aliases, build fails loudly → mechanical rename (`LoaderCircle`, `ChartCandlestick`, `ChartArea`, `ChartColumn`). `aria-hidden` default: icon-only buttons must carry their own `aria-label` — flag to Uma/Quinn in Phase 3a, not a build gate here.

### 2.10 @playwright/test 1.44 → 1.62.1 — 🟢
tests/e2e isolated package (tests/e2e/package.json:14); not in CI; needs running stack → validated by Quinn in Phase 3, not a merge gate on this branch. Registry: latest 1.62.1 (dist-tags).

---

## 3. NFR / acceptance for the migration

Baseline is NOT green (discover L26-30) → acceptance = **no regression vs baseline**, plus the pre-existing fixes explicitly claimed in §2.3.

| # | Gate | Target | Measure |
|---|---|---|---|
| N1 | backend/tests | ≥ **107 passed**; no new failures outside the known 26 (`test_user_simulation.py`, live-stack) + 2 non-collecting files (`test_next_features.py:630` SyntaxError, `test_api_e2e.py` ImportError) — fixing those 2 is welcome but not gated | pytest output pasted in PR |
| N2 | tests/api | ≥ **116 passed**; the 92 redis-dependent errors (`test_pr3_cache_service.py`) not counted | pytest output |
| N3 | Frontend build | `npm ci && npm run build` **green on Node 24** with Vite 8/TS7/nitro-beta matrix; SSR server boots (`node .output/server/index.mjs`) | build log + boot log |
| N4 | Docker | `docker build` green for frontend (`node:24-alpine`) + backend (`python:3.13-slim`) + CI docker-build job dispatch green | GHA run link / local build output |
| N5 | DB layer | `alembic upgrade head` (2 revisions: 0001, 0002) and `scripts/init_db.py` run clean under new SQLAlchemy/alembic pins vs fresh timescaledb-pg16; **no schema change on this branch** | command output |
| N6 | Worker smoke | celery app imports + beat schedule loads (`workers/celery_app.py`); one on-demand fetch round-trip vs yfinance 1.4.1 (may use recorded/live spot check) | log excerpt |
| N7 | Security | `pip-audit` on new lock: no new HIGH+ vs baseline run | pip-audit output |
| N8 | No floating deps | requirements.txt all `==`; package.json exact pins; `nitro-nightly@latest` eliminated | diff review |

Perf: no perf gate on this branch (no baseline p95 measured in discover) — Vite 8 build-time gain is a bonus, not a target.

---

## 4. Architecture decisions — "improve API" scope (Sara-owned)

> Contract discipline per `api-contract` skill. **Consumer inventory (evidence, not feeling):** frontend `src/services/api.js:12` (`baseURL: '/api'` — sole runtime consumer), tests/api suite (`tests/api/conftest.py:76-84` hits `/api/auth/*`), Playwright e2e, Caddy routes `/api/ws/*|/api/ai/*|/api/*` (caddy/Caddyfile:20-45), nitro proxy `'/api/**'` (vite.config.ts:23). No external/partner consumers (self-hosted; CLAUDE.md L5). **No contract artifact exists** ([output: Glob **/openapi*.{yaml,yml,json} → none]).

### ADR-001 — API versioning: `/api/v1` with legacy `/api` alias (window-bound)
- **Context**: prefixes hardcoded per-router (`APIRouter(prefix="/api/...")` in all 14 modules, e.g. stocks.py:19, auth.py:25); mounted flat in main.py:275-288. Single first-party consumer.
- **Options**: (A) in-place, no version — cheapest, but the envelope change (ADR-002) is breaking (error/response shape = contract) and in-place flip breaks any stale SSR bundle/browser tab mid-deploy; (B) `/api/v1` + legacy alias — both live during window; (C) header versioning — overkill for one consumer, hurts Caddy/nitro path routing.
- **Decision**: **B**. Strip `/api` from router-level prefixes (routers declare resource prefix only, e.g. `/stocks`); main.py mounts twice: `include_router(r, prefix="/api/v1")` (new envelope) and `include_router(legacy_r, prefix="/api")` (frozen shapes) during the window. Prefix-lift refactor executes under **Stan's** strategy; this ADR fixes the target shape only. `/api/ws/*` and `/api/ai/*` (SSE) stay unversioned in this round (protocol endpoints; Caddy match rules untouched — caddy/Caddyfile:20,32).
- **Routing invariant**: Caddy `reverse_proxy /api/* backend:8000` (Caddyfile:45) and nitro `'/api/**'` proxy already cover `/api/v1/*` — **zero Caddy/compose/nitro changes required** (docker-compose.ghcr.yml has no path routing; caddy service only, L158-170).
- **Deprecation window**: internal consumer floor per api-contract = 1 release cycle. Proposal: legacy `/api` emits `Deprecation` + `Sunset` headers at T0; removal only after request-count metric on legacy prefix = 0 (middleware counter on prefix — cheap) — **not** time alone. Window length = Open Q#2.
- **Consequences**: `openapi.yaml` (contract-first, Sara → before Phase 2) describes v1 only; oasdiff gate in CI from then on.

### ADR-002 — Response envelope: `BaseResponse[T]` becomes the v1 standard
- **Context**: envelope exists and is documented as mandatory ("Every endpoint MUST return BaseResponse", schemas/common.py:4) but adopted **only in system.py** ([output: Grep BaseResponse api/routes → system.py 5 matches]). 13 modules return ad-hoc shapes.
- **Decision**: `/api/v1` = `{data, meta}` envelope everywhere, incl. **error shape** (error = envelope with `data:null` + error block in meta — exact error schema lands in openapi.yaml). Legacy `/api` keeps current shapes frozen (two versions coexist — api-contract rule 3). Frontend `api.js` switches `baseURL: '/api/v1'` + unwraps `data` centrally in the axios interceptor (single choke point, api.js:11-15 — cheap because every call goes through this instance).
- **Consequences**: `meta.data_status/cached_layer/next_refresh_in` finally reach the client → enables honest stale-UI states (Uma Phase 1b input). Cost: v1 handlers wrap; legacy stays as-is → no dual-serialization logic needed (alias mounts the *old* handler set until sunset; Stan sequences which modules move first).

### ADR-003 — Caching/ETag policy (direction)
- **Context**: zero HTTP caching today — only SSE no-cache header exists ([output: Grep ETag|Cache-Control backend → ai_chat.py:411 only]). Server-side TTLs centralized in core/ttl_policy.py:22-51; 2-layer read cache (cache_service.py, CLAUDE.md CQRS).
- **Decision (direction, v1 GET read endpoints)**: (1) `Cache-Control: private, max-age=<ttl_policy value>` derived from the same constants (single source: `core/ttl_policy.py` — no second TTL table); (2) weak ETag from `(cache_key, meta.as_of)` on history/quote/fundamentals/screener-snapshot GETs + `If-None-Match` → 304 (saves payload on 40-60-symbol watchlist polling, discover-of-stakeholder CLAUDE.md L194); (3) no shared/proxy caching (`private` — auth'd API behind Caddy); (4) WS `data_ready` push remains the invalidation signal — ETag complements, does not replace CQRS flow.
- **Non-goal**: no Redis-side redesign; Stan owns implementation placement in stocks.py refactor.

### ADR-004 — Pagination standard
- **Context**: ad-hoc today — `limit: int = Query(8, ge=1, le=20)` (stocks.py:511), unbounded list responses e.g. watchlist `items: List[...]` (models/schemas.py:149).
- **Decision**: v1 list endpoints take `limit` (default per-endpoint, hard cap **200**) + `offset`; envelope meta extends with `total`, `limit`, `offset` (added to ResponseMeta as optional → non-breaking within v1 per api-contract additive rule). Cursor pagination rejected: dataset scale (personal watchlist/portfolio/alerts, ≤ hundreds of rows) doesn't justify it; revisit only if a table crosses ~10^5 rows for one user.

### ADR-005 — gunicorn worker class → `uvicorn-worker` package
- **Context**: `-k uvicorn.workers.UvicornWorker` (docker-compose.prod.yml:65, ghcr.yml:76); `uvicorn.workers` deprecated since uvicorn 0.30.0 (uvicorn.dev), still present at 0.52.4.
- **Decision**: add `uvicorn-worker` dep; command → `-k uvicorn_worker.UvicornWorker` in both compose files on this branch. Removes a deprecated import path while we're already rebuilding images. Rollback: revert command (R2).

### ADR-006 — `@types/node` pinned to Node 24 line (dissent vs task list's "26")
- Types must match runtime (`node:24-alpine`, user decision). `@types/node@26.4.1` describes Node 26 APIs → phantom-API type holes. Pin `^24` (exact patch resolved at install — registry dist-tags expose only `latest`; recorded as the one non-exact frontend pin, R2).

---

## 5. Rollback plan (R1) per layer + R0 list

| Layer | Rollback lever | Grade |
|---|---|---|
| Whole migration | branch `chore/deps-2026-09` never merges (pre-merge user gate) — main untouched | R1 |
| Frontend matrix | revert `package.json` + `package-lock.json` (both committed pre-bump). Partial fallbacks kept ready: `typescript@6.0.3`; Vite-7 set (`vite@7.1.7`+plugin-react 5+vite-tsconfig-paths 5); nitro: record the exact `nitro-nightly` version currently resolved in `frontend/package-lock.json` **before** the bump and pin that (kills the floating `@latest` even in rollback) | R1 |
| Backend matrix | revert `requirements.txt` (old file is itself fully pinned, requirements.txt:1-54). Per-package fallback: redis→7.1.0 (or keep 8.x with `protocol=2` first), pytest-asyncio→0.25.3, gunicorn→23.0.0 + old worker class | R1 |
| Docker/CI | image-level: GHCR deploys must use immutable sha/`IMAGE_TAG` (compose already parameterized `${IMAGE_TAG:-latest}`, ghcr.yml:47) — rollback = redeploy previous tag; never rely on `latest` | R1 |
| API v1 | alias design = rollback built-in: frontend reverts `baseURL` to `/api` (one line, api.js:12); legacy handlers untouched until sunset | R2 |
| DB | no schema change on branch → nothing to roll back; alembic/SQLAlchemy pin revert only | R2 |

**R0 items — STOP for user approval (3):**
1. **Merge `chore/deps-2026-09` → main** (user-decided pre-merge gate).
2. **Any prod deploy/push**: GHCR image push consumed by droplet 188.166.234.146, or any `deploy.yml` dispatch during this engagement.
3. **Sunset/removal of legacy `/api` prefix** (irreversible for live browser sessions/SSR bundles; requires traffic-metric = 0 evidence + user sign-off per api-contract T2).

---

## 6. Open questions → Oliver (5)

1. **TS7 spike verdict authority**: ถ้า Spike #1 fail → Dave auto-fallback `typescript@6.0.3` แล้ว note ใน PR เลย (recommended) หรือหยุดถามก่อน?
2. **Legacy `/api` sunset window**: 1 release cycle (recommended, single first-party consumer + traffic-metric gate) หรือ fixed 30 วัน?
3. **Envelope scope**: v1 ครบทั้ง 13 modules ใน engagement นี้ (frontend ตามทันที) หรือเฉพาะ modules ที่ Stan refactor รอบแรก (stocks/dashboard) แล้วที่เหลือ v1-passthrough?
4. **CI trigger**: เปิด `on: pull_request` สำหรับ ci.yml บน branch นี้ไหม (ตอนนี้ `workflow_dispatch` only, ci.yml:4 — big-bang ไม่มี CI net เลยถ้าไม่เปิด)? Recommended: เปิด.
5. **pytest 9**: ถ้า resolver ชน pytest-asyncio 1.4 → hold pytest 8.4.x โดยไม่ถาม (recommended) ใช่ไหม?

---

## 7. Hand-off
- **Stan**: §2.1 backtesting.py CQRS violation, ADR-001 prefix-lift sequencing, ADR-002 module order, ADR-003 placement in stocks.py.
- **Bella**: AC wording for N1-N8 + ADR-001/002 consumer-visible behavior.
- **Dave**: §1.4 pin rule, Spikes #1/#2 first, per-group commits (§0).
- **Sara (self, pre-Phase 2)**: produce `outputs/api/openapi.yaml` for v1 (contract-first mandate).
- **Quinn**: oasdiff/Schemathesis gate once openapi.yaml lands; Playwright suite post-stack.

## § Cross-read (iter 0) — reconciliation vs 02-bella-brd-ac.md / 03-stan-refactor-strategy.md

**CR-1 · TS7 fallback pin — FINAL: `typescript@~5.9.3`** (supersedes §1.1's 6.0.3). Stan ran the spike in-repo: 7.0.2 gives exact 4-error parity with 5.9.3 at 6.6× speed (03-stan §3.2), and fallback `~5.9.3 + restore baseUrl` is a proven one-commit revert (03-stan §3.4). My 6.0.3 came from an external guide, unverified against this repo — in-repo spike evidence wins. Adopting Stan's finding into the matrix: **TS7 hard-removed `baseUrl` (TS5102)** → tsconfig.json:12 `baseUrl` deleted, `paths` kept (03-stan §3.2 spike output).

**CR-2 · nitro + tsconfig-paths — FINAL values for Stan's WP-F0**: `"nitro": "3.0.260610-beta"` exact (registry dist-tags, §1.1) · **REMOVE `vite-tsconfig-paths` entirely** + `resolve: { tsconfigPaths: true }` in vite.config.ts — supersedes §1.1's "keep 6.1.1". Stan's evidence (tsconfck npm-deprecated "unmaintained", Vite 8 native support, no-ERESOLVE scratchpad install — 03-stan §3.3) upgrades my "R2 later" to in-branch; it also deletes the tree's only `typescript` peer edge.

**CR-3 · pytest × pytest-asyncio — FINAL**: anchor `pytest-asyncio==1.4.0`; `pytest==9.1.*` **iff** the resolver accepts the pair at the B1 lock commit, else auto-hold `pytest==8.4.*` — recorded in the lock commit message, no user round-trip (this answers my Open Q#5 → withdrawn).

**CR-4 · AC coverage (Bella B1-B8 / C1-C3 / M1-M5 vs this ADR)**
| AC | ADR backing |
|---|---|
| M1,M2,M5 | §3 N1-N5, §2.3 ✅ |
| M3 | §2.7 Spike#1 (+CR-1 fallback) ✅ — Stan §3.2/3.4 already satisfies the spike |
| M4 | §2.1 map ✅ **with correction to Bella's wording**: `services/providers/yahoo_*.py` + `stock_service.py` contain **no yfinance import** (raw query2 HTTP — §2.1 evidence); the map's real surface = 9 workers + backtesting.py:155. AC-M4 file list should be updated by Bella |
| B1 | ADR-002 ✅ (envelope = v1-only; resolves Bella F1 risk via single axios unwrap point, api.js:11) |
| B2 | ADR-001 alias + window ✅ |
| B3 | ADR-001 consequences + Stan §2.1 openapi snapshot ✅ |
| B4 | ✅ via coexistence: legacy `/api` keeps `.detail` shape frozen (AC-B4 gates the legacy prefix); v1 error envelope is a new contract with frontend updated same PR (ADR-002) |
| B5,B6,B8 | preservation ACs — no ADR decision required by design; gated by tests/curls (Bella DoD 4,11) |
| B7 | **now decided (was uncovered)**: fix the TEST — `tests/e2e/health.spec.ts:12` asserts a shape `/api/health` never returned (system.py:82 = BaseResponse); per ADR-002 the envelope is the standard → test asserts `body.data.database` etc. No top-level `status` field added |
| C1,C3 | ADR-003 non-goals: CQRS + ttl_policy values unchanged ✅ |
| C2 | **was unsupported — now reconciled**: §3 said "no perf gate (no baseline)"; accept Bella C2 by adding a cheap measured baseline — timed-curl P95 sample (n≥20, warm+cold) on `GET /api/dashboard` + `GET /api/screener` captured at Stan's WP-B0 (pre-bump) and re-run post-bump; regression >10% blocks per AC-C2. §3 NFR table gains row **N9** accordingly |
| (A1 count) | Bella §3.2 A1 says "7 total" `class Config:` sites — grep shows **8** (models/schemas.py ×6 + core/config.py:72 + api/routes/notes.py:24 — §2.5; Stan §2.2 also counts 8). Bella to correct AC-A1 |

**CR-5 · admin.py verdict (Bella F5/AC-D5) — CONFIRMED from code, in-scope D-series**: admin.py:14 imports only `get_current_user`; used at admin.py:47,84,115 (Bella cited :83 — actual :84). `require_admin` exists at api/middleware/auth.py:82 (`require_role(UserRole.admin)`) and **no route file references it** ([output: Grep require_admin backend → auth.py:82 only]). Any authenticated user can change retention policy / trigger housekeeping. Classification: **in-scope security hardening (sub-scope d, user chose all four — discover L10)** = 3-line `Depends(require_admin)` diff on this branch, gated by NEW AC-D5 test; NOT a separate pre-branch hotfix (endpoints have no frontend consumer per Bella §2.12, exploitation requires an authenticated account on a self-hosted single-user instance — severity moderate, prod-urgent hotfix not justified). Touches auth dependency wiring → flag for Sentinel/Chris eyes at Phase 3b per Safety rule (modify auth = R0-adjacent; this change *tightens* only).

## § r2 amendments (M5 spec revision — user decisions in 04-oliver-user-decisions.md)

### r2-1 · ADR-001 REVISED — FINAL: **in-place at `/api`** (no `/api/v1`, no alias, no Sunset)
User rejected the legacy alias (04-oliver L10). Re-decision between (A) in-place at `/api` vs (B') `/api/v1` without alias, evidence:
- **e2e mocks**: 20+ `page.route()` patterns hardcode literal `/api/<resource>` (`**/api/stocks/*/quote` mocks.ts:107, `**/api/watchlists**` :174, `**/api/auth/me` :219, `**/api/ai/chat` :294 …) — `/api/v1/stocks/...` does not match `**/api/stocks/...` → B' forces editing every mock; A touches none.
- **tests/api**: paths hardcode `/api/auth/*` (tests/api/conftest.py:76-84) and the 116-pass suite hits `/api/...` literals throughout → B' = suite-wide path rewrite; A = none.
- **Routers**: all 14 hardcode `prefix="/api/..."` (stocks.py:19 et al.) → B' additionally requires the prefix-lift refactor; A leaves mounting untouched (Stan's WP-B5 split unaffected).
- **Caddy/nitro/compose**: `/api/*` rules (Caddyfile:45, vite.config.ts:23, ghcr.yml no path routing) cover both options equally — no discriminator.
- **SSR/stale-tab risk**: with no alias, a stale browser bundle breaks under BOTH options (A: shape mismatch on 200s; B': 404s — and api.js:67 SILENT_PATHS would swallow those silently). No winner; user accepted the risk class by rejecting the alias.
→ **Decision: A. Envelope flip happens in place at `/api`; backend envelope commit + frontend `api.js` unwrap flip = same commit** (baseURL stays `/api`, api.js:12 unchanged; unwrap added in the axios instance). URL versioning deferred until a consumer outside this repo exists; contract versioning lives in `outputs/api/openapi.yaml` semver instead. ADR-002's "legacy frozen" clause is void; AC-B2's alias requirement and AC-B4's `.detail` preservation apply **pre-flip only** — post-flip error contract = envelope error shape, frontend interceptor updated same commit (Bella to revise AC-B2/B4 wording; CR-4 rows B2/B4 superseded).

### r2-2 · ADR-002 scope confirmed — all 13 route modules
Per user decision #1 (04-oliver L7): `BaseResponse{data,meta}` on **all 13 modules** in this branch. Nothing else in ADR-002 changes: single unwrap point remains api.js axios instance; `meta` fields per schemas/common.py:42-53; pagination meta per ADR-004; SSE (`/api/ai/chat` stream) + WS `/api/ws/prices` stay non-envelope (stream protocols, ai_chat.py:411, main.py:293) — envelope applies to JSON request/response bodies only. `/api/health` already conforms (system.py:82).

### r2-3 · NEW ADR-007 — Auth dead-code removal (user decision #3) · grade **R1**
Interpretation on record: CLAUDE.md L17 "NO custom token management" = no client-side refresh lifecycle. Storing + attaching the issued access JWT is retained as the minimum for `Authorization: Bearer` (api.js:18-24) and WS auth (authStore.js:51-52 token feeds useWebSocket) — Sentinel to confirm this interpretation at Phase 1c/3b (04-oliver L9 mandates Sentinel review).

**REMOVE — backend (7):**
| # | Item | Evidence |
|---|---|---|
| 1 | `POST /api/auth/register` handler | auth.py:28-46; dead chain: only caller is authStore.register (authStore.js:82) which no component invokes ([output: Grep `register\(` frontend/src → authStore.js:82 only]) |
| 2 | `POST /api/auth/login` handler | auth.py:49-74; no frontend caller (Bella §2.1 F3) |
| 3 | `POST /api/auth/refresh` handler | auth.py:171-206; both callers removed same commit (api.js:41, authStore.js:59) |
| 4 | `POST /api/auth/logout` handler | auth.py:209-218 — only revokes refresh tokens; with #6 it has nothing to revoke; frontend logout → local clear only (authStore.js:90-99 simplified) |
| 5 | Schemas `RegisterRequest`, `LoginRequest`, `RefreshRequest` | models/schemas.py:9,26,37; `TokenResponse` (schemas.py:31) loses `refresh_token` field |
| 6 | Refresh-token issuance in `/google` | auth.py:160-167 deleted; `/google` returns access_token only |
| 7 | `verify_password`, `create_refresh_token`, `hash_refresh_token` | core/security.py:19,34,39 — only callers are auth.py sites above ([output: Grep → auth.py + core/security.py only]) |

**REMOVE — frontend (2 files):**
- authStore.js: `jwtSecondsLeft` :18-25, refresh timer :27-45, `silentRefresh` :54-67, `register` :80-87, `refresh_token` storage :73,:92-97, `scheduleRefresh` calls :76,:120, checkAuth refresh branches :121-144 (simplify: 401 → clear token; One Tap re-auths via GoogleOneTapManager, __root.tsx:27-45 `disabled: isLoading||isAuthenticated` flips to enabled).
- api.js: 401 auto-refresh interceptor :27-62 (entire block).

**MUST STAY:** `/google` auth.py:77-159 (minus refresh issuance) · `/me` :221-263 · `/config` :266-271 · `create_access_token`/`decode_access_token` (JWT issuance for Google path) · `get_current_user` + `require_admin` (auth.py middleware; CR-5) · `hash_password` (external callers: tests/conftest.py:75, scripts/create_user.py:30) · `scripts/create_user.py` (ops tool, not API surface) · **`RefreshToken` model + table untouched** — dropping it = DB schema change = out of scope (Bella §1.2 STOP rule); rows simply stop being written · GoogleOneTapManager + `googleLogin` (minus refresh_token line authStore.js:73).

**Consequences / follow-through:**
- Rate limiter targets only `/api/auth/login` (rate_limit.py:30) → re-point to `POST /api/auth/google` same commit (brute-force protection must not silently vanish; AC-B6/D2 wording → Bella).
- `tests/api/conftest.py:74-86 auth_headers` registers+logs in via the removed routes → rewrite to mint JWT directly with `create_access_token` (pattern already exists: backend/tests/conftest.py:86-94). Register/login test coverage (tests/api/test_api_endpoints.py:69-200 per Bella §2.1) deleted with the routes.
- Session semantics change: 30-day refresh continuity (config.py:22) → 8h access token (config.py:21) + One Tap silent re-auth. If Google is unreachable at expiry, user sees login page. **R1** — rollback = `git revert` of the removal commits, zero DB/migration impact; inform user, no stop needed (user directed the removal).
- Docs same branch: CLAUDE.md L17 stays true (now actually true); REQUIREMENTS §auth resync rides the separate bd (04-oliver L15) except auth section correction which lands here.
- Removal count: **7 backend items + 2 frontend files (≈9 removal units)**.

### r2-4 · R0 list + rollback table updated
- R0 #3 (legacy `/api` sunset) **void** — no alias exists. **R0 list FINAL (2):** (1) merge `chore/deps-2026-09` → main; (2) any prod deploy / GHCR push / deploy.yml dispatch. (Matches 04-oliver L18.)
- Rollback table §5: row "API v1" replaced → **"API envelope flip (in-place)"**: single revert unit = the paired backend-envelope + frontend-unwrap commit (must be ONE commit or an atomic commit pair reverted together; api.js:12 baseURL never changes). Add row **"Auth removal (ADR-007)"**: R1, `git revert` removal commits, no DB rollback needed. CI-trigger row: per user decision #2, ci.yml stays `workflow_dispatch` — my Open Q#4 answered NO; N4's "CI docker-build job dispatch" becomes manual-dispatch-only with user OK.

## § r3 — ADR-001 final: `/api/v1`, no alias (user clarification via Oliver r3)

Final: **`/api/v1` prefix + envelope, NO legacy `/api` alias, backend + frontend flip in one commit.** Supersedes r2-1's option A. Three path exceptions below are part of the decision.

### r3-1 · WS + SSE/AI — **stay unversioned** (`/api/ws/prices`, `/api/ai/*`)
- Repo Caddy has dedicated matchers with protocol-critical settings: `@ws path /api/ws/*` long-timeout proxy (Caddyfile:20-22, Caddyfile.dev:21-22) and `@ai path /api/ai/*` (Caddyfile:32-34) with SSE flush — AIChatPanel.tsx:6: "SSE streaming works only when Caddy has flush_interval -1 on /api/ai/*". Moving these under `/api/v1` demotes them to the generic `/api/*` proxy block → loses WS timeout + SSE flush → regresses the documented "AI chat freeze" fix (CLAUDE.md Known Issues).
- **External constraint**: the old shared droplet's Caddy is owned by ShoDe Town, not this repo (CLAUDE.md: "Caddy is managed by ShoDe Town"), and routes `/api/ws/*`, `/api/ai/*`, `/api/*` (CLAUDE.md architecture diagram L79-82). Versioning those two paths would require coordinating an external system's config — out of this bd's control.
- Call sites confirmed frozen: useWebSocket.ts:39 (`/api/ws/prices`), aiService.js:37 (raw `fetch('/api/ai/chat')`).
- ai_chat's JSON endpoints (`GET /models`, `POST /analyze/{symbol}`, non-stream `POST /chat` — Bella §2.10) share the `/api/ai` prefix and stay there; they still adopt the **envelope** (r2-2 — envelope ≠ path version). aiService's 3 axios calls must bypass the v1 baseURL (explicit `baseURL: '/api'` per-call or a second thin instance) — flagged to Dave.

### r3-2 · Health — **`GET /api/health` stays unversioned** (infra contract, not API contract)
Consumers are infra: compose healthchecks `curl -f http://localhost:8000/api/health` at docker-compose.dev.yml:67, docker-compose.prod.yml:60, docker-compose.ghcr.yml:71. No Dockerfile `HEALTHCHECK` directive exists ([output: Grep HEALTHCHECK **/Dockerfile* → no matches]) — compose-level only, all three files unchanged. e2e health.spec.ts keeps hitting `/api/health` (B7 fix unaffected).
**Mechanics**: routers declare resource-only prefixes (`/auth`, `/stocks`, `/watchlists`, … — today hardcoded `/api/...` in all 14 declarations, stocks.py:19 et al.); `system.py` splits into `health` (mounted at `/api`) + rest (`/system/ready`, `/system/celery-stats`, `/market/fgi` → mounted under v1); main.py:275-288 becomes one `api_v1` aggregate mounted at `prefix="/api/v1"` + the 3 exception mounts (`/api/health`, `/api/ai`, WS route main.py:293 unchanged). rate_limit.py:30 path literal → `/api/v1/auth/google` (composes with ADR-007 re-pointing).

### r3-3 · Literal-change inventory (evidence-counted)
| Where | What | Count |
|---|---|---|
| frontend/src/services/api.js:12 | `baseURL: '/api'` → `'/api/v1'` | 1 |
| frontend/src/services/aiService.js | 3 axios call sites bypass v1 base (stay `/api/ai/*`); raw fetch :37 unchanged | 3 |
| frontend other | useWebSocket.ts:39, api.js:67 SILENT_PATHS (substring matchers), __root/useBackendReady (comments only) | 0 |
| backend routers | 14 prefix declarations lose `/api`; system.py split; main.py:275-288 mount block; rate_limit.py:30 | ~17 |
| tests/api | `/api/` literals → `/api/v1/` (minus ADR-007 removals) | 133 across 5 files [output: Grep count] |
| backend/tests | test_next_features.py 67 (currently non-collecting — rewrite when WP-B0 fixes it) · test_api_e2e.py 51 (quarantined, untouched) | 67 active |
| tests/e2e | 51 occurrences in 12 files; **exceptions stay**: health.spec.ts (5, `/api/health`), mocks.ts `**/api/ai/models`:179 + `**/api/ai/chat`:294, ai-chat.spec.ts (4) | ~40 |
| docs | CLAUDE.md architecture diagram (adds `/api/v1` line); compose healthchecks unchanged; REQUIREMENTS §6 = separate bd (04-oliver L15) | ~2 files |
**Total ≈ 260 occurrences / ~20 files, mechanical (sed-able), single commit with the envelope flip.**

### r3-4 · Caddy/nitro zero-change — **CONFIRMED, holds**
- Caddy `reverse_proxy /api/* backend:8000` (Caddyfile:45) already matches multi-segment paths in production (e.g. `/api/stocks/{symbol}/quote` flows through it today) → `/api/v1/...` matches identically. `@ws`/`@ai` matchers untouched by design (r3-1). Both Caddyfile + Caddyfile.dev + external ShoDe Town Caddy: **zero edits**.
- nitro `routeRules '/api/**'` proxy (vite.config.ts:23) + devProxy `'/api'` (:26) + server.proxy `'/api'` (:43): prefix globs cover `/api/v1/**`. **Zero edits.**
- docker-compose.ghcr.yml: no path routing (r2 evidence) — zero edits.

### r3-5 · New risk (recorded)
Mixed prefix surface: `/api/v1/*` (12 modules) + 3 frozen exceptions (`/api/health`, `/api/ai/*`, `/api/ws/prices`). Mitigation: the 3 exceptions + their rationale are first-class entries in `outputs/api/openapi.yaml`; Bella ACs reference this table so Quinn's contract gate knows the split. Residual: aiService dual-base wiring is the one non-mechanical frontend edit — mis-wiring silently 404s AI JSON endpoints (SILENT_PATHS does not cover `/models`/`/analyze` → error toasts would surface it; acceptable detection).

## Sources (external)
- yfinance changelog: https://github.com/ranaroussi/yfinance/blob/main/CHANGELOG.rst
- pytest-asyncio changelog: https://pytest-asyncio.readthedocs.io/en/stable/reference/changelog.html
- gunicorn 26.0.0: https://github.com/benoitc/gunicorn/releases/tag/26.0.0
- redis-py releases: https://github.com/redis/redis-py/releases
- uvicorn release notes: https://uvicorn.dev/release-notes/
- Vite 8.0: https://vite.dev/blog/announcing-vite8
- TS7/tsgo guide: https://www.pkgpulse.com/guides/tsgo-vs-tsc-typescript-7-go-compiler-2026
- Nitro v3 beta: https://nitro.build/blog/v3-beta
- lucide v1: https://lucide.dev/guide/version-1
- TanStack react-start changelog: https://github.com/TanStack/router/blob/main/packages/react-start/CHANGELOG.md
- Vite8+TanStack HMR issue: https://github.com/TanStack/router/issues/7059
- npm dist-tags (nitro, @types/node, @playwright/test): registry.npmjs.org `/-/package/<pkg>/dist-tags`
