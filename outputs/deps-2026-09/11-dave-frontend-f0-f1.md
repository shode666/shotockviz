# 11 — Dave: frontend chain WP-F0 → F1 (deps-2026-09)

bd: deps-2026-09 · phase 2 implement · iter 0 · role: Dave (frontend chain)
Worktree: `/home/claude/wt-frontend`, branch `wip/deps-frontend`, base `b022606` on `chore/deps-2026-09`
Toolchain used throughout: Node **24.20.0** (`/opt/node24/bin` first on PATH, verified `node -v` before every proof below), npm 11.19.0.
Inputs read (full): `00-oliver-discover.md`, `03-stan-refactor-strategy.md` §3 + §4 Chain F + §r3-C (work order), `01-sara-adr-migration.md` §1 frontend matrix + §2 breaking-change map + CR-1/CR-2, `02-bella-brd-ac.md` AC-M1/M2/M5 + M3 (Story), `05-sentinel-threat-model.md` §2.2/§2.3 (SEC-6/SEC-7) + S-AC-7. `shode-house:dev-gate` skill loaded — this task classified as "pure config/dependency change" (dev-gate § When NOT to use → not TDD-scoped; verification = build/typecheck/audit proof, matches dev-gate's own carve-out for config changes) with 2 small type-annotation-only fixes in WP-F1 that are narrowing/type-guard edits, not new business logic.

No Docker daemon available in this environment — `frontend/Dockerfile` edit is proven by **review only** (diff below), stated explicitly, not claimed as build-tested.

---

## WP-F0 — bumps (Vite 8 / plugin-react 6 / TanStack 1.16x / Node 24 / nitro exact pin / drop vite-tsconfig-paths)

**sha**: `01d27b9`
**Files** (exactly as owned): `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, `frontend/Dockerfile`

### What changed
- Exact-pinned all deps per `01-sara-adr-migration.md` §1.1 (no `^`/`~`, per Sara's "Pin style" rule + N8).
- `nitro`: dropped floating `npm:nitro-nightly@latest` → exact `"nitro": "3.0.260610-beta"` (closes SEC-7 / AB-7).
- Removed `vite-tsconfig-paths` (unmaintained transitive dep `tsconfck`) → added `resolve: { tsconfigPaths: true }` in `vite.config.ts` (Sara CR-2). **Verified this option is real** before using it — not trusting the ADR blind: unpacked the actual `vite@8.2.2` tarball and grepped its type defs:
  ```
  interface ResolveOptions extends EnvironmentResolveOptions {
    preserveSymlinks?: boolean;
    /** Enable tsconfig paths resolution  @default false */
    tsconfigPaths?: boolean;
  }
  ```
  (source: `node_modules`-equivalent unpack of `vite-8.2.2.tgz` `dist/node/index.d.ts:2028`, done in scratchpad, no repo files touched by the probe itself).
- Added `"typecheck": "tsc --noEmit"` script (previously absent — tsc was not in the build path at all).
- `frontend/Dockerfile`: `node:22-alpine` → `node:24-alpine`, both `builder` and runtime stages.

### Deviation from Sara's matrix (evidence-based correction, not a guess)
`01-sara-adr-migration.md:28` targets `@tanstack/react-router-devtools@1.170.32` ("lockstep with router"). Registry does not have that version:
```
$ npm install
npm error code ETARGET
npm error notarget No matching version found for @tanstack/react-router-devtools@1.170.32.
```
`npm view @tanstack/react-router-devtools dist-tags` → `{ latest: '1.167.1' }` (highest published version is `1.167.1`, the devtools package trails the router package on this line). **Pinned `1.167.1` instead** — the actual latest published version, not a guess. Flag to Sara/Oliver: matrix line for this one package needs correction.

### Proof
```
$ node -v
v24.20.0

$ npm install   # first run after rm package-lock.json (regenerating exact-pinned lock)
added 205 packages, and audited 206 packages in 18s
found 0 vulnerabilities

$ npm ls typescript
frontend@ /home/claude/wt-frontend/frontend
`-- typescript@5.9.3          # unchanged in F0 — devDep line still ^5.7.2, F1's job

$ npm ls vite-tsconfig-paths
frontend@ /home/claude/wt-frontend/frontend
`-- (empty)                   # confirmed removed

$ rm -rf node_modules && npm ci    # reproducibility check
added 204 packages, and audited 205 packages in 7s
found 0 vulnerabilities

$ npm run build
vite v8.2.2 building client environment for production...
✓ 2055 modules transformed. ... ✓ built in 1.64s
vite v8.2.2 building ssr environment for production...
✓ 111 modules transformed. ... ✓ built in 364ms
[nitro] Building [Nitro] (preset: node-server) ... √ Generated public .output/public
vite v8.2.2 building nitro environment for production...
✓ 2130 modules transformed. ... ✓ built in 709ms
[nitro] √ You can preview this build using npx vite preview

real    0m4.203s   # vs baseline 9.7s on Node 22 (00-oliver-discover.md:28) — faster, consistent
                    # with Vite 8 rolldown-engine claim (Stan §5, "Trial" ring)

$ npm audit --omit=dev
found 0 vulnerabilities        # baseline: 20 (2 low, 6 moderate, 11 high, 1 critical) —
                                # 05-sentinel-threat-model.md §2.2 SEC-6 — CLOSED

$ npm audit    # full, incl devDependencies
found 0 vulnerabilities        # baseline full: 23 (2 low, 7 moderate, 11 high, 3 critical) — CLOSED
```

`@/` path-alias resolution confirmed working at build time via native `resolve.tsconfigPaths` (no plugin): build output includes all `@/`-imported chunks (`routes-*.js`, `api-*.js`, etc.) with zero unresolved-import errors — direct evidence the native replacement works, not an assumption.

`frontend/src/routeTree.gen.ts` changed as a side-effect (codegen re-emit by `@tanstack/router-plugin` 1.168.35 during `npm run build`) — reviewed the diff: pure import/route declaration re-ordering (deterministic new sort order in the newer plugin), zero manual edits, zero semantic change (same 7 routes, same paths). Committed alongside F0 since it's a generated artifact of the F0 bump, not a hand-edit outside scope.

**Dockerfile change — review-only proof** (no Docker daemon in this environment, stated explicitly per task instructions):
```diff
-FROM node:22-alpine AS builder
+FROM node:24-alpine AS builder
...
-FROM node:22-alpine
+FROM node:24-alpine
```
Both stages use the base image only for `npm ci` + `npm run build` (builder) and `node .output/server/index.mjs` (runtime) — both actions verified working under Node 24.20.0 on host in this WP's other proofs above, so the image swap carries no untested code path beyond the base-image change itself. Not container-tested.

### 🔴 Scope gap discovered (not fixed — out of WP-F0 file ownership, flagging not drifting)
`frontend/Dockerfile.dev` is **still `node:22-alpine`** (`grep -n "FROM node" frontend/Dockerfile.dev` → `1:FROM node:22-alpine`). Sara's §1.5 target matrix (`01-sara-adr-migration.md:91`) lists `Dockerfile.dev` for the same bump, but Stan's WP-F0 file-ownership table (`03-stan-refactor-strategy.md` §4 Chain F, my actual work order) only lists `frontend/Dockerfile` — `Dockerfile.dev` is not in my declared scope. Left untouched per the scope contract (editing it would be scope drift). **Escalating to Oliver**: either amend a WP to cover it, or confirm it's dev-only / out of this branch's N4 gate.

---

## WP-F1 — TypeScript 7.0.2 native compiler

**sha**: `6d880d4`
**Files** (exactly as owned): `frontend/tsconfig.json`, `frontend/package.json` (typescript pin only), `frontend/src/components/chart/TradingChart.tsx`, `frontend/src/components/ui/EmptyState.tsx`

### What changed
- `package.json`: `"typescript": "^5.7.2"` → `"typescript": "~7.0.2"`. Verified `7.0.2` is the real `latest` dist-tag before pinning (`npm view typescript dist-tags` → `latest: '7.0.2'`), not trusting the ADR number blind.
- `tsconfig.json`: removed `"baseUrl": "."` — TS 7 hard-removed the option (`TS5102`), confirmed by the compiler error below. `paths` kept unchanged; resolves relative to the tsconfig dir with no `baseUrl` because WP-F0 already moved path resolution to Vite's native `resolve.tsconfigPaths` — `tsc` itself only needs `paths` for editor/typecheck purposes and Node's `paths`-relative-to-tsconfig-dir behavior (no `baseUrl`) is TS's documented fallback.
- `TradingChart.tsx:82-96` — the crosshair-move handler read `.value` off a `seriesData.get(...)` union (`LineData | HistogramData | BarData | CustomData`). `BarData` has no `.value`; `CustomData` (generic, unused series type in this app) has no guaranteed `.value` either. Fixed with `'value' in x` type guards — **type-narrowing only, zero runtime logic change**: the two series types that previously hit `.value` unconditionally (line/area → `LineData`/`HistogramData`, both of which DO have `.value`) still get the same value at runtime; the guard only changes behavior for `BarData`/`CustomData`, and `BarData`/`CustomData` series are never constructed anywhere in this component (`grep -n "addSeries" TradingChart.tsx` → only Candlestick/Line/Area/Histogram) — so this is a pure compile-time safety net with no observable runtime difference.
- `EmptyState.tsx:1` — `import { ReactNode } from 'react'` → `import type { ReactNode } from 'react'` (`verbatimModuleSyntax` requires type-only import syntax for a type-only symbol; TS1484).

### Proof
```
$ node -v
v24.20.0

$ npm install
added 1 package, changed 1 package, and audited 206 packages in 2s
found 0 vulnerabilities

$ npm ls typescript
frontend@ /home/claude/wt-frontend/frontend
`-- typescript@7.0.2

$ npm run typecheck
> tsc --noEmit
src/router.tsx(5,39): error TS2345: Argument of type '{ routeTree: ...}' is not
assignable to parameter of type '"strictNullChecks must be enabled in tsconfig.json"'.
                                                                    # exit 1, exactly 1 error
```
This is the exact 1-error target from `03-stan-refactor-strategy.md` §3.2/§3.4 spike: `router.tsx:5` is TanStack Router's intentionally branded compile-time error demanding `strictNullChecks: true` — **whitelisted, not fixed here** (flipping `strictNullChecks` is a 123-error ratchet per Stan's spike, out of scope for this branch — tracked as a follow-up bd per Sara/Stan open questions, already answered "separate bd" per `04-oliver-user-decisions.md:15`). `TradingChart.tsx` and `EmptyState.tsx` are confirmed **clean** — zero errors from either file.

