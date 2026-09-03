# 05 — Sentinel Threat Model: deps-2026-09 (Phase 1c)

bd: deps-2026-09 · iter 0 · author: Sentinel (SEC) · date 2026-09-03 · repo @ `73fac00` (read-only)
Inputs: 00-oliver-discover.md · 04-oliver-user-decisions.md · 01-sara-adr-migration.md (ADR-007 § r2, ADR-001 final § r3) · 02-bella-brd-ac.md (D1–D10)
Method: STRIDE per `secure` skill; all claims cite `file:line` or pasted tool output (NO MAGIC).

> **AI Persona Disclaimer**: security review by AI agent — findings evidence-backed, but pen test ต่อ live stack ยังไม่เกิด (Phase 3b). CVSS ไม่ประเมินเพราะไม่มี advisory detail per PYSEC id ใน output — ใช้ severity schema ของ review-checklist แทน.

---

## 0. Asset inventory + trust boundaries (post-change surface)

| Asset | Sensitivity | Evidence |
|---|---|---|
| JWT access token (HS256, 8h) | H | core/security.py:24-31, core/config.py:20-21 |
| `JWT_SECRET_KEY` | H | core/config.py:19, docker-compose.ghcr.yml:51 (env-only, no default in prod compose) |
| User data (watchlist/portfolio/alerts/notes/drawings) — money-adjacent (transactions) | H | models per routes §2 below |
| OHLCV/quote data + retention policy (destructible via housekeeping) | M | admin.py:19,105; workers/housekeeping |
| Google ID token (transit only) | H | auth.py:98-106 |
| Redis (cache + broker + pub/sub, no AUTH) | M | core/config.py:16 `redis://redis:6379/0`; not port-exposed (docker-compose.ghcr.yml:161-163 — only Caddy 80/443) |

Trust boundaries: Internet → Caddy (`caddy/Caddyfile:5-63`) → backend:8000 / frontend:3000 (Docker network, semi-trusted) → PG/Redis (trusted tier). External data ingress: Yahoo (workers), Google news RSS (news_fetcher.py:64-66 hardcoded host), SEC/Finnomena (fund_fetcher.py:35-40), Google OAuth certs (auth.py:98).

---

## 1. STRIDE — post-change surface

### 1.1 Auth (what remains after ADR-007: `/google` + `/me` + `/config`, JWT access only)

- **Google verify path**: `id_token.verify_oauth2_token(credential, ..., settings.google_client_id, clock_skew_in_seconds=60)` in executor + 5s timeout (auth.py:94-106); requires `email_verified` claim (auth.py:126). Audience pinned to client_id ✓. **S: mitigated.**
- **JWT**: HS256 pinned list `algorithms=[settings.jwt_algorithm]` (core/security.py:47-49) — no `alg:none` confusion ✓; `type=access` check :50. Refresh removal (ADR-007) ⇒ session = 8h access token (config.py:21), **no server-side revocation of access tokens** (stateless; pre-existing). Net effect = **surface reduction**: 30-day refresh tokens (localStorage, authStore.js:73) หายไป → XSS-stolen-token impact ลดจาก 30d silent renewal เหลือ ≤8h. **Sentinel confirms Sara r3 interpretation (01-sara § r2-3)**: เก็บ access JWT + attach `Authorization: Bearer` (api.js:18-24) = minimum ที่จำเป็น ไม่ขัด CLAUDE.md L17 ("no custom token management" = no refresh lifecycle) — CONFIRMED.
- 🔴 **SEC-4 (Medium)** — `jwt_secret_key` default `"dev-secret-key-change-in-prod"` ผ่าน validator ด้วย **warning เท่านั้น** (core/config.py:24-36 — raise เฉพาะ len<16; default ยาว 30 ตัว → ผ่าน) ⇒ ตั้งค่า default ใน prod ได้โดย boot สำเร็จ. prod/ghcr compose ไม่มี default (`${JWT_SECRET_KEY}` prod.yml:40, ghcr.yml:51 — unset ⇒ "" ⇒ ValueError ✓) แต่ copy ค่า dev ไปใส่ .env prod = เงียบ. Fix: raise เมื่อ `is_production` + default value (1 บรรทัด, sub-scope d).
- 🟡 **SEC-9 (Low)** — `/me` fast path ตอบ identity จาก JWT payload ล้วน ไม่เช็ก DB `is_active` (auth.py:242-252); protected routes อื่นเช็กผ่าน `get_current_user` DB query (middleware/auth.py:42) ✓ ⇒ user ถูก disable ยังเรียก `/me` ได้ ≤8h (display เท่านั้น, ไม่ใช่ authz). Track.
- **S (open registration)**: `/google` **auto-creates user สำหรับทุก Google account ที่ email_verified** (auth.py:139-147, role default `user` — models/user.py:21-22) — ไม่มี allowlist. ดู abuse chain AB-1 §4.

