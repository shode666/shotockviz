# deps-2026-09 — Phase 0 Discover (Oliver)

bd: deps-2026-09 · iter 0 · mode: Hybrid · tracker: markdown fallback (`outputs/deps-2026-09/state.json`)
Repo: github.com/shode666/shotockviz @ `73fac00` (main) — cloud read-only clone at `/home/claude/shotockviz-ro`; **writes land on the user's Mac** (`~/workspace/shotockviz`, mounted via device shell) — decided by user.

## User decisions (stated 2026-09-03)
- Strategy: **big-bang** — all bumps on one branch (`chore/deps-2026-09`), fix until green. (Oliver dissented: staged recommended; user chose big-bang.)
- Node target: **24 LTS** (`node:24-alpine`).
- TypeScript **7.x** included.
- "Improve API" = ALL FOUR: (1) code quality/structure, (2) API contract/versioning, (3) performance/caching, (4) security/hardening.
- Engagement mode: Hybrid — AFK through Plan→Implement→Review→Triage; stop at **pre-merge** and every **R0**.

## Stack evidence
- Frontend: React 19.2 + TanStack Start 1.132 + Vite 7.1 + TS 5.7 + Tailwind 4.1 + Zustand 5 + lightweight-charts 5.1; `nitro` pinned as `npm:nitro-nightly@latest` (🔴 floating). Dockerfile `node:22-alpine`.
- Backend: FastAPI 0.131 / uvicorn 0.41 / gunicorn 23 / SQLAlchemy 2.0.46 / alembic 1.14 / pydantic 2.12 / redis 7.1 / celery 5.6.2 / yfinance 0.2.65 / pytest 8.3 / pytest-asyncio 0.25. `python:3.13-slim`. 116 py files, 14,253 LOC (non-test).
- Backend routes: 15 modules in `backend/api/routes/`; `stocks.py` 672 LOC / 24 handlers (largest). Pydantic v1-style `class Config:` at `core/config.py:72`, `models/schemas.py` (6×), `api/routes/notes.py:24`.
- Alembic: only 2 revisions (`0001_ohlcv_bars`, `0002_add_currency`), no base schema; fresh DB uses `scripts/init_db.py` (commit `bd487ae`).
- CI: `.github/workflows/ci.yml` + `deploy.yml` are `workflow_dispatch` only. Deploy = GHA → GHCR → droplet 188.166.234.146 (`docs/deploy-gha.md`, `docker-compose.ghcr.yml`).
- Concurrent work: another session committed `ops-01` (`73fac00`) on main today — branch isolation mandatory.

## Registry: current → latest (queried 2026-09-03)
Frontend: Node 22→26.8.1 (LTS=24) · vite 7.1→8.2.2 · typescript 5.7→7.0.2 · @vitejs/plugin-react 5.0→6.1.1 · vite-tsconfig-paths 5.1→6.1.1 · @tanstack/react-start 1.132→1.168.49 · @tanstack/react-router 1.132→1.170.32 · router-plugin →1.168.35 · react-router-ssr-query 1.131→1.167.2 · react-devtools 0.7→0.10.12 · lucide-react 0.545→1.39.0 · react 19.2→19.2.8 · axios 1.13→1.20.0 · lightweight-charts 5.1→5.2.1 · tailwindcss/@tailwindcss/vite 4.1→4.3.3 · zustand 5.0.11→5.0.15 · @types/node 22→26.4.1 · nitro nightly→3.0.260610-beta · @playwright/test 1.44→1.62.1
Backend (⚠️ queried from Python 3.10 host — pip filtered; re-verify under 3.13 in `.venv`): fastapi 0.131→≥0.141.1 · uvicorn 0.41→≥0.52.4 · gunicorn 23→≥26.2 · asyncpg 0.30→≥0.31 · sqlalchemy 2.0.46→≥2.0.52 · alembic 1.14→≥1.19.1 · redis 7.1→≥8.1 · celery 5.6.2→≥5.6.3 · PyJWT 2.10→≥2.13 · google-auth 2.38→≥2.57 · python-multipart 0.0.20→≥0.0.32 · pandas 2.2.3→? · numpy 2.2.3→? · requests 2.32→≥2.34 · yfinance 0.2.65→≥1.7.0 (🔴 major) · pydantic 2.12→≥2.13.5 · pydantic-settings 2.8→≥2.15 · structlog 25→≥26.1 · python-telegram-bot 22.6→≥22.8 · pytest 8.3→≥9.1 · pytest-asyncio 0.25→≥1.4 (🔴 breaking) · aiosqlite 0.20→≥0.22 · pip-audit 2.9→≥2.10

## Test baseline (cloud, Python 3.13.7 venv, redis-server local, DATABASE_URL dummy asyncpg URL, sqlite in-memory fixtures)
- `backend/tests`: **107 passed / 26 failed / 5 skipped**; 2 files do not collect: `test_next_features.py:630` SyntaxError (`class TestVolumeSpike Alerts:`), `test_api_e2e.py` ImportError (`AlertCondition` missing from `models.alert`). All 26 failures in `test_user_simulation.py` (expects live stack).
- `tests/api` (root, PYTHONPATH=backend): **116 passed / 12 failed / 92 errors** (cache/redis-dependent — `test_pr3_cache_service.py` errors).
- Frontend `npm ci && npm run build` on Node 22: **green** (nitro build OK, 9.7s).
- E2E Playwright: not run (needs running stack).
- 🔴 Baseline is NOT green → migration acceptance = "no regression vs this baseline", not "all green", unless the plan fixes the pre-existing breakage explicitly.

## Open questions for Phase 1a
1. API versioning: introduce `/api/v1` with backward-compat alias, or in-place? (frontend `services/api.js` is the only consumer + Caddy routes `/api/*`).
2. yfinance 1.x: which provider functions break (`services/providers/yahoo_*.py`, 8 workers) — needs a breaking-change map before Dave touches it.
3. pytest-asyncio 1.x: `asyncio_mode=auto` + session-scoped event loop fixture in conftest — likely rewrite.
4. TS 7 native compiler: does TanStack router codegen + `vite-tsconfig-paths` 6 + `@vitejs/plugin-react` 6 work under it? Must be proven in a spike before commit to it (rollback to TS 5.9 is the R1 fallback).
