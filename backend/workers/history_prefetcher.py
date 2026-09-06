"""Celery task: pre-fetch OHLCV history for symbols with expired cache."""
from __future__ import annotations

from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger
from core import cache_keys
from core.symbol_utils import normalize_for_yahoo
from workers.helpers.symbol_loader import get_watched_symbols
from workers.helpers.cache_publisher import cache_and_publish_history
from workers.helpers.task_timing import timed_task

logger = get_logger(__name__)


# ── Liveness canary (bd:shotockviz-5e7.2) ──────────────────────────────────
#
# `prefetch_history` below only ever fetches a symbol whose `ohlcv:{symbol}:{tf}`
# key is COLD (`if redis_client.exists(cache_key): continue`), so its own
# write activity is a function of "which symbol happened to be cache-cold
# this beat", not "did the task run". Two other writers
# (`services/cache_orchestrator.py`, `workers/on_demand_listener.py` — both
# out of this bd's file scope) can keep a symbol's PRIMARY key warm forever
# without ever touching the sibling `:ts` freshness marker
# `cache_and_publish_history()` stamps (see `cache_publisher.history_ts_key`
# docstring), so a quiet `:ts` canary built on the general watchlist is
# indistinguishable from history_prefetcher being dead. Full failure-mode
# writeup: `workers/pipeline_health.py` module docstring, "bd:shotockviz-
# 5e7.1 — history and fundamentals".
#
# Fix, same shape as `price_fetcher.FALLBACK_IDX` (price_fetcher.py:46-51):
# a small, hardcoded symbol set refetched EVERY run, unconditionally,
# bypassing the cold-key skip below — so "this worker ran and its write
# path still works end to end" becomes provable independent of any
# watchlist.
#
# Reuses TWO existing entries from `price_fetcher.FALLBACK_IDX` rather than
# inventing new symbols — that list is already this project's audited,
# always-available (24/7, no market-hours dependency, weekday or weekend)
# canary pool (see price_fetcher.py's module docstring and its
# `_always`-gated Overview slot): "^GSPC" (US) and "^SET.BK" (Thai), one
# from each major market region this app covers, so a single ticker's
# yfinance flakiness (e.g. one instrument temporarily errors from Yahoo)
# does not read as "the worker is dead" — `pipeline_health.compute_
# staleness()` already takes the MAX ts across a canary set for exactly
# this reason (see its own module docstring), so either symbol succeeding
# keeps the canary fresh.
#
# Why not larger — the arithmetic:
#   `prefetch-history` beats every 30 min (celery_app.py:151-154,
#   `crontab(minute="*/30")`, MEASURED) = 48 runs/day.
#   Each canary symbol is now fetched on EVERY run regardless of cache
#   state, vs. at most once per 6h TTL (4x/day) before this change — net
#   NEW calls per symbol = 48 - 4 = 44/day.
#   2 canary symbols x 44 extra calls/day = 88 extra yfinance
#   `.history(period="6mo")` calls/day, forever. That is materially
#   heavier per-call than price_fetcher's canary (one lightweight batched
#   quote request, not a per-symbol 6-month daily-bar download +
#   PostgreSQL upsert), so this set is NOT sized to match fundamentals's
#   canary shape (that task's ENTIRE symbol set is already unconditional —
#   deliberately not mirrored here, because "every watched symbol, every
#   run" is 40-60 symbols x 48 runs/day of new load, CLAUDE.md "Watchlist
#   40-60 symbols", not 2 fixed ones). 2 is the minimum that buys the
#   single-instrument cross-check above; 1 has no redundancy against a
#   single ticker's transient failure, and 3+ buys no additional liveness
#   signal over 2 (a third canary's success/failure carries the same
#   "did the worker run" bit as the second) for 50% more recurring cost.
#
# Canary symbols are placed FIRST in the iteration order below (not
# appended after the watchlist), so their write completes near the START
# of the task run regardless of how long the rest of a potentially 40-60
# symbol watchlist takes afterward — this bounds `pipeline_health`'s
# staleness threshold to "one beat interval + two canary fetches", not
# "one beat interval + the whole task's worst-case duration" (see
# `pipeline_health.HISTORY_STALE_THRESHOLD_SECONDS` for how that bound is
# used).
HISTORY_CANARY_SYMBOLS = ["^GSPC", "^SET.BK"]


# ── Pure helper: parse yfinance DataFrame row → bar dict ──────────────────────

def _parse_bar(idx, row) -> dict | None:
    """Convert a single pandas DataFrame row to OHLCV bar dict.

    Args:
        idx: pandas Timestamp index.
        row: DataFrame row with Open, High, Low, Close, Volume.

    Returns:
        Bar dict or None if parsing fails.
    """
    try:
        return {
            "time": idx.strftime("%Y-%m-%d"),
            "time_unix": int(idx.timestamp()),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]),
        }
    except Exception:
        return None


# ── Pure helper: upsert bars to PostgreSQL ────────────────────────────────────

