"""
TTL (Time-To-Live) policy for every Redis cache key type.

Design goals:
  - Intraday bars expire quickly (60 s) so the chart stays near-live.
  - Daily+ bars can be stale for hours — one Yahoo hit per day is plenty.
  - Quotes expire in 60 s (Celery worker refreshes every minute anyway).
  - Fundamentals are slow-moving; 5-minute TTL is generous.
  - Screener snapshots are pre-computed by a worker every N minutes; the
    API just reads the snapshot, so we allow a long TTL here.
  - Lock TTL must be short (≤ provider timeout) so a crashed worker
    doesn't hold the lock forever.

All values are in **seconds**.
"""

from __future__ import annotations

# ── Timeframe → Redis TTL ────────────────────────────────────────────────────

#: Maps chart timeframe string to Redis TTL in seconds.
OHLCV_TTL: dict[str, int] = {
    "1m":  60,
    "5m":  60,
    "15m": 60,
    "1h":  3_600,    # 1 hour
    "4h":  3_600,    # 1 hour (aggregated from 1 h)
    "1D":  21_600,   # 6 hours
    "1W":  86_400,   # 24 hours
    "1M":  86_400,   # 24 hours
}

# ── Per-endpoint TTL constants ────────────────────────────────────────────────

#: Live price quote (Celery worker refreshes every 60 s).
QUOTE_TTL: int = 60

#: Company fundamentals — slow-moving, refresh every 5 minutes.
FUNDAMENTALS_TTL: int = 300

#: Symbol search results — very stable, refresh once per day.
SEARCH_TTL: int = 86_400

#: Mutual fund NAV — published once per business day.
FUND_NAV_TTL: int = 86_400

#: Screener snapshot — worker re-computes periodically; long TTL is fine.
SCREENER_SNAPSHOT_TTL: int = 300   # 5 minutes (matches worker interval)

#: SingleFlight lock — short enough that a crashed worker can't block forever.
LOCK_TTL: int = 15  # seconds

# ── Helpers ──────────────────────────────────────────────────────────────────

def ohlcv_ttl(tf: str) -> int:
    """
    Return the Redis TTL for the given timeframe.

    Raises ``KeyError`` if ``tf`` is not a recognised timeframe.
    Call :func:`utils.timeframes.validate` first to get a clean error message.
    """
    return OHLCV_TTL[tf]


def is_intraday(tf: str) -> bool:
    """Return True for sub-daily timeframes (1m / 5m / 15m / 1h / 4h)."""
    return tf in {"1m", "5m", "15m", "1h", "4h"}
