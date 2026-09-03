# 13 — Uma: Phase 3a UI Check (deps-2026-09)

bd: deps-2026-09 · phase 3a UI Check (POST gate) · iter 0 · role: Uma (ux-ui-designer)
Comparison: baseline `73fac00` (pre-branch, Node 22 build) vs HEAD `b76c0b9` (`chore/deps-2026-09`, Node 24 build).
Design intent for this branch: **zero visual/behavioral change** (dependency migration + `/api/v1` envelope flip + JS→TS). No Phase 1b artifact exists by design — baseline build IS the design source.

## Verdict: **PASS**

- Max pixel diff across 14 page/viewport combos: **0.0029%** (dashboard-desk, 38 px of 1,296,000) — fully attributed (see §2).
- axe (wcag2a + wcag2aa + wcag21aa): **identical violation sets baseline → HEAD on every page. Zero new violations.** (Pre-existing debt flagged in §3 — predates this branch.)
- All functional spot checks (renamed-icon render, VIX/FGI tooltips, error toast with envelope shape, Google One-Tap mount, keyboard order, focus-visible) pass with base↔head parity (§4).

## 0. Method (reproducible)

- Baseline: `git worktree add /home/claude/wt-baseline 73fac00` → `npm ci && npm run build` under Node 22.22.2 (`[output: node -v]`), served `PORT=4180 node .output/server/index.mjs`.
- HEAD: repo `frontend/` → `npm ci && npm run build` under Node 24.20.0, served on `PORT=4181`.
- Both built with `VITE_GOOGLE_CLIENT_ID=mock-client-id.apps.googleusercontent.com` (build-time var, identical both sides).
- Playwright (playwright-core, chromium-1194 = Chromium 141.0.7390.37 from `/opt/pw-browsers`) with **identical route-level mocks on both builds**: regex `/api/(v1/)?…` matches baseline `/api/*` and HEAD `/api/v1/*` paths; flat JSON bodies (HEAD's central unwrap is guarded by `_isEnvelope()` — `frontend/src/services/api.ts:56` — so flat bodies pass through identically). External hosts (fonts.googleapis/gstatic, accounts.google.com) blocked on both sides for determinism; `Date` frozen to `2026-09-01T10:00:00+07:00` via init script; animations/transitions disabled via injected CSS; `reducedMotion: 'reduce'`.
- Viewports: 1440×900 (`desk`) and 390×844 (`mob`). Pages: login (guest), chart `/`, dashboard, portfolio, alerts, screener, news (authenticated via mocked `/auth/me` + localStorage token).
- Diff: `pixelmatch` threshold 0.1, per-pixel count over full viewport.
- axe: axe-core injected into each desktop page, `runOnly: ['wcag2a','wcag2aa','wcag21aa']`, run on **both** builds.

## 1. Visual regression — per page/viewport

`[pixelmatch: outputs/deps-2026-09/ui-evidence/diff-*.png]` — full console output of the diff run:

```
page/viewport        diffPx     total       diff%
login-desk                 0   1296000    0.0000%
login-mob                  0    329160    0.0000%
chart-desk                 7   1296000    0.0005%
chart-mob                  0    329160    0.0000%
dashboard-desk            38   1296000    0.0029%
dashboard-mob              0    329160    0.0000%
portfolio-desk             0   1296000    0.0000%
portfolio-mob              0    329160    0.0000%
alerts-desk                0   1296000    0.0000%
alerts-mob                 0    329160    0.0000%
screener-desk              0   1296000    0.0000%
screener-mob               0    329160    0.0000%
news-desk                  0   1296000    0.0000%
news-mob                   0    329160    0.0000%
```

**Tolerance statement**: 12 of 14 combos are pixel-identical (0 diff px). Stated tolerance for the remaining 2: sub-0.01% diffs that are individually attributed to a named cause, not accepted as anonymous noise:

## 2. Attribution of the 2 non-zero diffs

### 2.1 dashboard-desk — 38 px, bbox x259-272 y559-573 (14×15 px)
This is the lucide `Zap` icon in the dashboard ALERTS card (`AlertsNearTarget.tsx` "active" counter). **lucide-react 1.39.0 redrew the Zap glyph** (rounded joints vs 0.545.0's sharp bolt) — 4× zoomed crops:
- `[screenshot: ui-evidence/crop-zap-lucide0545-base.png]` vs `[screenshot: ui-evidence/crop-zap-lucide139-head.png]`
Same size, position, color, stroke width, and semantics; icon renders fully (not an empty span). **Design Authority ruling: accepted deviation** — canonical upstream glyph refresh from the planned lucide 0.545→1.39 bump, not a layout/behavior regression. Documented here explicitly rather than silently passed.

### 2.2 chart-desk — 7 px, two clusters
Exact coordinates: `(698-703, 153-158)` = the lucide `GitFork`/"Fork" drawing-toolbar icon — same upstream glyph micro-refresh as §2.1; `(553-554, 688-689)` = 3 px of lightweight-charts canvas anti-aliasing (candles verified visually identical: `[screenshot: ui-evidence/base-chart-desk.png]` vs `head-chart-desk.png`). Accepted on the same grounds.

## 3. Accessibility — axe baseline → HEAD

`[axe report: ui-evidence/base-report.json + head-report.json]` (desktop pass, wcag2a/wcag2aa/wcag21aa):

| Page | BASE violations | HEAD violations | New? |
|---|---|---|---|
| login | button-name(critical×1), color-contrast(serious×31) | identical | 0 |
| chart | button-name(critical×2), color-contrast(serious×61) | identical | 0 |
| dashboard | button-name(critical×3), color-contrast(serious×38) | identical | 0 |
| portfolio | button-name(critical×2), color-contrast(serious×29) | identical | 0 |
| alerts | button-name(critical×6), color-contrast(serious×31) | identical | 0 |
| screener | button-name(critical×2), color-contrast(serious×38), select-name(critical×5) | identical | 0 |
| news | button-name(critical×4), color-contrast(serious×26) | identical | 0 |

**Zero new violations.** The pre-existing debt (icon-only buttons without `aria-label`, low-contrast text on the glass theme, unlabeled selects on screener) exists at `73fac00`, predates this branch, and per this bd's zero-change intent is **not** a Phase 3a blocker — but it is real WCAG 2.1 AA failure debt. → Recommend a follow-up bd (Uma AC + Dave fix + Quinn axe gate); node selectors are in the committed axe JSONs.

### WCAG 2.2 AA — 5 manual SC (per Uma agent contract, ห้ามเงียบ)
- 2.4.11 Focus Not Obscured: layout pixel-identical (≤0.0029%) and tab sequences byte-identical base↔head (§4.5) → no *new* obscuring introduced. Full sweep of the pre-existing layout = out of this migration's scope (no Phase 1b baseline claim exists to verify against).
- 2.5.7 Dragging Movements: watchlist drag-reorder exists (pre-existing, `PATCH /watchlists/*/stocks reorder`); untouched by this branch. Flagged into the same follow-up bd.
- 2.5.8 Target Size: interactive geometry pixel-identical base↔head → no new sub-24px targets introduced; pre-existing audit deferred to follow-up bd.
- 3.3.7 Redundant Entry: `N/A` — no multi-step form in this app.
- 3.3.8 Accessible Authentication: satisfied by design — login is Google OAuth only (no password/cognitive test); unchanged by this branch (ADR-007 removed password paths entirely).

## 4. Functional spot checks (delegation-mandated) — `[playwright: ui-evidence/func-base.json + func-head.json]`

1. **Renamed lucide icons render** — per-page census of `svg.lucide` elements, base → head: login 10→10, chart 28→28, dashboard 20→20, portfolio 16→16, alerts 16→16, screener 16→16, news 16→16; **emptyLucide = 0 on every page** (no icon rendered as an empty element). Confirms Dave's finding (`11-dave-frontend-f0-f1.md` §lucide): 1.x kept all 4 flagged aliases (`Loader2`, `CandlestickChart`, `AreaChart`, `BarChart2`); zero import fallout.
2. **VIX/FGI sidebar tooltips** — hover on each trigger: `.glass-tooltip` visible on both builds, portal-positioned right of the sidebar, **bounding boxes byte-identical** base↔head (VIX `{x:215,y:196.5,w:268.08,h:63.5}`; FGI `{x:215,y:232,w:312.11,h:63.5}`), Thai text renders.
3. **Error toast (envelope shape)** — `/alerts` mocked → 500. HEAD with envelope body `{data:null,meta:{error:{message:'MOCK-ENVELOPE-ERROR'}}}` → toast shows exactly `MOCK-ENVELOPE-ERROR` (proves `api.ts` reads `body.meta.error.message`, AC-B4-r3). Baseline with legacy `{detail:'MOCK-DETAIL-ERROR'}` → toast shows it (parity of the error UX preserved).
4. **Google One-Tap on /login** — GSI script stubbed at route level (accounts.google.com unreachable from this sandbox; stub fulfills `/gsi/client` and records calls). Both builds: `initialize` called with `client_id='mock-client-id.apps.googleusercontent.com'`, `prompt()` called (One-Tap manager in `__root.tsx` active for unauthenticated guest), GoogleLogin `renderButton` invoked and stub button mounted in the DOM. Base↔head identical.
5. **Keyboard tab-order + focus-visible** — login (6 tabs) and chart (12 tabs): sequences **byte-identical** base↔head; every focused element reports a visible focus ring (`outline`/`box-shadow` ≠ none); no positive `tabindex` anywhere. (Two icon-only `BUTTON[]` entries with empty accessible names in the chart sequence = the same pre-existing `button-name` axe debt from §3.)

Console/network during captures: all console errors are harness artifacts — deliberately blocked font/GSI requests (`ERR_FAILED`) and `ws://…/api/ws/prices` 502 (no backend in this sandbox, identical failure both builds). **Zero non-blocked application request failures on either build** (`failedReqs: []` on all 28 combos, `[report: ui-evidence/*-report.json]`).

## 5. Evidence index

`outputs/deps-2026-09/ui-evidence/` (1.2 MB, 19 files): base/head/diff PNGs for the 2 non-zero pages (`{base,head}-{chart,dashboard}-desk.png`, `diff-{chart,dashboard}-desk.png`), HEAD screenshots of the 5 zero-diff desktop pages + 2 mobile samples, 4× zoom Zap crops, axe+console reports (`{base,head}-report.json`), functional results (`func-{base,head}.json`). Full uncommitted set (all 28 shots + 14 diffs) lived in the session scratchpad; every committed diff% above is from the pasted pixelmatch run in §1.

## 6. Open items → Oliver (none blocking)

1. Follow-up bd recommended: pre-existing a11y debt — `button-name` (1-6 per page, critical), `color-contrast` (26-61 per page, serious), `select-name` (×5 screener), + WCAG 2.2 manual sweep (2.4.11/2.5.7/2.5.8). Present at `73fac00`; not introduced by this branch.
2. lucide 1.x glyph refresh (Zap, Fork) = accepted visual deviation, recorded in §2 — if stakeholder objects to new glyphs, options are pin-back or custom SVG (Uma to spec); no action by default.
3. One-Tap verified with a **stubbed** GSI script (sandbox cannot reach accounts.google.com) — real-GSI smoke belongs to Quinn/Aaron's full-stack Phase 3 pass on the Docker stack, per `11-dave-frontend-f0-f1.md` §Not covered.