### 1.2 Authz — admin + ownership sweep

- 🔴 **SEC-1 (High)** — admin.py:14 import เฉพาะ `get_current_user`; ใช้ที่ :47, :84, :115. `require_admin` (middleware/auth.py:82) ไม่มี route ใดใช้ (grep ยืนยันตาม Sara CR-5). Amplifier ที่ Sara ยังไม่ได้บันทึก: `PUT /retention-policy` validate แค่ resolution whitelist + `max_age_days >= 1` (admin.py:90-98, **ไม่มี upper bound ไม่จำเป็น แต่ lower bound 1 วัน = destructive**) แล้ว `POST /run-now` trigger housekeeping ทันที (admin.py:119-120) ⇒ authenticated non-admin ตั้ง `{"1d", 1}` + run-now = **ลบ daily bars เก่ากว่า 1 วัน (นโยบาย default เก็บ 730 วัน — admin.py:25) = data loss จริง**. รวมกับ open registration (§1.1) ⇒ chain ระดับ internet-reachable (AB-1). Fix = AC-D5 (`Depends(require_admin)` ×3) — in-scope Phase 2 branch นี้ per Sara CR-5; S-AC-1 gates ด้วย test.
- **Ownership sweep — PASS**: ทุก user-data route scope ด้วย `user_id == user.id`:
  watchlist.py:23,53,75,92,131,153 · portfolio.py:39,53,206,239,261 · portfolio_performance.py:35 · alerts.py:51,64,87,106,122 · notes.py:37,61,67,87 · drawings.py:24,42,64,85. ไม่พบ IDOR ใน HTTP surface. Envelope/prefix refactor (r3) ห้ามหลุด `Depends` เหล่านี้ — S-AC-2.

### 1.3 Middleware

- 🔴 **SEC-2 (High, DoS on new critical path)** — rate_limit.py keying สองปัญหา:
  (a) **Path literal**: จำกัดเฉพาะ `request.url.path == "/api/auth/login"` (rate_limit.py:30). Post-ADR-007 `/login` ถูกลบ + post-r3 prefix เปลี่ยน ⇒ ถ้าไม่ re-point limiter คุ้มครอง **ศูนย์ endpoint** เงียบ ๆ. Sara r3-2 สั่ง re-point `/api/v1/auth/google` แล้ว — S-AC-3 gates ด้วย test (Bella B6 ยังไม่มี test สำหรับ 429 — 02-bella RTM B6 "NEW").
  (b) **Key = `request.client.host`** (rate_limit.py:31) แต่ gunicorn รันโดยไม่มี `--forwarded-allow-ips`/proxy-headers (docker-compose.prod.yml:65 `gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000`) และ Caddy ส่ง `X-Forwarded-For` มา (Caddyfile:47) ซึ่ง backend **ไม่อ่าน** ⇒ ทุก client เห็นเป็น IP ของ Caddy container = **bucket เดียวทั้งระบบ**. Post-change `/google` คือ auth path เดียว ⇒ attacker ยิง 5 request เปล่า ๆ = **ล็อกทุกคนออกจากระบบ 15 นาที วนได้ไม่จำกัด, unauthenticated**. Fix Phase 2: trust XFF จาก Caddy (uvicorn-worker `--forwarded-allow-ips` = Docker subnet หรืออ่าน XFF ใน middleware โดย trust เฉพาะ hop เดียว) — S-AC-4.
