"""One definition of "a Thai fund NAV, shaped like a quote".

bd:shotockviz-ubw. `bd:shotockviz-3ir` stopped `workers/fund_fetcher.py` from
dual-writing the NAV into `quote:{symbol}` — that key carries a 120s TTL and
means "live equity quote", and an 86400s-TTL fund NAV sitting in it was read
by price alerts as if it were a live price.

The cost of that fix is that every consumer of `quote:{symbol}` must now go
and look in `fund:{symbol}` itself. Two already did
(`api/routes/stocks/quotes.py`, `api/routes/portfolio.py`) — each with its own
slightly different hand-rolled dict, one of which had already drifted (the
batch branch forwarded `ts`, the single-quote branch did not, until
`bd:shotockviz-f14` noticed). Three did not (`api/routes/dashboard.py`,
`workers/alert_checker.py`, `workers/sr_proximity_digest.py`) and would have
silently seen nothing at all for a fund symbol.

Five call sites for one conversion is exactly how the `quote:{symbol}` key
came to mean two different things in the first place, so the conversion lives
here once and every one of them calls it.

Pure and synchronous on purpose: the async routes and the sync Celery workers
both need it, and it does no I/O — the caller has already read the bytes.
"""
from __future__ import annotations

import json


def fund_payload_to_quote(symbol: str, raw: bytes | str | None) -> dict | None:
    """Convert a cached `fund:{symbol}` payload into the quote-shaped dict
    that consumers of `quote:{symbol}` expect, or None if there is nothing
    usable.

    `type: "fund_nav"` is the honest part of this: the value IS a NAV, not a
    traded price, and callers that care can tell the difference. `change`,
    `change_pct` and `volume` are zero because a fund NAV genuinely has none
    of them — this is a NAV reported as a NAV, not a fabricated quote.

    `ts` is forwarded from the payload (`fund_fetcher` stamps it) so the
    freshness machinery introduced by bd:shotockviz-f14/09j reports the NAV's
    real age. A NAV is T+1 by design and will read as hours old; that is the
    truth and must not be papered over by substituting fetch time.
    """
    if not raw:
        return None
    try:
        fund_data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(fund_data, dict):
        return None

    nav = fund_data.get("nav")
    if nav is None:
        return None
    try:
        price = float(nav)
    except (TypeError, ValueError):
        return None

    return {
        "symbol": symbol,
        "price": price,
        "change": 0.0,
        "change_pct": 0.0,
        "volume": 0,
        "type": "fund_nav",
        "nav_date": fund_data.get("date"),
        "ts": fund_data.get("ts"),
    }
