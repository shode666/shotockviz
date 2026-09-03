# 15 — Quinn: Integration/E2E/Contract Review (Phase 3b, deps-2026-09)

bd: deps-2026-09 · phase 3b (integration/E2E/contract, `∥` Chris) · iter 0 · role: Quinn (qa-engineer, adversarial)
Repo: `/home/claude/shotockviz-ro` · branch `chore/deps-2026-09` · HEAD `9e17712` at task start, `84aba7f` after Chris's parallel commit landed mid-review (not authored by me) · base `73fac00`
Toolchain (own-run): Python 3.13.7 `.venv`, Node 24.20.0, **real PostgreSQL 16.13 + Redis (PONG confirmed)** — created `stockviz`/`stockviz` role+db myself (`sudo -u postgres psql`, R2/reversible, sandbox-only — the DB server exists here, only the app role/db were missing) since the delegation's `DATABASE_URL` env var pointed at a real, reachable Postgres server once the role existed. This materially changed results vs Dave's/the recorded barrier's broken-DB sandbox — see Finding Q-1.

## Verdict: **FAIL** — block merge

Independently corroborates Chris's `14-chris-review.md` FAIL verdict via a different method (own-run integration with a real DB/Redis + live E2E execution, not static/unit analysis), and adds new findings his review didn't cover (test-suite baseline soundness, live E2E first-run results, WS/pub-sub live smoke, admin-403 live curl, axe cross-check). Two independent reviewers converge on: **rate-limit 429→500 regression against the branch's own named AC**, and **`tests/api/conftest.py`'s pytest-asyncio 1.x rewrite being incomplete**, from two unrelated angles (Chris: 3x reruns of the same broken-DB config; me: working-DB vs broken-DB diff). That convergence, from independent methods, is strong evidence these are real, not measurement noise.

**Counts**: 1 Critical (Q-1, corroborates CHRIS-01), 2 High (Q-2 corroborates CHRIS-02/03; Q-3 new), 4 Medium (Q-4, Q-5, Q-6 corroborates CHRIS-12, Q-8), 1 Low (Q-9).
**NEW failures vs baseline (tests/api, real DB)**: 31 (see Q-1) — all attributable to two named root causes, not random.
**E2E**: 108 passed / 72 failed / 180 run (ai-chat.spec.ts — 12 more tests — blocked at collection, pre-existing, see Q-7).
**Contract test**: `tests/api/test_contract_v1.py`, 25 tests — 22 pass / 3 blocked by the same pre-existing conftest fragility Chris names (CHRIS-01/04), not by contract logic defects (see §2).

---

## 0. Method note — why my numbers differ from Dave's/the recorded barrier

The delegation gave me `DATABASE_URL="postgresql+asyncpg://stockviz:stockviz@localhost:5432/stockviz"`. This role/db did not pre-exist (`psql -h localhost -U stockviz` → `fe_sendauth: no password supplied`; `sudo -u postgres psql -c '\du'` → only the `postgres` superuser existed). I created it (`CREATE ROLE stockviz ... SUPERUSER; CREATE DATABASE stockviz OWNER stockviz;`) — sandbox-local, reversible, R2. Dave's own sandbox (`12-dave-serial-s0-s3.md:8-12`) explicitly ran with this same role broken ("this sandbox's Postgres has broken auth... I preserved it rather than 'fixing' Postgres"). **My run and his run are therefore not the same experiment** — his `116p/12f/65e` "barrier" for `tests/api` is a measurement taken with the app's DB-touching lifespan permanently failing; mine is with it succeeding. I reproduced his exact numbers by deliberately pointing at a bad URL (`postgresql+asyncpg://nonexistrole:wrongpw@...`) — confirms his figures are accurate **for that condition**, not that the condition is representative. No TimescaleDB extension is available on this Postgres (`SELECT * FROM pg_available_extensions WHERE name LIKE '%timescale%'` → 0 rows) — table-level tests are unaffected, but I could not exercise any hypertable-specific behavior.

---

## 1. Test-suite accounting (work item 1)

### 1.1 `backend/tests` — reproducible, matches Dave's claim exactly

```
$ pytest backend/tests -q   (real DB, HEAD)
104 passed, 2 skipped, 37 deselected, 2 warnings in 0.17s
```
Matches `12-dave-serial-s0-s3.md`'s barrier exactly, under both broken- and working-DB conditions (backend/tests uses its own isolated in-memory sqlite via a StaticPool-backed engine — see `backend/tests/conftest.py:33-37` — unaffected by the app's Postgres lifespan). The 37-deselect is `pytest.ini`'s new `-m "not integration"` (WP-B0 hygiene) excluding `test_user_simulation.py`'s 37 tests (marked `pytestmark = pytest.mark.integration`) — confirmed this file has **zero** marker at baseline (`grep pytestmark` on `wt-base/backend/tests/test_user_simulation.py` → no match) and is a clean, documented, non-regressive exclusion. Explicitly ran with `-m integration` too: **26 failed / 6 passed / 5 skipped** — identical failure set to Bella's originally-recorded baseline (`107p/26f/5skip` before the WP-B0 marker split; `107+26+5=138`, and `104+37=141`≈consistent with a few new tests added). All 26 require a live Docker stack (documented, out-of-scope per Bella §1.2) — confirmed unaffected by migration.

**Verdict: PASS, no finding.**

### 1.2 `tests/api` — 🔴 Finding Q-1 (Critical): the recorded "no regression" claim for `tests/api` was measured against a condition that masks 31 real failures