- 🟡 **SEC-11 (Low)** — request_id.py:32-35 รับ `X-Request-ID` จาก client โดยไม่ validate format/length → structlog field injection surface (JSONRenderer escape ให้; header ผ่าน h11 ห้าม CR/LF อยู่แล้ว). แนะ cap 64 chars + charset check. Track.
- CORS: whitelist จาก env (main.py:258-265, config.py:48 default `http://localhost:5173`), `allow_credentials=True` + explicit origins ✓ — Bella D3 ครอบแล้ว.

### 1.4 Error envelope (ADR-002 v1) — info disclosure

- ปัจจุบันสะอาด: ไม่มี `detail=...{e}` pattern ใน routes ([output: Grep `detail=f?".*{(e|exc|err)` backend → no matches]); FastAPI app ไม่ได้เปิด debug (main.py:245-252 ไม่ส่ง debug param ⇒ Starlette default no-traceback); SSE error เป็น generic ไทย (ai_chat.py:400-406, fix 91db563 ยังอยู่ ✓).
- 🟡 **SEC-10 (Low)** — `GET /system/celery-stats` (unauth) ตอบ `"last_error": str(e)[:500]` + internal task error strings จาก Redis (system.py:205,213,222) = internal error text ต่อ unauthenticated caller. แนะ: ใส่ `require_admin` หรือ redact ตอน system.py ย้ายเข้า v1 (r3-2 ย้ายอยู่แล้ว — จุดแก้ถูกจับต้องพอดี). Track/in-branch cheap.
- Envelope flip เป็นจุดเสี่ยง regression: error block ใหม่ (schema ใน openapi.yaml ของ Sara) **ห้าม** มี exception class / traceback / SQL / path — S-AC-5 (testable grep บน response).

### 1.5 WS `/api/ws/prices` + SSE

- **WS ไม่มี auth ฝั่ง server เลย** — `websocket_prices` accept ทุก connection (main.py:293-296); ไม่มี token ใน query/header. Frontend gate ฝั่ง client เท่านั้น (`if (!token || !user?.id) return` — useWebSocket.ts:28) = ไม่ใช่ control. ตอบคำถาม Oliver: **ไม่มี ws auth via query token — cite main.py:294, useWebSocket.ts:28**.
- 🟡 **SEC-3 (Medium)** — `alert_triggered` ถูก `broadcast_all` ไปยัง **ทุก** WS client รวม unauthenticated (main.py:144-146); payload มี `symbol`, `condition` (type+value), `price`, `alert_id` ของ user เจ้าของ alert (alert_checker.py:62-69) = info disclosure ข้าม user + LINDDUN-D (detectability ของ trading intent). บวก: ไม่มี cap จำนวน connection/subscription ต่อ client (main.py:66-77) = memory DoS surface. WS อยู่นอก change surface (r3-1 freeze path) ⇒ **แนะ separate bd** (fix = per-user WS auth + targeted alert delivery + subscription cap), ไม่ gate branch นี้; branch นี้แค่ห้าม regress (AC-B8).
- SSE `/api/ai/*`: unversioned per r3-1; error generic ✓; `Cache-Control: no-cache` ✓ (ai_chat.py:411).

### 1.6 Security headers (caddy/Caddyfile — new droplet path)

