# BRD/AC — deps-2026-09 (Bella, Phase 1a)

bd: deps-2026-09 · iter 0 · role: business-analyst · parallel with Sara (ADR) / Stan (refactor strategy)
Repo: `/home/claude/shotockviz-ro` @ `73fac00`. Baseline evidence: `outputs/deps-2026-09/00-oliver-discover.md`.

---

## 1. Scope Statement

### 1.1 Stated scope (user decision, `00-oliver-discover.md:6-11`)
1. **Dependency migration**, big-bang, one branch `chore/deps-2026-09`: Node 22→24 LTS, TS 5.7→7.x, Vite 7→8, TanStack Start/Router 1.132→1.16x/1.17x, all other frontend + backend deps per registry table (`00-oliver-discover.md:22-23`).
2. **"Improve API"** — all four sub-scopes, each independently testable:
   - **(a) Code quality/structure** — fix pydantic v1-style `class Config:` (6 occurrences, see §2), dead/duplicate route registration, naming consistency.
   - **(b) API contract/versioning** — response envelope consistency, versioning decision (open question #1), error format consistency.
   - **(c) Performance/caching** — preserve CQRS pure-read pattern, cache TTLs, `<5s` P95 SLA (`REQUIREMENTS.md:314`).
   - **(d) Security/hardening** — rate limiting, auth, CORS, secrets — preserve or improve, never weaken.

### 1.2 OUT of scope (explicit — must-not-drift)
- New user-facing **features** (no new endpoints, no new alert types, no new indicators).
- **UI redesign** — visual/layout changes belong to Uma; not this bd.
- **DB schema changes** beyond what a dependency major bump *forces* (e.g. SQLAlchemy 2.0.46→≥2.0.52 is a patch/minor, no schema-forcing change identified in evidence). Any schema touch = STOP, escalate Oliver (R1).
- Resolving the **pre-existing test baseline failures** that are unrelated to deps (26 failures in `test_user_simulation.py` expect a live stack; 2 non-collecting files) — these are **not gated** by this migration; DoD requires "no regression vs baseline," not "fix pre-existing breakage," unless Dave's plan explicitly elects to fix a specific one (must be named, not implied).
- Deciding **yfinance 1.x** provider-function breaking-change map — that is Sara/Dave's technical spike (open question #2 in `00-oliver-discover.md:34`), Bella only requires the AC below to gate it.
- **Auth architecture redesign** — the auth contract inconsistency found in §2.1 (email+password endpoints + custom localStorage token refresh existing alongside the Google-One-Tap-only policy in `CLAUDE.md:17`) is flagged as a **risk/open question**, not fixed here, unless Oliver directs otherwise.

### 1.3 Scope-creep guard
Any FR below not traceable to (1) a dependency bump forcing a code change, or (2) one of the 4 named "improve API" sub-scopes = orphan = out of scope. Bella will flag at Phase 3b if diff introduces functionality not covered by an AC in §3.

---

## 2. API Surface Inventory (baseline contract — 55 HTTP endpoints + 1 WS)

Response envelope legend: **BR** = wraps in `schemas.common.BaseResponse` (`backend/schemas/common.py:58`); **RAW** = returns bare Pydantic model / ORM object / dict — no envelope.

🔴 **Finding F1 (contract inconsistency, pre-existing):** Only `GET /api/health` (`backend/api/routes/system.py:82`) uses `BaseResponse`. All other 54 endpoints return raw shapes. `frontend/src/routes/__root.tsx` and `frontend/src/components/pages/LoginPage.tsx` are the only 2 frontend files that reference `meta.`-prefixed strings — both are false-positive matches on `import.meta.env`, **not** BaseResponse consumption `[grep frontend/src: no BaseResponse envelope unwrapping anywhere]`. If sub-scope (b) wraps more endpoints in `BaseResponse`, **every** frontend service in `frontend/src/services/*.js` that does `api.get(...).then(r => r.data...)` breaks unless the axios response is unwrapped consistently — this is the #1 breaking-change risk for sub-scope (b).

🔴 **Finding F2 (pre-existing, latent):** `tests/e2e/health.spec.ts:12` asserts `body.status === 'ok'`, but `system.py:82` actually returns `{data: {database, redis, celery}, meta: {...}}` — **no top-level `status` key**. This E2E test was never run against the real stack (`00-oliver-discover.md:29` "E2E Playwright: not run"), so this mismatch is undetected today. Must be resolved (fix test or fix endpoint, pick one) as part of sub-scope (b), tracked as AC-B7.

### 2.1 Auth — `backend/api/routes/auth.py` (prefix `/api/auth`)
| Method/Path | Auth | Response model | Consumer (frontend) |
|---|---|---|---|
| POST `/register` | none | `UserResponse` (`models/schemas.py:45`) | **none found** — no frontend caller; only tested in `backend/tests`, `tests/api` |
| POST `/login` | none | `TokenResponse` (`models/schemas.py:31`) | **none found in `frontend/src/services/*.js`** — see F3 below |
| POST `/google` | none | `TokenResponse` | `frontend/src/store/authStore.js` `googleLogin()` (confirmed: calls `/auth/google`, stores `access_token`/`refresh_token` in localStorage — `authStore.js:52,72-76`) |
| POST `/refresh` | none (body has refresh_token) | `TokenResponse` | `frontend/src/services/api.js:41` (401-retry interceptor) + `authStore.js:59` (proactive `silentRefresh`) |
| POST `/logout` | none (body) | 204 | `authStore.js:94` |
| GET `/me` | Bearer (optional-fail 401) | `UserResponse` | `frontend/src/services/api.js` SILENT_PATHS includes `/auth/me` (`api.js:67`); called from `authStore.js` init |
| GET `/config` | none | raw dict `{google_client_id}` | not grepped explicitly but implied by `__root.tsx` `VITE_GOOGLE_CLIENT_ID` env var (build-time, not runtime fetch — `CLAUDE.md:87`) |

🔴 **Finding F3 (contradicts documented policy):** `CLAUDE.md:17` states *"Auth uses Google OAuth (one-tap) — NO custom token management on frontend... User explicitly demanded this 3 times."* Evidence contradicts this: `frontend/src/store/authStore.js:52-76` implements full custom JWT lifecycle (localStorage `access_token`/`refresh_token`, `scheduleRefresh`, `silentRefresh` via `POST /auth/refresh`) and `frontend/src/services/api.js:17-24,36-59` implements axios interceptor-based token attach + 401 auto-refresh. `POST /api/auth/register` and `/login` (password-based, `auth.py:28-75`) exist in the backend and are covered by `tests/api/test_api_endpoints.py:69-200` and `backend/tests` — but **no frontend caller found** for `/register` or `/login` (password flow appears backend-only / dead from the frontend's perspective; Google flow is the only frontend-reachable path, but it still uses custom token mgmt, not "no custom token management"). This is a **pre-existing architecture-vs-code drift**, not something deps migration causes — flagged as **Open Question #3**.

### 2.2 System/health — `system.py` (prefix `/api`)
| Method/Path | Auth | Response | Consumer |
|---|---|---|---|
| GET `/health` | none | `BaseResponse[dict]` (`system.py:82`) | `docker-compose healthcheck` + Caddy (per `CLAUDE.md:79`); e2e `tests/e2e/health.spec.ts` (currently mismatched, F2) |
| GET `/system/ready` | none | raw `{ready, cached, total}` | `frontend` polls every 3s per `system.py:163-164` docstring — consumer file not in `services/*.js` (likely a hook; `api.js:67` SILENT_PATHS has `/system/ready`) |
| GET `/system/celery-stats` | none | raw dict | admin/ops tooling — no frontend service file found |
| GET `/market/fgi` | none | raw dict / cached JSON | not in any `services/*.js` — orphan endpoint from frontend's perspective (no consumer found) |

### 2.3 Stocks — `stocks.py` (prefix `/api/stocks`), all pure-read/CQRS
| Method/Path | Auth | Response | Consumer |
|---|---|---|---|
| GET `/search` | optional | raw list of dict | `stockService.js:4` `search()` |
| GET `/names` | none | raw dict `{symbol: {name, market}}` | `stockService.js:7` `getNames()` |
| GET `/quotes` | none | raw dict `{symbol: quote\|null}` | `stockService.js:10` `getQuotesBatch()` |
| GET `/{symbol}/quote` | none | raw JSON or 202-pending | `stockService.js:13` `getQuote()` (404-tolerant) |
| GET `/{symbol}/history` | optional | `StockHistory` (`models/schemas.py:87`) | `stockService.js:22` `getHistory()` |
| GET `/{symbol}/rs` | optional | raw dict | **no consumer found in `services/*.js`** |
| GET `/{symbol}/fundamentals` | optional | `StockFundamentals` (`models/schemas.py:94`) | `stockService.js:23` `getFundamentals()` |
| GET `/{symbol}/financials` | optional | raw dict | **no consumer found in `services/*.js`** |
| GET `/{symbol}/earnings` | optional | raw dict | **no consumer found in `services/*.js`** |
| GET `/{symbol}/news` | optional | raw list | `stockService.js:24` `getNews()` |
| GET `/{symbol}/events` | none | raw dict | **no consumer found in `services/*.js`** |

### 2.4 Watchlist — `watchlist.py` (prefix `/api/watchlists`), all require auth
| Method/Path | Response | Consumer |
|---|---|---|
| GET `` | `list[WatchlistResponse]` (`models/schemas.py:144`) | `watchlistService.js:5` `getAll()` |
| POST `` | `WatchlistResponse` | `watchlistService.js:6` `create()` |
| PUT `/{id}` | `WatchlistResponse` | **no consumer found** |
| DELETE `/{id}` | 204 | `watchlistService.js:7` `delete()` |
| POST `/{id}/stocks` | raw `{message}` | `watchlistService.js:10` `addStock()` |
| DELETE `/{id}/stocks/{symbol}` | 204 | `watchlistService.js:11` `removeStock()` |
| PATCH `/{id}/stocks/reorder` | 204 | `watchlistService.js:13` `reorderStocks()` |

### 2.5 Portfolio — `portfolio.py` + `portfolio_performance.py` (prefix `/api/portfolio`), auth required
| Method/Path | Response | Consumer |
|---|---|---|
| GET `` | `list[TransactionResponse]` | `portfolioService.js:4` `getTransactions()` |
| GET `/analytics` | `PortfolioAnalytics` (`models/schemas.py:204`) | `portfolioService.js:5` `getAnalytics()` |
| POST `/transactions` | `TransactionResponse` | `portfolioService.js:6` `addTransaction()` |
| PUT `/transactions/{id}` | `TransactionResponse` | `portfolioService.js:7` `updateTransaction()` |
| DELETE `/transactions/{id}` | 204 | `portfolioService.js:8` `deleteTransaction()` |
| GET `/performance` | raw `{points, period, symbols}` (`portfolio_performance.py:21`) | `portfolioService.js:9` `getPerformance()` |

### 2.6 Alerts — `alerts.py` (prefix `/api/alerts`), auth required
| Method/Path | Response | Consumer |
|---|---|---|
| GET `` | `list[AlertResponse]` | `alertService.js:4` `getAll()` |
| POST `` | `AlertResponse` | `alertService.js:5` `create()` |
| PUT `/{id}` | `AlertResponse` | **no consumer found** |
| DELETE `/{id}` | 204 | `alertService.js:6` `delete()` |
| PATCH `/{id}/toggle` | `AlertResponse` | `alertService.js:7` `toggle()` |

### 2.7 Drawings — `drawings.py` (prefix `/api/drawings`), auth required — **no frontend `services/*.js` file exists for drawings** (likely called inline from a chart component, not audited here — flag for Sara/Dave code-search before touching).
| Method/Path | Response |
|---|---|
| GET `/{symbol}` | `list[DrawingResponse]` |
| POST `/{symbol}` | `DrawingResponse` |
| PUT `/{drawing_id}` | `DrawingResponse` |
| DELETE `/{drawing_id}` | 204 |

### 2.8 Screener — `screener.py` (prefix `/api/screener`), optional auth
| Method/Path | Response | Consumer |
|---|---|---|
| GET `` (query params `market/rsi/volume/macd/price`) | raw list of dict | `stockService.js:25` `screener()` |

🔴 **Finding F4:** `REQUIREMENTS.md:500-506` documents `POST /api/screener/run`, `GET/POST /api/screener/presets`, `DELETE /api/screener/presets/{id}` — **none of these exist in code** (`screener.py` has exactly one `GET ""` route, `screener.py:293`). REQUIREMENTS.md §6 (API Endpoints) is **stale/aspirational**, not a reliable contract source — do not use it as ground truth for this migration; ground truth = route files (this table).

### 2.9 Dashboard — `dashboard.py` (prefix `/api/dashboard`), optional auth
| Method/Path | Response | Consumer |
|---|---|---|
| GET `` | raw dict (`dashboard.py:300-342`) | `dashboardService.js:4` `getOverview()` |

### 2.10 AI Chat — `ai_chat.py` (prefix `/api/ai`), optional auth
| Method/Path | Response | Consumer |
|---|---|---|
| POST `/chat` (non-stream) | raw `{content}` | `aiService.js:7` `chat()` |
| POST `/chat` (stream=true) | SSE `text/event-stream` | `aiService.js:37` `chatStream()` (raw `fetch`, bypasses axios) |
| GET `/models` | raw `{models, available}` | `aiService.js:14` `listModels()` |
| POST `/analyze/{symbol}` | raw `{symbol, analysis}` | `aiService.js:11` `analyzeStock()` |

### 2.11 Notes — `notes.py` (prefix `/api/notes`), auth required
| Method/Path | Response | Consumer |
|---|---|---|
| GET `/{symbol}` | `NoteResponse` (local class, `notes.py:19`, pydantic v1-style `class Config:` at `notes.py:24` — matches Oliver's finding) | `notesService.js:4` `get()` |
| PUT `/{symbol}` | `NoteResponse` | `notesService.js:5` `upsert()` |
| DELETE `/{symbol}` | 204 | `notesService.js:6` `delete()` |

### 2.12 Admin — `admin.py` (prefix `/api/admin`), auth required (no role check — any authenticated user, not `require_admin`; see `admin.py:47,83,115` all use `get_current_user`, not `require_admin` from `api/middleware/auth.py:82`) — **no frontend consumer found in `services/*.js`**.
| Method/Path | Response |
|---|---|
| GET `/retention-policy` | `RetentionPolicyResponse` |
| PUT `/retention-policy` | raw `{status, policy}` |
| POST `/retention-policy/run-now` | raw `{status, message}` |

🔴 **Finding F5 (pre-existing security gap, in-scope for sub-scope (d)):** `admin.py` endpoints use `get_current_user` (any logged-in user), not `require_admin` (`api/middleware/auth.py:70-82`, which exists and is unused by any route file — `grep` confirms no route imports `require_admin`). Any authenticated user can currently read/change the data-retention policy and trigger housekeeping. Flagged as **AC-D5**.

### 2.13 Backtesting — `backtesting.py` (prefix `/api/backtest`), optional auth — no frontend consumer found in `services/*.js`.
| Method/Path | Response |
|---|---|
| GET `/strategies` | raw dict |
| POST `/run` | raw dict |

### 2.14 WebSocket — `main.py:293` `/api/ws/prices` — no auth (`websocket_prices`), actions `subscribe`/`unsubscribe`/`ping`. Consumer: `frontend/src/hooks/useWebSocket` (not fully audited — file exists per `CLAUDE.md`'s WS pub/sub description, out of HTTP inventory scope but AC-B8 covers it below).

### 2.15 Cross-cutting middleware (`backend/main.py:254-271`)
- CORS: `settings.cors_origins_list` (`core/config.py:60-61`) — `allow_methods=["*"]`, `allow_headers=["*", "X-Request-ID"]`.
- Rate limit: `api/middleware/rate_limit.py:8-46` — **only** `POST /api/auth/login` is limited (5 attempts / 15 min per IP). Docstring claims "guest=30/min, user=120/min enforced at route level via dependency" (`rate_limit.py:11-12`) but **no route file was found calling a per-route rate-limit dependency** — this claim in the docstring does not match observed code (grep of all route files shows no rate-limit dependency import outside `main.py`'s middleware registration). Flagged as **AC-D2** (verify or correct the claim).
- `python:3.13-slim` base, non-root user requirement per `REQUIREMENTS.md:343` — verify in Dockerfile (Sara's ADR territory, cited here only as an AC gate).

---

## 3. User Stories + Gherkin AC

Numbering: `AC-<subscope><n>`. Subscopes: **M**=dependency migration (cross-cutting), **A**=code quality, **B**=API contract/versioning, **C**=performance/caching, **D**=security/hardening.

### 3.1 Dependency migration (M)

**Story M1** — As the maintainer, I want the big-bang dependency bump to leave zero backend test regressions vs the recorded baseline, so I can trust the migration didn't silently break behavior.
```gherkin
Given the pre-migration baseline is 107 passed / 26 failed / 5 skipped in `backend/tests`
  and 116 passed / 12 failed / 92 errors in `tests/api`
  and 2 non-collecting files (`test_next_features.py`, `test_api_e2e.py`)
When the dependency bump branch `chore/deps-2026-09` runs the same suites under Python 3.13
Then passed-count in `backend/tests` is >= 107, AND failed-count is <= 26 (same or fewer), AND no new SyntaxError/ImportError collection failures are introduced beyond the 2 pre-existing ones
  And passed-count in `tests/api` is >= 116, AND failed+error count is <= 104 (12+92, same or fewer)
  And any test that flips from pass->fail is named explicitly in the hand-off with root cause (dep-caused vs pre-existing)
```

**Story M2** — As the maintainer, I want the frontend to build and the Docker images to build on the new base images, so deployment isn't blocked.
```gherkin
Given `node:22-alpine` → `node:24-alpine` and `python:3.13-slim` (unchanged) in the relevant Dockerfiles
When `docker-compose -f docker-compose.dev.yml build frontend` and `build backend` run on the migration branch
Then both builds exit 0
  And `npm run build` inside the frontend build produces the Nitro output (matching baseline: green, ~9.7s ± reasonable variance — `00-oliver-discover.md:28`)
  And `docker compose ps` shows both services healthy after `up -d` (GET /api/health returns non-500)
```

**Story M3** — As the maintainer, I want the TS7/TanStack/Vite8 spike proven before commit, so a mid-migration rollback isn't needed.
```gherkin
Given TanStack Start 1.132 + TanStack Router 1.132 + vite-tsconfig-paths 6 + @vitejs/plugin-react 6 targeted to run under TypeScript 7's native compiler
When Sara/Dave run a spike build (isolated, before the big-bang commit)
Then router codegen completes without error AND `tsc`/native-compiler typecheck passes on at least one route file
  Or the spike fails and the fallback (TS 5.9, per `00-oliver-discover.md:36`) is invoked and documented as a scope change (R1, requires Oliver sign-off per Ingress Guard)
```

**Story M4** — As the maintainer, I want yfinance 1.x provider breaking changes mapped before Dave edits `services/providers/yahoo_*.py`, so the 8 Celery workers that depend on it don't silently start returning bad data.
```gherkin
Given yfinance 0.2.65 → ≥1.7.0 is a major version bump (`00-oliver-discover.md:23`)
When Dave (or Sara) produces a breaking-change map for every yfinance call site in `services/providers/yahoo_*.py` and `services/stock_service.py`
Then each call site is marked: unaffected / signature-changed / removed-needs-replacement
  And no call site is left unclassified before the big-bang commit touches `requirements*.txt`
```

**Story M5** — As the maintainer, I want pytest-asyncio 1.x's mode/fixture change handled explicitly, so the test suite itself isn't the source of new failures.
```gherkin
Given `asyncio_mode=auto` + session-scoped event loop fixture in `backend/tests/conftest.py` under pytest-asyncio 0.25
When pytest-asyncio bumps to >=1.4 (breaking, per `00-oliver-discover.md:23,35`)
Then `conftest.py` fixtures are rewritten to the 1.x API before running the suite (not left broken and blamed on "flaky tests")
  And the AC-M1 pass/fail delta accounting is computed AFTER this fixture rewrite, not before
```

### 3.2 (a) Code quality / structure

**Story A1** — As a future maintainer, I want all Pydantic models on the v2-idiomatic `model_config = ConfigDict(...)` form, not the deprecated v1 `class Config:`, so the codebase doesn't emit deprecation warnings under Pydantic 2.12+/future 3.x.
```gherkin
Given `class Config:` is used at `core/config.py:72`, `models/schemas.py:52,140,151,189,242,269` (6 occurrences), and `api/routes/notes.py:24` (7 total)
When the code-quality pass runs
Then all 7 occurrences are converted to `model_config = ConfigDict(...)` (or `SettingsConfigDict` for `core/config.py`, which is a `BaseSettings` subclass)
  And `pytest -W error::DeprecationWarning -k pydantic` (or equivalent) shows zero Pydantic v1-config deprecation warnings
  And no response shape changes as an observable side effect (same fields, same types) — verified by diffing OpenAPI schema before/after (see AC-B mechanism)
```

**Story A2** — As a maintainer, I want duplicate router registration for `/api/portfolio` (both `portfolio.py:18` and `portfolio_performance.py:17` register the same prefix, merged only via `main.py:279-280`) documented or consolidated so future contributors don't accidentally create a route collision.
```gherkin
Given `portfolio.py` and `portfolio_performance.py` both declare `APIRouter(prefix="/api/portfolio")` and both are included separately in `main.py:279-280`
When code-quality review runs
Then either the two files stay split with a comment cross-referencing each other (minimum), or are merged into one router (if Dave judges it low-risk)
  And FastAPI startup does not emit a route-collision warning for any path (verify via `docker compose logs backend` at startup — no "Duplicate operation ID" or route conflict warnings)
```

### 3.3 (b) API contract / versioning

**Story B1** — As a frontend consumer, I want the response envelope to be applied consistently (or explicitly NOT applied, project-wide) so `services/*.js` callers don't need per-endpoint special-casing.
```gherkin
Given today only `GET /api/health` uses `BaseResponse` (F1) and the other 54 endpoints return raw shapes
When Oliver/user decides the envelope policy (Open Question #1)
Then the decision is written as an ADR (Sara) AND every endpoint in §2 either (a) is migrated to `BaseResponse` with the frontend axios layer updated in the SAME PR to unwrap `.data.data`/`.data.meta`, or (b) `BaseResponse` is documented as health/system-only by design
  And no endpoint is left in a "sometimes enveloped, sometimes not" state without an explicit written reason
```

**Story B2** — As a frontend consumer, I want zero endpoint path/method/required-field changes without a deprecation alias, so existing `services/*.js` calls (§2, all consumer columns) keep working.
```gherkin
Given the baseline path/method table in §2 (55 HTTP routes)
When any route's path, method, or required-request-field changes as a side effect of a dependency bump (e.g. FastAPI 0.131→≥0.141 changing validation defaults)
Then the OLD path/shape remains available (redirect, alias router, or backward-compatible field) for at least one release cycle
  And the change is listed explicitly in the hand-off diff with "BREAKING (aliased)" or "BREAKING (not aliased — approved by Oliver)" tag — silent breaking changes fail this AC
```

**Story B3** — As a developer, I want an OpenAPI diff between pre- and post-migration, so contract drift is caught mechanically, not by manual re-reading of 15 route files.
```gherkin
Given FastAPI auto-generates `/docs`/`/openapi.json` (docs disabled only in production, `main.py:249-250`)
When the migration branch is built
Then `GET /openapi.json` is captured BEFORE (baseline branch) and AFTER (migration branch) as two JSON snapshots
  And a diff tool (or manual diff) confirms: no path removed, no required field added to a request body without also being optional with a default, no response field removed
  And any diff hit is either justified (matches an approved AC-B2 breaking change) or blocks merge
```

**Story B4** — As a developer, I want error response format (currently FastAPI's default `{"detail": ...}`, consumed by `frontend/src/services/api.js:88-94`) preserved.
```gherkin
Given `api.js:88-94` parses `error.response.data.detail` (string OR array-of-{msg} for 422s)
When any backend dependency bump changes FastAPI/Pydantic's default validation-error shape
Then a 422 response still has `.detail` as either a string or a list of objects containing `.msg`
  And a manual curl of at least one validation-error-triggering endpoint (e.g. `POST /api/stocks/search` with missing `q`) confirms the shape unchanged
```

**Story B5** — As an operator, I want `/docs` (Swagger UI) and `/openapi.json` to render without error post-migration.
```gherkin
Given `docs_url="/docs"` when `not settings.is_production` (`main.py:249`)
When the migration branch backend is running in dev mode
Then `GET /docs` returns 200 and renders (no schema-generation exception in backend logs)
  And `GET /openapi.json` returns valid JSON parseable by a standard JSON parser
```

**Story B6** — As an operator, I want rate-limit and auth behavior preserved exactly.
```gherkin
Given `POST /api/auth/login` is limited to 5 attempts / 15 min per IP (`rate_limit.py:15-16`)
When 6 login attempts are made from the same IP within 15 minutes post-migration
Then the 6th attempt returns 429 with a `detail` message containing a retry-after hint (matches `rate_limit.py:41-44` shape)
  And `GET /api/auth/me` without a Bearer token still returns 401 with `WWW-Authenticate: Bearer` header (`auth.py:228-231`)
  And `GET /api/auth/me` with an expired/invalid token still returns 401 (`auth.py:236-239`)
```

**Story B7** — As QA, I want the F2 health-endpoint/e2e-test mismatch resolved, not carried forward silently.
```gherkin
Given `tests/e2e/health.spec.ts:12` expects `body.status === 'ok'` but `system.py:82` returns `{data: {...}, meta: {...}}` with no top-level `status`
When sub-scope (b) work lands
Then either the test is corrected to check `body.data.database === 'ok'` (etc.) matching the real BaseResponse shape, or the endpoint adds a top-level `status` field for backward compat — pick one, document which, and make `tests/e2e/health.spec.ts` pass when run against a live stack
```

**Story B8** — As a frontend consumer of the WebSocket, I want the `/api/ws/prices` message contract (`subscribe`/`unsubscribe`/`ping` actions, `data_ready`/`price_update`/`alert_triggered` message types per `main.py:306-314,144-153`) unchanged.
```gherkin
Given the WS action/type contract documented in `main.py:293-320`
When the migration lands
Then a WS client sending `{"action":"subscribe","symbol":"AAPL"}` still receives `{"type":"subscribed","symbol":"AAPL"}`
  And a WS client sending `{"action":"ping"}` still receives `{"type":"pong"}`
  And malformed JSON still receives `{"type":"error","message":"Invalid JSON"}` (`main.py:315-316`), not a connection drop
```

### 3.4 (c) Performance / caching

**Story C1** — As a user, I want cache-only pure-read endpoints to keep responding without calling external APIs directly.
```gherkin
Given CQRS: `GET /api/stocks/{symbol}/quote`, `/history`, `/fundamentals`, `/news` are documented pure-read (`stocks.py:250,303,422,577` docstrings)
When the migration lands
Then a `grep` of the migrated `stocks.py` for `yfinance`/`yf.` import inside the request-handling path (not inside `services/stock_service.py` background-fetch functions) still returns zero direct external calls at request time
  And a manual curl against a warm-cache symbol (e.g. `AAPL`) returns in <100ms (matches `stocks.py:307` docstring target)
```

**Story C2** — As a user, I want the documented `<5s` P95 SLA preserved for cache-miss paths.
```gherkin
Given `REQUIREMENTS.md:314` targets API P95 <5s for cache-only reads, and `dashboard.py:6` targets <3s even on cold cache, and `screener.py:306-307,347` caps at 4.5s internally
When a cold-cache request hits `GET /api/dashboard` or `GET /api/screener` post-migration
Then response time is measured (not assumed) via a load test or timed curl, and P95 does not regress >10% vs a pre-migration baseline measurement taken on the same hardware
```

**Story C3** — As a user, I want cache TTLs unchanged (60s quotes, 5min search, 4h fundamentals per `REQUIREMENTS.md:358`).
```gherkin
Given TTL constants live in `core/cache_keys.py` (referenced throughout `stocks.py`, `portfolio.py`, etc. — not yet read in full; Dave to confirm exact file)
When redis version bumps (7.1→≥8.1, `00-oliver-discover.md:23`)
Then `tests/api/test_pr2_cache_spec.py` (all TTL-assertion tests, e.g. `test_1d_ttl_is_6h`, `test_screener_ttl` — lines 104-154) still pass unmodified
```

### 3.5 (d) Security / hardening

**Story D1** — As a security reviewer, I want no dependency bump to introduce a known CVE.
```gherkin
Given `pip-audit 2.9→≥2.10` is in the registry (`00-oliver-discover.md:23`)
When the migration branch's `requirements*.txt` is finalized
Then `pip-audit` runs against it with zero HIGH/CRITICAL findings (MEDIUM+ findings listed with accept/defer decision, not silently ignored)
  And `npm audit` (or equivalent) on the frontend `package.json` shows zero HIGH/CRITICAL findings under the same rule
```

**Story D2** — As a security reviewer, I want the rate-limit docstring claim ("guest=30/min, user=120/min enforced at route level via dependency", `rate_limit.py:11-12`) reconciled with actual code.
```gherkin
Given no route file was found importing a per-route rate-limit dependency (grep across `backend/api/routes/*.py` for rate-limit dependency imports returns nothing except `main.py`'s middleware registration)
When sub-scope (d) work lands
Then either the per-route rate limiting is implemented to match the docstring, or the docstring is corrected to state only login is currently limited — the code and its own comment must agree
```

**Story D3** — As a security reviewer, I want CORS to remain a whitelist (not wildcard) in production.
```gherkin
Given `main.py:258-265` sets `allow_origins=settings.cors_origins_list` (from `.env` `cors_origins`, `core/config.py:48`)
When the migration lands
Then `cors_origins_list` in the production `.env` is still an explicit domain list (e.g. `stock.shode.dev`), never `*`, verified by reading the deployed `.env` reference in `docs/deploy.md` (not committed — verify the documented instruction, not a live secret)
```

**Story D4** — As a security reviewer, I want containers still running as non-root post base-image bump.
```gherkin
Given `REQUIREMENTS.md:343` requires "Container: Run as non-root user"
When `node:22-alpine`→`node:24-alpine` and any backend base image change lands
Then the Dockerfile still has a non-root `USER` directive AND `docker compose exec backend whoami` / `docker compose exec frontend whoami` returns a non-root username post-build
```

**Story D5** — As a security reviewer, I want the F5 admin-authorization gap fixed or explicitly deferred with owner sign-off.
```gherkin
Given `admin.py:47,83,115` use `get_current_user` (any authenticated user) instead of `require_admin` (`api/middleware/auth.py:70-82`, defined but unused)
When sub-scope (d) work lands
Then either `admin.py`'s three endpoints are changed to `Depends(require_admin)`, or the decision to defer is written down with Oliver's explicit sign-off (this is a real authorization bug, not a hypothetical — R1, inform+rollback per Discipline §R1)
```

**Story D6** — As a security reviewer, I want secrets handling unchanged — `.env`-only, never committed.
```gherkin
Given `JWT_SECRET_KEY`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, etc. are `.env`-sourced (`core/config.py:19,13,57` + `.env.example`)
When the migration branch is diffed
Then no `.env` file, no hardcoded secret, and no new secret-shaped string (matching common patterns: API keys, JWT secrets, DB passwords) appears in the git diff — verified by a secret-scan (e.g. `git diff | grep -E` for common patterns, or a proper scanner if Sara/Chris has one configured)
```

---

## 4. Definition of Done

| # | Item | Evidence required |
|---|---|---|
| 1 | Backend test suite run under Python 3.13 on migration branch | Paste `pytest` summary line; passed >= 107 (backend/tests), >= 116 (tests/api); failed/error counts <= baseline (AC-M1) |
| 2 | Frontend build green on Node 24 | Paste `npm ci && npm run build` output, exit 0 |
| 3 | Both Docker images build | Paste `docker compose -f docker-compose.dev.yml build` output for `frontend` + `backend`, exit 0 each |
| 4 | Stack boots and health-checks pass | Paste `docker compose ps` (all healthy) + `curl -s localhost/api/health` response body |
| 5 | OpenAPI snapshot diff | Two `openapi.json` files (pre/post) attached or diffed inline; every diff line justified against AC-B2/B3 |
| 6 | pip-audit + npm audit clean (or findings triaged) | Paste both tool outputs; zero unaddressed HIGH/CRITICAL |
| 7 | TS7/TanStack spike result | Pass: paste typecheck+build output. Fail: paste rollback decision + Oliver sign-off (R1) |
| 8 | yfinance breaking-change map | Table/list of every call site classified (unaffected/changed/removed) — attach as Dave's artifact, referenced here |
| 9 | pytest-asyncio conftest rewrite | Diff of `backend/tests/conftest.py` + green run under new pytest-asyncio |
| 10 | Pydantic v1-config cleanup (7 sites) | Diff showing all 7 `class Config:` → `model_config` conversions; zero deprecation warnings in test run |
| 11 | Rate-limit/auth/CORS/non-root preserved | Curl transcripts for AC-B6, D3, D4 |
| 12 | Admin authorization decision (F5) | Either code diff to `require_admin`, or written deferral with Oliver sign-off |
| 13 | Envelope policy decision (F1/B1) documented | ADR link (Sara) + confirmation every endpoint matches the decided policy |
| 14 | E2E suite run at least once against live stack | Paste Playwright summary (pass/fail counts) — baseline was "not run"; this migration is the first opportunity to establish one |
| 15 | changelog.md + tasklist.md updated | Per `CLAUDE.md:11` project rule — diff showing entries added |

**No regression rule**: baseline is NOT green (`00-oliver-discover.md:30`). DoD = "no new failures introduced, and every failure classified as pre-existing-vs-new," not "all green," unless a specific pre-existing failure is named in the plan as being fixed.

---

## 5. Requirements Traceability Matrix (AC → route/file → test)

| AC | Route / File | Test file (existing / NEW) |
|---|---|---|
| M1 | all backend routes | `backend/tests/*` (baseline), `tests/api/*` (baseline) — run as-is, compare counts |
| M2 | `frontend/Dockerfile`, `backend/Dockerfile` (not yet read — Sara/Dave to confirm paths) | manual `docker compose build` — NEW (no automated build-test exists) |
| M3 | `frontend/vite.config.ts`, `tsconfig.json`, TanStack router codegen | NEW — spike script, not yet existing |
| M4 | `backend/services/providers/yahoo_*.py`, `services/stock_service.py` | `backend/tests/test_services.py` (existing, partial coverage: `test_search_stocks_cache_hit/miss`, lines 96-127) — needs NEW tests per changed call site |
| M5 | `backend/tests/conftest.py` | the entire `backend/tests/*` suite depends on this — no dedicated test; regression = whole-suite red |
| A1 | `core/config.py:72`, `models/schemas.py:52,140,151,189,242,269`, `api/routes/notes.py:24` | NEW — no existing deprecation-warning test; add `pytest -W error::DeprecationWarning` gate |
| A2 | `api/routes/portfolio.py`, `api/routes/portfolio_performance.py`, `main.py:279-280` | NEW — startup log assertion |
| B1/B7 | `backend/schemas/common.py`, `system.py:82` | `tests/api/test_pr1_response.py` (existing, BaseResponse unit tests, lines 30-131 + integration 163-213); `tests/e2e/health.spec.ts` (existing, currently mismatched — must be updated per B7) |
| B2/B3 | all 55 routes in §2 | NEW — OpenAPI snapshot diff script |
| B4 | `frontend/src/services/api.js:88-94` | NEW — curl-based validation-error shape check; no existing frontend test found for this |
| B5 | `main.py:249-250` | NEW — `curl /docs`, `curl /openapi.json` |
| B6 | `api/middleware/rate_limit.py`, `api/routes/auth.py:221-263` | `tests/api/test_api_endpoints.py:129-145` (existing `/me` 401 tests); rate-limit itself — NEW (no existing rate-limit test found in `tests/api` or `backend/tests` greps) |
| B8 | `main.py:293-320` | NEW — no WS test found in `tests/e2e/*.spec.ts` list (none named `websocket` or `ws`) |
| C1 | `stocks.py:250,303,422,577` | `tests/api/test_api_endpoints.py:254-280,287-345` (existing quote/history/fundamentals cache-hit tests) |
| C2 | `dashboard.py:300`, `screener.py:293` | `backend/tests/test_user_simulation.py:263` (`test_dashboard_overview`, existing but requires live stack per baseline note) — NEW load-test for P95 |
| C3 | `core/cache_keys.py` (path unconfirmed — verify before use) | `tests/api/test_pr2_cache_spec.py:100-154` (existing, TTL assertions) |
| D1 | `requirements*.txt`, `frontend/package.json` | NEW — `pip-audit`/`npm audit` CI step (`pip-audit 2.9` already a dep per `00-oliver-discover.md:23`, but no evidence it runs in CI — `.github/workflows/ci.yml` not yet read, verify before claiming it's wired) |
| D2 | `api/middleware/rate_limit.py:11-12` | NEW |
| D3 | `main.py:258-265`, `core/config.py:48,60-61` | NEW — config-value assertion, not a runtime test |
| D4 | Dockerfiles (paths TBD) | NEW — `docker compose exec ... whoami` |
| D5 | `api/routes/admin.py:47,83,115`, `api/middleware/auth.py:70-82` | NEW — no existing admin-authz test found in `backend/tests` or `tests/api` greps |
| D6 | repo-wide | NEW — secret-scan step |

---

## 6. Open Questions for Oliver

1. **Envelope policy (F1/B1):** Does "improve API contract" mean wrapping all 55 endpoints in `BaseResponse` (large, all-consumer-touching change) or formalizing "BaseResponse = health/system-only by design" (smaller, contract-preserving)? This gates AC-B1/B2/B3 scope size significantly — needs a decision before Dave estimates.
2. **Versioning (`00-oliver-discover.md:33`):** Introduce `/api/v1` with alias, or keep in-place? Directly affects every row in §2's path column and every `services/*.js` `baseURL` config (`frontend/src/services/api.js:12`).
3. **Auth contract drift (F3):** `CLAUDE.md:17` says "no custom token management," but `authStore.js` + `api.js` implement one, and `POST /api/auth/register`/`/login` (password) exist server-side with no frontend caller found. Is this dead code to remove (scope creep if we do it here), a documentation error to fix (`CLAUDE.md` update, cheap), or intentionally out of scope entirely for this bd?
4. **Admin authorization gap (F5):** `admin.py` uses `get_current_user` not `require_admin` — real privilege-escalation-adjacent bug (any logged-in user can change data-retention policy). Fix now (small, well-scoped, arguably "security/hardening" in-scope) or defer to a separate bd?
5. **REQUIREMENTS.md staleness (F4):** §6 (API Endpoints) documents endpoints that don't exist (`/api/screener/run`, `/api/screener/presets`) and omits ~40 real ones. Should Bella open a follow-up bd to resync `REQUIREMENTS.md` with actual code (separate from this migration), so future BAs don't repeat this multi-hour re-derivation from source?

---

## § Cross-read (iter 0)

Read `outputs/deps-2026-09/01-sara-adr-migration.md` (incl. Sara's own `§ Cross-read (iter 0)`, lines 275-299) and `outputs/deps-2026-09/03-stan-refactor-strategy.md`. No rewrite of §1-6 above — corrections applied here only, per Oliver's instruction.

### 1. Contradictions (5)

| AC | Contradiction | Resolution |
|---|---|---|
| **AC-M4** | My file list (`services/providers/yahoo_*.py`, `services/stock_service.py`) is wrong — Sara's ADR §2.1 evidence (`[output: Grep "import yfinance" stock_service.py → no matches]`) shows those files use raw Yahoo v8 HTTP, not yfinance. Real yfinance surface = **9 Celery workers** (`price_fetcher.py`, `name_fetcher.py`, `fundamentals_fetcher.py`, `history_prefetcher.py`, `on_demand_listener.py`, `financials_history_fetcher.py`, `earnings_events_fetcher.py`, `corporate_actions_fetcher.py`, `symbol_registrar.py`) + `api/routes/backtesting.py:150-157` (CQRS violation, flagged to Stan not fixed here). | Replace AC-M4's "Given" clause file list with Sara §2.1's 10-row table; gate = Stan's WP-B0 golden-fixture capture (see new AC-M6) + WP-B3 fixture-green proof. |
| **AC-A1** | I stated "(7 total)" `class Config:` occurrences. Sara §2.5 and Stan §2.2 both independently grep-confirm **8**: `core/config.py:72` + `models/schemas.py:52,140,151,189,242,269` (6) + `api/routes/notes.py:24` (1) = 8. My count dropped `core/config.py:72` from the total while still listing it in the "Given" line — arithmetic error, not a factual gap. | Correct "(7 total)" → "(8 total)" in AC-A1's Given clause. |
| **AC-D5** | Two issues: (1) I cited `admin.py:83` for the `Depends(get_current_user)` line on the retention-policy-update endpoint; actual line is **84** (`:83` is the `body:` param, `:84` is `user:`) — Sara's CR-5 caught this. (2) My Open Question #4 asked "fix now or defer to separate bd" — Sara's CR-5 has **already decided**: in-scope on this branch (3-line `Depends(require_admin)` diff, gated by NEW AC-D5 test, flagged to Sentinel/Chris at Phase 3b since it touches auth wiring), not deferred. | Correct citation to `admin.py:47,84,115`. Withdraw Open Question #4 — resolved by Sara CR-5, in-scope. |
| **AC-B1** | My Given clause treats the envelope policy as still-open ("Given today only `/health` uses BaseResponse... When Oliver/user decides..."). Sara's **ADR-002** has already decided: `/api/v1` = `BaseResponse` everywhere (incl. error shape), legacy `/api` frozen as-is during the deprecation window (ADR-001). This also resolves my Open Question #1. | Rewrite AC-B1's "When/Then" to assert ADR-002's decided shape directly, not "wait for a decision." Open Question #1 → withdrawn, answered by ADR-001+ADR-002. |
| **AC-M3** | My "Then" clause ("router codegen completes without error AND typecheck passes on at least one route file") is looser than Stan's actual measured proof: `npm run typecheck` → **exactly 1 known error** (`router.tsx:5`, TanStack-branded, requires `strictNullChecks`, explicitly whitelisted) — not zero, not "at least one file passes." A looser AC would pass on a regression Stan's own gate would catch (e.g. a NEW unexplained error appearing). | Tighten AC-M3's Then clause to Stan §3.2/3.4's exact criterion: baseline is 1 whitelisted error (`router.tsx:5`); any additional error = fail. |

### 2. Stan work packages with no covering AC → 4 new AC proposed

| WP | Gap | New AC (one-line Gherkin) |
|---|---|---|
| **B0** (hygiene — yfinance golden-fixture capture, `03-stan §"Chain B" row B0`) | No AC requires golden fixtures to exist/be used as the characterization baseline before the yfinance bump lands. | **AC-M6**: `Given backend/tests/fixtures/yf_golden/ is captured against yfinance 0.2.65 BEFORE WP-B1's bump lands, When WP-B3 adapts provider/worker code to yfinance ≥1.4.1, Then each fixture's recorded output is diffed against the post-bump call and any field-level change is explicitly classified (unchanged / cosmetic / breaking) in the PR, not silently accepted.` |
| **B4** (redis-py 8 RESP3 pub/sub — Sara ADR §2.2 "highest-risk area", Stan WP-B4 proof only asserts pytest counts, no pub/sub smoke) | No AC exercises the Redis `price_updates` pub/sub → WebSocket broadcast bridge under RESP3 (my existing AC-B8 tests WS *action* contract, not the *publish path*). | **AC-M7**: `Given main.py:108-168 _redis_price_broadcaster subscribes to 'price_updates' via a separate aioredis connection under redis-py 8/RESP3, When a worker publishes a price_update/data_ready/alert_triggered message post-bump, Then a connected WS client still receives the exact same message shape it received pre-bump (manual publish→WS-receive smoke test, both protocol=3 default and the protocol=2 rollback lever per Sara §2.2).` |
| **B5** (stocks.py → package split, ordering constraint: static paths before `/{symbol}/*`) | My existing AC-B3 (generic OpenAPI diff) doesn't name the specific collision risk Stan flagged (`/quotes` vs `/{symbol}/quote`). A generic diff-empty check could miss a routing-order regression if FastAPI still resolves correctly by accident in dev but the underlying include-order is now fragile. | **AC-A3**: `Given the stocks.py split registers 5 sub-routers (03-stan §2.1) with static-path routers (search.py, quotes.py's /quotes) required before dynamic-path routers (quotes.py's /{symbol}/quote, history.py, fundamentals.py, news_events.py), When the package __init__.py include order is reviewed, Then a comment documents the ordering constraint AND a smoke test confirms GET /api/stocks/quotes still hits the batch handler, not a symbol-path handler misinterpreting "quotes" as a symbol.` |
| **F2** (13 `.js`→`.ts` conversions, "annotation-only, zero logic movement" self-imposed rule, explicitly named-risk file `authStore.js` — ties directly to my own **Finding F3** in §2.1) | No AC asserts the conversion is actually behavior-preserving, despite this being the single highest-risk file in the conversion set (token storage/refresh logic, contradicts `CLAUDE.md:17`'s stated policy per my F3). | **AC-A4**: `Given frontend/src/store/authStore.js and frontend/src/services/api.js are converted to .ts under WP-F2 with a stated "annotation-only, zero logic change" rule, When the conversion PR is reviewed, Then a line-by-line diff shows only type annotations added (no reordering, no new branches, no changed function signatures beyond adding types) AND the existing auth-flow tests (tests/api/test_api_endpoints.py:69-200, tests/e2e/auth.spec.ts) pass unmodified against the .ts build.` |

### 3. RTM updates

| AC | RTM change |
|---|---|
| AC-M4 | Route/File column → replace with Sara §2.1's 10-row call-site table (9 workers + `backtesting.py:150-157`); Test → NEW golden-fixture diff tests (see AC-M6) |
| AC-D5 | Route/File → `api/routes/admin.py:47,84,115` (was `:83`) |
| AC-M6 (new) | Route/File: `backend/tests/fixtures/yf_golden/` (new, Stan WP-B0) + all 9 worker files; Test: NEW |
| AC-M7 (new) | Route/File: `main.py:108-168`, `workers/price_fetcher.py:181`; Test: NEW — no existing pub/sub smoke test found in `backend/tests` or `tests/api` greps |
| AC-A3 (new) | Route/File: `backend/api/routes/stocks/__init__.py` (new package, Stan WP-B5); Test: NEW — extends AC-B3's OpenAPI-diff mechanism with the specific `/quotes` vs `/{symbol}/quote` smoke |
| AC-A4 (new) | Route/File: `frontend/src/store/authStore.js`→`.ts`, `frontend/src/services/api.js`→`.ts` (Stan WP-F2); Test: `tests/api/test_api_endpoints.py:69-200` (existing), `tests/e2e/auth.spec.ts` (existing) |
| AC-B1 | Test column unchanged (`tests/api/test_pr1_response.py`), but now also gated by Sara's ADR-002 + `outputs/api/openapi.yaml` (Sara pre-Phase-2 deliverable, not yet produced) |

**AC count after cross-read: 24 original + 4 new (M6, M7, A3, A4) = 28.**

---

## § r2 (user decisions)

Source: `outputs/deps-2026-09/04-oliver-user-decisions.md`. §1-6 above left unmodified; this section retires/rewrites/adds only, per Oliver's r2 instruction.

### 1. B-series affected by user decision #1 (envelope = all 13 modules) + #4 (no alias, in-place switch, no Sunset/Deprecation)

Path prefix note: user decision #4 rejects ADR-001 option B (`/api/v1` + alias) but Sara has not yet re-decided between option A (in-place `/api`) vs a bare `/api/v1` without alias (`04-oliver-user-decisions.md:10`). Every AC below cites the path as **"per ADR-001 r2 (path TBD)"** until Sara's amendment lands — do not read `/api` or `/api/v1` literally in these ACs yet.

| AC | Status | Reason |
|---|---|---|
| **AC-B1** | **RETIRED** — superseded by **AC-B1-r2** | Original Given clause treated envelope scope as an open decision ("Given today only `/health` uses BaseResponse... When Oliver/user decides..."). User decision #1 makes this unconditional and total (all 13 modules, this branch), and decision #4 removes the "legacy stays frozen" half. |
| **AC-B2** | **RETIRED** — superseded by **AC-B2-r2** | Original Then clause required "the OLD path/shape remains available... for at least one release cycle" — directly contradicts user decision #4 ("No alias — switch immediately (in-place)... NO dual mount, NO Deprecation/Sunset headers"). |
| **AC-B4** | **RETIRED** — superseded by **AC-B4-r2** | Original Then clause asserted the current `{"detail": ...}` error shape stays **unchanged** — false once every endpoint (incl. error responses, per ADR-002) envelopes atomically with no legacy fallback; there is no longer a "legacy `.detail` still works" branch to test. |
| AC-B3 | **AMENDED in place** (not retired) | OpenAPI pre/post diff mechanism is unchanged, but its acceptance criterion flips: previously "any diff = investigate," now "diff across all 55 routes is EXPECTED (envelope wrap is intentional) — the check becomes 'every diffed field matches the all-13-modules envelope plan, zero unplanned extras,' not 'zero diff.'" |
| AC-B6 | **AMENDED in place** (not retired) | Status codes (429, 401) and headers (`WWW-Authenticate`, retry-after) are unaffected by the envelope change and stay as originally written. Response **bodies** now wrap in `{data, meta}` too (e.g. 401 body becomes `{data: null, meta: {...}}` instead of bare `{"detail": "..."}`) — curl evidence in DoD item 11 must capture the new enveloped body, not the old bare shape. |
| AC-B7 | **unaffected** | `/api/health` already used `BaseResponse` pre-r2; the all-13-modules decision makes B7's fix (assert `body.data.database`, not top-level `status`) the norm rather than the exception. No change needed. |
| AC-B8 | **unaffected** | WS stays unversioned/un-enveloped per ADR-001 (`caddy/Caddyfile:20,32` untouched) — explicitly out of the envelope decision's scope. |
| DoD item 13 | **AMENDED** | "Envelope policy decision (F1/B1) documented" → policy is now decided (all 13, no alias); DoD item becomes "confirm all 13 modules match the decided policy, zero opt-outs," evidence = OpenAPI snapshot per AC-B3. |
| Open Questions #1, #2 (§6) | **already withdrawn** at cross-read (iter 0) — reconfirmed closed by user decision #1/#4, no new action. |

**AC-B1-r2**
```gherkin
Given user decision #1 (`04-oliver-user-decisions.md:7`): all 13 route modules get BaseResponse{data,meta} in this branch, no phased rollout
  And user decision #4 (`04-oliver-user-decisions.md:10`): no `/api/v1`+legacy-alias dual-mount — single path (prefix per ADR-001 r2, TBD), switched atomically
When the migration branch lands
Then every one of the 55 HTTP routes in §2 (all 13 modules: auth, system, stocks, watchlist, portfolio, alerts, drawings, screener, dashboard, ai, notes, admin, backtesting) returns `{data, meta}` — zero routes left in the old raw shape
  And `frontend/src/services/api.js`'s axios instance unwraps `.data.data` in a single interceptor choke point (`api.js:11-24` region) in the SAME commit as the backend change — no commit exists where backend is enveloped and frontend is not
```

**AC-B2-r2**
```gherkin
Given user decision #4: no deprecation window, no alias, no Sunset/Deprecation headers — atomic in-place switch
When any of the 55 routes' response shape changes (envelope wrap) as part of this branch
Then the backend commit and the frontend-consumer commit for that route land together (same PR, ideally same commit) — no intermediate state where one side expects the old shape and the other serves the new one
  And the hand-off diff lists every route whose shape changed (all 55, per AC-B1-r2) with old-shape vs new-shape side by side — "silently changed, not listed" fails this AC regardless of whether an alias exists
```

**AC-B4-r2**
```gherkin
Given user decision #1/#4: validation-error responses (422, 401, etc.) also envelope under ADR-002 — no legacy `.detail`-only path survives
When a validation-error-triggering request is sent post-migration (e.g. `POST /api/stocks/search` with missing `q`)
Then the response body is `{data: null, meta: {data_status: "unavailable", request_id: ..., ...}}` with the error detail relocated per ADR-002's error-block design (exact field name — TBD, Sara's `outputs/api/openapi.yaml` is the source of truth once it lands, not this AC)
  And `frontend/src/services/api.js:88-94`'s error-parsing logic is updated in the same commit to read the new location — old `error.response.data.detail` parsing is dead code after this lands, verified by grep showing zero remaining references to the pre-r2 shape
```

### 2. New D-series AC — auth dead-code removal (user decision #3)

🔴 **Blast-radius finding (new, r2):** `tests/api/conftest.py:74-84`'s `auth_headers` fixture — used by nearly every authenticated-endpoint test in `tests/api/test_api_endpoints.py` (watchlist/portfolio/alerts sections) and `backend/tests/test_next_features.py` — calls `POST /api/auth/register` then `POST /api/auth/login` to mint its token. **Removing those two routes breaks this fixture and, transitively, every test that depends on it** — this is a much larger regression surface than "delete 2 endpoints" suggests. By contrast, `backend/tests/conftest.py:98`'s own `auth_headers` fixture takes a pre-minted `valid_token` directly (no HTTP call) — **unaffected**. AC-D9 below gates this explicitly.

**AC-D7** — password routes removed
```gherkin
Given `POST /api/auth/register` (`auth.py:28-46`) and `POST /api/auth/login` (`auth.py:49-74`) have no frontend caller (confirmed §2.1 Finding F3)
When the auth dead-code removal lands
Then `POST /api/auth/register` and `POST /api/auth/login` return 404 or 405 (not 200/201/401) — proven by a NEW test asserting the removed status, not merely "no test exists for it"
  And `tests/api/test_auth.py` (currently 5 tests hitting these routes directly, lines 5-47) is deleted or rewritten to assert removal — not left green-but-stale
```

**AC-D8** — Google one-tap + JWT verify preserved
```gherkin
Given `POST /api/auth/google` (`auth.py:77-168`), `POST /api/auth/refresh` (`auth.py:171-206`), `POST /api/auth/logout` (`auth.py:209-218`), `GET /api/auth/me` (`auth.py:221-263`) are the routes NOT being removed
When the auth dead-code removal lands
Then `tests/api/test_auth.py::test_login_success` and `::test_me_unauthenticated` (the 2 of 5 tests that don't call `/register`/`/login` directly — lines 33-37, 50-52) still pass, rewired to mint their token via a non-HTTP path (see AC-D9)
  And `tests/e2e/auth.spec.ts` (renders `/login`, "shows the Google Sign-in button container" at line 32) passes unmodified — it never exercises password routes (confirmed by grep: no `register`/`login`-as-API-call matches, only the `/login` page route and the Google button)
```

**AC-D9** — test infrastructure rewired (prerequisite, not optional)
```gherkin
Given `tests/api/conftest.py:74-84`'s `auth_headers` fixture mints its token via `POST /api/auth/register` + `POST /api/auth/login` — both being removed (AC-D7)
When AC-D7 lands
Then `tests/api/conftest.py`'s `auth_headers` fixture is rewired BEFORE or IN THE SAME COMMIT as the route removal — e.g. mint a JWT directly via `core.security.create_access_token` against a DB-inserted test user, mirroring `backend/tests/conftest.py:98`'s already-safe pattern
  And every test that consumes `auth_headers` in `tests/api/test_api_endpoints.py` (watchlist/portfolio/alerts sections, ~15+ tests per §5 RTM) and `backend/tests/test_next_features.py` still passes — this is the single highest-leverage regression risk in the r2 auth work and must be verified BEFORE AC-M1's pass-count comparison is computed, not after
```

**AC-D10** — docs synced to code
```gherkin
Given `CLAUDE.md:17` ("Auth uses Google OAuth (one-tap)... NO custom token management on frontend... Tokens handled by useGoogleOneTapLogin") and `REQUIREMENTS.md:51-61` (FR-AUTH-001/002, "ไม่มี email+password registration") already stated the target policy that the code contradicted (Finding F3)
When AC-D7/D9 (route removal) and the frontend custom-token-logic removal (see AC-D9's sibling, frontend side: `frontend/src/store/authStore.js` + `frontend/src/services/api.js`) land
Then `frontend/src/store/authStore.js` and `frontend/src/services/api.js` no longer contain `localStorage`-based `access_token`/`refresh_token` get/set, `scheduleRefresh`/`silentRefresh` logic, or a 401-retry-via-`/auth/refresh` interceptor — proven by `grep -n "access_token\|refresh_token\|silentRefresh" frontend/src/store/authStore.js frontend/src/services/api.js` returning zero matches (or only matches inside a comment explaining the removal, not live code)
  And `CLAUDE.md:17` and `REQUIREMENTS.md` §2.1 (FR-AUTH-001/002/003) are edited in the SAME branch to describe the resulting code exactly — no further contradiction between docs and code (this closes Finding F3 and Open Question #3, both now resolved by user decision #3, not merely documented)
  And Sentinel reviews the auth-surface removal per Oliver's r2 note (`04-oliver-user-decisions.md:9`, "Sentinel must review auth surface removal") — evidence = Sentinel sign-off referenced in the PR, not assumed
```

Open Question #3 (§6, original) — **withdrawn**, resolved by user decision #3: remove dead code + fix docs (not "leave alone" or "just fix docs").

### 3. DoD addition

| # | Item | Evidence required |
|---|---|---|
| 16 | **CI not touched** (user decision #2) | `.github/workflows/ci.yml` diff shows **zero changes** to the `on:` trigger block (stays `workflow_dispatch` only, `ci.yml:4` per Sara §1.5) — this is an explicit non-change check, not an omission; a diff touching `ci.yml`'s trigger fails this item even if the rest of the file is untouched |

### 4. RTM updates

| AC | RTM row |
|---|---|
| AC-B1-r2, AC-B2-r2, AC-B4-r2 | Replace the AC-B1/B2/B4 rows (§5 original table) — Route/File unchanged (`schemas/common.py`, all 55 routes, `api.js:88-94`); Test: `tests/api/test_pr1_response.py` (existing) + NEW envelope-completeness test (asserts all 13 modules, not just system.py) |
| AC-D7 | Route/File: `backend/api/routes/auth.py:28-75` (routes to remove); Test: `tests/api/test_auth.py` (existing, 5 tests — 3 to delete/rewrite per AC-D7, 2 to rewire per AC-D8) |
| AC-D8 | Route/File: `auth.py:77-263` (routes kept); Test: `tests/api/test_auth.py::test_login_success,test_me_unauthenticated` (existing), `tests/e2e/auth.spec.ts` (existing) |
| AC-D9 | Route/File: `tests/api/conftest.py:74-84` (fixture to rewire), `backend/tests/conftest.py:98` (reference pattern, already safe); Test: NEW fixture rewrite + full `tests/api/test_api_endpoints.py` + `backend/tests/test_next_features.py` re-run (existing suites, now gated on the rewire) |
| AC-D10 | Route/File: `CLAUDE.md:17`, `REQUIREMENTS.md:49-61`, `frontend/src/store/authStore.js`, `frontend/src/services/api.js`; Test: NEW grep-based check (no dedicated automated test exists for doc-code sync) |

### 5. AC total

24 (original) + 4 (cross-read: M6, M7, A3, A4) = 28 → r2: retire 3 (AC-B1, AC-B2, AC-B4), add 3 replacements (AC-B1-r2, AC-B2-r2, AC-B4-r2) — net 0 — plus 4 new D-series (AC-D7, AC-D8, AC-D9, AC-D10).

**AC total after r2: 28 + 4 = 32.**

---

## § r3 — path final: `/api/v1`, no alias, 3 unversioned exceptions

Source: `outputs/deps-2026-09/01-sara-adr-migration.md` § r3 (lines 346-379). Final path: **`/api/v1`** for 12 of 13 modules (envelope + version together). **3 exceptions stay unversioned, at their current paths**: `GET /api/health` (infra contract — compose healthchecks, r3-2), `WS /api/ws/prices` (Caddy `@ws` long-timeout matcher, r3-1), `/api/ai/*` (Caddy `@ai` SSE-flush matcher — JSON sub-routes `/models`, `/analyze/{symbol}`, non-stream `/chat` still adopt the **envelope**, r3-1, just not the `/v1` path segment). §1-6 and prior r2 section left unmodified.

### 1. AC-B1-r2 / AC-B2-r2 / AC-B4-r2 → RETIRED, superseded by `-r3`

**AC-B1-r3**
```gherkin
Given user decision #1 (all 13 modules enveloped) + ADR-001 r3 final (`01-sara-adr-migration.md:346-348`): path = `/api/v1`, no legacy alias, single atomic commit
When the migration branch lands
Then 12 of 13 route modules (all except `system.py`'s `/health` sub-route, which stays at `/api/health` per AC-B9) are mounted under `prefix="/api/v1"` and return `{data, meta}` — e.g. `/api/v1/stocks/{symbol}/quote`, `/api/v1/watchlists`, `/api/v1/portfolio/analytics`, `/api/v1/auth/me`
  And `frontend/src/services/api.js:12` `baseURL` changes from `'/api'` to `'/api/v1'` in the SAME commit as the backend prefix-lift; `frontend/src/services/aiService.js`'s 3 axios call sites (`/models`, `/analyze/{symbol}`, non-stream `/chat`) explicitly bypass the v1 baseURL and keep calling `/api/ai/*` (r3-1) — verified by grep showing an explicit override (per-call `baseURL: '/api'` or a second axios instance), not an accidental double-prefix bug
```

**AC-B2-r3**
```gherkin
Given the r3-3 literal-change inventory (`01-sara-adr-migration.md:360-371`): ≈260 occurrences / ~20 files change mechanically in one commit (frontend `api.js` baseURL, 14 backend router prefix declarations, `rate_limit.py:30` path literal `/api/v1/auth/google`, 133 `tests/api` literals, 67 active `backend/tests` literals, ~40 `tests/e2e` literals excluding the 3 exception files)
When the `/api → /api/v1` prefix-lift lands
Then every literal listed in Sara's inventory is updated in the SAME commit (no partial-prefix state where some tests hit `/api/x` and the server only serves `/api/v1/x`)
  And the 3 exceptions (`/api/health`, `/api/ws/prices`, `/api/ai/*`) are explicitly excluded from the sed/rewrite — a literal-change script that touches those paths fails this AC (verified: `tests/e2e/health.spec.ts` 5 occurrences, `mocks.ts:179,294`, `ai-chat.spec.ts` 4 occurrences must remain `/api/health` and `/api/ai/*` unchanged)
```

**AC-B4-r3**
```gherkin
Given r3-2 mechanics: `system.py` splits into a `health` sub-router mounted bare at `/api` (so `GET /api/health` is unaffected) and the rest (`/system/ready`, `/system/celery-stats`, `/market/fgi`) moves under `/api/v1`
When a validation-error-triggering request hits any `/api/v1/*` route post-migration (e.g. `POST /api/v1/stocks/search` with missing `q`)
Then the response body is `{data: null, meta: {...}}` per ADR-002's error-block design (exact field — Sara's `outputs/api/openapi.yaml`, not this AC)
  And the SAME request against the 3 unversioned exceptions (e.g. malformed WS subscribe message) still returns its OWN pre-existing error shape (`main.py:315-316` `{"type":"error","message":"Invalid JSON"}` for WS) — the envelope decision does not retroactively apply to the 3 exceptions' error paths either
```

### 2. New AC-B9 — 3 unversioned exceptions still respond at old paths

```gherkin
Given r3-1/r3-2: `GET /api/health`, `WS /api/ws/prices`, and `/api/ai/*` (all sub-routes: POST /chat, GET /models, POST /analyze/{symbol}) are frozen at their CURRENT paths — no `/v1` segment, by design (infra contract + Caddy timeout/SSE-flush matchers that would break if demoted to the generic `/api/*` block)
When the `/api/v1` prefix-lift lands for the other 12 modules
Then `GET /api/health` still responds at exactly `/api/health` (not `/api/v1/health`) — verified by the SAME compose healthcheck commands unchanged: `docker-compose.dev.yml:67`, `docker-compose.prod.yml:60`, `docker-compose.ghcr.yml:71` (all `curl -f http://localhost:8000/api/health`) still pass with zero edits to those 3 files
  And `WS /api/ws/prices` still accepts connections at exactly that path (`frontend/src/hooks/useWebSocket.ts:39` unchanged)
  And `/api/ai/chat` (SSE stream), `/api/ai/models`, `/api/ai/analyze/{symbol}` still respond at `/api/ai/*` (not `/api/v1/ai/*`) — `frontend/src/services/aiService.js:37`'s raw `fetch('/api/ai/chat')` call needs zero edit
  And Caddy config (`caddy/Caddyfile`, `Caddyfile.dev`) requires **zero edits** — confirmed by Sara r3-4: `@ws`/`@ai` matchers untouched by design, generic `reverse_proxy /api/* backend:8000` already covers `/api/v1/...` identically
```

### 3. Other path-bearing AC — mechanical substitution table (no full Gherkin rewrite; `/api/*` → `/api/v1/*` unless listed as an exception)

| AC | Old path (this doc, pre-r3) | New path (r3) |
|---|---|---|
| AC-B3 (OpenAPI diff) | generic, all 55 routes | diff now expected across `/api/v1/*` (12 modules) + confirms 3 exceptions unchanged at old paths (cross-check against AC-B9) |
| AC-B6 (rate-limit/auth preserved) | `POST /api/auth/login`, `GET /api/auth/me` | `POST /api/v1/auth/login`, `GET /api/v1/auth/me` — `rate_limit.py:30`'s path-match literal updates to `/api/v1/auth/login` in the same commit (r3-3) |
| AC-B7 (health test) | `GET /api/health` | **unchanged** — confirmed exception, r3-2 |
| AC-B8 (WS contract) | `/api/ws/prices` | **unchanged** — confirmed exception, r3-1 |
| AC-C1 (pure-read cache-only) | `/api/stocks/{symbol}/quote` etc. | `/api/v1/stocks/{symbol}/quote`, `/api/v1/stocks/{symbol}/history`, etc. |
| AC-C2 (P95 preserved) | `/api/dashboard`, `/api/screener` | `/api/v1/dashboard`, `/api/v1/screener` |
| AC-D2 (rate-limit docstring reconciliation) | n/a (docstring claim, no route literal) | unchanged |
| AC-D5 (admin.py → require_admin) | `/api/admin/retention-policy` etc. | `/api/v1/admin/retention-policy` etc. |
| AC-D7 (password routes removed) | `POST /api/auth/register`, `POST /api/auth/login` | `POST /api/v1/auth/register`, `POST /api/v1/auth/login` — still return 404/405 at the NEW path (they're being deleted regardless of prefix; verify no route matches under either prefix) |
| AC-D8 (Google/JWT preserved) | `POST /api/auth/google`, `/refresh`, `/logout`, `GET /api/auth/me` | `POST /api/v1/auth/google`, `/api/v1/auth/refresh`, `/api/v1/auth/logout`, `GET /api/v1/auth/me` |
| AC-A3 (stocks split ordering) | `GET /api/stocks/quotes` vs `/{symbol}/quote` | `GET /api/v1/stocks/quotes` vs `/api/v1/stocks/{symbol}/quote` — collision risk identical, just under the new prefix |

### 4. RTM updates

All RTM rows whose "Route/File" column cites an `/api/...` path (§5 original table + § cross-read + § r2 tables) gain the same mechanical `/api/v1/*` prefix per the substitution table above, **except** rows for AC-B7, AC-B8, and AC-B9 (new row: Route/File = `system.py`'s health sub-router post-split, `main.py:293` WS route, `ai_chat.py` router — all 3 stay at old paths; Test = NEW compose-healthcheck + WS-connect + AI-fetch smoke, since no existing test currently asserts "these 3 stay unversioned while everything else moves").

### 5. AC total

32 (post-r2) → retire 3 (AC-B1-r2, AC-B2-r2, AC-B4-r2), add 3 replacements (AC-B1-r3, AC-B2-r3, AC-B4-r3) — net 0 — plus 1 new (AC-B9).

**AC total after r3: 32 + 1 = 33.**

