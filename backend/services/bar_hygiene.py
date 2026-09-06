"""One definition of "is this OHLCV bar usable at all".

bd:shotockviz-cjb. yfinance can return a daily row with a real `volume` but
NaN open/high/low/close. On 2026-09-04 exactly two such rows reached this
project's database (GLD and GOOGL, both with volume > 0), and because they
were the newest bar the screener rendered `price: "nan"` and `chg: "nan%"` in
the browser — a row that looks like a result and cannot be acted on.

The screener's read-side guard (`api/routes/screener.py`) stopped the symptom.
This is the writer-side rule: a bar with no prices should never be persisted
or cached in the first place, because every downstream reader inherits it —
the daily-bar cache feeds `alert_checker`'s 5 indicator alert types, and
`sr_auto_pivot` computes support/resistance levels from the same rows.

Dropping, not repairing. A bar with no prices is not a bar, and filling one in
would be the same fabrication this codebase has repeatedly had to remove:
`compute_sma` returning 0.0 and `compute_rsi` returning 50.0 on insufficient
data, both of which read as ordinary numbers to every caller.

⚠️ Auditing note for anyone sweeping the table in SQL: `WHERE close != close`
finds NOTHING. Postgres treats NaN as equal to itself and greater than every
other float, unlike IEEE 754 and unlike Python — the first sweep for this bug
reported zero affected rows for exactly that reason. Use
`WHERE close = 'NaN'::float8`.
"""
from __future__ import annotations

import math

# The fields a bar must have real numbers in. `volume` is deliberately NOT
# here: a zero-volume session is a real, meaningful fact (a halt, an illiquid
# Thai small-cap), whereas a priceless bar is not a bar at all.
_PRICE_FIELDS = ("open", "high", "low", "close")


def is_finite_bar(bar) -> bool:
    """True when every price field is a real, finite number.

    Accepts either shape this codebase carries bars in: a dict (what the
    yfinance conversion and the Redis cache use) or an ORM row / any object
    with the same attributes (what the screener reads from PostgreSQL).

    `math.isfinite` rejects NaN and both infinities. `float(None)` raises, so
    a missing or NULL field is rejected too rather than crashing the caller.
    """
    getter = bar.get if isinstance(bar, dict) else lambda k: getattr(bar, k, None)
    try:
        return all(math.isfinite(float(getter(f))) for f in _PRICE_FIELDS)
    except (TypeError, ValueError):
        return False


def drop_non_finite_bars(bars: list) -> tuple[list, int]:
    """Return (usable bars, number dropped), preserving order.

    Returns the count so callers can log it: silently discarding data is how a
    provider outage looks like normal operation. Every caller here logs when
    the count is non-zero.
    """
    usable = [b for b in bars if is_finite_bar(b)]
    return usable, len(bars) - len(usable)
