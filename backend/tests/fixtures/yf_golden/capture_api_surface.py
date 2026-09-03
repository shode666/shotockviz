"""bd:deps-2026-09 WP-B0 — yfinance 0.2.65 -> 1.4.1 characterization capture.

R1 (inform) — live-market-data golden fixtures could NOT be captured in the
cloud sandbox that ran this WP: `yfinance`'s curl_cffi-backed HTTP client
(TLS-fingerprint impersonation) gets `SSLError: Recv failure: Connection
reset by peer` against Yahoo's chart/quote endpoints through the sandbox's
TLS-intercepting egress proxy, even after `yf.set_config(proxy=...)` and a
direct `curl_cffi.requests.get(..., impersonate='chrome', proxies=...)` call
(same reset). Plain `requests` to the SAME Yahoo host through the SAME proxy
returns 200 with real JSON — so this is specifically curl_cffi's fingerprint
spoofing being rejected by the intercepting proxy, not a network/DNS/auth
failure. Tried: (1) yf.Ticker() bare, (2) yf.set_config(proxy=...), (3)
curl_cffi.requests.get() direct. All 3 attempts failed identically; stopped
per the 5-loop-iteration rule and switched strategy rather than burn the
whole WP on an environment constraint outside this branch's control.

Substitute strategy actually used (this script): install yfinance==0.2.65
(already in .venv) and yfinance==1.4.1 (isolated venv /tmp/yf14-venv) side by
side and diff the PUBLIC API SURFACE (property/method existence, delegation
target, call signature) for every call site enumerated in
outputs/deps-2026-09/01-sara-adr-migration.md §2.1, instead of diffing live
JSON payloads. This is a legitimate characterization for a *library* version
bump (the risk is "does the method still exist / same signature / same
delegation", not "did today's AAPL closing price change") and does not
require network access. Findings are recorded in api_surface_findings.md.

Run from repo root with BOTH interpreters and diff manually, or just read
api_surface_findings.md (already captured, this file documents/reproduces it):

    .venv/bin/python backend/tests/fixtures/yf_golden/capture_api_surface.py
    /tmp/yf14-venv/bin/python backend/tests/fixtures/yf_golden/capture_api_surface.py
"""
import inspect
import json
import sys

import yfinance as yf


def _sig(obj):
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "n/a"


def capture() -> dict:
    t = yf.Ticker("AAPL")
    out = {"yfinance_version": yf.__version__}

    # Properties used by workers/*.py + api/routes/backtesting.py (call-site
    # map: outputs/deps-2026-09/01-sara-adr-migration.md §2.1)
    props = [
        "fast_info", "info", "history", "earnings", "earnings_dates",
        "dividends", "splits", "financials", "balance_sheet",
    ]
    prop_report = {}
    for name in props:
        member = getattr(type(t), name, None)
        if member is None:
            prop_report[name] = {"exists": False}
            continue
        if isinstance(member, property):
            src = inspect.getsource(member.fget).strip()
            prop_report[name] = {
                "exists": True,
                "kind": "property",
                "delegates_to": src.splitlines()[-1].strip(),
            }
        else:
            prop_report[name] = {
                "exists": True,
                "kind": "method",
                "signature": _sig(member),
            }
    out["ticker_members"] = prop_report

    # fast_info attribute surface (price_fetcher.py, on_demand_listener.py:
    # last_price, regular_market_price, previous_close,
    # three_month_average_volume, regular_market_volume; name_fetcher.py:
    # short_name)
    from yfinance.scrapers.quote import FastInfo
    out["fast_info_attrs"] = sorted(n for n in dir(FastInfo) if not n.startswith("_"))

    # get_* method signatures actually invoked transitively
    getters = [
        "get_earnings", "get_earnings_dates", "get_dividends", "get_splits",
        "get_balance_sheet",
    ]
    getter_report = {}
    for name in getters:
        m = getattr(t, name, None)
        getter_report[name] = _sig(m) if m else "MISSING"
    out["getter_signatures"] = getter_report

    # PriceHistory.history real kwargs (Ticker.history is *args/**kwargs passthrough)
    from yfinance.scrapers.history import PriceHistory
    out["price_history_signature"] = _sig(PriceHistory.history)

    # Tickers batch class (price_fetcher.py, name_fetcher.py,
    # fundamentals_fetcher.py: yf.Tickers(...).tickers.get(symbol))
    out["tickers_init_signature"] = _sig(yf.Tickers.__init__)
    out["tickers_init_source"] = inspect.getsource(yf.Tickers.__init__).strip()

    # Fundamentals.earnings internal (financials_history_fetcher.py:137 —
    # Sara flagged "already deprecated/broken in late 0.2.x era, spike must
    # confirm exists in 1.4.1")
    from yfinance.scrapers.fundamentals import Fundamentals
    out["fundamentals_earnings_source"] = inspect.getsource(
        Fundamentals.earnings.fget
    ).strip()

    return out


if __name__ == "__main__":
    result = capture()
    fname = f"api_surface_{result['yfinance_version']}.json"
    with open(fname, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    print(f"wrote {fname}")
    print(json.dumps(result, indent=2, sort_keys=True))
