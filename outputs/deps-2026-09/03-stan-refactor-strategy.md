# deps-2026-09 — Refactor Strategy + Tech Radar (Stan, Phase 1a)

bd: deps-2026-09 · iter 0 · Stan (staff-engineer) · repo `73fac00` read-only clone `/home/claude/shotockviz-ro`
Scope: "improve API: code quality/structure" refactor strategy + tech-radar judgment + big-bang implementation sequencing. NOT here: version matrix / migration ADR / caching-versioning decisions (Sara), AC/BRD (Bella).

**Corrections to 00-oliver-discover.md** (evidence-checked):
- discover:16 says "stocks.py 672 LOC / 24 handlers" → measured: 672 LOC, **11 `@router` handlers / 13 `def`s** `[output: grep -c "@router" backend/api/routes/stocks.py → 11; grep -c "def " → 13]`.
- `services/stock_service.py` is **224 LOC**, not the 47KB monster CLAUDE.md:98 describes — already decomposed into `services/providers/` + `cache_orchestrator.py` `[output: wc -l]`. The complexity moved to providers (see §1).

---

## 1. Code-quality audit — measured

Tools installed into `.venv`: radon 6.0.1, ruff 0.16.5, mypy (uv pip install; no repo files touched).

### 1.1 radon cc (`radon cc -s -a backend/api backend/services backend/core`)

```
210 blocks (classes, functions, methods) analyzed.
Average complexity: B (5.338095238095238)
```

Worst offenders (grade D/F = must-fix; C = watch):

| file:line | function | grade (CC) |
|---|---|---|
| backend/services/providers/yahoo_provider.py:142 | `fetch_yahoo_direct` | **F (47)** |
| backend/api/routes/portfolio.py:46 | `get_analytics` | **F (43)** |
| backend/services/backtesting_engine.py:362 | `_compute_metrics` | D (29) |
| backend/api/routes/stocks.py:153 | `get_quotes_batch` | D (26) |
| backend/services/providers/yahoo_provider.py:37 | `fetch_quote_direct` | D (25) |
| backend/api/routes/portfolio_performance.py:22 | `get_portfolio_performance` | D (24) |
| backend/services/price_adjuster.py:27 | `adjust_prices` | D (24) |
| backend/services/providers/yahoo_fundamentals.py:16 | `fetch_fundamentals_direct` | D (24) |
| backend/api/routes/dashboard.py:94 | `_build_portfolio_summary` | D (21) |
| backend/services/backtesting_engine.py:197 | `_strategy_macd_crossover` | C (20) |
| backend/api/routes/stocks.py:99 / :338 | `get_stock_names` / `get_relative_strength` | C (19) / C (19) |
| backend/services/providers/stooq_provider.py:31 | `fetch_stooq_direct` | C (19) |
| backend/services/cache_orchestrator.py:172 | `fetch_stock_history` | C (17) |

LOC by module (top): stocks.py 672 · backtesting_engine.py 469 · ai_chat.py 468 · cache_orchestrator.py 378 · screener.py 353 · dashboard.py 342 `[output: wc -l]`. **Only stocks.py, backtesting_engine.py, ai_chat.py exceed 400 LOC**; only stocks.py is a route module >400.

### 1.2 ruff (`ruff check backend --statistics`, ruff 0.16.5 default ruleset, no repo config exists — `[output: find . -name '*.toml' → only backend/alembic.ini, backend/pytest.ini]`)

```
Found 747 errors. [*] 323 fixable with --fix
202 BLE001 blind-except        86 B008 function-call-in-default-argument (= FastAPI Depends idiom)
132 I001   unsorted-imports    77 F401 unused-import
 65 UP045  non-pep604-Optional 63 S110 try-except-pass
 31 RUF059 unused-unpacked-var 18 F541 f-string-no-placeholder
  7 F841 unused-variable        4 F821 undefined-name
  3 invalid-syntax              4 DTZ011 + 4 DTZ007 naive-datetime
```
- `--select E,F` alone: 530 errors `[output: ruff check backend --select E,F]`.
- 3× invalid-syntax = `backend/tests/test_next_features.py:630` (`class TestVolumeSpike Alerts:` — space in class name) — same file that fails pytest collection (discover:26).
- 4× F821 `Undefined name 'User'` = real lint findings at `models/alert.py:49`, `models/drawing.py:22`, `models/portfolio.py:36`, `models/watchlist.py:16` (relationship annotations without `TYPE_CHECKING` import) `[output: ruff --select F821 --output-format concise]`.
- 63× S110 try-except-pass is the genuine smell: silent swallow (e.g. stocks.py:212-216 fund-cache stage `except Exception: pass`). 202× BLE001 is largely the deliberate CQRS graceful-degradation pattern (stocks.py:167-185 Redis-down fallback) — do NOT mass-"fix"; require a logger call instead.

