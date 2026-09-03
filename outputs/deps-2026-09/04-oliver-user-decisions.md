# deps-2026-09 — User decisions after Phase 1a (Oliver relay, 2026-09-03)

Source: user answers via AskUserQuestion, iter 0 → triggers **M5 spec revision r2** (ADR-001 changes).

| # | Question | User decision | Effect |
|---|---|---|---|
| 1 | Envelope scope on v1 | **All 13 route modules** get `BaseResponse{data,meta}` in this branch | ADR-002 unchanged; Bella AC-B1 scope = all modules; Stan sequencing must cover all 13 (not stocks/dashboard only) |
| 2 | CI trigger | **Keep `workflow_dispatch` only** — do not change ci.yml triggers | No CI net; Chris/Quinn local evidence is the only gate. Oliver may dispatch ci.yml manually only with user OK (it is harmless but user said keep manual). |
| 3 | Auth drift | **Remove dead code + fix docs**: password `/register` `/login` routes (no frontend caller) and custom token logic in `authStore.js`/`api.js` that CLAUDE.md forbids | New AC (D-series) for Bella; Sentinel must review auth surface removal; docs (CLAUDE.md/REQUIREMENTS §auth) updated in same branch |
| 4 | Legacy `/api` alias | **No alias — switch immediately (in-place)** | ADR-001 option B rejected → Sara re-decides between option A (in-place at `/api`, envelope everywhere) vs `/api/v1` prefix without alias; either way NO dual mount, NO Deprecation/Sunset headers, no traffic-metric gate. Frontend `api.js` baseURL/unwrap flips in the same commit as backend. R0 #3 (legacy sunset) is void. |

Decided by Oliver (R2, informed to user, no objection):
- TS 7 fallback = `typescript@~5.9.3` (auto, R1) · pytest 9 hold to 8.4.x if resolver conflicts (auto) · nitro exact-pin `3.0.260610-beta` · drop `vite-tsconfig-paths` for Vite 8 `resolve.tsconfigPaths` · `@types/node` ^24
- `test_api_e2e.py` (`AlertCondition`) → quarantine on this branch; rewrite = separate bd
- `REQUIREMENTS.md` §6 resync → separate bd · TS strictness ratchet → separate bd
- `admin.py` auth (get_current_user → require_admin) = in-scope AC-D5 on this branch

Remaining R0 (2): merge `chore/deps-2026-09` → main · any prod deploy / GHCR push / deploy.yml dispatch.
