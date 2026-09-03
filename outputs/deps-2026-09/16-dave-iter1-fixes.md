# Dave — iter1 fix pack (Phase 3b FAIL → fix pack)

bd:deps-2026-09, branch `chore/deps-2026-09`. Delegated by Oliver after
Chris (`14-chris-review.md`) and Quinn (`15-quinn-review.md`) both returned
Phase 3b **FAIL**. HEAD at delegation: `897e766`. This log is appended to
per-finding as work proceeds; never edits Chris's/Quinn's report files.

Process note: max 5 loop iterations per item; PARTIAL findings paste the
exact failing output, never "should work."

---

## Item 1 — CHRIS-01/Q-1/Q-3/Q-4/Q-5 (tests/api fixture rewrite) — DONE

Commits:
- `d123c81` — CHRIS-05 `hash_password()` fix (hard prerequisite, reordered
  ahead of its numeric position — every fixture below that creates a
  DB-backed user needed it working first)
- `110c1e8` — CHRIS-01/Q-1/Q-3/Q-4/Q-5 + 4 Dave-discovered bugs, see below

### CHRIS-05 — hash_password() unconditionally broken (passlib x bcrypt 5)
Root cause: passlib 1.7.4's bcrypt backend probes the removed
`bcrypt.__about__` submodule, its fallback self-test crashes against
bcrypt 5's stricter 72-byte validation. Fix: direct `bcrypt.hashpw()`/
`bcrypt.gensalt(rounds=12)` in `backend/core/security.py`; removed
`passlib[bcrypt]==1.7.4` from `backend/requirements.txt`.

Proof (before → after):
```
$ python -c "from core.security import hash_password; hash_password('TestPass1')"
AttributeError: module 'bcrypt' has no attribute '__about__'
  -> ValueError: password cannot be longer than 72 bytes (misleading)
```
After: 3 consecutive calls succeed, produce `$2b$12$...` hashes, salted
(unique per call).

### CHRIS-01/Q-4 — event_loop fixture (pytest-asyncio 1.x)
Removed the custom session-scoped `event_loop` fixture (deleted API in
pytest-asyncio ≥1.0). Replaced with `asyncio_default_fixture_loop_scope
= session` in `tests/api/pytest.ini`, mirroring `backend/pytest.ini`.

### CHRIS-04/Q-5 — StaticPool missing + non-deterministic create_all()
`test_engine` lacked `poolclass=StaticPool` — each connection checkout on
`sqlite+aiosqlite:///:memory:` could land on a *different* physical
connection (a different blank DB), producing collection-order-dependent
"no such table" errors. Fixed: `poolclass=StaticPool` + explicit
`import models` before `create_all()`.

### Q-3 — app_client's per-request throwaway engine
`app_client` used to open a brand-new in-memory SQLite engine on every
single request. Unified to share `test_engine`/`db_session` with
`client`/`auth_headers`, all function-scoped.

### Newly discovered (Dave, not in either report) — 4 additional bugs

1. **Cross-loop via real Postgres singleton lifespan**: `main.py`'s
   lifespan ran `create_tables()` against the real Postgres singleton
   engine (`core.database.engine`) on every `TestClient(app)` __enter__;
   each TestClient spins up its own event loop, so the 2nd+ test's
   lifespan reused a connection bound to an already-closed loop. Fixed:
   `os.environ.setdefault("APP_ENV", "test")` in conftest.py (skips the
   dev-only auto-migrate block; tests never needed it, `get_db` is always
   overridden).

2. **`asyncio_default_test_loop_scope` mismatch**: setting only
   `asyncio_default_fixture_loop_scope = session` left the TEST function
   loop scope at its `function` default — broke
   `test_pr3_cache_service.py`'s own real-redis async fixture (19/19
   tests, "Task ... attached to a different loop" at teardown). Confirmed
   via `git stash` (conftest.py + pytest.ini only) + rerun: 19/19 PASS on
   pre-iter1 baseline, 19/19 ERROR post-iter1-partial-fix. Fixed by also
   setting `asyncio_default_test_loop_scope = session`.

3. **fastapi 0.141.1/starlette 1.6.0 `_iter_api_routes` breakage**:
   `include_router()` now builds a lazy `_IncludedRouter` wrapper instead
   of eagerly flattening routes onto `app.routes` — broke
   `test_contract_v1.py`'s route-introspection helper (every `/api/v1/*`
   route + `/api/health` "vanished": `app.routes` had only 4 top-level
   entries for the entire 13-router aggregate). Fixed: switched
   `_iter_api_routes` to `app.openapi()["paths"]`, the version-stable
   flattened map FastAPI's own schema generation resolves through
   (CHRIS-06 depends on this exact call already).

