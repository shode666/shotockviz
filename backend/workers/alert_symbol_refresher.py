"""Celery task: refresh quotes for symbols with an active price alert
every 60s, on top of (not instead of) the existing 6-slot round-robin.

bd:shotockviz-cm3 (b) — price_fetcher.py visits a given market slot once
every NUM_SLOTS (6) beats, so a symbol that only belongs to one slot
refreshes roughly every ~4-6 minutes; alert_checker.py samples that
120s-TTL quote cache every 60s. A level crossed and retraced inside that
gap is never observed and never logged (N6, outputs/backlog-2026-09/
10-tara-value.md). This task closes that gap for the symbols it actually
matters for — the ones with an ACTIVE PRICE_ABOVE/PRICE_BELOW alert —
without turning into a full-watchlist every-minute fetch (Oliver's
explicit constraint: keep the existing slot rotation for everything
else).

Scope: only PRICE_ABOVE/PRICE_BELOW alerts read the quote cache this
task refreshes. The 5 indicator alert types (RSI/Golden-Death-Cross/
Volume-Spike, bd:shotockviz-06e) read the daily OHLCV cache instead,
which history_prefetcher already refreshes on its own 30-min cadence —
a 1-min OHLCV refresh is out of scope here (bar-close indicators don't
change intrabar the way "crossed the level" does).

Market-hours gated per symbol (reuses price_fetcher's own hour-check
functions) so this does not poll Yahoo Finance for a market that is
closed, every 60s, forever — see the call-volume note in
workers/celery_app.py's beat_schedule entry.
"""
from __future__ import annotations

from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger
from core.symbol_utils import is_thai_stock, is_crypto
from workers.helpers.cache_publisher import cache_and_publish_quotes
from workers.helpers.task_timing import timed_task
from workers.price_fetcher import (
    _set_hours,
    _us_hours,
    _asia_hours,
    _eu_hours,
    _is_asia,
    _is_europe,
    yfinance_batch_quotes,
)

logger = get_logger(__name__)


def _get_active_price_alert_symbols() -> list[str]:
    """Distinct symbols with at least one is_active PRICE_ABOVE/PRICE_BELOW
    alert. Excludes the 5 indicator alert types (see module docstring —
    they don't read this cache).

    bd:shotockviz-93h — no longer filters on `status`. Alerts are standing
    with a cooldown now (models/alert.py's AlertStatus docstring), so an
    already-TRIGGERED alert can fire again once its cooldown elapses and
    still needs a fresh quote to compare against in the meantime — the old
    `status == ACTIVE` filter would have starved every alert of quote
    refreshes forever after its first fire, silently defeating "standing"
    for the one thing this task exists to keep current.
    """
    try:
        from sqlalchemy import create_engine, select, distinct
        from core.config import settings
        from models.alert import Alert, AlertType

        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    select(distinct(Alert.symbol)).where(
                        Alert.is_active == True,
                        Alert.alert_type.in_([AlertType.PRICE_ABOVE, AlertType.PRICE_BELOW]),
                    )
                ).fetchall()
            return [row[0] for row in rows if row[0]]
        finally:
            engine.dispose()
    except Exception as e:
        logger.warning("Failed to load active price-alert symbols", error=str(e))
        return []


def _is_market_open_for(symbol: str, utc_now: datetime) -> bool:
    """Same per-symbol market-hours classification price_fetcher.py uses
    for its own slot rotation — reused rather than re-implemented, so
    "is this market open" cannot drift between the two callers.
    """
    if is_thai_stock(symbol):
        return _set_hours(utc_now)
    if _is_asia(symbol):
        return _asia_hours(utc_now)
    if _is_europe(symbol):
        return _eu_hours(utc_now)
    if is_crypto(symbol):
        return True
    return _us_hours(utc_now)  # catch-all: US equities, indices, FX, gold


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
@timed_task("refresh_alert_symbols")
def refresh_alert_symbols(self):
    """Every 60s: batch-refresh quotes for symbols with an active price
    alert whose market is currently open, independent of the 6-slot
    round-robin in price_fetcher.fetch_prices.
    """
    import redis as redis_lib
    from core.config import settings

    symbols = _get_active_price_alert_symbols()
    if not symbols:
        return {"symbols": 0, "open": 0, "priced": 0}

    utc_now = datetime.now(timezone.utc)
    open_symbols = [s for s in symbols if _is_market_open_for(s, utc_now)]
    if not open_symbols:
        return {"symbols": len(symbols), "open": 0, "priced": 0}

    r = redis_lib.from_url(settings.redis_url)
    quotes = yfinance_batch_quotes(open_symbols)
    count = cache_and_publish_quotes(quotes, r)

    logger.info(
        "Alert-symbol quotes refreshed",
        alert_symbols=len(symbols),
        open_symbols=len(open_symbols),
        priced=count,
        ts=utc_now.isoformat(),
    )
    return {"symbols": len(symbols), "open": len(open_symbols), "priced": count}
