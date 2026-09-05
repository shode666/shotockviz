# bd:ui-honesty-2026-09 — UI honesty pass (F1–F12)

Tracker: `bd:shotockviz-bct` (beads). Branch `main`, `34136c2` → `7f8a7d6`
(14 commits: 12 per-feature + E2E + REQUIREMENTS.md).
Engagement dates: 2026-09-05. Team: Bella (spec) · Sara (HLD/ADR) ·
Dave (impl, 4 iterations) · Chris + Quinn (review) · Tara (backlog value) ·
Aaron (Caddy) · Oliver (verify + triage + commits).

## Problem

An audit of the shipped UI found 28 places where a control looked
functional and was not: drawing tools that drew shapes lost on reload,
Settings dropdowns that saved nothing, a hardcoded "Live" indicator and a
`setInterval` wall clock labelled "last update", a "Delayed 15min" claim
nobody measured, an Export CSV button with no handler, news cards linking
to `#`, and an expired alert reporting itself as merely paused. Scope
taken here: 9 HIDE + 15 SMALL-FIX + 3 dead-code deletions = features
F1–F12. Four REAL-WORK items were deferred (now beads, see below).

## Decisions (ADRs)

### ADR-UH-001 — StatusBar freshness comes from client-side WS artifacts, not a celery-stats poll
Candidates: (a) `useWebSocket().isConnected` + `appStore.dataReadyPayload._key`
(already present, zero new I/O); (b) poll `GET /api/v1/system/celery-stats`
(`main.py:303` — real, but adds a polling loop and reports worker-side
freshness, not what the user sees); (c) a timestamp from `price_update`
(the handler branch was empty and was being deleted).
**Decision: (a).** `isConnected` is prop-drilled one level from
`__root.tsx` to `StatusBar`.
Consequences: no new network call, no new store field; the meaning is
exactly "when the last data batch reached this browser"; guests get no
signal at all (see ADR-UH-001a); `_key` stamps message arrival, not the
exchange trade — accepted, that is the honest reading.

### ADR-UH-001a (r2 revision) — the timestamp is scoped to the symbol on screen, and remembered
Chris's review found (a) satisfied the letter of the AC while still
overclaiming: `setDataReadyPayload` fires for **every** `data_ready`, so a
`history_prefetcher` sweep (30 min) or `fundamentals_fetcher` run (4 h) for
an unrelated symbol refreshed the on-screen clock. Bella issued an r2 AC:
only `data_type === 'quote'` **and** (`symbol === selected` or `symbol === '*'`)
may move it; a symbol switch resets to "—"; the label names what it
measures (`ราคา {sym} อัปเดตล่าสุด`).
A second review pass found the first implementation of that scoping was a
stateless filter over a single overwritten slot, so a non-qualifying
message **reset an already-earned timestamp to "—"**. Fixed with a pure
reducer `nextLastUpdate()` plus component-local state — still no store
field, so `useChartData`'s use of the same payload is untouched.

**Known limitation, accepted by the user:** in healthy operation this label
reads "—" almost always. The real 1-minute quote refresh publishes
`type:"price_update"` with a server `ts` (`workers/helpers/cache_publisher.py:36`);
`data_ready` with `data_type:"quote"` only fires from the Celery-outage
fallback (`services/cache_orchestrator.py:340`). Showing true price age from
that `ts` is tracked as `bd:shotockviz-09j`.

### ADR-UH-002 — Hide means remove from the render path
No feature-flag framework (user constraint), but re-enabling must stay
cheap. Decision: delete the JSX and its import; delete the component file
too when it has no plausible near-term consumer. `MultiChartLayout` and
`VolumeProfile` were deleted (zero importers); `DrawingToolbar` was deleted
as well once user-drawn S/R lines were carved out into their own bead.
Rollback is `git revert` of a single per-feature commit.

### ADR-UH-003 — Form validation is a pure function per form plus inline errors, no library
Alternatives rejected: react-hook-form/zod (a new dependency for two
forms, against the no-new-deps NFR); bare HTML5 `required` (no control over
Thai copy or error placement, and not testable under `node --test`).
Consequence: no validate-on-change — the scope was "stop failing silently".

### ADR-UH-004 — Dashboard reuses utils/marketStatus.ts; market hours stay client-side
Alternatives rejected: a backend endpoint with a holiday calendar
(over-engineering outside this scope); a shared React context (excess
abstraction for two consumers).
Consequence: holiday/DST handling stays wrong, but now wrong in exactly
one place for every consumer at once instead of differently per component.

## Verification — 12/12 PASS

Verified by Oliver in a browser against the dev stack (`https://localhost`,
9 containers healthy), as a real logged-in user and as a guest.