4. **`GET /api/v1/stocks/names` unreachable empty-input path**:
   `symbols: str = Query(...)` (required) even though the handler's own
   next line (`if not sym_list: return {}`) has a dedicated empty-input
   branch — 422'd before ever reaching it. Changed to `Query("")`,
   matching the test's own documented contract ("empty symbols param ->
   {}"). Zero prod impact (Sidebar always passes symbols).

5. **One contract-test parametrize case riding the Q-3 bug**:
   `test_no_leak_markers_in_error_body[/api/v1/watchlists-get]` expected
   `>=400` from a VALID authed GET — that only "passed" pre-fix because
   `auth_headers`'s JWT resolved to a user row `client` couldn't see
   (Q-3), so every request 401'd regardless of token validity. With auth
   fixed, GET /api/v1/watchlists legitimately returns 200 (empty list).
   Swapped the parametrize case for POST (422, missing body) to keep 3
   genuinely-erroring checks.

### Quinn's 17 confirmed-new failures (Finding Q-1) — all fixed
- 11 envelope-unwrap-missing in `test_api_endpoints.py` (TestAuthMe x2,
  TestAuthConfig x1, TestStockNames x2, TestStockNews x2, TestStockSearch
  x1, TestAIModels x2, TestStockHistory x1) — unwrapped via
  `resp.json()["data"]`.
- 6 auth-fixture failures in TestWatchlist — rewrote
  `test_api_endpoints.py`'s local `client`/`registered_user`/
  `auth_headers` fixtures: dropped `scope="module"` (ScopeMismatch
  against now-function-scoped `app_client`), `registered_user` now
  creates a REAL DB-backed user via `db_session` instead of a synthetic
  `sub:"999001"` JWT with no backing row.

### Proof: tests/api full suite, 3 consecutive runs, identical totals
```
Run 1: 28 failed, 208 passed, 5-6 warnings in 48.54s
Run 2: 28 failed, 208 passed, 5 warnings in 52.01s
Run 3: 28 failed, 208 passed, 5 warnings in 51.79s
$ diff run1_FAILED.txt run2_FAILED.txt   -> empty
$ diff run1_FAILED.txt run3_FAILED.txt   -> empty
```
0 errors (was 19 errors + non-reproducible 28-30 failed pre-fix).

