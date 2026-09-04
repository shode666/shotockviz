# yfinance 0.2.65 -> 1.4.1 characterization (WP-B0, gates WP-B3)

bd: deps-2026-09 · Dave (backend chain) · captured 2026-09-03 pre-bump
Source: `api_surface_0.2.65.json` (this venv) vs `api_surface_1.4.1.json`
(`/tmp/yf14-venv`, discarded scratch venv — re-derivable from `capture_api_surface.py`).

## R1 — why this is API-surface diff, not live-data diff

Live Yahoo Finance calls through `yfinance` are **BLOCKED in this sandbox**:
curl_cffi (yfinance's HTTP client, does TLS-fingerprint impersonation) gets
`SSLError: Recv failure: Connection reset by peer` against
`query1.finance.yahoo.com` through the sandbox's TLS-intercepting egress
proxy. Confirmed NOT a general network/DNS/proxy-auth problem: plain
`requests.get()` to the *same* Yahoo endpoint through the *same* proxy
returns `200` with real JSON. Three fix attempts (bare `yf.Ticker()`,
`yf.set_config(proxy=...)`, direct `curl_cffi.requests.get(impersonate=
'chrome', proxies=...)`) all failed identically — stopped per the
5-loop-iteration rule (Oliver's instruction) rather than spend the whole WP
fighting an environment limitation outside this branch's control.

Substitute: diffed the **public API surface** (property/method existence +
delegation target + call signature) that all 10 repo call sites depend on,
using yfinance 0.2.65 (this repo's `.venv`) vs yfinance 1.4.1 (isolated
scratch venv, PyPI reachable fine — only Yahoo's data endpoint is blocked).
This answers the real risk for a *library version bump* ("does the method
still exist / same signature / same delegation chain"), which live JSON
values would not answer any better (today's AAPL price is irrelevant to
whether `.fast_info.last_price` still exists next month).

**Residual risk not covered by this method**: Yahoo's JSON *response shape*
itself (dict keys inside `.info`, e.g. `trailingPE`/`shortName`) is server-side
and not versioned by the yfinance package — a genuine live-data smoke test
(`_fetch_quote`/`_fetch_fundamentals`/`_fetch_history` round-trip against a
real symbol) is still required once this branch reaches an environment with
Yahoo access (Quinn/Phase 3, or Dave locally when this lands on the user's
Mac). Flagging this explicitly per Oliver's instruction ("record the delta
explicitly — don't silently change data semantics").

## Call-site-by-call-site verdict (10 sites, Sara §2.1 map)

| # | File:lines | yfinance surface used | 0.2.65 vs 1.4.1 | Verdict |
|---|---|---|---|---|
| 1 | `workers/price_fetcher.py:137,144` | `yf.Tickers(...)`, `.tickers` dict, `t.fast_info` (`last_price`,`regular_market_price`,`previous_close`,`three_month_average_volume`,`regular_market_volume`) | `Tickers.__init__` byte-identical source both versions; `FastInfo` attr list **identical** (23 attrs) both versions — **and `regular_market_price`/`regular_market_volume` are NOT in that list in EITHER version** (pre-existing dead `getattr(...,default=None)` fallback, unaffected by bump — see Finding F-YF-1 below) | **unaffected** |
| 2 | `workers/name_fetcher.py:56,77-84` | `Tickers`, `t.fast_info.short_name`, `.info.get("shortName"/"longName")` | `short_name` also NOT in `FastInfo` attr list in either version (same dead-path as #1); `.info` property mechanism (delegates through `YfData`/`Quote` scraper) unchanged in both source trees | **unaffected** |
| 3 | `workers/fundamentals_fetcher.py:56-67` | `Tickers`, `.info` dict keys (`trailingPE`,`priceToBook`,`trailingEps`,`dividendYield`,`marketCap`,`beta`,`fiftyTwoWeekHigh`,`fiftyTwoWeekLow`,`averageVolume`) | `.info` property delegation chain unchanged; keys are Yahoo JSON field names, not yfinance-internal — governed by Yahoo's response, not this bump | **unaffected by the bump itself**; residual risk = Yahoo JSON shape (see Residual risk above) |
| 4 | `workers/history_prefetcher.py:99-100` | `yf.Ticker(...).history(period="6mo", interval="1d")` | `PriceHistory.history` real signature: only change is `proxy=` kwarg **removed** (deprecated, unused by repo — repo never passes it); `period`/`interval`/all other kwargs identical | **unaffected** |
| 5 | `workers/on_demand_listener.py:124-128` (`_fetch_quote`) | `yf.Ticker(...).fast_info` (same attrs as #1) | same as #1 | **unaffected** |
| 6 | `workers/on_demand_listener.py:171-188` (`_fetch_history`) | `yf.Ticker(...).history(period=, interval=)` | same as #4 | **unaffected** |
| 7 | `workers/on_demand_listener.py:339-343` (`_fetch_fundamentals`) | `yf.Ticker(...).info` | same as #3 | **unaffected by the bump**; residual = Yahoo JSON shape |
| 8 | `workers/financials_history_fetcher.py:90-91` | `.financials` (→ `.income_stmt`), `.balance_sheet` (→ `get_balance_sheet(pretty=True)`) | delegation chain byte-identical source both versions | **unaffected** |
| 9 | `workers/financials_history_fetcher.py:137` | `ticker.earnings` (indexed by fiscal year, `.loc[fiscal_year, "Earnings"]`) | 🔴 **Sara flagged as highest risk.** `Ticker.earnings` → `get_earnings()` → `Fundamentals.earnings` property. **`Fundamentals.earnings.fget` source is BYTE-IDENTICAL in both versions**: `warnings.warn("'Ticker.earnings' is deprecated as not available via API...")`; `return None`. **`ticker.earnings` already returns `None` in the CURRENT (0.2.65, pre-bump) codebase** — the `if earnings is not None and fiscal_year in earnings.index:` branch at financials_history_fetcher.py:137-139 is **already permanently dead code today**, and stays exactly as dead after the bump. **Zero behavior change from this bump; not a new regression** — confirmed by source, not assumed | **unaffected (confirmed pre-existing no-op in both versions)** |
| 9b | `workers/financials_history_fetcher.py:150` | `ticker.dividends` (same call as #10) | see #10 | **unaffected** |
| 10 | `workers/corporate_actions_fetcher.py:101,124` | `ticker.dividends` (→ `get_dividends()`), `ticker.splits` (→ `get_splits()`) | delegation chains identical; only `proxy=` kwarg dropped from `get_dividends`/`get_splits` (unused by repo, property access never passes it) | **unaffected** |
| 11 | `workers/earnings_events_fetcher.py:87,93` | `ticker.earnings_dates` (→ `get_earnings_dates()`), `.history(period="2y", interval="1d")` | `get_earnings_dates` signature: `(limit=12, proxy=SENTINEL)` → `(limit=12, offset=0)` — repo calls the *property* `.earnings_dates` (no args passed) so this is a non-issue; delegation `earnings_dates` → `get_earnings_dates()` unchanged | **unaffected** |
| 12 | `workers/symbol_registrar.py:121-122` | `ticker.info.get("shortName"/...)` | same as #3 | **unaffected by the bump**; residual = Yahoo JSON shape |
| 13 | `api/routes/backtesting.py:155-157` | `yf.Ticker(...).history(period=, interval="1d")` | same as #4 | **unaffected** (separate finding: this call runs **inside the API process**, violating the documented CQRS pure-read pattern — flagged to Stan per Sara §2.1, NOT fixed on this branch, out of WP-B3 scope) |

## Finding F-YF-1 (new, this WP) — pre-existing dead fallback in price_fetcher.py / on_demand_listener.py

`getattr(info, "regular_market_price", None)` and
`getattr(info, "regular_market_volume", None)` (price_fetcher.py:144-146,
on_demand_listener.py:129-131) reference `FastInfo` attribute names that do
**not exist** on the `FastInfo` object in either 0.2.65 or 1.4.1 (confirmed:
`dir(FastInfo)` — 23 attrs, neither name present). These `getattr(...,
default=None)` calls always fall through to `None`, meaning the `or`
fallback (`getattr(info, "last_price", None) or getattr(info,
"regular_market_price", None)`) never actually uses the second branch — it
either gets `last_price` or nothing. **This is unaffected by the version
bump** (identical in both) — NOT fixed here per WP-B3 scope ("adapt to 1.x
API against B0 golden fixtures... refactor of those functions is NOT in
scope", 03-stan-refactor-strategy.md WP-B3 row). Flagged for the
complexity-extraction follow-up bd (Stan's Open Question #3).

## AC-M4 classification summary (unaffected / signature-changed / removed)

All 13 call sites (10 files, some with 2 sites): **unaffected**. Zero
call sites classified `signature-changed` or `removed-needs-replacement`.
No call site left unclassified — AC-M4 satisfied by this table.

## AC-M6 status

Golden-fixture *live-data* capture is **PARTIAL / BLOCKED** (see R1 above) —
substituted with the API-surface characterization above, which is the
evidence WP-B3 actually needs to proceed safely. Re-run
`capture_api_surface.py` (this dir) under both interpreters to reproduce.
