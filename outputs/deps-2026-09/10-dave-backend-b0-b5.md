# deps-2026-09 — Dave: backend chain WP-B0 → B5 (Phase 2 Implement)

bd: deps-2026-09 · iter 0 · role: Dave (backend chain, sequential, worktree
`/home/claude/wt-backend`, branch `wip/deps-backend`, base
`d41a3fc`/`b022606` on `chore/deps-2026-09`)
Toolchain: `uv venv --python 3.13 .venv`, Python 3.13.7. Env for tests:
`DATABASE_URL=postgresql+asyncpg://stockviz:stockviz@localhost:5432/stockviz
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=dev-only-secret-key-0123456789abcdef` (sqlite in-memory
fixtures; DATABASE_URL only needs to parse — confirmed, no Postgres was
actually reached by backend/tests). A local `redis-server` (Redis 7.0.15)
was running on `localhost:6379` and used for live redis-py 8 verification.
No Docker daemon in this sandbox — Dockerfile edits (backend/Dockerfile
comment) are proven by review only here; `docker build` must run on CI or
the user's Mac, stated explicitly per instruction.

Status: **DONE** — all 6 WPs (B0-B5) landed, zero PARTIAL/BLOCKED at the
WP level (one sub-item, live-Yahoo-data round-trip, is explicitly flagged
open — see WP-B3 below — but did not block the WP itself, which completed
via a substitute verification method).

---

## WP → commit sha

| WP | sha | Files | Verdict |
|---|---|---|---|
| B0 | `291c84a` | test_next_features.py, test_api_e2e.py, test_user_simulation.py, pytest.ini, pyproject.toml (new), tests/fixtures/yf_golden/ (new) | DONE |
| B1 | `eaf89f1` | requirements.txt, requirements-dev.txt (new), Dockerfile | DONE |
| B2 | `d717e8c` | tests/conftest.py, pytest.ini, core/config.py, models/schemas.py, api/routes/notes.py, tests/test_config_security.py (new) | DONE |
| B3 | `5b124a5` | tests/fixtures/yf_golden/wp_b3_verification.md (new) — 0 code files changed | DONE (verification-only, see note) |
| B4 | `2f90bb7` | tests/fixtures/redis8_verification.md (new) — 0 code files changed | DONE (verification-only, see note) |
| B5 | `9fc96e3` | api/routes/stocks.py (deleted) → api/routes/stocks/ (7 new files), models/{alert,drawing,portfolio,watchlist}.py | DONE |

---

## WP-B0 — hygiene