### 1.3 mypy (`mypy --ignore-missing-imports backend/api backend/core`)

```
Found 121 errors in 17 files (checked 29 source files)
 37 [union-attr]  27 [operator]  18 [arg-type]  11 [return-value]  9 [attr-defined]
```
Representative real bugs surfaced: `api/routes/ai_chat.py:185` `"type[WatchlistItem]" has no attribute "user_id"` (attr-defined), `api/routes/auth.py:256` `Select.where` receives plain `bool`.

**Verdict**: average B is healthy; damage is concentrated in ~12 functions (2×F, 7×D) and in test hygiene. This is a *targeted* refactor, not a rewrite (anti-pattern: "doesn't follow standards — rewrite" refused).

---

## 2. Backend refactor strategy (behavior-preserving)

### 2.1 Split `stocks.py` (672 LOC, 11 handlers) — router composition, HTTP contract frozen

Current: single `APIRouter(prefix="/api/stocks")` at stocks.py:19, registered at main.py:277. Handlers `[output: grep -n "@router" stocks.py]`: `/search`:34, `/names`:98, `/quotes`:152, `/{symbol}/quote`:248, `/{symbol}/history`:296, `/{symbol}/rs`:337, `/{symbol}/fundamentals`:417, `/{symbol}/financials`:442, `/{symbol}/earnings`:508, `/{symbol}/news`:572, `/{symbol}/events`:625.

Target package (pure file moves, zero handler-body edits in the split commit):

```
backend/api/routes/stocks/
├── __init__.py       # router = APIRouter(prefix="/api/stocks", tags=["stocks"])
│                     # router.include_router(search.router) … ORDER: static before /{symbol}
├── _shared.py        # _YAHOO_SYMBOL_RE, _is_yahoo_fetchable, VALID_TIMEFRAMES (stocks.py:22-31)
├── search.py         # /search, /names                    (~2 handlers, ~150 LOC)
├── quotes.py         # /quotes, /{symbol}/quote           (~150 LOC)
├── history.py        # /{symbol}/history, /{symbol}/rs    (~130 LOC)
├── fundamentals.py   # /{symbol}/fundamentals, /financials, /earnings (~160 LOC)
└── news_events.py    # /{symbol}/news, /{symbol}/events   (~110 LOC)
```

- `main.py:277 app.include_router(stocks.router)` — unchanged (package `__init__` exports `router`). Zero import-site churn.
- 🔴 Ordering constraint: sub-routers with static paths (`/search`, `/names`, `/quotes`) MUST be included before `/{symbol}/*` sub-routers — FastAPI matches in registration order; `/quotes` would otherwise match `/{symbol}/quote`'s parent pattern space. Encode order in `__init__.py` with a comment.
- No other route module needs splitting: next-largest route file ai_chat.py = 468 LOC but only 3 handlers (ai_chat.py:295/417/436) — its bulk is SSE plumbing, cohesive; leave it.
- Complexity extraction (get_quotes_batch D26 → pull Stage-1/2/3 into `services/quote_reader.py`; portfolio.py:46 F43 → `services/portfolio_analytics.py`; portfolio_performance.py:22 D24; dashboard.py:94 D21) — **deferred to a follow-up bd**, NOT in the big-bang branch. Rationale (DISSENT vs "fix everything now"): big-bang already carries 20+ version bumps; mixing behavior-adjacent extraction into the same branch destroys bisectability. The file split above is mechanically safe; body rewrites are not.

**Proof of behavior preservation (characterization):**
1. OpenAPI snapshot: `cd backend && ../.venv/bin/python -c "from main import app; import json; print(json.dumps(app.openapi(), sort_keys=True))" > /tmp/openapi.before.json` — capture BEFORE split, diff AFTER must be empty (paths, params, response models identical).
2. Existing tests: `backend/tests/test_services.py`, `test_cache_keys.py`, `test_symbol_utils.py`, `test_screener_indicators.py` + root `tests/api/test_api_endpoints.py` (116-pass baseline, discover:27) — pass count must not regress.

### 2.2 pydantic v2 `model_config` migration — 8 sites (verified `[output: grep -rn "class Config" backend --include='*.py' | grep -v tests]`)

| Site | Replace with |
|---|---|
| core/config.py:72 (`env_file=".env"`, `env_file_encoding="utf-8"`) | `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")` (import from `pydantic_settings`) |
| models/schemas.py:52, 140, 151, 189, 242, 269 (all `from_attributes = True`) | `model_config = ConfigDict(from_attributes=True)` (import from `pydantic`) |
| api/routes/notes.py:24 (`from_attributes = True` on `NoteResponse`) | same `ConfigDict` form |