```
$ npm run build
vite v8.2.2 building client environment ... ✓ built in <1s
vite v8.2.2 building ssr environment ... ✓ built in 337ms
[nitro] Building [Nitro] ... √ Generated public .output/public
vite v8.2.2 building nitro environment ... ✓ built in 671ms
real    0m3.511s

$ rm -rf node_modules && npm ci
added 205 packages, and audited 206 packages in 8s
found 0 vulnerabilities

$ npm audit --omit=dev
found 0 vulnerabilities

$ npm audit
found 0 vulnerabilities
```

`git status --short frontend/` after this WP showed exactly the 5 declared/lockfile files — no scope drift, no unexpected regeneration (routeTree.gen.ts unchanged this time since router-plugin version was untouched between F0 and F1 builds).

### TS 7 kept — no fallback needed
Both proof passes (typecheck + build) succeeded on the first attempt within budget (iter 1 of max 5). The `typescript@~5.9.3` + restore-`baseUrl` R1 fallback documented in Sara CR-1 / Stan §3.4 was **not invoked**.

---

## lucide-react rename check (requested in delegation)

`lucide-react` bumped `0.545.0` → `1.39.0` in WP-F0. Per `01-sara-adr-migration.md` §2.9, the legacy alias names flagged as at-risk were: `Loader2`, `CandlestickChart`, `AreaChart`, `BarChart2`. **Build succeeded with zero import errors** on `npm run build` in both WP-F0 and WP-F1 passes above — a broken/removed icon import would fail the build immediately (named ESM import of a non-existent export). Confirmed no rename fallout via direct evidence:
```
$ grep -rn "from 'lucide-react'" src --include='*.tsx' --include='*.jsx' -l | xargs grep -o "Loader2\|CandlestickChart\|AreaChart\|BarChart2" | sort -u
Loader2
CandlestickChart
AreaChart
BarChart2
```
All 4 legacy names still resolve and the build transforms them cleanly — **lucide-react 1.x kept all 4 flagged aliases, zero renames needed in this repo.** (`aria-hidden`-default-on-icons and icon-only-button `aria-label` audit is explicitly out of my scope — flagged by Sara/Stan to Uma/Quinn Phase 3a, not a build gate.)