```
# broken DB (reproduces Dave's exact numbers):
12 failed, 116 passed, 2 warnings, 65 errors in 54.31s

# real, working DB (my delegation's env, HEAD):
43 failed, 147 passed, 9 warnings, 4 errors in 29.72s
```
Diffing the FAILED sets (broken-DB run vs working-DB run) confirms the 12 pre-existing failures are identical in both (6× `TestFetchYahooDirectTimeoutHandling` + 3× `TestFetchStockHistoryTimeoutHandling` + 2× wrong-query-param + 1× `TestConcurrentQuoteRequests` — matches Dave's own accounting in `12-dave-serial-s0-s3.md:177-190` exactly). **31 additional failures appear only when the DB actually works** — because the app's real `asyncpg` lifespan now succeeds instead of erroring out before the test body's real assertions ever run. I also built and ran a **73fac00 baseline worktree** (`uv venv` + old `requirements.txt`, real Postgres) to distinguish pre-existing-vs-new the correct way (not just re-running HEAD twice):

```
# 73fac00, real DB:
33 failed, 153 passed, 14 warnings, 34 errors in 40.91s
```
`comm`-diffing HEAD's working-DB FAILED set against base's working-DB FAILED set gives exactly **17 genuinely NEW-at-HEAD failures** (the other 14 of the 31 were already-broken-differently at base too, e.g. the removed password-auth tests count separately — see below), split into two distinct, fully-diagnosed root causes:

**(a) 11 failures — envelope not unwrapped in `tests/api/test_api_endpoints.py`** (test debt, not a prod bug): `TestAuthMe`×2, `TestAuthConfig`×1, `TestStockNames`×2, `TestStockNews`×2, `TestStockSearch`×1, `TestAIModels`×2, `TestStockHistory::test_history_returns_200_with_bars`×1. Root cause identical every time: `KeyError: 'email'` / `AssertionError: assert False = isinstance({'data':...,'meta':...}, list)` — the test reads `body["email"]`/`isinstance(body, list)` directly, but HEAD's real response is `{"data": {...}, "meta": {...}}` (S2's envelope, working correctly). Dave's WP-S2 log (`12-dave-serial-s0-s3.md:192-199`) says he fixed "4 genuine envelope regressions" — but **only in `test_timeout_handling.py`**, not in `test_api_endpoints.py`, the primary endpoint test file covering ~40 of the app's ~55 routes. **This means the automated regression gate for the envelope migration has an 11-test blind spot on the single highest-traffic test file in the repo** — not caught by Dave's broken-DB sandbox because these tests never got far enough to reach the assertion.

**(b) 6 failures — `TestWatchlist` × 6, a genuine S1-introduced test-infra bug** (see Q-3 below for full root cause — cross-referenced by Chris as "Q-3" in `14-chris-review.md:41`, confirming independent discovery).

