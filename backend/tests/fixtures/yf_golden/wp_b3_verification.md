# WP-B3 — yfinance 1.x adaptation: verification (zero code changes)

bd: deps-2026-09 · Dave · captured post-B1 bump (yfinance 1.4.1 active in `.venv`)

## Outcome: no code changes required in `services/providers/*.py` or `workers/*.py`

`services/providers/*.py` has **zero yfinance imports** (confirmed:
`grep -rln "yfinance\|import yf" services/providers/` → empty) — matches
`01-sara-adr-migration.md` §2.1's finding (raw Yahoo v8 HTTP, not
yfinance). Nothing to adapt there.

`workers/*.py` (9 files) + `api/routes/backtesting.py` — the WP-B0
characterization (`api_surface_findings.md`, captured pre-bump against
both yfinance 0.2.65 and 1.4.1 installed side by side) already classified
**all 13 call sites as unaffected** by the version bump: identical
delegation chains (`.earnings` → `get_earnings()` → `Fundamentals.earnings`
property, `.dividends`/`.splits`/`.history()`/`.financials`/
`.balance_sheet`/`.fast_info`/`.info` — all byte-identical source between
versions for the parameters this repo actually passes). Per
`03-stan-refactor-strategy.md` WP-B3's own scope note ("adapt to 1.x API
against B0 golden fixtures... refactor of those functions is NOT in
scope"), and since the characterization found nothing to adapt, this WP is
a verification pass, not a code-change pass.

## Verification performed (this WP, post-B1 bump, yfinance==1.4.1 active)

1. Import smoke — all 9 worker modules + `api.routes.backtesting` import
   cleanly under yfinance 1.4.1:

```
$ .venv/bin/python -c "import workers.symbol_registrar, workers.corporate_actions_fetcher, \
  workers.price_fetcher, workers.on_demand_listener, workers.earnings_events_fetcher, \
  workers.history_prefetcher, workers.fundamentals_fetcher, workers.name_fetcher, \
  workers.financials_history_fetcher, api.routes.backtesting"
OK workers.symbol_registrar
OK workers.corporate_actions_fetcher
OK workers.price_fetcher
OK workers.on_demand_listener
OK workers.earnings_events_fetcher
OK workers.history_prefetcher
OK workers.fundamentals_fetcher
OK workers.name_fetcher
OK workers.financials_history_fetcher
OK api.routes.backtesting
```

2. Existing coverage green (Stan's WP-B3 proof command):

```
$ .venv/bin/pytest tests/test_services.py tests/test_screener_indicators.py -q
49 passed, 2 warnings in 0.06s
```

## Residual risk (unchanged from WP-B0, repeated here per Oliver's instruction)

Live-Yahoo-data round-trip (`_fetch_quote`/`_fetch_fundamentals`/
`_fetch_history` actually returning correct values against a real symbol)
could NOT be exercised in this sandbox (network to Yahoo blocked for
yfinance's curl_cffi client — see `api_surface_findings.md` R1 for the
3-method reproduction). This is a genuine gap this WP cannot close from
here; flagged for Quinn (Phase 3, live stack) or a local run on the user's
Mac before this branch is considered fully proven end-to-end for the data
plane. AC-M4 (call-site classification) and AC-M6 (characterization gate)
are satisfied by the API-surface method; the live-value smoke is NOT
satisfied and is explicitly named as open, not silently assumed.