- มีแล้ว: HSTS preload, nosniff, X-Frame-Options DENY, Referrer-Policy, `-Server` (Caddyfile:8-14) ✓.
- 🟡 **SEC-8 (Medium)** — 3 ประเด็น:
  1. `X-XSS-Protection "1; mode=block"` (Caddyfile:11) = deprecated header มีช่องโหว่ของตัวเอง — **remove** (กติกา Sentinel: ห้ามใช้).
  2. CSP (Caddyfile:13) มี `script-src 'unsafe-inline' 'unsafe-eval'` — อ่อนจน XSS ป้องกันไม่ได้จริง และทำให้ access token ใน localStorage (ยังอยู่หลัง ADR-007) steal ได้.
  3. CSP **ไม่มี `https://accounts.google.com`** ใน script-src/frame-src/connect-src — Google One Tap (GSI) โหลด script+iframe จาก host นั้น; `default-src 'self'` จะ block ⇒ branch นี้ทำให้ Google เป็น auth path เดียว = **ต้อง verify ว่า login ยังทำงานใต้ header ชุดนี้บน live stack** (Phase 3b evidence: screenshot + console ไม่มี CSP violation). หมายเหตุ: old shared droplet ใช้ Caddy ของ ShoDe Town (CLAUDE.md) — header ชุดนั้นอยู่นอก repo.
  Fix แนะนำ: X-XSS-Protection ลบ + เติม GSI origins = in-branch (2 บรรทัด, sub-scope d); CSP nonce/strict-dynamic rework = **separate bd** (report-only 2 สัปดาห์ก่อน enforce ตาม `secure` skill — ห้ามข้ามขั้น).
- Backend image non-root ✓ (backend/Dockerfile:19-20,34 `USER stockviz`) — Bella D4 backend ok; frontend Dockerfile ให้ Aaron/Quinn เช็กใน D4 ตามเดิม.

### 1.7 Redis 8 / RESP3 (security angle เท่านั้น — perf/compat เป็นของ Sara §2.2)

- Redis ไม่มี AUTH (config.py:16) — ยอมรับได้เพราะ network-internal เท่านั้น (ghcr.yml expose แค่ Caddy 80/443). Pre-existing, no change on branch. Track เป็น hardening backlog (Low).
- Pub/sub bridge (main.py:125-133) เป็น internal-trusted producer (workers) — ไม่มี untrusted input path ใหม่จาก RESP3. No new threat; AC-M7 (Bella) ครอบ functional smoke แล้ว.

---

## 2. Dependency supply chain (tool output — current pins @73fac00)

### 2.1 pip-audit (venv py3.13, `pip-audit -r backend/requirements.txt --no-deps --disable-pip`)

```
Found 16 known vulnerabilities in 4 packages
pyjwt            2.10.1  PYSEC-2026-120/175/176/177/178/179, PYSEC-2025-183   Fix ≤2.13.0
python-multipart 0.0.20  PYSEC-2026-1852/3036/3037/3038/3039/3040             Fix ≤0.0.31
requests         2.32.3  PYSEC-2026-1872/2275                                 Fix ≤2.33.0
pytest           8.3.5   PYSEC-2026-1845                                      Fix 9.0.3
```
- **PyJWT 2.10.1 = 7 advisories บน auth path ที่รันอยู่ prod ตอนนี้** — target ≥2.13 (01-sara §1.3) ปิดครบ ✓. เพิ่มน้ำหนักให้ migration ไม่ใช่แค่ hygiene.
- python-multipart target ≥0.0.32 ✓ · requests ≥2.34 ✓ ปิดครบ.
- ⚠️ **pytest caveat**: fix อยู่ที่ 9.0.3; Sara CR-3 มี fallback hold `pytest==8.4.*` ถ้า resolver ชน — 8.4.x **ยังติด PYSEC-2026-1845** และ backend/Dockerfile:13-14 ติดตั้ง requirements.txt ทั้งไฟล์ลง **prod image** (pytest/pip-audit ship ไป prod ด้วย) ⇒ ถ้า hold 8.4 ต้องบันทึก accept-risk ใน lock commit (exploitability ต่ำ — test tool ไม่อยู่ใน request path) หรือแยก requirements-dev.txt (แนะ, แต่เป็น R2 ให้ Stan ตัดสิน scope). S-AC-6.
- **Dave MUST re-run pip-audit บน resolved lock ใหม่** (N7 ของ Sara) — transitive deps ยังไม่ถูก audit ที่นี่ (`--no-deps`).