**Delta accounting**: 11 (a) + 6 (b) = 17 confirmed-new-vs-base-with-working-DB. My earlier raw 31-vs-broken-DB-12 count included the same 17 plus 14 tests that were ALSO already failing at base-with-working-DB for unrelated reasons (5 pre-existing `TestFetchYahooDirectTimeoutHandling`/`TestFetchStockHistoryTimeoutHandling`/mock-target-broken tests not in Dave's 12-count because his 12-count came from the *broken-DB* run where a different subset errors instead of fails — reconciled by direct base-vs-head, working-DB-vs-working-DB, comparison above, which is the only sound comparison).

**Impact**: AC-M1 ("no regression vs baseline... any test that flips pass→fail is named explicitly") was signed off using a measurement where the app's own DB connection permanently fails — this makes the "no regression" claim **untestable, not proven**, for the ~60% of `tests/api` that depend on the app actually booting against a database. This is the same root problem Chris's CHRIS-01 names (non-reproducible counts) from a different angle (his: 3 identical reruns of the broken-DB condition give 3 different totals due to a *different*, event-loop-timing bug, §1.4 below; mine: the broken-DB condition itself is non-representative and hides 17 real, 100%-reproducible failures). **Both must be fixed before AC-M1 can be soundly signed off.**

`Password-auth test removal (S1) — verified exactly as claimed`: base-only FAILED tests no longer present at HEAD = exactly `TestLogin`×3, `TestLogout`×1, `TestRegister`×2, `test_auth.py::test_register_duplicate_email`×1 = 7 tests, all password-auth (ADR-007). **Matches the delegation's expectation exactly** ("S1 deletions must be exactly the password-auth tests") — confirmed via `comm -13` on the FAILED sets, not assumed.

### 1.3 🔴 Finding Q-4 (Medium→escalated, corroborates CHRIS-01) — `tests/api/conftest.py`'s session-scoped `event_loop` fixture is incompatible with pytest-asyncio ≥1.4 + real asyncpg

Running the full `tests/api` suite together (many `TestClient(app)` lifespans in one pytest session against real Postgres) intermittently produces:
```
RuntimeError: Task <Task pending name='anyio.from_thread.BlockingPortal._call_func' ...>
  got Future <Future pending cb=[BaseProtocol._on_waiter_completed()]> attached to a different loop
RuntimeError: Event loop is closed
```
`tests/api/conftest.py:32-36` still defines `@pytest.fixture(scope="session") def event_loop(): loop = asyncio.new_event_loop(); yield loop; loop.close()` — the exact pattern Sara's ADR (`01-sara-adr-migration.md §2.3`) mandated removing, and which Dave correctly removed from `backend/tests/conftest.py` but never touched here (`git diff 73fac00..HEAD -- tests/api/pytest.ini` → empty). Individual tests pass in isolation every time; running the full file/session triggers it non-deterministically. **This is exactly Chris's CHRIS-01** (he found it via 3 full-suite reruns giving 3 different totals; I found it building my own `test_contract_v1.py` and hitting the identical error running the whole file vs individual tests). Independent convergence on the same root cause and the same fix (delete the fixture, set `asyncio_default_fixture_loop_scope = session` in `tests/api/pytest.ini`, mirroring `backend/tests/conftest.py`).

### 1.4 🟡 Finding Q-5 (Medium) — `tests/api/conftest.py`'s `test_engine` fixture is collection-order-dependent ("no such table: stocks")

Reproduced standalone: any test touching the `stocks` table (e.g. `/api/v1/screener`) fails with `sqlite3.OperationalError: no such table: stocks` if it's among the first tests pytest executes in a session, because `test_engine`'s `Base.metadata.create_all()` (session-scoped, runs once) fires before anything has imported the `models` package and registered all ORM tables on `Base.metadata`. Worked around it in my own `test_contract_v1.py` by force-importing `models` at module top (see file header comment) — this is a **local workaround, not a conftest fix** (out of my write scope). Chris independently found the same symptom via a different root cause (`tests/api/conftest.py:41` missing `poolclass=StaticPool`, his CHRIS-04) — both point at the same file needing the rigor `backend/tests/conftest.py` already has; may be compounding, not duplicate, bugs.

---

## 2. Contract test (work item 2) — `tests/api/test_contract_v1.py` (new file, committed)

25 tests across 6 classes. Run individually/in small batches (full-session run hits Q-4 above):

```
TestPrefixWhitelist::test_every_api_route_is_v1_or_a_named_exception        PASS
TestPrefixWhitelist::test_named_exceptions_actually_exist_and_are_reachable PASS
TestEnvelopeShapePublic (3 params: auth/config, stocks/names, screener)     3/3 PASS
TestEnvelopeShapeAuthed (4 params: watchlists, portfolio, alerts, auth/me)  4/4 PASS
TestErrorEnvelope::test_401_no_token                                        PASS
TestErrorEnvelope::test_403_wrong_role (S-AC-1)                             PASS
TestErrorEnvelope::test_404_unknown_v1_path                                 PASS
TestErrorEnvelope::test_405_wrong_method                                    PASS
TestErrorEnvelope::test_422_validation_error                                PASS
TestErrorEnvelope::test_no_leak_markers_in_error_body (3 params)            3/3 PASS
TestHealthEndpointContract::test_health_returns_enveloped_shape_not_flat_status  PASS
TestHealthEndpointContract::test_health_needs_no_auth                       PASS
TestNoLegacyAlias (4 params: watchlists/search/portfolio/alerts old paths)  4/4 PASS
```
22/25 pass individually; the 3 that fail in a full-session run are victims of Q-4, not contract-logic defects (isolated reruns of each pass clean). **Mechanical prefix rule (AC-B2/B3): PASS** — introspects `app.routes` directly (not a fixed list), zero routes outside `/api/v1` + the 3 named exceptions, and confirms the exceptions are non-vacuous (at least one real route under each). **Envelope shape (AC-B1): PASS** on the curated reachable-with-empty-fixtures set. **Error envelope (S-AC-5): PASS** — 401/403/404/405/422 all `{data:null, meta:{error:{message}}}`, zero leak markers (`Traceback`, `Exception`, file paths, SQL fragments). **S-AC-1 (admin 403): PASS** both via this suite AND independently via live curl (§2.1). **No-legacy-alias: PASS** — old unversioned REST paths all 404, confirming ADR-001 r2's "no dual mount, in-place switch" decision was actually implemented, not just documented.

### 2.1 Live-server verification (real uvicorn + real Postgres/Redis) — beyond what sqlite fixtures alone can prove

```
$ curl /api/health
{"data":{"database":"ok","redis":"ok","celery":"fail"},"meta":{...}}   HTTP 200

$ curl /api/v1/no-such-endpoint        → 404 {"data":null,"meta":{...,"error":{"message":"Not Found"}}}
$ curl -X DELETE /api/v1/stocks/search → 405 {"data":null,"meta":{...,"error":{"message":"Method Not Allowed"}}}
$ curl /api/v1/watchlists (no token)   → 401 {"data":null,"meta":{...,"error":{"message":"Not authenticated"}}}
$ curl /api/v1/stocks/search (no q)    → 422 {"data":null,"meta":{...,"error":{"message":"Validation failed"}}}
$ curl /api/ai/no-such                 → 404 {"data":null,"meta":{...,"error":{"message":"Not Found"}}}

# S-AC-1, real users seeded (id 999 role=user, id 998 role=admin):
$ curl -H "Authorization: Bearer <user-JWT>"  /api/v1/admin/retention-policy  → 403 "Required role: ['admin']"
$ curl -H "Authorization: Bearer <admin-JWT>" /api/v1/admin/retention-policy → 200 {"data":{"policy":[...]},...}
```
All PASS, clean envelope, no leak. **AC-B7 / health.spec.ts (F2/CHRIS-12 — 🟡 Finding Q-6, corroborates)**: `/api/health` returns `{data:{database,redis,celery},meta:{...}}` — confirmed **no top-level `status` key exists**. `tests/e2e/health.spec.ts:12` still asserts `body.status === 'ok'` (unchanged, `git diff` on the file shows only a comment edit, not the assertion) — **live-run-confirmed**: all 3 `health.spec.ts` tests FAIL when actually executed (§3.2). This is Bella's own-named Finding F2/AC-B7, explicitly required to be closed this branch, and it wasn't — independently confirmed by Chris (static, CHRIS-12) and me (live E2E run, §3.2). Docker-compose healthchecks are unaffected (`test: ["CMD","curl","-f","http://localhost:8000/api/health"]` — `curl -f` only checks HTTP status ≥400, never inspects the body — verified by reading all 3 compose files' healthcheck lines), so DoD item 4 is not blocked by this, only the E2E test/AC-B7 itself.

### 2.2 🔴 Finding Q-2 (High, corroborates CHRIS-02/03) — rate-limit 429 degrades to unhandled non-JSON 500; independently reproduced live, on BOTH head and baseline

```
$ for i in 1..6; curl -X POST /api/v1/auth/google -d '{"credential":"bad"}'; done
attempts 1-5: 503 {"data":null,"meta":{...,"error":{"message":"Google OAuth not configured..."}}}
attempt 6:    500 Internal Server Error   (bare text/plain, NOT the {data,meta} envelope)
```
Server log root cause (matches Chris's CHRIS-02 exactly): `HTTPException(429, ...)` raised **inside** `RateLimitMiddleware.dispatch()` (a `BaseHTTPMiddleware`) propagates past `ExceptionMiddleware` straight to `ServerErrorMiddleware`, which returns Starlette's generic non-enveloped 500. I additionally **built and ran the 73fac00 baseline app** and reproduced the *identical* bug against the old `/api/auth/login` path — **confirms this is architecturally pre-existing** (same `raise HTTPException(...)` inside `dispatch()` pattern at baseline too, unrelated to the Starlette 0.52.1→1.6.0 major bump specifically — I checked: same failure mode both versions). **This does not reduce severity for merge purposes**: S-AC-3 (Sentinel) and AC-B6 (Bella) both **explicitly, newly** require a verified 429 on this exact branch, and the bug is a **merge blocker per Sentinel's own gate** ("branch ห้าม merge ถ้า S-AC-1..4 ไม่เขียว" — `05-sentinel-threat-model.md:180`), regardless of when the bug was introduced. Fix: move the check to a route dependency, or catch `HTTPException` in `dispatch()` and return `JSONResponse` directly (same recommendation as Chris).

---

## 3. E2E (work item 3) — Playwright, HEAD nitro build, real mocks

### 3.0 Method
Built `frontend` (`VITE_GOOGLE_CLIENT_ID=mock-client-id...`, `npm run build` → nitro `.output/`), served `PORT=4182 node .output/server/index.mjs`. `@playwright/test` isn't installed in the repo (`tests/e2e/node_modules` doesn't exist, `package.json` only lists it as a devDependency never installed) — shimmed a local `node_modules/@playwright/test` re-exporting the globally-available `playwright/test` (v1.56.1, from `/opt/node-tools`) — **not committed** (sandbox-only workaround, removed after use; a real environment needs `npm install` in `tests/e2e/`). Added `tests/e2e/playwright.quinn.config.ts` (new file, **committed**) extending the repo's own `playwright.config.ts` unmodified, only adding `BASE_URL` support (already there) + Chromium launch args to black-hole `accounts.google.com`/`fonts.googleapis.com`/`fonts.gstatic.com` (sandbox has no route to them — same 3 hosts Uma's Phase 3a report blocked for the same reason, `13-uma-ui-check.md §0`) — without this the suite hangs indefinitely retrying through the sandbox's outbound proxy.

### 3.1 `ai-chat.spec.ts` — 🟡 Finding Q-7 (Medium) — blocked at collection, pre-existing, zero migration diff
```
Error: First argument must use the object destructuring pattern: page
   at ai-chat.spec.ts:68     test.beforeEach(setupWithAI);
```
`setupWithAI(page: any)` (line 22) isn't destructured `{ page }` — current Playwright enforces this at collection time; the whole file (12 tests) can't run. `git diff 73fac00..HEAD -- tests/e2e/ai-chat.spec.ts` → **empty, zero changes ever** — confirmed 100% pre-existing, unrelated to migration; simply never caught because E2E was never run before (`00-oliver-discover.md:29`).

### 3.2 Remaining 13 files (168 collected... 180 shown, ai-chat excluded) — full run

```
$ BASE_URL=http://127.0.0.1:4182 playwright test -c playwright.quinn.config.ts \
    alerts.spec.ts auth.spec.ts chart-timeframes.spec.ts chart.spec.ts health.spec.ts \
    navigation.spec.ts portfolio.spec.ts quote-fetch.spec.ts screener.spec.ts search.spec.ts \
    settings.spec.ts sidebar.spec.ts timeout.spec.ts watchlist-autocomplete.spec.ts \
    --trace on --reporter=list
108 passed (15.4m)
```
Per-file: alerts 8/15 · auth 6/8 · chart-timeframes 10/13 · chart 8/9 · **health 0/3** · navigation 10/12 · portfolio 6/12 · quote-fetch 8/11 · screener 12/13 · search 5/12 · **settings 2/16** · sidebar 8/9 · timeout 4/7 · watchlist-autocomplete 10/15.

**🟡 Finding Q-8 (Medium) — this is the first-ever E2E execution against a live page (baseline: "E2E Playwright: not run", `00-oliver-discover.md:29`), so there is no pre-migration run to diff against the way §1 allowed for `tests/api`.** `git diff 73fac00..HEAD --stat -- tests/e2e/` shows only 10 files touched, **38 lines changed total, all literal `/api/` → `/api/v1/` path swaps in `mocks.ts` + spec files** — no assertion-logic changes anywhere. Spot-checked 4 representative failure clusters to distinguish "migration regression" from "latent, never-run test debt":
- `auth.spec.ts:55` / `settings.spec.ts:85` ("shows user avatar button") — `getByRole('button', {name:'T'})` **without `exact:true`** hits a Playwright strict-mode violation (10 buttons whose accessible name contains the substring "T" on a real rendered page). `git diff` on both lines → **zero change from baseline**, the fragile locator existed before this branch. Same failure class explains most of `settings.spec.ts`'s 14 failures (cascading from the same broken avatar-button locator in its own setup).
- `chart-timeframes.spec.ts` — 0-diff from baseline; failures are 8-30s timeouts, not assertion mismatches — consistent with "never run, first real page load reveals real timing/selector issues," not a migration-caused shape change.
- `health.spec.ts` — **all 3 fail**, root cause fully diagnosed and migration-adjacent (AC-B7, §2.2/Q-6): `body.status` doesn't exist; this ONE file's failures ARE attributable to a specific, named, unaddressed AC, unlike the rest.
- `watchlist-autocomplete.spec.ts` — 5/15 fail on "authenticated" search-dropdown assertions; not yet root-caused individually (time-boxed).

**I did not root-cause all 72 individually** (time-boxed against a first-ever run of a 180-test suite) — the pattern strongly supports "pre-existing test-quality debt surfaced by finally running the suite," not "migration regression," for everything except `health.spec.ts` (Q-6, migration-adjacent AC gap) and the two remaining files below. **Every failing test is named above and in the raw log** (`/tmp/.../scratchpad/e2e-head-full.txt`, not committed — too large; screenshots+traces at `/tmp/.../scratchpad/e2e-evidence/test-results/`, also not committed, 201MB) — Dave/QA must triage each by name before merge, this review does not certify them fixed.

**Console/network evidence** (one representative failing test, `portfolio.spec.ts` "Add Transaction modal"): screenshot shows the Portfolio page rendering correctly (glassmorphism, ₿ symbols, Thai labels, empty-state illustration) — the modal simply never opens on click within the 30s timeout, a real, reproducible app-interaction bug, not a rendering/CSS regression. `[screenshot: /tmp/.../scratchpad/e2e-evidence/test-results/portfolio-Portfolio-Page-—-c0b09-tion-modal-has-Symbol-input-chromium/test-failed-1.png]`.

**AC-B8 (WS action/type contract)** — covered live, not via this Playwright run (WS specs don't exist in `tests/e2e/*.spec.ts`, confirmed by name, matches Bella's RTM "no existing WS test found") — see §4.

---

## 4. Prefix whitelist re-grep + dual-base check (work item 4)

Re-ran independently (git-tracked files only, corrected regex vs my first pass which truncated `/api/v1`→`/api/v`): **96 raw matches outside a naive `/api/v1|health|ai|ws` filter, ALL accounted for as false positives or documented exceptions** — router-file-local prefix declarations (`/api/admin`, `/api/stocks`, etc.) that get correctly nested under the `/api/v1` aggregate router in `main.py:287-301` (live-verified: `curl /api/v1/admin/retention-policy` works, `curl /api/admin/retention-policy` 404s); 2 external third-party API calls (`services/embedding_service.py` → Ollama's own `/api/embed`, `workers/fund_fetcher.py` → an external fund-data host's `/api/fund/*`, both third-party hosts, not this app's surface); the quarantined `backend/tests/test_api_e2e.py` (confirmed module-level `pytest.skip`); a documented historical comment in `tests/api/conftest.py:96`; and the intentional 404-probe literal in `health.spec.ts:24`. **Zero live drift — matches Dave's claim, PASS.**

`aiService.ts` dual-base — confirmed statically (all 4 call sites: `chat`, `analyzeStock`, `listModels` pass `{baseURL:'/api'}` per-request override; `chatStream` uses raw `fetch('/api/ai/chat', ...)`) — **not independently confirmed via a Playwright network trace** (`ai-chat.spec.ts` is the only spec exercising this path and it's blocked at collection, Q-7). Static evidence only; **flagged as not-fully-runnable-here** for the network-trace half of this AC.

---

## 5. WS + Redis pub/sub live smoke (work item 5, AC-M7) — **PASS, full evidence**

Started `uvicorn main:app` for real (real Postgres + Redis), connected a real `websockets` client:
```
PING-> {"type":"pong"}
SUBSCRIBE-> {"type":"subscribed","symbol":"AAPL"}
MALFORMED-> {"type":"error","message":"Invalid JSON"}
# redis-py 8 PUBLISH price_updates -> WS client receives it:
PUBSUB-BRIDGE-> {"type":"price_update","symbol":"AAPL","price":123.45}
```
AC-B8 (ping/pong, subscribe, malformed-JSON error) and AC-M7 (Redis pub/sub → WS broadcast bridge under redis-py 8/RESP3) **both fully confirmed with live, own-run evidence** — no gaps.

---

## 6. Perf smoke (work item 6, AC-C2) — **inconclusive, sandbox-limited, explicitly caveated**

```
/api/health, n=50 each:  HEAD p50=2.10s p95=2.11s | BASE p50=2.10s p95=2.12s  (statistically identical)
/api/v1 (v.s. /api) stocks/search, n=20 each: HEAD p50=4.11s p95=4.53s | BASE p50=3.90s p95=4.62s
```
`/api/health`'s ~2.1s is dominated entirely by `_celery_health_check()`'s `inspect.ping(timeout=2.0)` — **identical on both sides** because neither sandbox has a running Celery worker; this measures "how long the celery-ping timeout is," not real health-check latency, and is **not usable evidence for AC-C2**. `/stocks/search` (cold cache, no external network reachable from this sandbox for yfinance) is dominated by connect-timeout/retry logic on both sides (~4s either way); the ~5.5% HEAD-vs-BASE delta is within noise for n=20 samples both bottlenecked on the same external-timeout floor, **not a usable P95 measurement for the documented "<100ms warm cache" target (AC-C1) or the "<5s P95" SLA (AC-C2)**. **Not runnable here**: needs a populated cache (real yfinance/Celery worker warming it) and a real Celery worker responding to health pings — neither exists in this sandbox. No perf regression evidence either way; flag for a full-stack Docker run before merge.

---

## 7. axe-core cross-check (work item 7) — **PASS, independently confirms Uma's Phase 3a numbers**

Own-run (`axe-core@4` via `npm install --no-save`, npm registry directly reachable per this sandbox's `NO_PROXY` allowlist), fresh Playwright browser session, `/dashboard` page, authenticated mock, `runOnly: ['wcag2a','wcag2aa','wcag21aa']`:
```
QUINN-AXE-DASHBOARD: {"button-name":{"impact":"critical","count":3},"color-contrast":{"impact":"serious","count":36}}
```
Uma's report (`13-uma-ui-check.md §3`): `button-name(critical×3), color-contrast(serious×38)`. **`button-name` count matches exactly (3=3)**; `color-contrast` differs by 2 (36 vs 38) — expected variance from different mock payloads (I used empty watchlist/quote arrays; Uma used populated mock data, so slightly fewer low-contrast DOM nodes render on my run) — **same violation IDs, same impact levels, no new violation types, no critical-count discrepancy**. Confirms Uma's Phase 3a a11y evidence independently. Console errors during the check are sandbox artifacts (blocked font/GSI hosts, WS 502 — no backend proxying in this isolated check), matching Uma's own documented pattern exactly.

---

## AC matrix — Quinn-owned axes (integration/E2E/contract/load/a11y/WS)

| AC | Verdict | Evidence |
|---|---|---|
| B2/B3 (prefix + OpenAPI-adjacent) | ✅ PASS (prefix) / see Chris CHRIS-06 (OpenAPI itself, his axis) | §4 |
| B1/B3 (envelope shape) | ✅ PASS | §2, `test_contract_v1.py` |
| B4-r3/S-AC-5 (error envelope, no-leak) | ✅ PASS | §2.1 |
| B6/S-AC-3 (rate-limit 429) | 🔴 FAIL | Q-2, corroborates CHRIS-02/03 |
| B7 (health e2e fixed) | 🔴 FAIL | Q-6, corroborates CHRIS-12 |
| B8 (WS contract) | ✅ PASS | §5, live smoke |
| M1 (tests/api no regression, my axis: soundness of the measurement) | 🔴 FAIL | Q-1, corroborates CHRIS-01 |
| M5 (pytest-asyncio conftest rewrite) | 🔴 FAIL | Q-4, corroborates CHRIS-01 |
| M7 (redis pub/sub smoke) | ✅ PASS | §5 |
| S-AC-1 (admin 403/200) | ✅ PASS | §2.1, live curl + `test_contract_v1.py` |
| C1/C2 (perf) | ⚠️ NOT PROVEN (not FAIL) | §6, sandbox-limited |
| DoD-14 (E2E run at least once) | 🟡 PARTIAL | §3 — run, but 40% first-run failure rate, mostly untriaged |
| a11y (axe cross-check) | ✅ PASS | §7 |

---

## Findings register

| ID | Finding | Severity | File:line | Fix owner |
|---|---|---|---|---|
| Q-1 | `tests/api` AC-M1 sign-off measured under a permanently-broken DB condition; masks 17 confirmed-new failures (11 envelope-unwrap-missing test debt + 6 auth-fixture bug) | 🔴 Critical | `tests/api/test_api_endpoints.py` (11), `tests/api/conftest.py:91-109` (6) | Dave (Phase 2) |
| Q-2 | Rate-limit 429 degrades to unhandled non-JSON 500 (pre-existing bug, newly a named merge-blocking AC) | 🟠 High | `backend/api/middleware/rate_limit.py:56-63` | Dave (Phase 2) |
| Q-3 | `auth_headers` fixture (S1/AC-D9) mints JWT against a different DB engine than `test_api_endpoints.py`'s `client` override → silent 401 on all Watchlist CRUD tests | 🟠 High | `tests/api/conftest.py:73-109` | Dave (Phase 2) |
| Q-4 | `tests/api/conftest.py`'s session-scoped `event_loop` fixture incompatible with pytest-asyncio ≥1.4 + real asyncpg (non-deterministic RuntimeErrors) | 🟡 Medium (test-infra, blocks sound measurement) | `tests/api/conftest.py:32-36` | Dave (Phase 2) |
| Q-5 | `test_engine` fixture's `create_all()` can run before `models` is imported → collection-order-dependent "no such table" | 🟡 Medium | `tests/api/conftest.py:39-46` | Dave (Phase 2) |
| Q-6 | `tests/e2e/health.spec.ts` still asserts the pre-envelope `body.status` shape; AC-B7 not actually closed | 🟡 Medium | `tests/e2e/health.spec.ts:12` | Dave (Phase 2) |
| Q-7 | `ai-chat.spec.ts` blocked at Playwright collection (non-destructured fixture param) — pre-existing, zero diff from baseline | 🟡 Medium | `tests/e2e/ai-chat.spec.ts:22,68,100,161` | Dave or follow-up bd |
| Q-8 | 72/180 E2E tests fail on first-ever execution; sampled root causes are pre-existing fragile locators/timing, not migration regressions, but untriaged in bulk | 🟡 Medium | see §3.2 list | Dave (Phase 2) + Quinn (follow-up automate-test pass) |
| Q-9 | `tests/e2e/` has no installed `node_modules`; `@playwright/test` devDependency was never `npm install`ed in this subproject | 🔵 Low | `tests/e2e/package.json` | Aaron (CI wiring) |

Convergent with `14-chris-review.md`: Q-1↔CHRIS-01, Q-2↔CHRIS-02, Q-3↔(cited as "Q-3" in CHRIS-01's own text), Q-4↔CHRIS-01, Q-5↔(cited as "Q-5"), Q-6↔CHRIS-12.

---

## Loop routing recommendation

- Q-1, Q-3, Q-4, Q-5, Q-6, Q-8 → **Phase 2 (Dave fix)** — test-infra + AC-B7 gaps, no spec/AC revision needed (ACs are already correct, implementation is incomplete)
- Q-2 → **Phase 2 (Dave fix)** — per Chris's fix recommendation (route-level dependency or catch-and-JSONResponse)
- Q-7, Q-9 → **Phase 2 (Dave) or follow-up bd** — pre-existing E2E infra debt, not blocking on its own but should not be silently left in "broken forever" state
- No spec/AC issues found requiring Phase 1a (Bella+Sara) revision — all findings are implementation/test-infra gaps against already-correct, already-decided ACs (agrees with Chris's same conclusion)

---

## Not runnable here (≤3 lines, full detail above)

1. **Docker builds / `docker compose up` / real healthcheck cycle** — no Docker daemon in this sandbox (confirmed by both Chris and me independently); DoD items 3-4 unverified by anyone this engagement.
2. **Warm-cache perf (<100ms AC-C1) / true P95 (<5s AC-C2)** — no reachable external network for yfinance to warm the cache, no running Celery worker for the health-check ping; my perf numbers are dominated by sandbox timeout floors, not real latency (§6).
3. **`ai-chat.spec.ts` (12 tests) + AC-B8/AI dual-base network-trace half** — blocked at Playwright collection by a pre-existing fixture-signature bug (Q-7); static code evidence only for the aiService dual-base claim.

---

## Artifacts

- `tests/api/test_contract_v1.py` (new, committed) — 25 contract tests
- `tests/e2e/playwright.quinn.config.ts` (new, committed) — sandbox runner config, documents why it exists
- Full E2E log: `/tmp/claude-0/-home-claude/95065622-d12f-5933-9418-0aff975c7c30/scratchpad/e2e-head-full.txt` (not committed, reference only)
- Screenshots/traces: `/tmp/claude-0/-home-claude/95065622-d12f-5933-9418-0aff975c7c30/scratchpad/e2e-evidence/test-results/` (not committed, 201MB, reference only)
- This report: `outputs/deps-2026-09/15-quinn-review.md`

## Sign-off
- Quinn: FAIL, 2026-09-03 (Phase 3b) — corroborates Chris's independent FAIL verdict via a different method (own-run integration + live E2E, not static/unit)
- Handoff: `Quinn ▸ Dave : Q-1..Q-9 (bd deps-2026-09) — Phase 2 fix, then re-run both tests/api (working DB) and this E2E suite before next review pass`

---

# § iter 1 re-verify

bd: deps-2026-09 · phase 3b re-verify · iter 1 · role: Quinn (adversarial)
Branch `chore/deps-2026-09`, Dave's iter1 fix pack (`d123c81, 110c1e8, e053c17, 3ca1a73, c2e2e40, e3d46bf, ca6b6af, df98204`, log `16-dave-iter1-fixes.md`), plus Chris's own parallel iter1 re-verify already landed on the branch (`8d1f180`, appended to `14-chris-review.md`, verdict FAIL — new finding CHRIS-16). HEAD for this re-verify: `8d1f180`.
Method: **own-run only, own-built baseline**. Chris's `§ iter 1 re-verify` was read for orientation (not trusted) — every claim re-executed independently below, including a *second, fresh* `73fac00` worktree/venv/frontend-build built from scratch this session (the iter0 one had already been torn down) so both my `tests/api` and my E2E baseline comparisons are against a real, freshly-built pre-migration artifact, not a cached one.

## Verdict: **FAIL** — 1 High-severity finding open (Q-10, converges independently with CHRIS-16), all other Q-1..Q-9 findings close clean

## Item 1 — `tests/api`, 3× reproducibility + full 26-failure classification

3 back-to-back runs, byte-identical:
```
run1: 26 failed, 212 passed, 5 warnings in 51.49s
run2: 26 failed, 212 passed, 5 warnings in 51.18s
run3: 26 failed, 212 passed, 5 warnings in 51.47s
```
`diff` on the 3 runs' `FAILED` test-ID lists: **run1==run2==run3, identical set, 26 IDs.** **Q-4 (event_loop cross-loop bug) CLOSED** — was non-reproducible (3 different totals) at iter0, now byte-identical 3/3.

Classification against a **fresh** `73fac00` worktree (`/home/claude/wt-quinn-baseline`, new `uv venv`, `uv pip install -r backend/requirements.txt -r tests/api/requirements.txt`, same live Postgres/Redis, same env vars): baseline itself is **still non-reproducible** (run1: 33F/153P/34E, run2: 35F/151P/34E — the pre-fix `event_loop` bug, confirmed present at baseline exactly as expected). Took the **union** of both baseline runs' FAILED+ERROR test IDs (72 unique) and compared against HEAD's 26:
```
comm -12 head_ids.txt baseline_union_ids.txt | wc -l   -> 26   (ALL 26 present in baseline)
comm -23 head_ids.txt baseline_union_ids.txt            -> (empty — zero HEAD-only IDs)
```
Then re-ran the exact same 26 test IDs at baseline with `--tb=line` and diffed failure *reasons* (not just IDs) against HEAD's: every one matches — same `AttributeError` on the same removed/renamed attributes (`_run_screener`, `_fetch_yahoo_direct`, `_get_yf_auth`, `_load_bars_from_db`, `fetch_stock_quote` — all confirmed absent at baseline too via the same mock-target-not-found error), same `assert 200 == 400`/`assert 200 == 404`/`assert 503 == 200`/`assert '1D' == '1W'` assertion mismatches, same `feedparser.parse was not called`. **All 26 = pre-existing-identical-at-73fac00, proven by re-running the identical baseline binary, not just diffing source. Zero NEW.**

## Item 2 — `test_contract_v1.py` + `openapi-v1.json`

```
$ pytest -q test_contract_v1.py
collected 23 items
test_contract_v1.py .......................              [100%]
======================== 23 passed, 2 warnings in 8.31s ========================
```
**23/23 pass** (file has 23 tests total, not 25 — correcting my own iter0 report's count). Runs clean as a **whole-file** run now (Q-4's fix removed the need for the individual-test workaround from iter0).

**Note (transparency, not a blocker):** Dave's `110c1e8` touched this file twice — fastapi 0.141.1/starlette 1.6.0 changed `include_router()` to a lazy wrapper that broke my `_iter_api_routes` route-introspection helper (fixed by switching to `app.openapi()["paths"]`), and one parametrize case (`GET /api/v1/watchlists` → `POST`) that only ever "passed" pre-fix because of the exact CHRIS-04/Q-5 bug being fixed in the same commit (a valid authed `GET` legitimately returns `200`, not an error, so it never belonged in the error-envelope test in the first place). Outside the delegation's stated "hands off Quinn's files" scope, but well-justified and independently re-verified correct by my own-run above — not re-litigating, just flagging.

`openapi-v1.json` — live `/openapi.json` (fresh `uvicorn` boot, port 8020) diffed structurally against the committed `outputs/deps-2026-09/openapi-v1.json` (updated by Dave's `c2e2e40`):
```
LIVE      200 schema: {"type":"object","properties":{"data":{},"meta":{"$ref":"#/components/schemas/ResponseMeta"}},"required":["data","meta"]}
COMMITTED 200 schema: (byte-identical, key order differs only)
LIVE/COMMITTED 422 schema: {"$ref": "#/components/schemas/ErrorEnvelope"} (both)
live paths=43, committed paths=43 (match)
```
**CHRIS-06/contract regeneration CONFIRMED CLOSED** — committed file matches the live app exactly, envelope + error/422 shapes both correct.

## Item 3 — E2E live run + 69-classification re-verify

Rebuilt the frontend fresh (`npm run build`, HEAD). First build used the default `VITE_API_URL=http://backend:8000` (Docker-hostname, unreachable here) — caught this before running (`grep backend:8000 .output/server/index.mjs`), rebuilt with `VITE_API_URL=http://127.0.0.1:8020` pointed at my own live HEAD `uvicorn`, confirmed the proxy resolves (`curl :3000/api/health` → `200`, real envelope body) before running the suite.

```
$ BASE_URL=http://127.0.0.1:3000 playwright test -c playwright.quinn.config.ts --reporter=list
Running 194 tests using 1 worker
...
79 failed
115 passed (18.9m)
```
**194 total** (was 180 in iter0 — **+14 ai-chat.spec.ts, now collecting and executing: Q-7 CLOSED at the collection level**). Per-file (own-run, this session):
```
ai-chat 6/14 · alerts 7/15 · auth 5/7 · chart 8/12 · chart-timeframes 15/20 · health 3/3
navigation 14/16 · portfolio 4/12 · quote-fetch 8/12 · screener 16/18 · search 3/14
settings 1/16 · sidebar 13/14 · timeout 3/6 · watchlist-autocomplete 9/15
```
**health.spec.ts: 3/3 PASS, live** — CHRIS-12/Q-6 confirmed closed against a real running backend, not just at source.

**Correction to my own iter0 §3.2 table**: several per-file *totals* were undercounted there (e.g. chart-timeframes 13→20, navigation 12→16, screener 13→18, sidebar 9→14, search 12→14) — root cause: files using repeated `test.describe.each`/parametrized blocks at one `line:col` (e.g. `chart-timeframes.spec.ts:138:9` × 5 distinct indicator-toggle tests) weren't fully enumerated by my original manual transcription. Not a regression, a self-correction; this session's exported pass/fail-by-test-ID data is authoritative going forward.

**69-classification re-verify — built and ran the REAL `73fac00` baseline live** (not git-diff reasoning alone, which is all Dave's `df98204` had access to, no Docker there either): fresh `npm install` + `VITE_API_URL=http://127.0.0.1:8020 npm run build` in the baseline worktree, served on port 3001, ran the identical 13 non-ai-chat/non-health spec files (`ai-chat.spec.ts` excluded — see below):
```
Running 177 tests using 1 worker
...
72 failed
105 passed (14.7m)
```
Diffed HEAD's 79 failing test IDs against this **live baseline's** 72 failing test IDs by exact name+description string:
```
HEAD-fail tests NOT in BASE-fail set: 8   (all 8 are ai-chat.spec.ts — see below)
```
**71 of 79 HEAD failures are byte-identical test-ID matches against a live-executed 73fac00 baseline** — pre-existing-identical, proven stronger than the requested "spot-check ≥10" (full live diff, not sampling). Zero new regressions in the 13 classic spec files.

**ai-chat.spec.ts's 8 failures**: baseline could never execute this file — running baseline's full suite un-excluded crashes at collection with `First argument must use the object destructuring pattern: page` at `ai-chat.spec.ts:68`, **the exact same Q-7 bug, byte-identical, confirmed present in the 73fac00 source** (own-run reproduction, not inference). Dave's `df98204` fix only destructures the parameter to unblock *collection* — it touches zero assertion logic. Spot-checked 1 of the 8 (`clicking chevron-down closes the panel`): root cause is a fragile locator, `page.locator('[style*="bottom: 52"]')` — matching on an inline-CSS-string substring, the same class of locator-fragility (violates this project's own "`data-testid` > ARIA > text" rule) seen driving many of the other 71 failures elsewhere in the suite. Not individually root-caused for the remaining 7 (time-boxed), but classification holds: **pre-existing test debt, first-ever execution, not a migration or fix-caused regression.**

**Total E2E NEW failures this iteration: 0.**

## Item 4 — rate-limit 429 envelope + trusted-proxy, live `uvicorn` curl

**429 envelope — CLOSED.** 6 rapid `POST /api/v1/auth/google` (no XFF, same origin):
```
attempt 1-5: HTTP:503
attempt 6:   HTTP:429
body: {"data":null,"meta":{"request_id":"...","data_status":"unavailable",...,"error":{"message":"Too many login attempts. Try again in 900 seconds."}}}
```
Proper enveloped JSON, not the raw non-JSON 500 from iter0. **CHRIS-02/Q-2 CONFIRMED CLOSED.**

**Trusted-proxy — REPRODUCED OPEN, independently.** `trusted_proxies_list` confirmed `[]` by default (`python -c "from core.config import settings; print(settings.trusted_proxies_list)"`). Flushed the rate-limit key, then 6 requests each with a **distinct** spoofed `X-Forwarded-For` (`10.0.0.1`..`10.0.0.6`) from loopback:
```
attempt 1-6 (XFF=10.0.0.1..6): HTTP:503 (never 429)
$ redis-cli keys "rate:login:*"
rate:login:10.0.0.1
rate:login:10.0.0.2
rate:login:10.0.0.3
rate:login:10.0.0.4
rate:login:10.0.0.5
rate:login:10.0.0.6
```
6 separate buckets keyed by the **attacker-controlled spoofed IP**, not the real peer — the bypass CHRIS-03's app-level fix was supposed to close still works end-to-end over a real socket. Root cause confirmed independently:
```
$ python -c "import uvicorn; c=uvicorn.config.Config(app='main:app'); print(c.proxy_headers, c.forwarded_allow_ips)"
True 127.0.0.1
```
uvicorn 0.52.4's own default (`proxy_headers=True, forwarded_allow_ips="127.0.0.1"`) rewrites `scope["client"]` from the spoofed XFF at the ASGI layer, **before** the app-level `TRUSTED_PROXIES` check ever runs, whenever the connecting peer is loopback — true of every environment used across this entire engagement (dev, this sandbox, and per `grep -rn "proxy.headers\|forwarded.allow.ips" docker-compose*.yml backend/Dockerfile*` → zero results, no override anywhere in any of the 3 compose files or the Dockerfile).

**Finding Q-10 (High, NEW this iteration, independently converges with Chris's CHRIS-16)** — same root cause, same reproduction method (live-uvicorn curl, not `TestClient`), found via my own separate methodology before reading Chris's report in detail. Per house rule ("security finding present = block merge") and Sentinel's threat model (AB-2/AB-6), this alone keeps my verdict at FAIL. Fix/route: same as CHRIS-16 — Dave (Phase 2, pin `--proxy-headers=false`/`forwarded_allow_ips=""` on every uvicorn/gunicorn invocation across all 3 compose files, or explicitly document+accept the loopback trust boundary and correct `rate_limit.py`'s now-inaccurate docstring), escalate to Sentinel for deployment-topology verification.

## Item 5 — WS/pub-sub smoke (AC-M7), re-run on HEAD

```
PING-> {"type":"pong"}
SUBSCRIBE-> {"type":"subscribed","symbol":"AAPL"}
MALFORMED-> {"type":"error","message":"Invalid JSON"}
PUBSUB-BRIDGE-> {"type":"price_update","symbol":"AAPL","price":123.45}
```
**Full PASS, byte-identical to iter0.** AC-B8 + AC-M7 remain fully confirmed, no regression.

## Q-1..Q-9 disposition summary

| ID | iter0 sev | iter1 disposition |
|---|---|---|
| Q-1 | 🔴 Critical | **CLOSED** — 17 iter0-new failures resolved by the fixture rewrite; current 26 tests/api failures are a different, now-fully-reclassified set, all pre-existing-identical (Item 1 above) |
| Q-2 | 🟠 High | **CLOSED** (429 envelope) — see Item 4. Superseded by new Q-10 for the trusted-proxy half |
| Q-3 | 🟡 Medium | **CLOSED** — `app_client`/`client`/`auth_headers` engine unification (Dave's `110c1e8`), confirmed via clean `test_admin_authz.py`/contract-test runs |
| Q-4 | 🟡 Medium | **CLOSED** — reproducibility confirmed 3/3 (Item 1) |
| Q-5 | 🟡 Medium | **CLOSED** — `StaticPool` + forced `models` import in conftest.py; my file's own workaround is now redundant but harmless (untouched, out of scope to remove) |
| Q-6 | 🟡 Medium | **CLOSED** — health.spec.ts live 3/3 pass (Item 3), corroborates CHRIS-12 |
| Q-7 | 🟡 Medium | **CLOSED at collection** — ai-chat.spec.ts now executes (14 tests); 8 internal failures reclassified as pre-existing test debt, not re-opening Q-7 |
| Q-8 | 🟡 Medium | **CLOSED / upgraded to certainty** — 69 pre-existing claim now proven via live baseline execution (71 exact matches, Item 3), not just git-diff inference |
| Q-9 | 🔵 Low | **NO CHANGE** — CI/tests/e2e node_modules gap, Aaron's territory, not re-checked this iteration (informational, unaffected by this fix pack) |

**NEW this iteration: Q-10 (High)** — see Item 4.

## Not runnable here (iter1, ≤3 lines)

1. Docker build/boot/healthcheck cycle — still no Docker daemon in this sandbox, unchanged constraint.
2. Warm-cache/Celery-backed perf (AC-C1/C2) — still no reachable yfinance network or live Celery worker; not re-attempted this iteration (iter0's caveat stands).
3. Full individual root-cause of all 71+8 pre-existing E2E failures — classification is proven (byte-identical test IDs against a live baseline, Item 3), but not every one individually root-caused; recommend a dedicated follow-up bd for locator-fragility cleanup (data-testid migration).

## Artifacts (iter1)

- `tests/api/iter1_head_run{1,2,3}.txt`, `iter1_baseline_run{1,2}.txt` — reproducibility + baseline classification raw output
- `tests/e2e/iter1_e2e_full2.txt` (HEAD, 194 tests), `iter1_e2e_baseline_run2.txt` (73fac00, 177 tests) — full E2E diff evidence
- Fresh `73fac00` worktree: `/home/claude/wt-quinn-baseline` (venv + frontend build both rebuilt from scratch this iteration)
- All raw logs at `/tmp/claude-0/-home-claude/95065622-d12f-5933-9418-0aff975c7c30/scratchpad/iter1_*` (not committed, reference only, per iter0's same convention)
- This report: `outputs/deps-2026-09/15-quinn-review.md`

## Sign-off (iter1)
- Quinn: **FAIL**, 2026-09-03 (Phase 3b iter1) — Q-1..Q-9 all closed or reclassified with stronger own-run evidence than iter0; **Q-10 (High)** newly found via live-uvicorn curl, independently converges with Chris's CHRIS-16 (same root cause, same fix). Blocks merge until Dave closes it.
- Handoff: `Quinn ▸ Dave : Q-10/CHRIS-16 (bd deps-2026-09) — Phase 2 fix (uvicorn/gunicorn proxy-header trust across all 3 compose files), then Quinn/Chris re-verify iter2`