Mechanical, v2-supported since 2.0; `class Config` is deprecated and removed in pydantic v3 — do it now while touching pydantic 2.12→2.13.
**Proof**: `cd backend && ../.venv/bin/python -W error::DeprecationWarning -c "from core.config import settings; import models.schemas; import api.routes.notes"` exits 0 (currently raises PydanticDeprecatedSince20 under `-W error`), plus full pytest run.

### 2.3 Typing/consistency rules + toolchain — exact config

Add **`backend/pyproject.toml`** (new file; repo has none today):

```toml
[tool.ruff]
target-version = "py313"
line-length = 110

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "UP", "B", "S110", "S112", "DTZ", "RUF", "F401"]
# NOT enabled yet: BLE001 (202 hits = deliberate CQRS degrade pattern; revisit post-bump)
ignore = []

[tool.ruff.lint.flake8-bugbear]
# FastAPI DI idiom — kills all 86 B008 false positives without disabling B008
extend-immutable-calls = ["fastapi.Depends", "fastapi.Query", "fastapi.Path", "fastapi.Body", "fastapi.Header"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S110", "S112", "DTZ"]

[tool.ruff.lint.isort]
known-first-party = ["api", "core", "models", "services", "workers"]

[tool.mypy]
python_version = "3.13"
ignore_missing_imports = true
check_untyped_defs = true
warn_unused_ignores = true
plugins = ["pydantic.mypy"]
# Ratchet stage 2 (follow-up bd): disallow_untyped_defs = true for core.* and services.*
```

Rules of the road (enforced by the config above, not prose):
- New `except Exception:` requires a `logger.*` call in the handler body (S110/S112 catch silent ones).
- `Optional[X]`/`List[X]` → `X | None`/`list[X]` — 65× UP045 + 7× UP006, all auto-fixable (`ruff check --fix`).
- Naive datetimes (DTZ007/DTZ011, 8 hits) must pass an explicit `tz=` — market-hours code (CLAUDE.md:169 ICT) makes naive `date.today()` a real bug class.
- Mypy strictness: start at `check_untyped_defs` (121-error baseline recorded in §1.3 = ratchet ceiling; CI fails if count rises). `--strict` now would be noise-driven-development.
- Formatter: `ruff format` (line-length 110). No black/isort — one tool.

Gate commands: `.venv/bin/ruff check backend && .venv/bin/ruff format --check backend && .venv/bin/mypy backend/api backend/core`.

---

## 3. Frontend

### 3.1 JS → TS conversion set (all 13 remaining .js files, 877 LOC total `[output: find frontend/src -name '*.js' | xargs wc -l]`; routes/components already TS — 49 .ts/.tsx files)

Conversion order (dependency leaves first):
1. `src/utils/formatters.js` (184) · `src/utils/indicators.js` (159) — pure functions, trivial.
2. `src/services/api.js` (106) — axios instance + JWT interceptors; type the interceptor chain + `ApiError`.
3. `src/services/{stockService,watchlistService,portfolioService,alertService,notesService,dashboardService}.js` (29/20/13/11/10/8) — thin wrappers over `api`; return types come free once api.ts is typed.
4. `src/services/aiService.js` (99) — SSE stream reader; type the event payloads.
5. `src/store/authStore.js` (159) · `src/store/appStore.js` (72) — Zustand 5 `create<State>()`; typing these lights up every consumer component.
6. `src/hooks/useAuth.js` (7) — one-liner re-export of authStore.

⚠️ authStore.js touches token storage — CLAUDE.md:17 "NO custom token management on frontend" is a 3×-user-demanded rule: conversion is type-annotation ONLY, zero logic movement.

### 3.2 tsconfig under TS 7 — measured spike, not opinion

Current tsconfig (frontend/tsconfig.json): `strict: false`, `baseUrl: "."`, `paths {"@/*": ["./src/*"]}`, `allowJs: true`, no typecheck script — `npm run build` = `vite build` only, **tsc is not in the build path at all** `[frontend/package.json scripts: dev/build/preview only]`.