### 2.2 npm audit (frontend, Node 22 host)

```
npm audit --omit=dev : 20 vulnerabilities (2 low, 6 moderate, 11 high, 1 critical)
npm audit (full)     : 23 (2 low, 7 moderate, 11 high, 3 critical)
```
Prod-relevant critical/high (from `npm audit --omit=dev --json`):
- **critical seroval ≤1.5.2** (fromJSON type confusion) — transitive via TanStack SSR serialization
- high **axios 1.0.0–1.17.0** (SSRF NO_PROXY bypass + prototype-pollution auth bypass) → target **1.20.0** ปิด ✓
- high **vite 7.0.0–7.3.3** (dev-server file read ×3 — dev-time exposure) → Vite 8.2.2 ปิด ✓
- high **h3 2.0.0-beta–rc.17** (path traversal serveStatic, SSE injection) — **nitro runtime dep = SSR server จริงบน prod** → ต้อง verify version ที่ nitro `3.0.260610-beta` ดึงมา post-bump
- high undici / ws / nanoid / picomatch / postcss / js-yaml / browserslist / form-data — ส่วนใหญ่ transitive; คาดหมดหลัง bump แต่**ห้าม assume**
- critical vitest <3.2.6 (dev-only, ไม่ ship)

**Gate**: Dave re-run `npm audit --omit=dev` บน lock ใหม่; **zero critical/high ที่ unaddressed** = merge gate (ตรง Bella D1). S-AC-7.

### 2.3 nitro-nightly floating pin — CONFIRMED closed by Sara CR-2

- ปัจจุบัน: `"nitro": "npm:nitro-nightly@latest"` (frontend/package.json:25); lock resolve ค้างที่ `nitro-nightly-3.0.1-20260223-102354-c0b46421` ([output: node package-lock query]). ทุก re-install ที่ไม่ยึด lock = ดึง nightly ตัวใหม่ที่ไม่มีใคร review = unreviewable supply chain + ไม่มี provenance.
- Sara matrix: `"nitro": "3.0.260610-beta"` exact, ตัด `npm:` alias (01-sara §1.1 + CR-2) — **ปิดช่องนี้สมบูรณ์** ✓ เงื่อนไขเดียว: pin ต้อง **exact ไม่มี `^`/`~`** และ N8 (no floating deps) ตรวจ diff.

### 2.4 Secret scan

- gitleaks/trufflehog ไม่มีในเครื่องนี้ ([output: which → empty]) — รันได้เฉพาะ **pattern-scan lite**: `git grep -E "(AKIA…|PRIVATE KEY|ghp_…|xox…|AIza…)"` → **0 match**; ไม่มีไฟล์ `.env` ถูก track (git ls-files → `.env.example` เท่านั้น). **ไม่ใช่ substitute ของ gitleaks เต็ม (no entropy scan, no history scan)** — Dave/Aaron รัน gitleaks จริงใน Phase 2/3b บนเครื่อง Mac = S-AC-8. Honesty: นี่คือข้อจำกัด ไม่ใช่ PASS เต็ม.

### 2.5 External ingestion posture (yfinance 1.x / feedparser / SEC API)

- **SSRF fix 91db563 ยังอยู่ครบที่ HEAD**: fund_fetcher `_SAFE_SYMBOL_RE` + `url_quote(symbol, safe='')` (fund_fetcher.py:28-31,211,216-219 — `/` ถูก encode ⇒ path traversal ไม่ได้); on_demand_listener `_VALID_SYMBOL_RE` + validate (on_demand_listener.py:15,65) ✓. yfinance 0.2→1.4 ไม่เปลี่ยน trust model (Yahoo data = untrusted, shape gated ด้วย golden fixtures AC-M6) — invariant ที่ต้องคงไว้: **symbol validation ก่อนสร้าง URL/query ทุก provider call** = S-AC-9.
- feedparser 6.0.11 (requirements.txt:44) — ไม่ติด advisory ใน pip-audit run นี้; RSS host hardcode `news.google.com` + `quote_plus` บน query (news_fetcher.py:57-66) ⇒ no SSRF; frontend ไม่มี `dangerouslySetInnerHTML` ([output: Grep frontend/src → no matches]) ⇒ React escape ปิด XSS sink ของ news title.
- Cache poisoning via symbol case: mitigated — ทุก endpoint `.upper()` ก่อน key (stocks.py:110,165,258,317,361,428) + cache_keys single source (core/cache_keys.py docstring L4-9).

