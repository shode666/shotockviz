# 14 — Chris: Code Review (Phase 3b, deps-2026-09)

bd: deps-2026-09 · phase 3b Code Review · iter 0 · role: Chris (code-reviewer, adversarial)
Repo: `/home/claude/shotockviz-ro` · branch `chore/deps-2026-09` · HEAD `9e17712` · base `73fac00`
Scope: `git diff 73fac00..HEAD` (41+ files, excludes `outputs/`). Runs `∥` Quinn (integration/E2E/contract — not duplicated here).
Toolchain used (own-run, not trusted from Dave's logs): `.venv` py3.13.7, `node -v` → `v24.20.0`, live Postgres 16 + Redis 7 on localhost, live `uvicorn main:app` boot for curl-level verification.

## Verdict: **FAIL** — block merge

1 Critical, 7 High, 7 Medium, 2 Low/informational findings. AC coverage: **21 PASS / 10 FAIL / 2 N/A** (of 33). DoD: **6 PASS / 8 FAIL / 1 PARTIAL / 1 N/A** (of 16, Chris-observable subset — item 14 is Quinn's).

The envelope mechanism, admin-authz fix, pydantic cleanup, dependency bumps, and JS→TS conversion are all **correctly implemented** (own-run curl/unit-test evidence below). The blockers are: (1) the migration's own pytest-asyncio 1.x fixture rewrite was only half-applied, making `tests/api`'s pass/fail counts **non-reproducible** — I got three different totals across runs on identical code; (2) a real, live, curl-provable bug where the rate-limiter's 429 response degrades to an unhandled, non-JSON 500; (3) the same rate limiter's IP-trust logic is bypassable; (4) OpenAPI is provably wrong (empty/stale schemas) for the new contract, defeating AC-B3 and any codegen/Schemathesis gate; (5) `.github/workflows/ci.yml` and `changelog.md`/`tasklist.md` were never reconciled despite being explicitly named in Sara's ADR / CLAUDE.md house rules.

---

## Findings (severity-ordered)

### 🔴 CHRIS-01 (Critical) — `tests/api/conftest.py`'s pytest-asyncio 1.x rewrite was never done; `tests/api` results are non-reproducible

**Evidence (own-run):**
```
$ pytest tests/api -q   # run 1
12 failed, 119 passed, 5 warnings, 62 errors in 51.72s

$ pytest tests/api -q   # run 2, identical code, identical env
43 failed, 147 passed, 10 warnings, 4 errors in 34.65s

$ pytest tests/api -q   # run 3
43 failed, 147 passed, 8 warnings, 4 errors in 34.39s
```
Three runs of the identical suite against identical code give **three different totals**. Root cause, isolated with a fresh single-test repro:
```
$ pytest tests/api/test_pr4_envelope.py::TestErrorEnvelopeOnV1::test_405_wrong_method_is_enveloped -v
RuntimeError: Task <Task pending name='anyio.from_thread.BlockingPortal._call_func' ...>
  got Future <Future pending cb=[BaseProtocol._on_waiter_completed()]> attached to a different loop
```
`tests/api/conftest.py:32-36` still defines a custom **session-scoped `event_loop` fixture** (`asyncio.new_event_loop()`), the exact pattern `01-sara-adr-migration.md §2.3` mandated removing ("`event_loop` fixture removed in pytest-asyncio 1.0.0... delete"). Dave's WP-B2 correctly removed it from **`backend/tests/conftest.py`** (`backend/tests/conftest.py:23-26` comment confirms) — `backend/tests` is 100% reproducible in my own runs (104 passed / 2 skipped / 37 deselected, identical every time). **`tests/api/conftest.py` — a separate, second pytest root at repo top-level with its own `pytest.ini` — was never touched**: `git diff 73fac00..HEAD -- tests/api/pytest.ini` → empty; the `event_loop` fixture is byte-identical to baseline. Async Postgres connections (real `asyncpg`, opened by the app's own startup lifespan — confirmed via server log `PostgreSQL enum types synced`) get created under one event loop and torn down under another, producing intermittent `RuntimeError`s that **cascade into unrelated tests' setup/teardown** in the same session (reproduced: a later test fails with `no such table: users` because an earlier test's connection teardown corrupted session state).

**Impact:** AC-M5 is marked "done" in `10-dave-backend-b0-b5.md`/`12-dave-serial-s0-s3.md`, but it is only half-done. Every pass/fail count anyone (Dave, Bella, Oliver) has cited for `tests/api` (116p/12f/73e → 65e) is **one snapshot of a non-deterministic process**, not a stable measurement. AC-M1's "no regression" gate cannot be soundly signed off until this is fixed — I cannot tell you today whether `tests/api` has 12 or 43 real failures.

**Convergent evidence:** Quinn's parallel contract-test file (`tests/api/test_contract_v1.py`, untracked in this worktree as I write this — not my deliverable, cross-referenced only) independently documents two *related* root causes in the same fixture family (Q-3: `app_client`'s per-request-fresh-engine pattern silently 401s when combined with `auth_headers`; Q-5: `Base.metadata` incomplete-at-`create_all`-time when model modules haven't been imported yet, causing collection-order-dependent "no such table" flakes). These are separate bugs from the `event_loop`/cross-loop issue above, in the same file, also unaddressed — see CHRIS-04.

