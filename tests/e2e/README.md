# ShotockViz E2E tests (Playwright)

bd:deps-2026-09 iter1 (Q-9, Low, owner: Aaron/CI wiring) — this
subproject's dependencies (`@playwright/test`) have never been installed
here.

## Before running locally or wiring into CI

```bash
cd tests/e2e
npm install                          # `package-lock.json` is repo-wide
                                      # .gitignore'd (same convention as
                                      # frontend/) — use `npm install`,
                                      # not `npm ci`, here and in any
                                      # future CI job for this dir.
npx playwright install --with-deps   # browser binaries
npm test                             # or: npx playwright test
```

## Requires a live stack

These tests hit a running backend + frontend (no request mocking at the
network layer beyond what individual specs set up via `helpers/mocks.ts`)
— see `playwright.config.ts` for the expected base URL. There is
currently no CI job that runs this suite (deliberately — see
`outputs/deps-2026-09/15-quinn-review.md` §3 for the first-ever full run
and its pass/fail breakdown, and `outputs/deps-2026-09/16-dave-iter1-fixes
.md` for the pre-existing-vs-migration-caused triage of that run's 72
failures).