---

## 3. Security AC — S-series (inject เข้า AC set ของ Bella; Dave อ่านก่อน Phase 2)

| # | AC (testable) | Evidence gap ที่มา |
|---|---|---|
| **S-AC-1** | `GET/PUT/POST /api/v1/admin/*` ด้วย token role=user → **403** (ทั้ง 3 routes); ด้วย role=admin → 200. NEW test (ยังไม่มี — Bella RTM D5 "NEW") | admin.py:47,84,115 |
| **S-AC-2** | Post prefix-lift/envelope: ทุก route ใน §1.2 ownership list ยังมี `Depends(get_current_user)` + `user_id == user.id` filter — verified โดย diff review + existing authz tests ยัง pass; ไม่มี route ใดหลุด dependency ระหว่าง refactor | watchlist/portfolio/alerts/notes/drawings cites §1.2 |
| **S-AC-3** | `POST /api/v1/auth/google` ครั้งที่ 6 ภายใน 15 นาที (จาก client IP เดิม) → **429**; และ path เดิม `/api/auth/login` ไม่มี limiter อ้างถึงอีก (grep rate_limit.py) | rate_limit.py:30 |
| **S-AC-4** | Rate limiter key = **real client IP** หลัง Caddy: ยิงจาก 2 source IP (จำลองด้วย XFF ต่างกันผ่าน Caddy) → คนละ bucket; ยิงตรง backend ด้วย XFF ปลอม (ไม่ผ่าน Caddy) → **ไม่** trust header | rate_limit.py:31 + docker-compose.prod.yml:65 (no forwarded config) |
| **S-AC-5** | Error envelope ทุก 4xx/5xx บน `/api/v1/*`: body ไม่มี substring `Traceback`, exception class name (`Error:`, `Exception`), SQL fragment, หรือ filesystem path — asserted โดย test ยิง 422 + forced 500 | ADR-002 error block; ปัจจุบันสะอาด (§1.4) ห้าม regress |
| **S-AC-6** | ถ้า pytest hold ที่ 8.4.x (CR-3 fallback): lock commit message บันทึก PYSEC-2026-1845 accept-risk อย่าง explicit; ไม่งั้น pytest ≥9.0.3 | pip-audit output §2.1; backend/Dockerfile:13-14 |
| **S-AC-7** | บน lock/pins ใหม่: `pip-audit` (full, ไม่ใช่ --no-deps) + `npm audit --omit=dev` — **0 critical/high unaddressed**; findings ระดับ moderate ลง list triage ใน PR (ตรง Bella D1, เพิ่มความเข้มว่า full-deps) | §2.1-2.2 outputs |
| **S-AC-8** | gitleaks (หรือ trufflehog) รันบน branch diff + ไฟล์ใหม่ทั้งหมดก่อน merge → 0 finding, paste output (pattern-scan ของ Sentinel ไม่นับเป็น substitute) | §2.4 |
| **S-AC-9** | ทุก call site ใน yfinance adaptation (9 workers, AC-M4 map): symbol ผ่าน validation (`_VALID_SYMBOL_RE`-class) ก่อนถึง provider/URL — regression test สำหรับ fund_fetcher + on_demand_listener ยัง pass; ห้าม refactor ตัด validator ออก | fund_fetcher.py:211, on_demand_listener.py:65 |
| **S-AC-10** | `jwt_secret_key` validator: `is_production` + default value → **raise** (boot fail), พร้อม unit test | core/config.py:24-36 |
| **S-AC-11** | caddy/Caddyfile: ลบ `X-XSS-Protection` (:11); เติม `https://accounts.google.com` ใน `script-src`/`frame-src`/`connect-src` ของ CSP (:13); Phase 3b evidence = login ผ่าน Google One Tap บน live stack โดย **0 CSP violation ใน browser console** (screenshot + console paste) | Caddyfile:11,13 |

