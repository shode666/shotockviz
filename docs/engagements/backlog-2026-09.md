# backlog-2026-09 — the night the silent failures were found and cleared

Tracker: beads (`bd list`, `bd show <id>`). Branch `main`, `34136c2` → `9e6abc2`.
2026-09-05 evening → 2026-09-06 morning ICT. **64 issues closed, 1 open.**

This engagement began as `bd:ui-honesty-2026-09` (12 UI features, recorded in
`ui-honesty-2026-09.md`) and turned into a full backlog run when the review
of that work kept surfacing things that were broken and silent.

## How the backlog was built and ordered

Per the user's rule for this engagement: **the domain expert judges value,
then the product manager sequences.**

- **Tara** (trading-expert) tiered all 28 open issues against the real user —
  a Thai+US swing/position trader with a 40-60 symbol watchlist who trades SET
  hours and checks US pre-market at 20:00 ICT — on impact, money/decision risk,
  and frequency. She was explicitly told a backlog where everything is MEDIUM is
  useless, and she used SKIP where she meant it.
- Reading the code to do that, she found **nine things the backlog did not
  contain**, including the two worst bugs of the session.
- **Patrick** turned her value calls into ordered waves, weighing dependencies,
  deploy coupling and blast radius, and produced a kill list. He disagreed with
  her on one tier and said so rather than silently re-ranking.

Both artifacts are consolidated here; the per-issue detail lives in the beads.

## What was actually broken

Ordered by how badly it lied, not by how hard it was to fix.

| Found | Reality |
|---|---|
| **Price alerts had never fired** | `alert_checker` read `cache:quote:{sym}`; the cache writes `quote:{sym}`. 0 keys matched against 31 that existed. The comment above the line asserted the opposite, and `CLAUDE.md` claimed this class of bug was already fixed. `sr_proximity_digest` had it too and had been reading a price of 0 for every symbol. |
| **Five of seven alert types could not fire** | The UI offered RSI, Golden/Death Cross and Volume Spike; the checker evaluated only Price Above/Below. And `_resolve_alert_type` mangled the UI's own "RSI Below" label into an invalid enum, so an RSI alert created through the real UI would have 422'd anyway. |
| **The default alert channel delivered nothing** | `in_app` was the default; the checker returned early for anything but Telegram. The only delivery was a 5-second toast over a WebSocket that was dead in production. |
| **WebSockets were dead twice over** | Two `header_up` lines broke Caddy's `/api/ws/*` upgrade (404 through Caddy, 101 straight to the backend) — and even fixed, no price update could arrive, because the client never sent a `subscribe` frame. |
| **The portfolio invented losses** | An unpriced holding contributed zero to value and its full cost to cost — a fabricated loss equal to the whole position, in the normal state after 16:30 ICT. Three surfaces folded the same book three different ways, one adding THB and USD raw. Commission was stored and never read. Splits were never applied, so a 2:1 showed a ~50% loss that never happened. |
| **A cleanup script nearly deleted nine real funds** | The bare-ticker guard used `startswith` against fund-*house* prefixes, so `TISCOGF`, `SCBLT1`, `KFLTF70` all counted as "ambiguous". |
| **The type gate had never passed** | `strict: false` since the initial commit, so `tsc` failed permanently on one error and every new type error was indistinguishable from it. |
| **The E2E suite gated nothing** | 76 red tests. Several were green while asserting the opposite of their own claim. |

Plus: `TransactionUpdate.date` resolved to `NoneType` (the field name shadowed
the type) so no transaction date could be edited; clicking a screener result
threw and did nothing; the WebSocket was unauthenticated and broadcast every
user's alerts to every socket; guest quote polling was unmetered; mobile could
not reach Login, News or Settings, and then could not log out; VWAP was
poisoned for a whole day by a single close-only bar.

## What was decided rather than built

The rejections carry as much of this engagement's meaning as the fixes.