- `test_next_features.py:630` `class TestVolumeSpike Alerts:` → `TestVolumeSpikeAlerts` (syntax fix mandated by Stan's WP table). This UNMASKED a separate pre-existing bug (all 28 tests in that file reference a `client` fixture that doesn't exist in conftest.py — only `async_client` does; file's own docstring says these are "FAILING tests that define the specification for Phase 2 features," i.e. intentionally-red future-feature specs, not baseline coverage). Quarantined module-level with an explicit `pytest.skip(..., allow_module_level=True)` + reasoning comment, per Bella's DoD scope ("pre-existing failures not gated unless Dave's plan explicitly elects to fix a specific one" — not elected here).
- `test_api_e2e.py` — quarantined module-level (imports `AlertCondition`, confirmed absent from `models/alert.py` and nowhere else in non-test code).
- `test_user_simulation.py` — `pytestmark = pytest.mark.integration` (whole file, live-stack-only, matches the 26f/6p/5s baseline exactly). Deselected via `backend/pytest.ini` `addopts = ... -m "not integration"` ONLY — `.github/workflows/ci.yml` untouched (user decision #2 / DoD item 16, r3-B-1 correction).
- New `backend/pyproject.toml` (ruff + mypy config, Stan §2.3, repo had none).
- **yfinance golden fixtures — R1 (inform), method substituted**: live Yahoo Finance calls are BLOCKED in this sandbox. `yfinance`'s curl_cffi client gets `SSLError: Recv failure: Connection reset by peer` against `query1.finance.yahoo.com` through the sandbox's TLS-intercepting egress proxy. Confirmed NOT a general network/proxy-auth failure: plain `requests.get()` to the SAME host through the SAME proxy returns `200` with real JSON. Tried 3 fix methods (bare `yf.Ticker()`, `yf.set_config(proxy=...)`, direct `curl_cffi.requests.get(impersonate='chrome', proxies=...)`) — all failed identically. Stopped per the 5-loop-iteration rule and substituted **API-surface characterization**: installed yfinance 0.2.65 (this repo's `.venv`) and yfinance 1.4.1 (isolated scratch venv `/tmp/yf14-venv`, discarded, reproducible via `capture_api_surface.py`) side by side and diffed property/method existence + delegation target + call signature for every call site in Sara's §2.1 map (9 workers + `api/routes/backtesting.py`, 13 call sites total). **All 13 classified `unaffected`** — full table in `backend/tests/fixtures/yf_golden/api_surface_findings.md`. Notable finding (F-YF-1, new): `Fundamentals.earnings.fget` source is byte-identical in both versions and always returns `None` — `financials_history_fetcher.py:137`'s `ticker.earnings`-indexed EPS branch is **already permanently dead code today** (pre-existing, not a bump-caused regression), resolving Sara's flagged highest-risk item with evidence rather than assumption.

**Backend/tests baseline after B0** (before any dependency bump):
```
101 passed, 2 skipped, 37 deselected, 10 warnings in 0.23s
```
Reconciles exactly to `00-oliver-discover.md`'s 107p/26f/5s: 107 = 101 + 6
(test_user_simulation's own passes, now deselected); 26f + 5s are entirely
inside test_user_simulation.py (verified by running it alone with `-m ""`:
`26 failed, 6 passed, 5 skipped`). Zero collection errors (was 2). **Note
for Oliver/Stan**: Stan's own WP-B0 proof command expected "≥107 pass"
under `-m "not integration"`, but the true number is 101 — a module-level
`pytestmark` necessarily deselects test_user_simulation's 6 passing tests
along with its 26 failing ones (no practical way to keep 6/32 tests
selected via one marker without per-test annotation, out of scope). This is
a measurement correction, not a regression: 0 tests flipped from pass to
fail; 6 were filtered out of the default run, still passing under `-m ""`.

---

## WP-B1 — dependency bumps

All targets per `01-sara-adr-migration.md` §1.3. Pin rule §1.4 followed:
`uv pip install` against updated floors, `uv pip freeze` back to exact `==`.

Frozen versions (direct deps, full `pip freeze` pasted below for transitive
audit trail):
```
fastapi==0.141.1        uvicorn[standard]==0.52.4   gunicorn==26.2.0
uvicorn-worker==0.4.0    asyncpg==0.31.0             sqlalchemy[asyncio]==2.0.52
alembic==1.19.1          redis==8.1.0                celery==5.6.3
PyJWT==2.13.0            bcrypt==5.0.0               passlib[bcrypt]==1.7.4
google-auth==2.57.0      python-multipart==0.0.32    pandas==3.0.5
numpy==2.5.2             requests==2.34.2            httpx==0.28.1 (unchanged)
yfinance==1.4.1          psycopg2-binary==2.9.10 (unchanged)
pydantic==2.13.5         pydantic-settings==2.15.0   email-validator==2.2.0 (unchanged)
structlog==26.1.0        python-telegram-bot==22.8   feedparser==6.0.11 (unchanged)
```
Dev-only (new `backend/requirements-dev.txt`, `-r requirements.txt` at top,
per Oliver/Sentinel Q3 decision — S-AC-6 mitigation):
```
pytest==9.1.1  pytest-asyncio==1.4.0  pytest-cov==7.1.0  aiosqlite==0.22.1
pip-audit==2.10.1  ruff==0.16.5  mypy==2.3.1
```
Resolver accepted `pytest==9.1.1` + `pytest-asyncio==1.4.0` together —
Sara's CR-3 fallback (hold `pytest==8.4.x`) was **not needed**.

**Split verified**: fresh venv from `requirements.txt` alone has no
`pytest` module (`ModuleNotFoundError`); `requirements-dev.txt` installs
both files cleanly. `backend/Dockerfile` comment documents the dev install
command (`uv pip install -r backend/requirements-dev.txt`).

**pip-audit** (SEC-5, S-AC-7):
```
$ pip-audit -r backend/requirements.txt
No known vulnerabilities found
$ pip-audit -r backend/requirements-dev.txt
No known vulnerabilities found
```
Was: 16 known vulnerabilities in 4 packages pre-bump (PyJWT ×7 auth-path
advisories, python-multipart ×6, requests ×2, pytest ×1 — `05-sentinel-threat-model.md`
§2.1). **All 16 closed. 0 remaining.**

Test deltas after B1 (vs B0): `backend/tests` 101p/0f/2skip/37deselected —
IDENTICAL. `tests/api` 116p/12f/73errors — pass/fail counts IDENTICAL to
`00-oliver-discover.md` baseline (116/12); error count DOWN from 92 to 73
(not investigated — `tests/api/*` is WP-S1/S2 territory, forbidden to me).

---

## WP-B2 — pytest-asyncio 1.x + pydantic v2 model_config

- `backend/tests/conftest.py`: removed the custom session-scoped
  `event_loop` fixture (pytest-asyncio 1.x deleted the fixture/API
  entirely) — session-loop semantics now come from
  `asyncio_default_fixture_loop_scope = session` in `backend/pytest.ini`.
- `AsyncClient(app=app, ...)` → explicit `ASGITransport(app=app)` (httpx
  0.28 removed the `app=` shortcut). This fixture (`async_client`) had
  **zero currently-passing callers** at the time of the fix (its only
  consumer, `test_api_e2e.py`, was already quarantined in B0) — fixing it
  is not a regression-risk surface, just correctness for the future.
- 8 `class Config:` sites → `model_config` (AC-A1, corrected count 7→8 per
  Bella's cross-read): `core/config.py:72` → `SettingsConfigDict`;
  `models/schemas.py` ×6 (byte-identical `from_attributes = True` — bulk
  `replace_all`); `api/routes/notes.py:24` → `ConfigDict`.
  Proof: `python -W error::DeprecationWarning -c "from core.config import
  settings; import models.schemas; import api.routes.notes"` exits 0 (was
  raising `PydanticDeprecatedSince20` pre-change).
- **Opportunistic, in-scope fix (S-AC-10, `05-sentinel-threat-model.md`
  SEC-4)**: `core/config.py` was already in this WP's file scope. The
  `jwt_secret_key` validator now **raises** (boot fail) instead of only
  warning when `APP_ENV=production` and the value is still the shipped
  default — closes "default secret silently reaches prod." New
  `backend/tests/test_config_security.py` (3 tests): raises in production,
  warns-only in development, custom secret boots clean in production.

Test deltas after B2 (vs B1): `backend/tests` **104**p/0f/2skip/37deselected
(+3 = the 3 new S-AC-10 tests). 8 Pydantic deprecation warnings gone from
the test summary (confirmed present at B1 checkpoint, absent at B2).
`tests/api` 116p/12f/73errors — IDENTICAL to B1.

---

## WP-B3 — yfinance 1.x adaptation

**Zero code changes** in `services/providers/*.py` or `workers/*.py`.

`services/providers/*.py` has zero yfinance imports (confirmed, matches
Sara's ADR finding — raw Yahoo v8 HTTP). The WP-B0 characterization already
classified all 13 call sites across `workers/*.py` (9 files) +
`api/routes/backtesting.py` as unaffected by the bump. This WP re-verified
against the ACTUAL bumped dependency (`yfinance==1.4.1`, live since B1):

```
$ .venv/bin/python -c "import workers.symbol_registrar, workers.corporate_actions_fetcher, \
  workers.price_fetcher, workers.on_demand_listener, workers.earnings_events_fetcher, \
  workers.history_prefetcher, workers.fundamentals_fetcher, workers.name_fetcher, \
  workers.financials_history_fetcher, api.routes.backtesting"
OK x10 (all modules)

$ .venv/bin/pytest tests/test_services.py tests/test_screener_indicators.py -q
49 passed, 2 warnings in 0.06s
```

**Open, explicitly flagged (not silently dropped, per Oliver's R1
instruction)**: live-Yahoo-data round-trip (`_fetch_quote`/
`_fetch_fundamentals`/`_fetch_history` returning correct VALUES, not just
"the method exists") could not be exercised from this sandbox — network to
Yahoo is blocked (see WP-B0). Flagged for Quinn (Phase 3, live stack) or a
local run on the user's Mac before the data plane is considered fully
proven end-to-end. AC-M4 (classification) and AC-M6 (characterization
gate) are satisfied; the live-value smoke is NOT and should not be assumed
green.

---

## WP-B4 — redis-py 8 client

**Zero code changes** in `core/redis.py`, `services/cache_service.py`,
`services/cache_orchestrator.py` (the 3 files Stan's table assigns to this
WP). Verified live against the sandbox's redis-server 7.0.15 (server stays
7, client bumps to 8 — Sara ADR §1.5):

```
$ .venv/bin/python -c "... ping/get/set/info ..."
redis-py version: 8.1.0
ping: True
get: ok
redis_version: 7.0.15

$ .venv/bin/python -c "... pub/sub round trip on 'price_updates' ..."
received: {'type': 'message', 'pattern': None, 'channel': 'price_updates',
           'data': '{"type": "data_ready", "data_type": "quote", "symbol": "AAPL"}'}
```

The `await aioredis.from_url(...)` auto-init pattern (Sara's flagged
"deprecation candidate," §2.2) is retained and works in 8.1.0. The pub/sub
path (Sara's flagged "highest-risk area", RESP3) round-trips cleanly with
the exact message shape `main.py`'s WS broadcaster expects.

**Residual, out of this WP's file scope, explicitly flagged not fixed**:
`services/stock_service.py:91` and `services/providers/yahoo_provider.py:129`
(bare `from_url` without explicit timeouts, per Sara §2.2) are not in
Stan's WP-B4 file list — not touched, not assigned to any WP in the
current 11-package plan, flagged for Stan/Oliver routing. `main.py`'s
`_redis_price_broadcaster` (the actual WS-side consumer) is forbidden to
me (WP-S1/S2/S3 territory) — the full publish→WS-receive smoke (AC-M7)
still needs a live-stack pass post-barrier.

Test deltas after B4 (vs B2/B3): `backend/tests` 104p/0f/2skip/37deselected
— IDENTICAL. `tests/api` 116p/12f/73errors — IDENTICAL.

---

## WP-B5 — stocks.py split (last, on green)

`backend/api/routes/stocks.py` (672 LOC, 11 handlers) → package
(`api/routes/stocks/{__init__,_shared,search,quotes,history,fundamentals,news_events}.py`),
per `03-stan-refactor-strategy.md` §2.1. Pure file move, zero handler-body
edits. Prefix kept verbatim `/api/stocks` (the `/api/v1` flip is WP-S2's
job — barrier boundary respected). `main.py:14,277` needed **zero
changes** (`from api.routes import stocks` resolves to the package
transparently).

**OpenAPI snapshot diff (AC-B3/A3 mechanism)**: captured a TRUE "before"
by temporarily staging the new package dir aside so Python resolved the
old `stocks.py` file, snapshotted, restored, deleted `stocks.py`,
re-snapshotted:
```
before paths: 47   after paths: 47   before == after (dict equality): True
```
Byte-for-byte identical, re-verified again after ruff auto-fix reorganized
imports in the new files (still `True`).

**AC-A3 routing-order smoke** (static `/quotes` vs dynamic
`/{symbol}/quote`): documented the constraint in `__init__.py` and
`quotes.py` docstrings (static-before-dynamic, in BOTH the include_router
order and quotes.py's internal handler-definition order), then proved it
live:
```
GET /api/stocks/quotes -> 200 {'AAPL': None}
```
(the batch-handler dict shape — NOT a 202-pending single-quote response
that would result if "quotes" were shadow-matched as a `{symbol}`).

**F821 fix** (AC-A1-adjacent, `models/{alert,drawing,portfolio,watchlist}.py`):
`Mapped["User"]` forward-ref strings had no real import, only a
`# type: ignore[name-defined]`. Added `if TYPE_CHECKING: from models.user
import User` to each (no circular import — `models.user` doesn't import
these back) and removed the now-dead `# type: ignore` comments
(pyproject.toml's `warn_unused_ignores = true` would otherwise flag them).
`ruff check --select F821 .`: 0 errors (was 4).

**Gate commands**:
```
$ ruff check backend --statistics
Found 597 errors.   (was 606 at B0 baseline — down, not up)

$ mypy backend/api backend/core --ignore-missing-imports
Found 120 errors in 16 files   (was 121 in 17 files, Sara discover-doc
                                 baseline — within the ratchet ceiling)
```
Pre-existing S110/BLE001/etc. patterns intentionally left per Stan §1.2
("do NOT mass-fix" — deliberate CQRS graceful-degradation pattern).

Test deltas after B5 (vs B4, FINAL): `backend/tests` **104**p/0f/2skip/37deselected
— IDENTICAL to B2-B4 checkpoints. `tests/api` **116**p/12f/73errors —
IDENTICAL to B1-B4 checkpoints.

---

## Final numbers summary (vs 00-oliver-discover.md baseline)

| Suite | Baseline | Final (post-B5) | Delta |
|---|---|---|---|
| `backend/tests` (default run) | 107p/26f/5s, 2 non-collecting | 104p/0f/2skip/37deselected | 0 collection errors (was 2); 0 regressions; +3 new tests (S-AC-10); test_user_simulation.py's 6p/26f/5s cleanly separated via `-m "not integration"`, itself unchanged |
| `tests/api` (root suite) | 116p/12f/92e | 116p/12f/73e | pass/fail IDENTICAL; errors DOWN 92→73 (improvement, unexplored — out of scope) |
| `pip-audit -r backend/requirements.txt` | 16 vulns / 4 pkgs | **0** | closed 16/16 |
| `pip-audit -r backend/requirements-dev.txt` | n/a (file didn't exist) | **0** | new file, clean |
| `ruff check backend` | n/a (no config existed) | 597 (B0 introduced config at 606, split brought it to 597) | monitored, not a gate target this branch |
| `mypy backend/api backend/core` | 121 errors / 17 files | 120 errors / 16 files | within ratchet ceiling |
| OpenAPI (`/api/stocks/*` paths) | 47 paths total (whole app) | 47 paths total | byte-identical dict equality, pre/post B5 split |

## Open items handed to Oliver / next WPs (not silently dropped)

1. Live-Yahoo-data round-trip for the 9 workers (WP-B3) — unverifiable in
   this sandbox, needs Quinn/Phase 3 live stack or a local Mac run.
2. `services/stock_service.py:91` + `services/providers/yahoo_provider.py:129`
   bare `from_url` (no explicit timeouts, redis-py 8 default 5s applies) —
   not in any WP's file scope in the current 11-package plan, needs Stan/Oliver
   routing.
3. AC-M7's full publish→WS-receive smoke (the WS-side half, `main.py`) is
   forbidden to me — needs a WP-S1/S2/S3-adjacent owner or Quinn Phase 3.
4. Stan's WP-B0 proof-command comment ("expect ≥107 pass" post-deselect)
   should be corrected to "101" in any future re-read of that doc — recorded
   here as a measurement correction, not a regression.
5. `test_api_e2e.py` (AlertCondition) and `test_next_features.py` (client
   fixture / Phase-2 TDD specs) quarantines are both explicitly named,
   ticketed, and NOT silently passing — whoever owns those follow-up bds
   (Stan's Open Question #1) should read the quarantine comments in-file.

## Barrier readiness

Both my chain's proof gates (full `backend/tests` + `tests/api` ≥ baseline,
pip-audit clean) are green. Chain F (frontend) status not observed from
this worktree — Oliver/Sara own barrier confirmation before the serial
tail (S1/S2/S3) starts. I did not touch any WP-S1/S2/S3 file
(`backend/api/routes/auth.py`, `backend/core/security.py`,
`backend/api/middleware/rate_limit.py`, `tests/api/*`, `CLAUDE.md`,
`REQUIREMENTS.md`, `backend/main.py` route mounts) or anything under
`frontend/`, `tests/e2e/`, `.github/` — confirmed via `git diff --stat`
below.

```
$ git diff --stat d41a3fc..HEAD -- frontend tests/e2e .github backend/api/routes/auth.py backend/core/security.py backend/api/middleware/rate_limit.py tests/api backend/main.py CLAUDE.md REQUIREMENTS.md
(no output — zero changes to any forbidden path)
```