Spike results (TS 7.0.2 installed in scratchpad, run against this repo's sources — no repo files modified):

| Run | Result |
|---|---|
| `tsc 5.9.3 --noEmit` (repo as-is) | **4 errors** (TradingChart.tsx:91, :96 TS2339; EmptyState.tsx:1 TS1484; router.tsx:5 TS2345), 6.6s `[output: npx tsc --noEmit; tsc --version → 5.9.3]` |
| `tsc 7.0.2` vs repo tsconfig | **TS5102: Option 'baseUrl' has been removed** — hard error, config change mandatory |
| `tsc 7.0.2` with baseUrl removed (paths kept, relative) | **identical 4 errors, 1.0s (6.6× faster)** — full semantic parity with 5.9.3 on this codebase |
| `tsc 7.0.2` + `strictNullChecks: true` | 123 errors |
| `tsc 7.0.2` + `strict: true` | 193 errors (79 TS2339, 49 TS7053, 14 TS18047) |

Strictness plan: bump branch keeps `strict: false` and fixes the 4 baseline errors that are fixable without strictNullChecks (3 of 4; router.tsx:5 TS2345 is TanStack Router's branded error *demanding* `strictNullChecks` — it stays whitelisted). Follow-up bd: `strictNullChecks: true` (123-error ratchet) → `strict: true` (193). New `typecheck` script = `tsc --noEmit`, CI-gated against a 4-error snapshot, ratcheting down.

tsconfig diff for the bump branch:
```jsonc
// REMOVE:  "baseUrl": ".",          ← TS 7 hard-removed (TS5102, spike-proven)
// KEEP:    "paths": {"@/*": ["./src/*"]}   ← resolves relative to tsconfig dir without baseUrl
// ADD:     nothing else changes in the bump branch
```

### 3.3 TS 7 toolchain impact — the four suspects, checked

- **`typescript` peer deps**: only consumer in the tree is `tsconfck@3.1.6` (via vite-tsconfig-paths), peer `typescript ^5.0.0` *optional* `[output: npm ls typescript → typescript@5.9.3, vite-tsconfig-paths→tsconfck→typescript deduped; node -e read of tsconfck package.json]`. Scratchpad install test of `typescript@7.0.2 + vite-tsconfig-paths@6.1.1 + vite@8`: npm resolves cleanly by nesting typescript@5.9.3 under tsconfck — **no ERESOLVE** `[output: npm install in scratchpad → "added 23 packages", npm ls shows nested 5.9.3]`. Also observed: `npm warn deprecated tsconfck@3.1.6: unmaintained`.
- **`vite-tsconfig-paths`**: Vite 8 ships native `resolve.tsconfigPaths` — drop the plugin entirely in this bump; that removes the only typescript peer edge AND an unmaintained transitive dep. Sources: [vitejs/vite#22112](https://github.com/vitejs/vite/issues/22112), [vitest-dev/vitest#10054](https://github.com/vitest-dev/vitest/issues/10054), [vite-tsconfig-paths README](https://github.com/aleclarson/vite-tsconfig-paths).
- **TanStack router codegen** (`@tanstack/router-plugin` → routeTree.gen.ts): package has **no typescript dependency or peer** `[output: node -e read of @tanstack/router-plugin/package.json → deps.ts=undefined, peer.ts=undefined]` — uses its own parser, immune to TS 7.
- **`@vitejs/plugin-react`** (babel-based) and **vite/nitro**: no typescript dep/peer `[output: same package.json probe]`. `vite build` never invokes tsc, so the compiler swap cannot break the build.
- **Compiler-API consumers** (the actual TS 7 hazard — "TypeScript 7.0 does not ship with an API… @typescript/typescript6 side-by-side for tools like typescript-eslint", [Announcing TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)): this repo has **no eslint/prettier/biome config** `[output: ls frontend | grep -iE eslint|prettier|biome → empty]` — zero API consumers. The side-by-side `@typescript/typescript6` alias is NOT needed here.

### 3.4 TS 7 verdict: **GO** ✅

Evidence chain: (a) 7.0.2 is a GA release, 2026-07-08, not a preview ([announcement](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)); (b) spike shows exact error parity on this codebase at 6.6× speed; (c) zero compiler-API consumers in the repo; (d) build path doesn't use tsc; (e) the single required change (drop `baseUrl`) is proven above. Trial-criteria note (my own rule: <6-month GA usually = refuse): TS 7 gets an exception because the native port has 12+ months of public preview (`@typescript/native-preview`, 8.5M weekly downloads per the announcement) and Microsoft ships VS Code on it — criteria met via ADR exception, Sara to record.
**Fallback pin if anything surfaces mid-branch (R1)**: `typescript@~5.9.3` + restore `baseUrl` line — one-commit revert, no other file depends on TS version.

---

## 4. Big-bang implementation sequencing (branch `chore/deps-2026-09`)

Two independent chains = two Daves max. File-scope contracts are disjoint across chains; within a chain, packages are strictly sequential (same Dave), so intra-chain file reuse is safe.

### Chain B (backend Dave) — WP-B0 → B5 sequential

| WP | Owns files | Work | Prove (exact commands, run from repo root) |
|---|---|---|---|
| **B0 hygiene** (FIRST commit — baseline-broken tests fixed/quarantined HERE) | `backend/tests/test_next_features.py`, `backend/tests/test_api_e2e.py`, `backend/tests/test_user_simulation.py`, `backend/pytest.ini`, **new** `backend/pyproject.toml`, **new** `backend/tests/fixtures/yf_golden/` | 1) test_next_features.py:630 `class TestVolumeSpike Alerts:` → `TestVolumeSpikeAlerts`. 2) test_api_e2e.py:38 imports `AlertCondition` which does not exist anywhere in `backend/models/alert.py` (only AlertType/AlertStatus/AlertChannel `[output: grep -rn AlertCondition backend --include='*.py' -l | grep -v tests → empty]`) → module-level `pytest.skip(..., allow_module_level=True)` + ticket ref (Q1 below). 3) mark test_user_simulation.py `@pytest.mark.integration` (26 live-stack failures, discover:26), add `-m "not integration"` to CI invocation. 4) add §2.3 pyproject. 5) **capture yfinance 0.2.65 golden fixtures** (record real provider outputs to JSON) BEFORE any bump — WP-B3's characterization baseline | `cd backend && ../.venv/bin/pytest tests -q --collect-only 2>&1 \| tail -2` → 0 errors; `../.venv/bin/pytest tests -q -m "not integration"` → record new baseline (expect ≥107 pass / 0 collect-fail) |
| **B1 bumps** | `backend/requirements.txt`, `backend/Dockerfile` | All version bumps per Sara's matrix in one commit (incl. yfinance 1.x, redis 8, pytest-asyncio 1.x) — fallout fixed in B2-B4, one concern per commit | `uv pip install -r backend/requirements.txt` clean; `cd backend && ../.venv/bin/pytest tests -q -m "not integration"` → failures enumerated per package, assigned to B2/B3/B4 |
| **B2 pytest-asyncio 1.x + pydantic config** | `backend/tests/conftest.py`, `backend/models/schemas.py`, `backend/core/config.py`, `backend/api/routes/notes.py` | Delete custom session `event_loop` fixture (conftest.py:25-29 — removed API in pytest-asyncio 1.x) → `asyncio_default_fixture_loop_scope = session` in pytest.ini (`asyncio_mode = auto` already set, pytest.ini:17). §2.2 model_config ×8 | `cd backend && ../.venv/bin/pytest tests -q -m "not integration"` ≥ B0 baseline; `-W error::DeprecationWarning` import probe (§2.2) exits 0 |
| **B3 yfinance 1.x** | `backend/services/providers/*.py`, `backend/workers/*.py` | Adapt to 1.x API against B0 golden fixtures. Highest-CC code in repo lives here (yahoo_provider.py:142 F47) — behavior lock via fixtures is mandatory, refactor of those functions is NOT in scope | `cd backend && ../.venv/bin/pytest tests/test_services.py tests/test_screener_indicators.py -q` + golden-fixture tests green |
| **B4 redis 8 client** | `backend/core/redis.py`, `backend/services/cache_service.py`, `backend/services/cache_orchestrator.py` | redis-py 7.1→8.1 API fallout | `cd backend && ../.venv/bin/pytest tests -q -m "not integration"`; `PYTHONPATH=backend .venv/bin/pytest tests/api -q` (root suite, 116-pass baseline discover:27) |
| **B5 stocks split** (LAST — only on green) | delete `backend/api/routes/stocks.py`, **new** `backend/api/routes/stocks/` (7 files, §2.1), `backend/models/{alert,drawing,portfolio,watchlist}.py` (F821 TYPE_CHECKING imports only) | §2.1 mechanical split + `ruff check --fix` autofixes (I001/F401/UP045 — 323 fixable) | OpenAPI snapshot diff empty (§2.1); full pytest ≥ baseline; `ruff check backend` clean; `mypy backend/api backend/core` ≤121 |