---

## Summary — merge-gate items this WP satisfies

| Gate | Target | Result |
|---|---|---|
| N3 (Sara §3) | `npm ci && npm run build` green on Node 24 | ✅ green, 4.2s (F0) / 3.5s (F1), both < baseline 9.7s |
| M3 (Bella Story M3) | TS7 spike proven or fallback invoked+documented | ✅ proven — 1 whitelisted error, TS7 kept, no fallback |
| N8 (Sara §3) | No floating deps | ✅ all exact pins; `nitro-nightly@latest` eliminated |
| S-AC-7 / SEC-6 (Sentinel) | 0 critical/high unaddressed on new lock, `npm audit --omit=dev` | ✅ 0/0/0/0 (was 1 critical + 11 high) |
| SEC-7 (Sentinel) | nitro floating pin closed | ✅ exact `3.0.260610-beta` |

## Not covered by this WP (explicitly out of my scope, per Oliver's delegation)
- `frontend/src/services/api.js`, `aiService.js`, `frontend/src/store/authStore.js`, `frontend/src/routes/__root.tsx` — WP-S1/S2/S3 (serial tail, different Dave).
- `.js` → `.ts` conversion (13 files) — WP-S3.
- Backend anything — other worktree.
- `frontend/Dockerfile.dev` — flagged above as a discovered gap, not touched.
- SSR server boot smoke (`node .output/server/index.mjs`) and Docker image build — CLAUDE.md rule 1 ("NEVER run servers on host") + no Docker daemon in this environment; both are Sara N3/N4 gate items belonging to Quinn/Aaron's Phase 3 verification with the real stack, not proven here beyond static `npm run build` success.