| F | What was wrong | Evidence it is fixed |
|---|---|---|
| F1 | Drawing toolbar drew shapes lost on reload | `/Drawing:/.test(body)` → false; chart reflows, no gap |
| F2 | Timezone / Default TF / Chart Type saved nothing; side-nav `aria-current` hardcoded to item 0 | 0 `<select>` elements remain; at 900×420 `scrollTop=0` → `General:true`, `scrollTop=207.5` (max) → `Notification:true` |
| F3 | "Live" hardcoded; timestamp was a wall clock; unmeasured "Delayed 15min" | guest → both indicators absent; WS down → `○ Offline`; WS up → `● Live`; after `PUBLISH price_updates '{"type":"data_ready","data_type":"quote","symbol":"NVDA"}'` → `18:22:48`, unchanged 4 s later |
| F4 | Dashboard closed SET at 16:00 and ignored the lunch break | Navbar and Dashboard agree at the same instant; boundary pinned in `marketStatus.test.ts` |
| F5 | VWAP selectable on 1D/1W/1M where it draws nothing | 1D → `disabled`, `aria-disabled="true"`, `title:"VWAP is intraday-only"`; 1h → enabled |
| F6 | Guest watchlist showed blank prices; guest row click gave `—` | guest rows show NVDA 230.36, AAPL 319.97, TSLA 354.08…; clicking AAPL → header `AAPL \| US \| 319.97 \| -7.67 -2.34%` |
| F7 | Empty submits returned silently | both modals stay open with `กรุณาระบุ symbol` / `กรุณาระบุค่า` / `กรุณาระบุจำนวน` / `กรุณาระบุราคา` |
| F8 | `DELETE /notes/{symbol}` existed with no control | backend logged `DELETE /api/v1/notes/NVDA … 204 No Content` + the SQL delete; textarea cleared |
| F9 | "Save Filter" had no backend; "Export CSV" had no handler | Save Filter gone; 13 results → `screener-results-2026-09-05.csv`, 914 bytes, correct header, `NFLX,"Netflix, Inc.",…` quoted |
| F10 | `href={n.url \|\| '#'}`; RightPanel emitted `href="undefined"` | url-less item injected end-to-end → plain `DIV`, `href` null, sr-only `ไม่มีลิงก์บทความ`; 0 `#` anchors |
| F11 | EXPIRED fell through to "หยุดชั่วคราว" (paused) | seeded alerts → `หมดอายุ` rgb(244,63,94) vs `หยุดชั่วคราว` rgb(148,163,184) vs `ทำงานอยู่` rgb(16,185,129) |
| F12 | 374 lines of unimported components; empty `price_update` branch | grep returns nothing; build green |

Gates on the committed tree: `npx tsc --noEmit -p .` → 1 line (the
pre-existing `src/router.tsx` strictNullChecks baseline, tracked as
`bd:shotockviz-9z0`); `npm run build` → 0 errors; `node --test "src/utils/*.test.ts"`
→ **76/76**; `tests/e2e/ui-honesty-2026-09.spec.ts` → **15/15**.
Across the three touched E2E files: 45 passed / 6 failed, the 6 all
pre-existing and beaded.

## Review outcome

- **Chris** (Standards, 7-dimension): PASS-with-findings — 0 Critical,
  0 High, 4 Medium, 3 Low, 1 Suggestion. All 4 Medium were fixed before
  commit (F3 scope, CSV formula injection, CSV UTF-8 BOM, scrollspy
  missing-section guard).
- **Quinn** (integration/E2E/a11y): PASS-with-findings, then FAIL on
  re-review — her two new tests caught the F3 timestamp-reset regression
  described in ADR-UH-001a. Fixed, re-run green. Her Q-3 (High, a11y)
  was also fixed: inline errors now carry `id` + `aria-describedby`.
- One fix was **rejected by Oliver and redone**: pairing `aria-disabled`
  with `role="link"` on a non-focusable `<div>` announced "link,
  unavailable" for something that is not a link — a widget role on a
  non-focusable element, and the same class of dishonesty this engagement
  exists to remove. It was also partly motivated by keeping an existing
  E2E selector passing. Replaced with sr-only text and the test updated.

## Out-of-scope work done in the same session

`caddy/Caddyfile` and `caddy/Caddyfile.dev` set `header_up Connection {>Connection}`
and `header_up Upgrade {>Upgrade}` on the `/api/ws/*` proxy. On Caddy
v2.11.4 that **breaks the WebSocket upgrade**: Caddy forwards a plain HTTP
request and FastAPI answers 404 (a `WebSocketRoute` never matches an `http`
scope). Through Caddy: 404; straight to `backend:8000` with the same
handshake: `101 Switching Protocols`; after removing the two lines: 101
through Caddy, and the app's StatusBar flipped `○ Offline` → `● Live`.
Production was confirmed affected the same way. Fixed in commit `2a1774e`,
**not deployed** — tracked as `bd:shotockviz-suc`.

## Follow-ups (open beads, not closed by this engagement)

Deferred REAL-WORK from the spec: edit alert · edit transaction ·
portfolio allocation pie + risk metrics · mobile nav to /login /news
/settings. Carved out: user-drawn S/R lines (`shotockviz-474`) ·
symbol classification for bare Thai tickers. Found in review:
`AlertStatus.EXPIRED` never set by any backend path (`shotockviz-43x`) ·
E2E `mockAuthSession` self-logout (`shotockviz-f9y`) · 2 stale screener
assertions (`shotockviz-tl0`) · guest quote polling unmetered ·
`useMarketStatus()` extraction · Sidebar ternary duplication · scrollspy
magic constant · `qty=0`/`price=0` business rule · tsconfig `strict:false`
debt. Found by Tara while assessing backlog value, all confirmed against
the source: **price alerts never fire** (`alert_checker` reads
`cache:quote:{sym}`, cache writes `quote:{sym}` — 0 vs 31 live keys) ·
portfolio fabricates a loss when a quote is uncached ·
`price_update` cannot reach any browser because the client never sends
`{"action":"subscribe"}` · silent hardcoded USD/THB 33.0 fallback.

`bd list` is the source of truth for all of these.

## Note — evidence archival

The phase-report trail for this engagement (audit, Bella spec + r2,
Sara HLD/ADR, three Dave reports, Oliver's verify log, Chris and Quinn
review reports) lived in `outputs/ui-honesty-2026-09/`, which is
gitignored (`.gitignore:139`) and was never tracked. Following the
precedent set by `deps-2026-09`, everything durable — the ADRs above, the
verification table, the review outcome — is consolidated into this
document and the beads, and the folder is removed. The ADRs had no other
home in this repository before now.