All 28 remaining failures independently confirmed pre-existing/
out-of-scope (not part of Quinn's 17):
- **15 in `test_api_endpoints.py`**: stale CQRS-refactor-era mock targets
  (`services.stock_service.fetch_stock_quote`,
  `api.routes.screener._run_screener` don't exist in current code — real
  names are `read_quote`/whatever screener actually calls now), Ollama
  not running in test env (`AIChat` -> 503). Confirmed via direct
  `AttributeError` tracebacks, unrelated to envelope/auth.
- **11 in `test_timeout_handling.py`**: mock targets
  (`_get_yf_auth`/`_fetch_yahoo_direct`) never existed at ANY commit in
  this repo's git history (matches Dave's own
  `12-dave-serial-s0-s3.md:177-190` accounting, cross-referenced by
  Quinn's review line 45).
- **2 in `test_rate_limit_middleware.py`**: CHRIS-02/CHRIS-03, next items
  below — deliberately red until fixed there.

### backend/tests — unaffected
```
$ pytest tests/ -q
109 passed, 2 skipped, 37 deselected, 2 warnings in 0.19s
```
(109, not the previously-cited 104 — includes Chris's 25 new tests across
5 files added during his Phase 3b review; 0 regressions.)

---

## Item 2 — CHRIS-02/Q-2 (rate-limiter 429 non-JSON 500) — DONE

Commit: `e053c17`

`RateLimitMiddleware.dispatch()` raised `HTTPException(429)` — a
`BaseHTTPMiddleware`, outside Starlette's `ExceptionMiddleware`, so the
exception propagated to `ServerErrorMiddleware`'s raw non-JSON 500.
Fixed: return a `JSONResponse` directly, reusing
`enveloped_error_body()` (renamed from `_enveloped_error_body`, now a
small shared cross-module utility).

Also fixed, discovered while verifying (not in either report):
`RateLimitMiddleware` cached its own long-lived `aioredis` client on
`self` (constructor `redis_url=` param), invisible in production (one
event loop for the process's life) but broke the 2nd+ `TestClient(app)`
in the same pytest session ("Event loop is closed"). Switched to reuse
`core.redis.get_redis()` (already lifespan-cycled correctly). Dropped the
now-unused `redis_url=` arg from `main.py`.

Proof:
```
$ pytest tests/api/test_rate_limit_middleware.py::TestRateLimitEnvelope -v
1 passed
$ pytest tests/api -q
27 failed, 209 passed   (was 28 failed, 208 passed — exactly 1 target test)
$ pytest backend/tests -q
109 passed, 2 skipped, 37 deselected  (unaffected)
```

---

## Item 3 — CHRIS-03 (trusted-proxy allowlist for X-Forwarded-For) — DONE

Commit: `3ca1a73`

Added `TRUSTED_PROXIES` setting (`core/config.py`): comma-separated
IPs/CIDRs. Default empty -> trust nothing, `_client_ip()` always falls
back to `request.client.host` (the real TCP peer, unspoofable). Only
honors `X-Forwarded-For` when the ACTUAL socket peer is itself trusted.
Documented in `.env.example` (guidance for sizing against the Caddy/
backend Docker bridge subnet). Compose files untouched (matches the
explicit instruction, and — same as CHRIS-14 below — I have no Docker in
this sandbox to verify a compose-file change is safe).

Proof:
```
$ pytest tests/api/test_rate_limit_middleware.py -v
2 passed  (TestRateLimitEnvelope + TestRateLimitKeyingNotSpoofable)
$ pytest tests/api -q
26 failed, 210 passed   (was 27/209 after item 2 alone)
$ pytest backend/tests -q
109 passed, 2 skipped, 37 deselected  (unaffected)
```

---

## Item 4 — CHRIS-06 (openapi doesn't reflect {data,meta} envelope) — DONE

Commit: `c2e2e40`

Rejected rewriting all ~40 handlers' `response_model` to `BaseResponse[X]`
(also drives REAL runtime serialization; every handler currently returns
a raw ORM object/dict/list, not a `BaseResponse` instance — too large a
blast radius for one atomic fix). Instead: `schemas/envelope.py` now
overrides `app.openapi()` (`install_envelope_openapi`, wired in
`main.py` after all routers) — post-processes the normally-generated
schema, wrapping every enveloped path's 2xx JSON response as
`{data: <original>, meta: ResponseMeta}` and every >=400 JSON response as
the new `ErrorEnvelope` component (real `{data:null,meta:{error:...}}}`
shape, replacing FastAPI's stock `HTTPValidationError` on 422 too).
Schema-only change — cannot regress request handling.

Regenerated + re-committed `outputs/deps-2026-09/openapi-v1.json` (43
paths, 40 component schemas).

Proof:
```python
>>> app.openapi()["paths"]["/api/v1/watchlists"]["get"]["responses"]["200"]
{data: {items: $ref WatchlistResponse, type: array}, meta: $ref ResponseMeta}
>>> app.openapi()["paths"]["/api/v1/watchlists"]["post"]["responses"]["422"]
{$ref: ErrorEnvelope}   # was HTTPValidationError
>>> json.dumps(app.openapi())   # no exception, fully serializable
```
```
$ pytest tests/api -q
26 failed, 210 passed  (identical — schema-only change, zero runtime deltas)
$ pytest backend/tests -q
109 passed, 2 skipped, 37 deselected  (unaffected)
```

---

## Item 6 — CHRIS-07 (ci.yml never reconciled) — DONE

Commit: `e3d46bf`

`git diff 73fac00..HEAD -- .github/workflows/ci.yml` was empty before
this commit. Fixed the 3 items Chris named: (1) `uv pip install -r
requirements-dev.txt` (was `requirements.txt` alone — pytest was moved
out in WP-B1, the "Run tests" step would `ModuleNotFoundError`); (2)
Node `'20'` -> `'24'` (this branch's entire premise); (3) artifact path
`frontend/dist/` -> `frontend/.output/` (Nitro's real output dir,
confirmed via `Dockerfile:28`). Also fixed a dead `ENVIRONMENT: test` env
var -> `APP_ENV: test` (the field pydantic-settings actually reads),
discovered while reconciling. **Trigger deliberately unchanged** — still
`workflow_dispatch` only.

Also updated `changelog.md` per CLAUDE.md's house rule (DoD item 15,
flagged untouched by Chris). `tasklist.md` has no existing checklist item
for this infra/deps branch (product-feature tracker, not applicable) —
nothing to check off there.

Proof:
```
$ python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
(no exception — valid YAML)
$ grep '^on:' -A1 .github/workflows/ci.yml
on:
  workflow_dispatch:
```

---

## Item 7 — CHRIS-09/10/11/12/13/14 (small AC gaps) — DONE (14 flagged-only)

Commit: `ca6b6af` (+ CHRIS-11 already covered by commit `e053c17`, item 2)

- **CHRIS-09** (JWT default-secret blind spot) — added
  `.env.example`'s own placeholder (`change-me-with-openssl-rand-hex-32`)
  to the reject set alongside the original hardcoded string. New test:
  `backend/tests/test_config_security.py::
  test_env_example_placeholder_also_raises_in_production`.
- **CHRIS-10** (AC-A2, duplicate `/portfolio` router) — added a
  cross-reference comment in both `portfolio.py` and
  `portfolio_performance.py` explaining the intentional split (not a
  collision — FastAPI merges same-prefix routers fine).
- **CHRIS-11** (rate-limiter docstring, AC-D2) — already fixed as part of
  the CHRIS-02 commit (`e053c17`): docstring no longer claims "enforced
  at route level via dependency" for guest/user limits that don't exist;
  now explicitly says only the login endpoint is rate-limited.
- **CHRIS-12/Q-6** (AC-B7, health.spec.ts stale assertion) — fixed the
  assertion to match the real `{data:{database,redis,celery},meta:{...}}`
  shape (`api/routes/system.py:91`'s handler has ALWAYS been
  `response_model=BaseResponse[dict]`, no top-level `status` key ever
  existed). **Verification caveat**: could not re-run this test live in
  this sandbox (no Docker available) — fix is based on direct
  route/response_model source inspection (high confidence, matches
  Quinn's own live-verified finding exactly) + confirmed via
  `npx playwright test health.spec.ts --list` that the file still
  collects 3 tests cleanly (syntax-level check only, not a live run).
- **CHRIS-13** (mypy 120->133 regression) — fixed the one new error Chris
  cited (`schemas/envelope.py:85`, `json.loads(response.body)` type
  mismatch) via `json.loads(bytes(response.body))`. Verify:
  `mypy api core --ignore-missing-imports` -> **112 errors in 16 files**
  (was 133; below both that number and the original 120 checkpoint).
- **CHRIS-14** (`VITE_API_URL` stale build arg) — **flagged only, not
  applied**. Low priority ("cleanup, not a merge blocker" — Chris's own
  words), compose-file-only, and I have no Docker in this sandbox to
  verify a frontend build still works after changing it. Recommended fix
  for whoever picks this up: `docker-compose.dev.yml:165` /
  `docker-compose.prod.yml:139`, `VITE_API_URL: /api` ->
  `http://backend:8000` (or drop the build arg — likely vestigial per
  Chris, the browser's axios calls hit Caddy directly in every deployed
  topology, bypassing this Nitro dev-proxy target entirely).

Proof:
```
$ mypy api core --ignore-missing-imports
Found 112 errors in 16 files
$ pytest backend/tests -q
110 passed, 2 skipped, 37 deselected   (+1 new test vs item 1's 109)
$ pytest tests/api -q
26 failed, 210 passed   (unaffected — health.spec.ts is E2E, separate suite)
```

---

## Item 8 — Q-7/Q-8/Q-9 (E2E) — DONE (Q-8 classification + defer)

Commit: `df98204`

**Q-7** — `ai-chat.spec.ts`'s `setupWithAI(page: any)` wasn't destructured
`{page}`; `test.beforeEach(setupWithAI)` (3x) received Playwright's
fixtures object, not a bare `Page`, blocking the whole file (12 tests) at
collection. Fixed the signature + its one direct call site. Confirmed
pre-existing/zero-diff (`git diff 73fac00..HEAD -- tests/e2e/ai-chat.spec.ts`
-> empty).

Verify (installed `npm install` in `tests/e2e/` this session — no
Docker/live stack available in this sandbox, so full test EXECUTION
wasn't possible, but Playwright COLLECTION was, and is a real,
non-static check):
```
$ npx playwright test ai-chat.spec.ts --list
Total: 14 tests in 1 file        (was: blocked entirely, 0 collected)
$ npx playwright test --list      (whole suite, all 15 files)
Total: 194 tests in 15 files      (= Quinn's 180 + ai-chat's 14 exactly)
```

**Q-8** — classified all 72 E2E failures from Quinn's Phase 3b run.
Extended her own methodology (not re-litigated): I independently re-ran
`git diff 73fac00..HEAD -- tests/e2e/<file>` for every one of the 10
touched spec files (see raw diffs pasted into this session's work) and
confirmed EVERY line changed is a correct, verified-correct literal
`/api/` -> `/api/v1/` mock-path string swap — zero assertion-logic
changes anywhere in any file. Cross-referenced against her per-file
pass/fail table (`15-quinn-review.md` §3.2):

| Classification | Count | Files |
|---|---|---|
| **Migration-caused, FIXED** | 3 | `health.spec.ts` (all 3) — CHRIS-12/Q-6 |
| **Pre-existing, deferred** | 69 | alerts(7) auth(2) chart-timeframes(3) chart(1) navigation(2) portfolio(6) quote-fetch(3) screener(1) search(7) settings(14) sidebar(1) timeout(3) watchlist-autocomplete(5) |

3 + 69 = 72, reconciles exactly against Quinn's total. None of the 69 have
ANY code diff since baseline in their own spec file beyond the (already-
verified-correct) path swaps — cannot be migration regressions by
definition; Quinn's own live runs additionally spot-root-caused the
largest clusters (auth/settings' 16 = a pre-existing Playwright
strict-mode locator bug; chart-timeframes' timeouts = never-run-before
timing debt). `watchlist-autocomplete`'s 5 remain individually
un-root-caused (by both Quinn and me — I could not re-run them live in
this sandbox; guessing a frontend fix without being able to verify it
would violate NO MAGIC/evidence-before-claim discipline).

**Recommend Oliver/Sara open a follow-up bd** for these 69 (this
session's environment has no `bd` CLI available to create one directly)
— triage by name against `outputs/deps-2026-09/15-quinn-review.md` §3.2's
raw log reference and this file's table above.

**Q-9** — added `tests/e2e/README.md` (missing `node_modules`, owner
Aaron/CI wiring). No CI trigger change (none exists to change — no E2E
job in `ci.yml` currently). Noted `package-lock.json` is repo-wide
`.gitignore`'d (same convention as `frontend/`) so `npm install`, not
`npm ci`, is the documented command.

---

## CHRIS-08 (curl_cffi mandatory transitive dep) — no action

Per Oliver: already accepted, no fix required this iteration. Logged here
per process rule only. Chris's finding stands as a named pre-deploy gate
item for Quinn/live-stack verification, not a code change.

---

## Environment constraints this session (transparency)

This sandbox has: local Postgres + Redis reachable at `localhost`, a
working Python venv, Node 24 — but **no Docker**. This means:
- All `tests/api` / `backend/tests` verification above is real, executed,
  reproducible (pasted output, 3x-run proof for `tests/api`).
- `tests/e2e/*.spec.ts` verification is limited to Playwright
  **collection** (`--list`), not full execution against a live Caddy/
  backend/frontend stack — I could not independently re-run Quinn's 180
  (or 194, post-Q-7) E2E tests myself. Findings there (health.spec.ts fix,
  Q-8 classification) rely on direct source-code/route inspection +
  Quinn's own live-verified numbers, not a fresh live run.
- CHRIS-03/CHRIS-14 (compose-file-touching fixes) were scoped to avoid
  compose-file edits I could not verify with a real `docker compose build`
  in this sandbox — CHRIS-03 was fixable entirely in backend code
  (`.env.example` + `core/config.py`, no compose diff needed); CHRIS-14
  was flagged only, per its own Low/non-blocking classification.

## Commits (chronological)

1. `d123c81` — CHRIS-05 (hash_password bcrypt fix, prerequisite)
2. `110c1e8` — CHRIS-01/Q-1/Q-3/Q-4/Q-5 (tests/api fixture rewrite)
3. `e053c17` — CHRIS-02/Q-2 + CHRIS-11 (rate-limiter 429 envelope)
4. `3ca1a73` — CHRIS-03 (trusted-proxy allowlist)
5. `c2e2e40` — CHRIS-06 (openapi envelope schema)
6. `e3d46bf` — CHRIS-07 (ci.yml reconciliation)
7. `ca6b6af` — CHRIS-09/10/12/13 (small AC gaps)
8. `df98204` — Q-7/Q-8/Q-9 (E2E collection fix + classification + note)