D-series ของ Bella (D1–D10) — Sentinel review แล้ว: ครอบถูกจุด, ไม่มีข้อขัด; S-series ข้างบนเป็น **ส่วนเพิ่ม** ไม่ทับซ้อน (S-AC-1 = test ที่ D5 ยังไม่มี, S-AC-3/4 = ช่องที่ B6 ไม่ครอบเพราะ B6 ไม่มี test อยู่แล้ว).

---

## 4. Abuse cases (trading/data domain)

| # | Anti-story | Verdict |
|---|---|---|
| **AB-1** | Attacker ที่มี Google account ใด ๆ → `POST /auth/google` auto-provision (auth.py:139-147) → เรียก `PUT /api/admin/retention-policy` `{"1d",1}` + `POST .../run-now` (get_current_user เท่านั้น) → **ลบ historical daily bars ~2 ปีบน prod** | 🔴 พิสูจน์ได้จาก code; ปิดด้วย S-AC-1 (require_admin). Residual: open registration ยังอยู่ — Open Q#1 |
| **AB-2** | Attacker unauthenticated ยิง `POST /api/v1/auth/google` เปล่า 5 ครั้ง → global rate bucket (Caddy IP) เต็ม → **ทุก user login ไม่ได้ 15 นาที** วนไม่จำกัด | 🔴 ยืนยันจาก rate_limit.py:31 + no proxy-header trust; ปิดด้วย S-AC-4 |
| **AB-3** | Attacker เปิด WS `/api/ws/prices` โดยไม่ auth → รับ `alert_triggered` ของ user อื่น (symbol/เงื่อนไข/ราคา = trading intent) + spam subscribe ไม่จำกัด | 🟡 SEC-3, separate bd |
| **AB-4** | SSRF via fund symbol → internal URL (`http://redis:6379`, metadata IP) | ✅ HOLDS — fix 91db563 verified at HEAD (§2.5) |
| **AB-5** | Cache poisoning via symbol case (`aapl` vs `AAPL` คนละ key → เสิร์ฟ stale/ปลอม) | ✅ mitigated — `.upper()` + cache_keys (§2.5) |
| **AB-6** | Rate-limit bypass via new prefix: limiter key on `/api/auth/login` แต่ traffic ไป `/api/v1/...` → limiter เป็น no-op เงียบ | 🔴 จะเกิดแน่ถ้า Dave ลืม — S-AC-3 gates |
| **AB-7** | Supply chain: nightly nitro publish ที่ compromised ถูกดึงเข้า build ถัดไป | ✅ closed by exact pin `3.0.260610-beta` (§2.3) + N8 |
| **AB-8** | XSS (จาก dep ใด ๆ) → ขโมย access token ใน localStorage | 🟡 residual ≤8h (ดีขึ้นจาก 30d หลัง ADR-007); CSP อ่อน (SEC-8) คือ enabler — CSP rework = separate bd |

---

## 5. Findings register + verdict per finding