def _upsert_bars_to_db(engine, symbol: str, timeframe: str, bars: list[dict]) -> int:
    """Save OHLCV bars to PostgreSQL, skipping existing rows.

    Args:
        engine: SQLAlchemy sync engine.
        symbol: Stock symbol.
        timeframe: e.g. "1D".
        bars: List of bar dicts with time_unix, time (str), OHLCV.

    Returns:
        Number of new rows inserted.
    """
    from sqlalchemy import text
    from services.bar_hygiene import drop_non_finite_bars

    # bd:shotockviz-cjb — yfinance can return a daily row with a real volume
    # but NaN open/high/low/close, and this used to persist it verbatim. Two
    # such rows reached the DB on 2026-09-04 and the screener rendered them as
    # `price: "nan"` in the browser. Every reader inherits a bad row —
    # alert_checker's 5 indicator types and sr_auto_pivot's level computation
    # both read these bars — so it is refused here rather than guarded five
    # times downstream.
    bars, dropped = drop_non_finite_bars(bars)
    if dropped:
        logger.warning(
            "Refused to persist bars with non-finite OHLC",
            symbol=symbol, timeframe=timeframe, dropped=dropped, kept=len(bars),
        )

    inserted = 0
    with engine.connect() as conn:
        for bar in bars:
            exists = conn.execute(text(
                "SELECT 1 FROM ohlcv_bars WHERE symbol = :symbol "
                "AND timeframe = :timeframe AND time_unix = :time_unix"
            ), {"symbol": symbol, "timeframe": timeframe, "time_unix": bar["time_unix"]}).first()

            if not exists:
                conn.execute(text(
                    "INSERT INTO ohlcv_bars "
                    "(symbol, timeframe, time_unix, time_str, open, high, low, close, volume) "
                    "VALUES (:symbol, :timeframe, :time_unix, :time_str, "
                    ":open, :high, :low, :close, :volume)"
                ), {
                    "symbol": symbol, "timeframe": timeframe,
                    "time_unix": bar["time_unix"], "time_str": bar["time"],
                    "open": bar["open"], "high": bar["high"],
                    "low": bar["low"], "close": bar["close"],
                    "volume": bar["volume"],
                })
                inserted += 1
        conn.commit()
    return inserted


# ── Pure helper: fetch history for a single symbol ────────────────────────────

def _fetch_symbol_history(symbol: str) -> list[dict]:
    """Fetch 6-month daily history from Yahoo Finance.

    Args:
        symbol: Internal symbol (e.g., "PTT.BK", "AAPL").

    Returns:
        List of bar dicts, or empty list on failure.
    """
    import yfinance as yf

    yahoo_sym = normalize_for_yahoo(symbol)
    ticker = yf.Ticker(yahoo_sym)
    hist = ticker.history(period="6mo", interval="1d")

    if hist.empty:
        logger.debug("No history data", symbol=symbol)
        return []

    bars = []
    for idx, row in hist.iterrows():
        bar = _parse_bar(idx, row)
        if bar:
            bars.append(bar)
    return bars


# ── Main task ─────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
@timed_task("prefetch_history")
def prefetch_history(self):
    """Keep OHLCV history cache warm for all watched symbols.

    Flow:
      1. Unconditionally refresh HISTORY_CANARY_SYMBOLS FIRST — bd:shotockviz
         -5e7.2 liveness canary, bypasses the cache-freshness skip (see
         module comment above)
      2. Get all symbols from watchlist + portfolio
      3. Skip symbols with fresh Redis cache (canaries from step 1 exempt)
      4. Fetch from Yahoo Finance (1D bars, 6mo range)
      5. Save to PostgreSQL + Redis (6h TTL)
      6. Publish data_ready notification
    """
    import redis as redis_lib
    from sqlalchemy import create_engine
    from core.config import settings

    watched_symbols = get_watched_symbols()

    # bd:shotockviz-5e7.2 — canaries run FIRST, always, even for a symbol
    # nobody watches; dedupe against a canary symbol that also happens to
    # be genuinely watched so it is not processed twice in one run.
    canary_symbols = list(HISTORY_CANARY_SYMBOLS)
    canary_set = set(HISTORY_CANARY_SYMBOLS)
    remaining_symbols = [s for s in watched_symbols if s not in canary_set]
    symbols = canary_symbols + remaining_symbols

    if not symbols:
        logger.info("No symbols to prefetch history for")
        return

    redis_client = redis_lib.from_url(settings.redis_url)
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

    updated_count = 0
    cached_count = 0
    canary_refreshed = 0
    timeframe = "1D"

    for symbol in symbols:
        try:
            cache_key = cache_keys.ohlcv(symbol, timeframe)
            is_canary = symbol in canary_set
            # bd:shotockviz-5e7.2 — canary symbols skip the cold-key gate
            # entirely; every other symbol keeps the original cost-saving
            # "only fetch if cache expired" behavior unchanged.
            if not is_canary and redis_client.exists(cache_key):
                cached_count += 1
                continue

            bars = _fetch_symbol_history(symbol)
            if not bars:
                continue

            # Persist to PostgreSQL
            _upsert_bars_to_db(engine, symbol, timeframe, bars)

            # Cache in Redis (strip time_unix for lightweight JSON)
            cache_bars = [{k: v for k, v in b.items() if k != "time_unix"} for b in bars]
            # bd:shotockviz-5e7.1 — cache_and_publish_history() also stamps
            # a sibling `{cache_key}:ts` freshness marker here (see its
            # docstring in workers/helpers/cache_publisher.py for why that
            # is a companion key rather than a change to `bars`' shape).
            # This is the ONLY call site that ever writes it — other paths
            # that touch the same `cache_key` (services/cache_orchestrator.py,
            # workers/on_demand_listener.py) don't. bd:shotockviz-5e7.2 —
            # for canary symbols, this fresh `:ts` write on every beat IS
            # the liveness proof `pipeline_health.HISTORY_STALE_THRESHOLD_
            # SECONDS` alerts on.
            cache_and_publish_history(
                redis_client, cache_key, cache_bars,
                ttl=21600, symbol=symbol, timeframe=timeframe,
            )
            updated_count += 1
            if is_canary:
                canary_refreshed += 1

        except Exception as e:
            logger.debug("Error fetching history", symbol=symbol, error=str(e))
            continue

    logger.info(
        "History prefetch complete",
        total=len(symbols), updated=updated_count, cached=cached_count,
        canary_refreshed=canary_refreshed, canary_total=len(canary_symbols),
        ts=datetime.now(timezone.utc).isoformat(),
    )