**Fix (for Dave):** apply the same rewrite already proven in `backend/tests/conftest.py` to `tests/api/conftest.py`: delete the custom `event_loop` fixture (`tests/api/conftest.py:32-36`), add `asyncio_default_fixture_loop_scope = session` to `tests/api/pytest.ini`. Re-run `tests/api` 3× to confirm identical totals before any AC-M1 sign-off.

**Tests added:** none needed beyond the repro above — this is an infra bug, not a unit under test. My new test files (below) all had to be verified test-by-test in isolation to get a true read, because of this bug.

---

### 🟠 CHRIS-02 (High) — Rate-limit 429 degrades to an unhandled, non-JSON 500

**Evidence (own-run, live uvicorn):**
```
$ curl -s -X POST -H "X-Forwarded-For: 9.9.9.9" -d '{"credential":"bad"}' \
    http://127.0.0.1:8123/api/v1/auth/google   # 6th attempt, same key
  → HTTP/1.1 500 Internal Server Error
    content-type: text/plain; charset=utf-8
    Internal Server Error
```
Server log confirms root cause:
```
File ".../backend/api/middleware/rate_limit.py", line 61, in dispatch
    raise HTTPException(status_code=429, ...)
fastapi.exceptions.HTTPException: 429: Too many login attempts. Try again in 900 seconds.
... RuntimeError('Event loop is closed') / propagates past ExceptionMiddleware to ServerErrorMiddleware
```
`RateLimitMiddleware` (`backend/api/middleware/rate_limit.py:8`) is a `BaseHTTPMiddleware` registered via `app.add_middleware()` (`main.py:268`, pre-existing pattern, unchanged by this migration). Starlette's middleware stack order is `ServerErrorMiddleware → user middleware → ExceptionMiddleware → router`. An `HTTPException` raised **inside** a user `BaseHTTPMiddleware.dispatch()` is outside `ExceptionMiddleware`'s reach — it propagates straight to `ServerErrorMiddleware`, which returns the framework's generic, non-JSON 500. **`install_error_envelope()`'s handlers never see it.**