| ID | Finding | Severity | Fix where |
|---|---|---|---|
| SEC-1 | admin.py authz gap + destructive retention amplifier (AB-1) | 🟠 **High** | Phase 2 branch นี้ (AC-D5 + S-AC-1) |
| SEC-2 | Rate limiter: global bucket behind Caddy + path literal จะตกยุค (AB-2, AB-6) | 🟠 **High** | Phase 2 branch นี้ (S-AC-3, S-AC-4) |
| SEC-5 | 16 pip vulns current pins (PyJWT×7 auth path) | 🟠 High (มีอยู่แล้วบน prod) | ปิดโดย bump เอง; gate S-AC-7 |
| SEC-6 | 20 npm prod vulns (1 critical seroval, 11 high) current pins | 🟠 High (มีอยู่แล้ว) | ปิดโดย bump; gate S-AC-7 re-run |
| SEC-7 | nitro-nightly@latest floating | 🟠 High → **closed** by Sara pin (verify N8) | Phase 2 (pin commit) |
| SEC-3 | WS: no auth, alert broadcast ข้าม user, no sub cap (AB-3) | 🟡 Medium | **separate bd** (WS นอก change surface r3-1); branch นี้แค่ no-regress |
| SEC-4 | JWT default secret = warning-only in prod | 🟡 Medium | Phase 2 branch นี้ (S-AC-10, 1 บรรทัด) |
| SEC-8 | X-XSS-Protection deprecated + CSP unsafe-inline/eval + GSI origins missing | 🟡 Medium | Split: S-AC-11 in-branch (ลบ header + เติม GSI origin + Phase 3b live verify); CSP nonce rework = separate bd |
| SEC-9 | /me fast path ข้าม is_active | 🔵 Low | track (separate bd หรือแถม Phase 2 ถ้าแตะ auth.py อยู่แล้ว) |
| SEC-10 | /system/celery-stats leak internal error strings unauth | 🔵 Low | Phase 2 opportunistic (system.py split อยู่แล้วใน r3-2) |
| SEC-11 | X-Request-ID unvalidated | 🔵 Low | track |
| SEC-12 | Redis no AUTH (internal-only) · settings.debug default True (log verbosity) | 🔵 Low | backlog, no change this branch |

**CRITICAL ที่ block Phase 2 start: ไม่มี.** SEC-1/SEC-2 เป็น High ที่ **แก้ในตัว Phase 2 เอง** (คือเนื้องาน ไม่ใช่ blocker ของการเริ่ม) — แต่เป็น **merge blocker**: branch ห้าม merge ถ้า S-AC-1..4 ไม่เขียว. SEC-5/6 คือสถานะ prod ปัจจุบัน — การ **ไม่ทำ** migration ต่างหากที่แพงขึ้นทุกวัน.

Pre-implement gate (Sentinel): ✅ STRIDE posted · ✅ S-AC ready to merge เข้า AC set (Bella append) · Sara ADR รองรับ mitigations (require_admin/limiter re-point อยู่ใน r2/r3 แล้ว) · Reggie: attack surface ลด (routes หาย 4) — runbook แก้ตอน Phase 4.

---

## 6. Open questions → Oliver (3)

1. **Open registration (AB-1 residual)**: หลัง require_admin แล้ว Google account ใดก็ยัง auto-provision เป็น user ได้ (auth.py:139-147) บน instance ส่วนตัว — ต้องการ email allowlist (`GOOGLE_ALLOWED_EMAILS` env, ~5 บรรทัด, sub-scope d) ใน branch นี้ หรือแยก bd? (Sentinel แนะ: ใน branch — มันคือ hardening ที่ user สั่งเอง)
2. **SEC-3 WS hardening** เปิดเป็น separate bd เลยไหม (WS auth + targeted alert delivery + connection cap) — Sentinel แนะ yes, priority Medium.
3. **pytest hold 8.4 caveat (S-AC-6)**: ถ้า resolver บังคับ hold — ยอม accept-risk PYSEC-2026-1845 ใน prod image หรือให้ Stan แยก requirements-dev.txt ใน branch นี้เลย?

---

## Sign-off
- Sentinel: ✅ 2026-09-03 (Phase 1c) — pen test จริง + header live-verify ตามมาที่ Phase 3b
- รอ: Sara (ADR ack S-AC-10/11) · Bella (append S-series เข้า AC set) · Oliver (Q1-Q3)

Handoff:
```
Sentinel ▸ Bella : S-AC-1..11 append เข้า AC set (bd deps-2026-09)
Sentinel ▸ Dave  : security AC injected — อ่าน §3 ก่อน Phase 2; re-run pip-audit/npm audit บน lock ใหม่
Sentinel ▸ Oliver: Open Q1-Q3 + SEC-3 separate-bd proposal
```