- **Sharpe and Beta struck**, not implemented — no return series, and for Beta
  an unmade decision about which index a mixed SET+US book is measured against.
  (The benchmark itself exists; that was a correction to Oliver's brief.)
- **Max Drawdown struck** — `/portfolio/performance` is a market-value series
  of a book with external cash flows, so a scale-out halves the line without a
  satang lost. Peak-to-trough measures portfolio size, not performance.
- **`AlertStatus.EXPIRED` struck** rather than implemented — declared, never
  assigned. But `INACTIVE`, which looked identical, was analysed separately and
  kept: pausing is real and works, it just runs through `is_active`.
- **Rights offerings excluded from split restatement** — nothing records whether
  the user subscribed, for how much, at what price. Affected symbols are named.
- **Dividends never touch cost basis** — folding them in fabricates a gain.
- **User-drawn S/R levels kept out of the proximity digest** — a private entry
  mark is not a curated level worth a twice-daily push, and Alerts already owns
  "tell me at this price".
- **`unsafe-inline` kept in the production CSP** — TanStack Start SSR emits
  inline hydration scripts and a nonce needs per-request coordination a static
  header cannot do. For a single-user app whose only untrusted content is RSS
  headlines, removing it blind is breakage for near-zero risk reduction.
- **Float money left as Float** — measured, not asserted: every money field
  leaves through `round(x, 2)`, so the threshold is 0.005 THB; the worst-case
  bound is ~3.4e-6 THB, a margin of ~1,470×. The bound holds because no derived
  money is persisted — the fold is pure and runs per read. Migrating would have
  changed zero output (the service downcasts to `float` regardless of column
  type) while making the cost-flow and split invariants *less* exact.
- **`/api/health` slowness not "fixed" by weakening the check** — the user
  rejected a WONTFIX, and the constraint that implied drove the design: same
  broadcast ping, same timeout, same meaning; it just stopped standing in the
  request's way. 2.2s → 0.01s.

## Recurring failure modes worth remembering

1. **A comment asserting the opposite of the code.** The alert cache-key bug
   survived because the line above it explained, confidently, why it was right.
2. **A second implementation of one rule.** FX diverged across three surfaces;
   the identity-rate disclosure was duplicated on the dashboard; the same
   `startswith` predicate poisoned a cleanup script. Every fix shared the
   decision and differed only in rendering.
3. **Tests that pass without proving anything.** Indicator toggles matched
   `bg-violet-500`, which only ever appeared in the *inactive* class, so
   default-on indicators passed by being switched off. Two portfolio tests were
   green only in company. Three fixes were caught about to go tautological.
4. **Tests depending on data they never declare.** Exactly one seam —
   `load_actions` opening its own session, bypassing the injected `test_db`.
5. **A control that explains itself wrongly.** The date-lock note blamed a
   server limitation four hours after the server was fixed.

## Validation

Everything below was run by Oliver, not taken from an agent's report. Several
agents had no shell and said so rather than claiming green — that was correct
behaviour and is why these numbers are independent.

```
backend       docker-compose -f docker-compose.dev.yml exec -T backend \
              sh -c "cd /app && python -m pytest tests/ -q -m 'not integration'"
              → 250 → 556 passed, 2 skipped (2 pre-existing quarantines)

types         docker-compose ... exec -T frontend sh -c "npx tsc --noEmit -p ."
              → TSC_EXIT=0   (was: permanently 1 error, since the initial commit)

frontend unit docker-compose ... exec -T frontend \
              sh -c 'cd /app && node --test "src/utils/*.test.ts"'
              → 60 → 140 passed, 0 failed

E2E           cd tests/e2e && npx playwright test --reporter=list
              → 76 red → 226 passed, 0 failed  (~5 min)

migrations    docker-compose ... exec -T backend sh -c "cd /app && alembic upgrade head"
              → 0006, 0007, 0008 applied clean

production    curl -sk https://stock.shode.dev/api/health            → 200
              raw WS handshake to /api/ws/prices                     → 403 (was 404)
              30 rapid GETs on /api/v1/stocks/quotes                 → 429 at #29
              curl -sk -D - https://stock.shode.dev/ | grep -i csp   → no unsafe-eval
```

The WS result is the subtle one: **403 is the pass, 404 was the failure.** 404
meant an HTTP request had reached a `WebSocketRoute` — the upgrade never
happened. 403 is the auth guard rejecting a tokenless socket *after* a
successful upgrade, and dev returns the identical 403 to the same probe.

## Deployed, and not

One deploy on 2026-09-06 ~08:20 ICT, Sunday, both markets closed — GH run
34003724539, green through migrations and the health check. It carried the
alert fix, the Caddy WS fix, WS auth, the rate limit, the CSP, the portfolio
valuation and FX work, and the ui-honesty features.

**Ten commits made after that deploy are on `main` and not in production**:
corporate-action restatement, the `/api/health` fix, user-drawn S/R levels, the
allocation breakdown, pre-hydration states, strict types, and the date-lock and
dashboard-FX corrections. The user chose to keep them local for now.

## Note — evidence archival

`outputs/backlog-2026-09/` held Tara's 28-issue value assessment, Patrick's
wave sequencing and a JSON export of the backlog. That folder is gitignored
(`.gitignore:139`) and was never tracked, so the durable parts — how the
backlog was ordered, what was killed and why, the failure modes, and the
validation commands — are consolidated here and the folder removed. This
follows the precedent set by `deps-2026-09` and `ui-honesty-2026-09`.