### Chain F (frontend Dave) — WP-F0 → F2 sequential, parallel to Chain B (zero shared files)

| WP | Owns files | Work | Prove |
|---|---|---|---|
| **F0 bumps** | `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, `frontend/Dockerfile` | Vite 8 + plugin-react 6 + TanStack 1.168 + Node `node:24-alpine` + nitro pinned **exact** beta (kill `npm:nitro-nightly@latest`, vite.config import `nitro/vite` unchanged); **remove `vite-tsconfig-paths`**, add `resolve: { tsconfigPaths: true }` (§3.3); add `"typecheck": "tsc --noEmit"` script | `cd frontend && npm ci && npm run build` green on Node 24 (baseline: green on 22, 9.7s, discover:28); alias `@/` imports resolve in build |
| **F1 TS 7** | `frontend/tsconfig.json`, `frontend/package.json` (typescript pin — same-chain sequential, no conflict), `frontend/src/components/chart/TradingChart.tsx`, `frontend/src/components/ui/EmptyState.tsx` | `typescript@~7.0.2`; remove `baseUrl` (§3.2); fix TradingChart.tsx:91/:96 (narrow union before `.value`) + EmptyState.tsx:1 (`import type`) | `cd frontend && npm run typecheck` → exactly 1 known error (router.tsx:5 strictNullChecks-branded, whitelisted); `npm run build` green |
| **F2 JS→TS** | the 13 `.js` files of §3.1 (renamed `.ts`) + import-site extension-free imports (no edits needed — imports are specifier-only) | §3.1 order; annotation-only, zero logic change (authStore rule §3.1 ⚠️) | `npm run typecheck` error count ≤ F1; `npm run build` green |

Merge order at pre-merge gate (user stop point): Chain B and Chain F land on the same branch; B0 commits first (baseline fix benefits everyone), then chains interleave freely — no shared files. E2E Playwright + full-stack verify = Phase 3, out of my scope.

---

## 5. Tech radar note (deps-2026-09 slice)

| Item | Ring | Rationale (evidence) |
|---|---|---|
| TypeScript 7.0 | **Adopt** (this repo) | Spike parity + no API consumers (§3.4). Org-wide: Trial until repos WITH typescript-eslint prove the `@typescript/typescript6` side-by-side |
| Vite 8 (Rolldown) | **Trial** | Bundler engine swap, GA but young plugin ecosystem; this bump is the trial instance. Exit criteria: build green + no prod SSR regression for 1 month |
| Nitro 3 beta | **Trial with exact pin** — current `npm:nitro-nightly@latest` (package.json) = **Hold, remove immediately** | Floating nightly in a prod lockfile is the single worst supply-chain item in this repo. Pin exact `3.0.x-beta` build (Sara's matrix picks the number) |
| yfinance 1.x | **Trial with gate** | Unofficial-API scraper crossing 0.x→1.x; golden-fixture characterization (WP-B0/B3) is the gate. It feeds all 8 Celery workers (CLAUDE.md:210-218) — blast radius = entire data plane |
| redis-py 8 | **Adopt** | Mature client, server stays Redis 7; fallout is mechanical (WP-B4) |
| pytest-asyncio 1.x | **Adopt** | Maintenance-mandatory; repo impact = one fixture (conftest.py:25) + one ini line |
| Node 24 | **Adopt** | Active LTS ([nodejs.org releases](https://nodejs.org/en/about/previous-releases), [endoflife.date/nodejs](https://endoflife.date/nodejs)) — user decision confirmed sound |
| Node 26 | **Assess** | Current line, LTS promotion ~Oct 2026; nothing in this repo needs 26 features. Revisit next quarter |
| vite-tsconfig-paths / tsconfck | **Hold — remove** | tsconfck npm-deprecated "unmaintained" `[output: npm warn deprecated tsconfck@3.1.6]`; Vite 8 native replacement exists (§3.3) |

Sources: [Announcing TypeScript 7.0 (devblogs.microsoft.com)](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/) · [vitejs/vite#22112](https://github.com/vitejs/vite/issues/22112) · [vitest-dev/vitest#10054](https://github.com/vitest-dev/vitest/issues/10054) · [vite-tsconfig-paths](https://github.com/aleclarson/vite-tsconfig-paths) · [nodejs.org previous releases](https://nodejs.org/en/about/previous-releases) · [endoflife.date/nodejs](https://endoflife.date/nodejs)

---

## 6. Open questions for Oliver

1. `test_api_e2e.py` imports `AlertCondition` that no longer exists in `models/alert.py` — WP-B0 quarantines with skip+ticket; does rewriting that e2e suite become a new bd, or die? (It's the only e2e coverage of alerts.)
2. WP-B5 (stocks.py split) rides the big-bang branch as final commits (my recommendation, openapi-diff-proven) — confirm, or split to a separate PR post-merge?
3. Complexity extraction backlog (portfolio.py:46 F43, yahoo_provider.py:142 F47, +7 D-grade — §2.1) → new bd with RICE input from me? Not in this branch by design.
4. Strictness ratchet follow-up bd (`strictNullChecks` = 123 errors measured, `strict` = 193) — schedule next quarter or attach to the complexity bd?
5. Nitro exact-pin number and `resolve.tsconfigPaths` swap must match Sara's matrix — flag to her that my WP-F0 assumes both; conflict = her matrix wins, my WP-F0 contract updates.

---

## § r3 — work package update (spec revision per 04-oliver-user-decisions.md + Sara ADR § r2/§ r3 + Bella § r2/§ r3)

Inputs: `04-oliver-user-decisions.md` (all read) · `01-sara-adr-migration.md:301-394` (r2-1..r3-5) · `02-bella-brd-ac.md:474-643` (AC-B1-r3/B2-r3/B4-r3/B9, AC-D7-D10, DoD 16). §4 above is **superseded by the ordered list below**; §1-3 audit/strategy content stands. Original open questions #1 (quarantine — answered: quarantine, 04-oliver:14), #4 (ratchet — separate bd, 04-oliver:15), #5 (nitro pin `3.0.260610-beta` + tsconfigPaths — confirmed, 04-oliver:13) are closed.

### r3-A · Why the v1+envelope flip cannot live inside either parallel chain

AC-B1-r3 (`02-bella-brd-ac.md:588-594`) mandates backend prefix-lift + frontend `api.js:12` baseURL flip in the **SAME commit**; AC-B2-r3 mandates all ≈260 literals (`01-sara-adr-migration.md:360-371`: 14 router prefixes + main.py mounts + rate_limit.py + api.js + aiService dual-base + 133 `tests/api` + 67 `backend/tests` + ~40 `tests/e2e`) in that same commit. One commit spanning backend + frontend + both test trees **cannot be split across two Daves** — so the two-chain parallelism of §4 ends at a **barrier**, and the flip (plus ADR-007, which also spans `auth.py` + `authStore.js` + `api.js`) runs in a **serial tail owned by one Dave**. Collision is avoided by construction, not by file lists.

Additional ordering forced by ADR-007 (`01-sara-adr-migration.md:315-341`):
- **Auth removal BEFORE the flip** — Sara's 133-literal count is "minus ADR-007 removals" (r3-3 table row `tests/api`); removing `/register`,`/login`,`/refresh`,`/logout` first means 4 fewer routes to prefix-lift/envelope, and the `auth_headers` rewire (AC-D9, `tests/api/conftest.py:74-84` → mint via `create_access_token`, pattern `backend/tests/conftest.py:98`) makes the fixture path-independent before the path rewrite.
- **Auth removal BEFORE JS→TS conversion** (old WP-F2) — converting `silentRefresh`/refresh-timer/401-retry code (`authStore.js:18-67`, `api.js:27-62`) to TS and then deleting it is waste; ADR-007's line refs also assume `.js`. So F2 moves to the end of the serial tail (now WP-S3).

### r3-B · Corrections to §4 (r3)

1. **CI untouched (user decision #2, DoD 16 `02-bella-brd-ac.md:562`)**: §4 WP-B0 phrase "add `-m 'not integration'` to CI invocation" is **retracted** — no WP touches `.github/workflows/ci.yml` (triggers stay `workflow_dispatch`, evidence gate = local runs). The deselect lands in `backend/pytest.ini` `addopts` (file already owned by B0) or the documented local command only.
2. WP-B5 (stocks split) still precedes the flip; WP-S2's prefix-lift then edits `backend/api/routes/stocks/__init__.py` (one line) instead of `stocks.py:19` — noted so Sara's r3-3 inventory line "stocks.py:19 et al." maps to the post-split file.
3. §4 "Merge order" paragraph void — replaced by the barrier model below.

### r3-C · Final ordered WP list (11 packages)

**Chain B (backend Dave) — sequential, parallel to Chain F:**

| WP | Owns files (delta vs §4 noted) | Prove |
|---|---|---|
| **B0 hygiene** | as §4 + correction r3-B-1 (deselect via pytest.ini only, no ci.yml) | `cd backend && ../.venv/bin/pytest tests -q --collect-only 2>&1 \| tail -2` → 0 errors; baseline recorded |
| **B1 bumps** | as §4 | as §4 |
| **B2 pytest-asyncio + pydantic model_config** | as §4 | as §4 |
| **B3 yfinance 1.x** | as §4 | as §4 (golden fixtures from B0) |
| **B4 redis 8** | as §4 | as §4 |
| **B5 stocks split** | as §4 — split keeps prefix `"/api/stocks"` verbatim (flip is S2's job, AC-A3 ordering risk re-checked there) | OpenAPI diff empty **at old paths**; full pytest ≥ baseline |

**Chain F (frontend Dave) — sequential, parallel to Chain B:**

| WP | Owns files | Prove |
|---|---|---|
| **F0 bumps** | as §4 (nitro pin `3.0.260610-beta`, drop vite-tsconfig-paths → `resolve.tsconfigPaths` — both confirmed 04-oliver:13) | `npm ci && npm run build` green on Node 24 |
| **F1 TS 7** | as §4 | `npm run typecheck` = 1 whitelisted error; build green |

**BARRIER** — both chains green (full backend pytest + `tests/api` ≥ baseline, frontend build+typecheck green). Serial tail, **single Dave** (this is where the two-Dave contract intentionally ends):

| WP | Owns files | Work | Prove |
|---|---|---|---|
| **S1 auth removal (ADR-007)** | `backend/api/routes/auth.py`, `backend/models/schemas.py` (auth schemas + TokenResponse), `backend/core/security.py`, rate-limiter file (`rate_limit.py:30` re-point to `/api/auth/google` — still old prefix, S2 lifts it), `frontend/src/store/authStore.js`, `frontend/src/services/api.js` (401-refresh interceptor block :27-62 only — baseURL/unwrap untouched here), `frontend/src/routes/__root.tsx` (One Tap `disabled` flip, r2-3), `tests/api/conftest.py`, `tests/api/test_auth.py`, `tests/api/test_api_endpoints.py` (register/login coverage deletion), `CLAUDE.md:17`, `REQUIREMENTS.md` §auth | 7 backend items + 2 frontend files per ADR-007 table; AC-D9 rewire in SAME commit as route removal | `PYTHONPATH=backend .venv/bin/pytest tests/api -q` ≥ baseline-minus-deleted; NEW AC-D7 404/405 test green; AC-D10 grep: `grep -n "refresh_token\|silentRefresh" frontend/src/store/authStore.js frontend/src/services/api.js` → 0 live-code matches; `npm run build` green; Sentinel sign-off ref in PR (AC-D10) |
| **S2 envelope + `/api/v1` flip (ONE commit)** | 14 router prefix declarations (incl. `stocks/__init__.py`), `backend/api/routes/system.py` (health sub-router split, r3-2), `backend/main.py` (:275-288 `api_v1` aggregate + 3 exception mounts; :293 WS untouched), rate-limiter literal → `/api/v1/auth/google`, `backend/models/schemas.py`/`schemas/common.py` (envelope wiring, all 13 modules), `frontend/src/services/api.js` (baseURL `'/api/v1'` + `.data.data` unwrap + error-parse per AC-B4-r3), `frontend/src/services/aiService.js` (3 axios sites bypass v1 base — dual-base wiring, r3-1), `tests/api/*` (133 literals), `backend/tests/test_next_features.py` (67 literals), `tests/e2e/**` (~40 literals + `mocks.ts`; exceptions excluded: `health.spec.ts` ×5, `mocks.ts:179,:294`, `ai-chat.spec.ts` ×4 stay), `CLAUDE.md` architecture diagram | Envelope (all 13, AC-B1-r3) + prefix-lift (12 modules) + 3 exceptions frozen (AC-B9) — atomic | OpenAPI snapshot: 12 modules under `/api/v1/*`, `/api/health` + `/api/ai/*` at old paths (AC-B3-r3); full backend pytest + `tests/api` ≥ baseline; whitelist grep: `grep -rn "'/api/" frontend/src tests backend/tests --include='*.{js,ts,tsx,py}'` → only `/api/v1`, `/api/health`, `/api/ws/prices`, `/api/ai/` remain; compose healthcheck lines diff-empty (docker-compose.dev.yml:67, prod:60, ghcr:71 — AC-B9); `npm run build` green. e2e literals proven by grep only (suite needs live stack — Quinn Phase 3) |
| **S3 JS→TS conversion** (old F2) | the remaining `.js` files of §3.1 (now slimmed: authStore/api post-S1/S2) | annotation-only, §3.1 order + authStore ⚠️ unchanged | `npm run typecheck` ≤ F1 count; `npm run build` green |

### r3-D · File-scope collisions (declared, all resolved by sequencing)

| File | Touched by | Resolution |
|---|---|---|
| `frontend/src/services/api.js` | F-chain adjacency, S1 (interceptor removal), S2 (baseURL+unwrap), S3 (→ .ts) | serial tail, one Dave; S1/S2 edit disjoint regions but land as separate sequential commits anyway |
| `frontend/src/store/authStore.js` | S1, S3 | serial |
| `backend/models/schemas.py` | B2 (model_config), S1 (auth schema removal), S2 (envelope) | barrier guarantees B2 long-landed |
| `backend/tests/test_next_features.py` | B0 (syntax fix), S2 (67 literals) | same-chain then serial |
| `tests/api/conftest.py` + suite | S1 (auth_headers rewire), S2 (path literals) | serial, S1 before S2 by design (r3-A) |
| `rate_limit.py` | S1 (re-point), S2 (v1 literal) | serial |
| `.github/workflows/ci.yml` | **nobody** | DoD 16 non-change check |

**Net**: 11 WPs (B0-B5, F0-F1, S1-S3). Parallelism = 2 Daves until the barrier; tail is serial by AC construction (same-commit mandates). The flip = WP-S2; auth removal = WP-S1 (before S2). No unresolved collision.