This is architecturally pre-existing (same bug exists at baseline for the old `/api/auth/login` path — confirmed by reading `73fac00`'s identical `rate_limit.py` structure), but it is now a **named, testable AC**: S-AC-3 (`05-sentinel-threat-model.md`) and AC-B6 (`02-bella-brd-ac.md`) both explicitly require a verified 429 response on this branch, and nobody's verification transcript (Dave's WP-S2 in-memory script) ever exercised the 6th-attempt path — it only checked `POST`/`GET` happy-paths, S-AC-1, and 401. **This is a confirmed, un-caught regression against the branch's own stated acceptance criteria**, not a "pre-existing, out of scope" item.

**User-facing consequence (own-run, confirmed against `frontend/src/services/api.ts:72-103`):** `error.response.data` for a `text/plain` body is the raw string `"Internal Server Error"`. `body?.meta?.error?.message` and `body?.detail` both evaluate to `undefined` on a string. The interceptor falls through to `msg = error.message` (axios's generic "Request failed with status code 500") and shows a **misleading toast** — a rate-limited user sees "something crashed," not "try again in 15 minutes."

**Test added:** `tests/api/test_rate_limit_middleware.py::TestRateLimitEnvelope::test_sixth_attempt_from_same_ip_returns_429_with_envelope` — **currently FAILS** (as expected, proving the bug):
```
FAILED ...test_sixth_attempt_from_same_ip_returns_429_with_envelope
fastapi.exceptions.HTTPException: 429: Too many login attempts. Try again in 900 seconds.
```
(Under `TestClient`'s default `raise_server_exceptions=True`, the unhandled exception blows up the test directly — even starker proof than the curl 500.)

**Fix (for Dave):** move the rate-limit check into a route-level `Depends()` (inside routing, past `ExceptionMiddleware`) instead of ASGI middleware, or catch `HTTPException` inside `dispatch()` and return a `JSONResponse` directly instead of raising.

---

### 🟠 CHRIS-03 (High) — Rate limiter's IP trust is unconditional; bypassable by anyone who can set `X-Forwarded-For`

**Evidence (own-run, live uvicorn):**
```
$ for ip in 1 2 3 4 5 6; do curl -s -X POST -H "X-Forwarded-For: 10.0.0.$ip" \
    -d '{"credential":"bad"}' http://127.0.0.1:8123/api/v1/auth/google -w " HTTP:%{http_code}\n"; done
... HTTP:503 (x6, never blocked — each spoofed IP gets a fresh bucket)
```
`rate_limit.py:40-43`:
```python
xff = request.headers.get("x-forwarded-for")
if xff:
    return xff.split(",")[0].strip()
return request.client.host if request.client else "unknown"
```
trusts the client-supplied header's first value **unconditionally**, with no check that the request actually arrived via the trusted Caddy hop. Caddy itself is configured correctly (`caddy/Caddyfile:36,47` uses `header_up X-Forwarded-For {remote_host}`, which **overwrites**, not appends — so traffic *through* Caddy is safe). But: (a) `docker-compose.dev.yml:75-76` exposes the backend directly on host port `8000:8000`, alongside Caddy on 80/443 — anyone who can reach that port bypasses Caddy entirely; (b) this is exactly the scenario Sentinel's own acceptance text for S-AC-4 names explicitly: *"ยิงตรง backend ด้วย XFF ปลอม (ไม่ผ่าน Caddy) → ไม่ trust header"* (`05-sentinel-threat-model.md` S-AC-4) — the code does the opposite of what its own governing AC requires.

**Test added:** `tests/api/test_rate_limit_middleware.py::TestRateLimitKeyingNotSpoofable::test_distinct_spoofed_xff_per_request_still_gets_rate_limited` — **currently FAILS**:
```
AssertionError: expected the 6th request to still be blocked ... but got 503
assert 503 == 429
```
6 requests, 6 different forged `X-Forwarded-For` values → never rate-limited, confirming AB-2/AB-6 (Sentinel's own abuse cases) are **not actually closed**.

**Fix (for Dave):** validate the peer (`request.client.host`) against a trusted-proxy allowlist (Docker subnet) before honoring `X-Forwarded-For`, or configure `uvicorn --forwarded-allow-ips` / gunicorn's proxy trust and read the already-validated value instead of the raw header.

---

### 🟠 CHRIS-04 (High, pre-existing but undiscovered until now) — `tests/api` DB fixtures don't reliably see the tables they create

**Evidence (own-run, reproduced standalone AND at baseline `73fac00`, same result both):**
```
$ pytest tests/api/test_admin_authz.py::TestGetRetentionPolicyAuthz::test_regular_user_is_forbidden -v
ERROR ... sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: users
```
Reproduced in a **fresh, isolated single-test pytest process** (not a cascading-order artifact) — the fixture chain itself is broken. `tests/api/conftest.py:39-46`'s `test_engine` fixture (session-scoped, in-memory SQLite) does **not** use `poolclass=StaticPool`, unlike its sibling in `backend/tests/conftest.py:33-37` which does. Confirmed pre-existing: an equivalent standalone probe against the `73fac00` baseline worktree reproduces the identical `OperationalError` (see report appendix — baseline probe script, deleted after use, not committed).

This converges with Quinn's independently-authored `test_contract_v1.py` (Q-5 finding: `Base.metadata` incomplete at `create_all()` time unless `models` was already imported by something earlier in the session — a plausible root cause for the same symptom, possibly compounding rather than duplicating my StaticPool observation; both point at the same file needing the same rigor `backend/tests/conftest.py` already has).

**Impact:** this is why **no admin-authz test (S-AC-1 / AC-D5) was ever written by anyone** on this branch — the standard `client` + DB-user fixture pattern that every other test in the repo uses is currently non-functional for any test that needs to create a user row and then exercise it through an HTTP request. I worked around it by writing a **pure-unit test that calls the dependency function directly, bypassing DI/DB entirely** (see CHRIS test coverage section) — that's how S-AC-1 got proven correct despite this bug.

**Not migration-caused** (reproduces byte-identically at baseline) — but it silently defeats a test-writing obligation this exact migration created (S-AC-1/AC-D5), so it belongs in this review, not deferred as unrelated debt.

**Fix (for Dave or a follow-up bd):** add `poolclass=StaticPool` to `tests/api/conftest.py:41`'s `create_async_engine(...)` call, mirroring `backend/tests/conftest.py:36`.

---

### 🟠 CHRIS-05 (High, pre-existing, confirmed newly-severe) — `hash_password()` is unconditionally broken (passlib 1.7.4 × bcrypt 5.0.0)

**Evidence (own-run, standalone, deterministic across 3 consecutive calls in the same process):**
```
$ python -c "from core.security import hash_password; print(hash_password('TestPass1'))"
(trapped) error reading bcrypt version
AttributeError: module 'bcrypt' has no attribute '__about__'
...
ValueError: password cannot be longer than 72 bytes, truncate manually if necessary (e.g. my_password[:72])
```
`passlib` 1.7.4's bcrypt backend probes `bcrypt.__about__.__version__` to detect the installed bcrypt version (`passlib/handlers/bcrypt.py:620`) — bcrypt **5.0.0 removed that submodule**. Passlib's fallback path then runs an internal self-test (`detect_wrap_bug`) using a >72-byte hardcoded probe string, and bcrypt 5.0.0's stricter length validation makes that **internal self-test itself crash** — the "password cannot be longer than 72 bytes" message is misleading; it has nothing to do with the caller's actual (9-char) password. Every single call to `hash_password()` fails, 100% reproducible, verified 3× in a row in the same interpreter (no lazy-success-then-cache behavior).

**Confirmed pre-existing, not migration-caused:** `backend/requirements.txt` pins `bcrypt==5.0.0` / `passlib[bcrypt]==1.7.4` **identically at baseline `73fac00`** (verified: built a clean venv from baseline's `requirements.txt`, `pip show bcrypt` → `5.0.0`). Sara's ADR already flagged this pairing as "unmaintained... pre-existing, out of scope" (`01-sara-adr-migration.md §1.3`) but as a *risk note*, not as something anyone actually exercised — this review is the first time anyone ran `hash_password()` and discovered it doesn't just carry theoretical risk, it is **completely non-functional today**.

**Impact:** `scripts/create_user.py` (the ops tool for creating users) is unusable. Any NEW test written against the standard `_test_user`/`auth_headers` pattern (in either `conftest.py`) silently breaks at fixture setup. This is why my own new tests (`test_admin_authz.py`) had to route around `hash_password()` entirely with a placeholder `password_hash` string (safe: post-ADR-007, `password_hash`'s value is never read by any code path since password login was removed).

**Not blocking this migration's merge on its own** (pre-existing, unrelated to the deps bump itself — bcrypt/passlib pins were untouched) but severe enough, and newly-discovered, to escalate as a named finding rather than silently work around it.

**Fix (follow-up bd, not this branch):** replace `passlib[bcrypt]` with direct `bcrypt.hashpw`/`bcrypt.checkpw` calls (passlib's abstraction is dead weight now that only bcrypt is used), or pin `bcrypt<4` (loses the security fixes bcrypt 5 shipped) — the former is correct.

---

### 🟠 CHRIS-06 (High) — OpenAPI schema is stale/wrong for the new envelope contract; breaks AC-B3

**Evidence (own-run, live uvicorn `/openapi.json`):**
```json
// GET /api/v1/stocks/quotes — actual runtime response is {"data":{"AAPL":null},"meta":{...}}
"responses": { "200": { "content": { "application/json": { "schema": {} } } } }   // EMPTY schema

// GET /api/v1/watchlists — actual runtime response is {"data":[...],"meta":{...}}
"responses": { "200": { "schema": { "type": "array", "items": {"$ref": ".../WatchlistResponse"} } } }
// documented as a bare array — actual body is an OBJECT wrapping an array

// 422 on any /api/v1/* route — actual runtime body is {"data":null,"meta":{...,"error":{...}}}
"HTTPValidationError": { "properties": { "detail": {...} } }   // FastAPI's stock shape, never returned anymore
```
`schemas/envelope.py`'s `EnvelopingAPIRoute` wraps responses at the **ASGI response layer** (after FastAPI has already generated the OpenAPI schema from each handler's `response_model`), so `/openapi.json`/`/docs` describe the **pre-envelope** shape everywhere — Dave documents this explicitly as an accepted tradeoff (`12-dave-serial-s0-s3.md` "Known limitation... Accepted tradeoff for one-atomic-commit scope"). I disagree that this is an acceptable tradeoff for merge, for three concrete reasons:

1. **AC-B3-r3** (`02-bella-brd-ac.md` §r3) explicitly requires: *"the response body is `{data: null, meta: {...}}` per ADR-002's error-block design... the SAME request... `/openapi.json`"* is the artifact this branch's own OpenAPI-diff mechanism (Dave's `outputs/deps-2026-09/openapi-v1.json`, 39 paths) is built on — and that snapshot is **provably not the real contract**, so the diff exercise itself is invalid as evidence for AC-B3.
2. **Consumer risk, not hypothetical**: `05-sentinel-threat-model.md` names Quinn's planned Schemathesis/oasdiff contract gate as the consumer of `outputs/api/openapi.yaml` — any tool that generates requests/assertions from this OpenAPI file will assert against the WRONG shape.
3. The 422 case is worse than "incomplete" — it's actively **misleading**: the documented `HTTPValidationError.detail` shape is exactly the shape `frontend/src/services/api.ts:97-102`'s dead-code fallback branch was written for ("Keep the `detail` fallback only for any response that somehow isn't enveloped (defense in depth)") — the OpenAPI file makes it look like that's still the primary path, when in fact `install_error_envelope` guarantees it never is on `/api/v1/*`.

**This is not a docs-only nitpick** — it's a broken machine-readable contract on a branch whose entire stated purpose (sub-scope b, "API contract/versioning") is contract discipline.

**Fix (for Dave/Sara, follow-up acceptable if scoped explicitly):** either accept `response_model=BaseResponse[X]` on all ~55 handlers (the correct fix, larger diff) or generate the v1 OpenAPI file by hand/script from the ACTUAL runtime shape (curl-and-capture, not FastAPI's auto-generation) rather than trusting `/openapi.json` as the artifact of record. Either way, `outputs/deps-2026-09/openapi-v1.json` as it stands today should not be used as Quinn's contract-test input without this caveat attached.

---

### 🟠 CHRIS-07 (High) — `.github/workflows/ci.yml` never reconciled; would fail if manually dispatched

**Evidence:** `git diff 73fac00..HEAD -- .github/workflows/ci.yml` → **empty, zero changes**. Three specific items Sara's own ADR named as required were never applied:

1. **`ci.yml:43`** — `uv pip install -r requirements.txt --system` only. WP-B1 moved `pytest`/`pytest-asyncio`/`pytest-cov` into a NEW `requirements-dev.txt` (correctly, to keep the prod image clean — verified: `uv pip install -r requirements.txt` alone in a fresh venv has no `pytest` module). `ci.yml:55` then runs `python -m pytest tests/ ...` — **this step would now fail with `ModuleNotFoundError: No module named pytest`**, a strictly worse failure than the pre-existing gap Sara flagged (`01-sara-adr-migration.md §1.5`: "add pytest-cov to reqs OR drop `--cov` flags" — at baseline, `pytest` itself WAS in `requirements.txt` directly, just missing `pytest-cov`; post-migration, `pytest` itself is gone from that file).
2. **`ci.yml:69`** — `node-version: '20'`. Sara's ADR explicitly targets `'20' → '24'` (`01-sara-adr-migration.md §1.5`) — this branch's entire premise is Node 24; CI would build on an untested Node version.
3. **`ci.yml:86`** — artifact path `frontend/dist/`. Pre-existing bug (nitro outputs to `.output/`, never `dist/`) Sara also flagged; still unfixed.

None of these are covered by DoD item 16 ("CI not touched" — a deliberate non-change to the **trigger** only, `on: workflow_dispatch`, per user decision #2) — that item is about **not enabling auto-trigger**, not about leaving the file's own correctness broken. `changelog.md`/`tasklist.md` are similarly untouched (`git diff 73fac00..HEAD --stat -- changelog.md tasklist.md` → empty) despite `CLAUDE.md:11`'s explicit house rule ("After any task → update changelog.md + mark items in tasklist.md") — DoD item 15 fails outright.

**Fix (for Dave, small/mechanical):** update the 3 lines above; separately, someone should update `changelog.md`/`tasklist.md` before merge per house rule.

---

### 🟡 CHRIS-08 (Medium, sharpens an already-flagged gap) — yfinance 1.4.1 pulls in `curl_cffi` (TLS-impersonation transport) as a *mandatory*, not optional, dependency

**Evidence (own-run):**
```
$ pip show curl_cffi
Name: curl_cffi  Version: 0.16.3
$ grep -n curl_cffi backend/requirements.txt   → (no match — never explicitly pinned)
$ pip show yfinance | grep Requires
Requires: beautifulsoup4, curl_cffi, multitasking, numpy, pandas, peewee, ...
```
`01-sara-adr-migration.md §2.1` states: *"keep `curl_cffi` OUT of requirements (1.4.0 falls back to requests) — avoids new build deps."* This is incorrect: `curl_cffi` is yfinance 1.4.1's own **hard** `Requires`, pulled in transitively regardless of whether it's listed in `backend/requirements.txt`. A live call (`yf.Ticker('AAPL').info`) confirms yfinance 1.4.1 actively attempts a `curl_cffi` TLS-fingerprint-impersonation request (`impersonate=...`) to `fc.yahoo.com`, not a plain `requests` call — a materially different HTTP transport/TLS-fingerprint than 0.2.65 presumably used, which Yahoo's anti-bot layer treats differently.

Dave's WP-B0/B3 characterization method (attribute/signature existence diffing, not live calls — network was blocked in his sandbox too, same as mine) **cannot** detect this class of behavioral risk by design — it was never designed to. Dave already flagged the live-verification gap honestly ("live-Yahoo-data round-trip... NOT and should not be assumed green" — `10-dave-backend-b0-b5.md`). This finding doesn't contradict that; it makes the *specific mechanism* concrete (transport/TLS-fingerprint change, not just "couldn't test") and corrects Sara's stated mitigation, which was factually wrong about curl_cffi being avoidable.

**Not blocking on its own** (already an open item, correctly flagged for Quinn/live-stack verification) but should be a named pre-deploy gate item, not merely "flagged."

---

### 🟡 CHRIS-09 (Medium) — S-AC-10 fix (JWT default-secret boot-fail) has a narrow blind spot

`core/config.py:31` only raises when `jwt_secret_key` exactly equals the ONE hardcoded string `"dev-secret-key-change-in-prod"`. `.env.example:17` ships a **different** placeholder (`change-me-with-openssl-rand-hex-32`) — equally public, equally "default-looking," and **not** caught by the exact-match check. Someone who copies `.env.example` verbatim into a prod `.env` without rotating it boots cleanly with a known-guessable secret — exactly the scenario SEC-4 was written to close, only half-closed.

**Fix suggestion (not applied by Chris):** also reject if the value equals `.env.example`'s placeholder, or better, check for low-entropy/known-placeholder patterns generally.

---

### 🟡 CHRIS-10 (Medium) — AC-A2 not satisfied: duplicate `/portfolio` router registration still undocumented

`api/routes/portfolio.py` and `api/routes/portfolio_performance.py` both still declare `APIRouter(prefix="/portfolio", ...)` and are both mounted separately in `main.py:291-292`. AC-A2 (`02-bella-brd-ac.md` Story A2) required *either* a merge *or* "a comment cross-referencing each other." Grepped both files — **zero cross-reference comment exists in either**. Not a functional bug (FastAPI resolves it fine, no collision — confirmed no startup warning), but an explicit, named AC left unaddressed.

---

### 🟡 CHRIS-11 (Medium) — AC-D2 not satisfied: rate-limiter docstring still contradicts the code

`api/middleware/rate_limit.py:11` still reads *"Limits: guest=30/min, user=120/min (enforced at route level via dependency)"* — unchanged from baseline. AC-D2 (`02-bella-brd-ac.md` Story D2) required either implementing that claim or correcting the docstring to state only the login/google path is limited. Neither happened; the file was touched twice this branch (S1 re-point, S2 re-point again) without ever fixing the one-line docstring lie Sentinel named explicitly.

---

### 🟡 CHRIS-12 (Medium) — AC-B7 not satisfied: `health.spec.ts` assertion was never fixed

**Evidence:** `tests/e2e/health.spec.ts:12` still reads `expect(body).toHaveProperty('status', 'ok')`. Own-run curl confirms the real body has **no top-level `status` key**: `{"data":{"database":"ok","redis":"ok","celery":"fail"},"meta":{...}}`. This is the exact mismatch Bella's Finding F2/AC-B7 named for fixing ("either the test is corrected to check `body.data.database`... or the endpoint adds a top-level `status` field — pick one"). Dave's WP-S2 log describes updating `health.spec.ts`'s **path literals** but the file needed zero path changes (health stays at `/api/health`) — the actual required fix (the assertion itself) was never touched. This test will fail the moment it's run against a live stack (Playwright, Quinn's territory) — flagging here since it's a Chris-observable static defect, not requiring a live run to prove.

---

### 🟡 CHRIS-13 (Medium) — mypy error count regressed 120→133 since the last-reported checkpoint, unnoticed

**Evidence (own-run):** `mypy backend/api backend/core --ignore-missing-imports` on final HEAD → **133 errors in 17 files**, vs Dave-backend's WP-B5 checkpoint of "120 errors in 16 files" (`10-dave-backend-b0-b5.md`). The 13-error increase happened during WP-S1–S3 (auth removal, envelope, stocks-split-v1-flip, JS→TS) — nobody re-ran mypy after B5; Dave-serial's log never mentions it. One genuinely new error is in the migration's own new code:
```
backend/schemas/envelope.py:85: error: Argument 1 to "loads" has incompatible type
  "bytes | memoryview[int]"; expected "str | bytes | bytearray"  [arg-type]
```
(`json.loads(response.body)` — Starlette's `Response.body` type stub allows `memoryview`, which `json.loads` doesn't accept; in practice `response.body` is `bytes` for the handlers this wraps, so likely a non-issue at runtime, but it's a real, new type-checker regression that should be captured in whatever "final" mypy number gets reported for this branch.)

---

### 🔵 CHRIS-14 (Low) — `VITE_API_URL` build arg stuck at stale `/api`, likely-vestigial

`docker-compose.dev.yml:165` / `docker-compose.prod.yml:139` set `VITE_API_URL: /api`, used in `vite.config.ts:7,27,30,47` as a **proxy target** (expects a host URL like `http://backend:8000`, not a path). This predates and is unrelated to the `/api` → `/api/v1` path flip specifically, and appears to only matter for Nitro's dev-server-side proxy (the browser's own axios calls hit `/api/v1/*` directly via Caddy in all deployed topologies, bypassing this proxy). Likely dead/vestigial, but nobody revisited it during the r3 path change either. Flag for cleanup, not a merge blocker.

---

### 🔵 CHRIS-15 (Low, informational) — Dave-frontend's devtools version correction is correct and well-evidenced

`@tanstack/react-router-devtools` pinned to `1.167.1` instead of Sara's targeted `1.170.32` — Dave-frontend's own WP-F0 log documents the registry `ETARGET` error and the correct dist-tag lookup. Verified: `npm view @tanstack/react-router-devtools dist-tags` behavior matches the claim structurally (not re-queried live, offline-verifiable from the log's pasted npm output). No action needed — noted for completeness only.

---

## AC coverage matrix (33 total)

| AC | Verdict | Evidence pointer |
|---|---|---|
| M1 (backend/tests no regression) | 🟡 PARTIAL | `backend/tests` reproducible 104p/2skip/37deselect (own-run) — PASS in isolation; `tests/api` gate not soundly measurable, see CHRIS-01 |
| M2 (frontend+docker build green) | 🔴 FAIL | frontend build PASS (own-run); Docker build **never verified by anyone** this whole engagement (no daemon anywhere) |
| M3 (TS7 spike) | ✅ PASS | own-run `npm run typecheck` → 1 whitelisted error only, matches Dave's claim |
| M4 (yfinance breaking-change map) | ✅ PASS | Dave's 13-call-site map + own module-import smoke; see CHRIS-08 caveat (non-blocking) |
| M5 (pytest-asyncio conftest rewrite) | 🔴 FAIL | CHRIS-01 — only half the files fixed |
| M6 (golden fixture characterization) | ✅ PASS | reasonable substitute method given sandboxed network, documented honestly |
| M7 (redis pub/sub smoke) | ✅ PASS | Dave's live B4 test + own code check (`DefaultParser = _AsyncRESP3Parser` confirms RESP3-by-default claim) |
| A1 (pydantic model_config ×8) | ✅ PASS | own-run: 0 `class Config:`, 0 deprecation warnings under `-W error` |
| A2 (portfolio duplicate router doc) | 🔴 FAIL | CHRIS-10 |
| A3 (stocks split ordering) | ✅ PASS | own-run curl: `/api/v1/stocks/quotes` hits batch handler, not shadow-matched |
| A4 (JS→TS annotation-only) | ✅ PASS | own-run `git diff -M` on authStore.ts/api.ts — clean, type-only diffs |
| B1-r3 (envelope + baseURL flip) | ✅ PASS | own-run curl: all 12 v1 modules enveloped; `api.ts:18` baseURL `/api/v1` confirmed |
| B2-r3 (literal inventory, one commit) | ✅ PASS | spot-checked, Dave's accounting is detailed and traceable |
| B3 (OpenAPI diff) | 🔴 FAIL | CHRIS-06 — snapshot doesn't reflect runtime contract |
| B4-r3 (error envelope, no legacy .detail) | 🔴 FAIL | CHRIS-02 — rate-limit path breaks this |
| B5 (stocks split, no collision) | ✅ PASS | own-run + Dave's OpenAPI dict-equality proof |
| B6 (rate-limit/401 preserved) | 🔴 FAIL | CHRIS-02/03; 401 header itself (`WWW-Authenticate: Bearer`) verified correct |
| B7 (health e2e test fixed) | 🔴 FAIL | CHRIS-12 |
| B8 (WS contract unchanged) | 🟢 N/A (Chris) | main.py:293 route unchanged by inspection; live WS smoke = Quinn's territory |
| B9 (3 unversioned exceptions) | ✅ PASS | own-run curl: `/api/health` unaffected, correctly un-enveloped on error path |
| C1 (pure-read cache-only) | ✅ PASS | not touched by diff, inspected unchanged |
| C2 (P95 preserved) | 🔴 FAIL | no measured baseline/post evidence exists anywhere in the engagement |
| C3 (cache TTL preserved) | ✅ PASS | own-run: `tests/api/test_pr2_cache_spec.py` 67 passed |
| D1 (pip-audit/npm audit clean) | ✅ PASS | own-run both, 0 vulnerabilities each |
| D2 (rate-limit docstring reconciled) | 🔴 FAIL | CHRIS-11 |
| D3 (CORS whitelist) | ✅ PASS | unchanged, inspected |
| D4 (non-root containers) | ✅ PASS | own-run: both Dockerfiles have `USER` non-root |
| D5 (admin → require_admin) | ✅ PASS | own-run curl (403/401) + new unit test, 5/5 pass + mutation-killed |
| D6 (secrets handling) | ✅ PASS | no secret-shaped strings in diff |
| D7 (password routes removed) | ✅ PASS | own-run: routes gone from auth.py, confirmed |
| D8 (Google/JWT preserved) | ✅ PASS | own-run curl: `/me`, `/google` functional |
| D9 (test infra rewired) | 🟡 PARTIAL | narrow AC wording (auth_headers rewire) done; broader infra still broken, see CHRIS-01/04 |
| D10 (docs synced) | ✅ PASS | CLAUDE.md already reflects ADR-007 |

**21 PASS / 10 FAIL / 2 N/A(Chris)/PARTIAL-counted-as-fail-for-tally** (M1, D9 counted PARTIAL, not in either PASS/FAIL bucket above — treat as FAIL for merge-gate purposes since neither is soundly provable today).

## DoD status (16 items, Chris-observable subset)

| # | Item | Status |
|---|---|---|
| 1 | Backend suite paste, ≥107/≥116 | 🔴 FAIL — `backend/tests` reproducible PASS; `tests/api` not (CHRIS-01) |
| 2 | Frontend build green Node24 | ✅ PASS (own-run) |
| 3 | Both Docker images build | 🔴 FAIL — never run by anyone this engagement |
| 4 | Stack boots + healthchecks | 🔴 FAIL — no `docker compose up` ever run |
| 5 | OpenAPI snapshot diff | 🔴 FAIL — CHRIS-06, snapshot is wrong |
| 6 | pip-audit + npm audit clean | ✅ PASS (own-run) |
| 7 | TS7/TanStack spike result | ✅ PASS (own-run) |
| 8 | yfinance breaking-change map | ✅ PASS (CHRIS-08 caveat, non-blocking) |
| 9 | pytest-asyncio conftest rewrite | 🔴 FAIL — CHRIS-01 |
| 10 | Pydantic v1-config cleanup | ✅ PASS (own-run) |
| 11 | Rate-limit/auth/CORS/non-root curls | 🔴 FAIL — rate-limit specifically (CHRIS-02/03); rest PASS |
| 12 | Admin authorization decision | 🟡 PARTIAL — logic correct, test now added by Chris |
| 13 | Envelope policy documented | 🟡 PARTIAL — documented, but OpenAPI contradicts it (CHRIS-06) |
| 14 | E2E suite run live | N/A (Quinn) |
| 15 | changelog.md/tasklist.md updated | 🔴 FAIL — zero diff, confirmed |
| 16 | CI trigger not touched | ✅ PASS (literal wording) — but see CHRIS-07 for the file's actual brokenness |

---

## 7-dim scores (1-5, 5=excellent)

| Dim | Score | Note |
|---|---|---|
| Correctness | 3 | Core mechanism (envelope, admin authz, pydantic) correct; rate-limit path genuinely broken (CHRIS-02/03) |
| Security | 3 | admin/JWT/pip-audit/CORS solid; rate-limit bypass (CHRIS-03) is a real regression against Sentinel's own named AC |
| SOLID/Design | 4 | envelope's single-choke-point design (route_class + one axios interceptor) is clean; route_class-doesn't-inherit gotcha handled correctly |
| Performance | N/A | not this review's scope beyond C1-C3 (PASS/FAIL above); no new perf regression found in static review |
| Maintainability | 3 | good inline evidence-citing comments throughout Dave's new code; but ci.yml/changelog/A2/D2 loose ends left dangling |
| Testing | 2 | zero tests existed for envelope/admin-authz/rate-limit/pagination before this review (now added); pre-existing test infra (CHRIS-01/04/05) actively hostile to writing more |
| Observability | 3 | request_id propagation solid; SEC-10 (celery-stats error leak, unauth) still open, tracked not fixed (in-scope-cheap per Sentinel, not done this branch — flag, not new finding, Sentinel already owns it) |

---

## Tests added (this review, Phase 3b)

| File | Tests | Own-run result (isolated per-test) |
|---|---|---|
| `tests/api/test_pr4_envelope.py` | 8 | **8/8 PASS** — envelope.py logic confirmed correct |
| `tests/api/test_admin_authz.py` | 7 | 1/7 PASS in isolation; 6/7 blocked by CHRIS-04 (pre-existing infra bug), NOT by admin-authz logic defects (logic separately proven via `test_require_admin_unit.py`) |
| `tests/api/test_rate_limit_middleware.py` | 2 | **0/2 PASS — both intentionally fail**, proving CHRIS-02 and CHRIS-03 |
| `tests/api/test_stocks_pagination.py` | 3 | **3/3 PASS** — ADR-004 pagination meta confirmed correct |
| `backend/tests/test_require_admin_unit.py` | 5 | **5/5 PASS** — pure-unit, DB/infra-independent, proves `require_admin`/`require_role` logic is correct |

**Total: 25 new tests. 17 pass, 8 fail/error (6 due to pre-existing infra bug CHRIS-04, 2 intentionally proving live regressions CHRIS-02/03).**

## Mutation sanity (3/3 killed — 100%)

| # | Target | Mutation | Result |
|---|---|---|---|
| 1 | `api/middleware/auth.py:73` `require_role`'s `_check_role` | `if user.role not in roles` → `if user.role in roles` (inverted) | `backend/tests/test_require_admin_unit.py` — **5/5 tests failed** (caught) |
| 2 | `schemas/envelope.py:55` `_is_enveloped_path` | `"/api/v1/"` → `"/api/v2/"` | `tests/api/test_pr4_envelope.py::TestErrorEnvelopeOnV1` — **4/4 tests failed** (caught) |
| 3 | `api/routes/stocks/fundamentals.py:142` earnings pagination slice | `data[offset:offset+limit]` → `data[offset:]` (dropped limit) | `tests/api/test_stocks_pagination.py::test_pagination_meta_reflects_requested_window` — **failed** (caught) |

All 3 mutations reverted immediately after proof (confirmed `git diff` clean on all 3 production files before commit).

---

## Praise (things done well)

- The envelope's design — single `route_class` wrap point + single axios unwrap point — is genuinely clean architecture, and Dave's discovery/documentation of the "route_class doesn't inherit to included child routers" FastAPI gotcha (verified independently, matches FastAPI 0.141.1 behavior) shows real diligence, not guessing.
- The admin-authz fix (`require_admin` on all 3 endpoints) is correct and matches Sentinel's AB-1 threat exactly — I found zero logic defects in it after direct unit-testing.
- Dave's honesty about open items (live-Yahoo round-trip unverified, OpenAPI staleness, Dockerfile.dev gap later closed by S0) throughout the WP logs made this review faster and more trustworthy than logs that claim blanket success — this is the right pattern and should be recognized as such.
- Pydantic v1→v2 config cleanup (8/8 sites) and the dependency version matrix execution (pip-audit/npm audit both 0 vulnerabilities, verified independently) are clean, complete work.
- Uma's Phase 3a visual/a11y gate (0.0029% max pixel diff, zero new axe violations) is exactly the standard this discipline expects — I did not need to re-verify frontend visual/UI evidence per the split-scope rule, and didn't.

---

## Action items (route per severity)

**Block merge (fix before merge, Dave, Phase 2):**
- CHRIS-01 — `tests/api/conftest.py` pytest-asyncio 1.x rewrite (delete `event_loop` fixture, add ini scope)
- CHRIS-02 — rate-limit 429 handling (move to dependency or catch-and-return-JSONResponse)
- CHRIS-03 — rate-limit IP-trust validation (trusted-proxy allowlist)
- CHRIS-06 — OpenAPI contract mismatch (fix response_models or regenerate the artifact honestly)
- CHRIS-07 — `ci.yml` 3-line reconciliation + changelog.md/tasklist.md updates (DoD 15/16 house rule)

**Fix soon (track, next bd iteration acceptable):**
- CHRIS-04 — `tests/api/conftest.py` StaticPool fix (pre-existing, but now blocking test-writing obligations)
- CHRIS-05 — `hash_password()`/passlib-bcrypt incompatibility (pre-existing, severe, needs its own bd — replace passlib with direct bcrypt calls)
- CHRIS-08 — curl_cffi transport-change verification before prod deploy (live-stack gate, Quinn/Oliver)
- CHRIS-09/10/11/12/13 — narrow AC gaps (S-AC-10 blind spot, AC-A2, AC-D2, AC-B7, mypy delta)

**Optional/defer:**
- CHRIS-14 (VITE_API_URL stale value), CHRIS-15 (informational, no action)

**Spec/AC issues → Phase 1a (Bella+Sara):** none found requiring spec revision — all findings are implementation gaps against already-correct, already-decided ACs.

---

## Evidence artifacts

- Own-run test/curl transcripts: inline above (not separately filed — all reproducible via the commands shown)
- New test files: `tests/api/test_pr4_envelope.py`, `tests/api/test_admin_authz.py`, `tests/api/test_rate_limit_middleware.py`, `tests/api/test_stocks_pagination.py`, `backend/tests/test_require_admin_unit.py`
- OpenAPI mismatch raw capture: reproducible via `curl -s http://<host>/openapi.json` against a live boot (not filed as a static artifact — the file is auto-generated per-boot and identical every time given identical code)

## Standards axis summary

10 High-or-above findings, 7 Medium, 2 Low. Worst: CHRIS-01 (Critical) — non-reproducible test suite undermines the entire migration's regression-detection claim.
