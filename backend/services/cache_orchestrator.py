"""Cache orchestration — L1/L2/L3/L4 multi-layer cache for stock data.

Handles the 4-layer cache strategy:
  L1: Redis (hot, short TTL)
  L2: PostgreSQL (persistent, warm)
  L3: External source (Yahoo Finance, Stooq)
  L4: Synthetic intraday (generated from daily when L3 fails)

This module bridges all layers and coordinates data flow.
"""
import asyncio
import json
from typing import Optional

import redis.asyncio as aioredis

from core.config import settings
from core.logger import get_logger
from core import cache_keys
from models.schemas import StockQuote, OHLCVBar, StockFundamentals

# Import providers and generators
from services.providers.yahoo_provider import (
    fetch_yahoo_direct as _fetch_yahoo_direct,
    fetch_quote_direct as _fetch_quote_direct,
    fetch_fundamentals_direct as _fetch_fundamentals_direct,
)
from services.providers.stooq_provider import fetch_stooq_direct as _fetch_stooq_direct
from services.generators.synthetic_bars import generate_synthetic_intraday as _generate_synthetic_intraday
from services.db_helpers import _load_bars_from_db, _save_bars_to_db, _bars_to_db_rows

logger = get_logger(__name__)

# Cache TTLs by timeframe (in seconds)
_HISTORY_TTL = {
    "1m": 60, "5m": 300, "15m": 900,
    "1h": 3600, "4h": 3600,
    "1D": 21600, "1W": 86400, "1M": 86400,
}

# Fundamentals negative cache sentinel
_FUNDAMENTALS_NULL_SENTINEL = "__null__"


async def get_redis() -> aioredis.Redis:
    """Get or create the global Redis client.

    Cached for the lifetime of the process.
    """
    # Import here to avoid circular dependency
    from services.stock_service import get_redis as _get_redis_cached
    return await _get_redis_cached()


async def _notify_data_ready(data_type: str, symbol: str, extra: dict | None = None):
    """Publish a 'data_ready' event via Redis pub/sub so WebSocket clients know
    fresh data is available and should re-fetch.

    Args:
        data_type: "quote", "history", "fundamentals", "dashboard"
        symbol: ticker symbol (or "*" for broadcast)
        extra: optional metadata (e.g. {"timeframe": "1D"})
    """
    try:
        r = await get_redis()
        msg = {"type": "data_ready", "data_type": data_type, "symbol": symbol}
        if extra:
            msg.update(extra)
        await r.publish("price_updates", json.dumps(msg))
    except Exception as e:
        logger.debug("Failed to publish data_ready", error=str(e))


async def fetch_quote_now(symbol: str) -> Optional[StockQuote]:
    """Fetch current quote, BLOCKING until a result is available.

    Used by portfolio analytics, dashboard, and batch endpoints where real
    prices are required (not fire-and-forget).

    Strategy:
      1. Redis cache hit → return immediately (sub-millisecond).
      2. "Not-found" cache hit → return None immediately (avoid hammering Yahoo
         for symbols that don't exist, e.g. Thai mutual funds like MPDIVMF).
      3. Cache miss → await fetch_quote_direct() with a 20s hard cap → cache
         result (or cache None for 5 min) → return.

    The timeout is essential: batch endpoints call this for every watchlist
    symbol in parallel via asyncio.gather().
    """
    cache_key = cache_keys.quote(symbol)
    not_found_key = cache_keys.quote_not_found(symbol)

    try:
        r = await get_redis()
        # L1: live quote cache (60 s TTL, written by Celery and by us below)
        cached = await r.get(cache_key)
        if cached:
            return StockQuote(**json.loads(cached))
        # L2: "not found" cache — skip Yahoo for symbols we know don't exist
        if await r.exists(not_found_key):
            return None
    except Exception as e:
        logger.error("Redis quote cache read failed (fetch_quote_now)", error=str(e))

    # Cache miss — fetch directly with 20s timeout
    is_transient_failure = False
    try:
        quote = await asyncio.wait_for(_fetch_quote_direct(symbol), timeout=20.0)
    except asyncio.TimeoutError:
        logger.warning("fetch_quote_now: timeout (not caching as not-found)", symbol=symbol)
        is_transient_failure = True
        quote = None
    except Exception as e:
        logger.warning("fetch_quote_now: error (not caching as not-found)", symbol=symbol, error=str(e))
        is_transient_failure = True
        quote = None

    try:
        r = await get_redis()
        if quote:
            await r.setex(cache_key, 60, quote.model_dump_json())
        elif not is_transient_failure:
            # Only cache "not found" when Yahoo explicitly returned empty data —
            # NOT on timeout / network error (which would poison valid symbols like NVDA).
            await r.setex(not_found_key, 300, "1")
    except Exception:
        pass

    return quote


async def fetch_stock_fundamentals(symbol: str) -> Optional[StockFundamentals]:
    """Fetch fundamental data for a symbol.

    Negative caching: if Yahoo Finance rate-limits all attempts, stores a
    sentinel in Redis for 5 min so we don't hammer Yahoo on every retry.
    Overall timeout of 12 s prevents the endpoint from hanging when all
    Yahoo Finance requests are slow or rate-limited.
    """
    cache_key = cache_keys.fundamentals(symbol)
    try:
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            if cached == _FUNDAMENTALS_NULL_SENTINEL:
                return None  # negative cache hit — data not available right now
            return StockFundamentals(**json.loads(cached))
    except Exception:
        pass

    try:
        fundamentals = await asyncio.wait_for(
            _fetch_fundamentals_direct(symbol), timeout=12.0
        )
    except asyncio.TimeoutError:
        logger.warning("fetch_stock_fundamentals timed out", symbol=symbol)
        fundamentals = None

    try:
        r = await get_redis()
        if fundamentals:
            await r.setex(cache_key, 300, fundamentals.model_dump_json())
        else:
            # Negative cache — avoid hammering Yahoo when rate-limited
            await r.setex(cache_key, 300, _FUNDAMENTALS_NULL_SENTINEL)
    except Exception:
        pass

    return fundamentals


async def fetch_stock_history(symbol: str, timeframe: str) -> list[OHLCVBar]:
    """Fetch historical OHLCV data (4-layer cache).

    L1: Redis (hot)  →  L2: PostgreSQL (persistent)  →  L3: Yahoo/Stooq (source)
    L4: Synthetic intraday (generated from daily when external source fails)
    """
    # Import here to avoid circular dependency
    from services.stock_service import TF_CONFIG, DAILY_TIMEFRAMES

    if timeframe not in TF_CONFIG:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    cache_key = cache_keys.ohlcv(symbol, timeframe)
    ttl = _HISTORY_TTL.get(timeframe, 900)

    # L1: Redis
    try:
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            return [OHLCVBar(**item) for item in json.loads(cached)]
    except Exception as e:
        logger.warning("Redis cache read failed", error=str(e))

    # L2: PostgreSQL
    db_bars = await _load_bars_from_db(symbol, timeframe)
    if db_bars:
        logger.info("Serving from DB", symbol=symbol, timeframe=timeframe, bars=len(db_bars))
        try:
            r = await get_redis()
            await r.setex(cache_key, ttl, json.dumps([b.model_dump() for b in db_bars]))
        except Exception:
            pass
        return db_bars

    # L3: External source
    logger.info("Fetching from source (first time)", symbol=symbol, timeframe=timeframe)
    cfg = TF_CONFIG[timeframe]

    bars = await _fetch_yahoo_direct(symbol, cfg["interval"], cfg["period"], timeframe)

    if not bars and "." not in symbol and timeframe in DAILY_TIMEFRAMES:
        logger.info("Yahoo unavailable, trying Stooq", symbol=symbol, timeframe=timeframe)
        bars = await _fetch_stooq_direct(symbol, cfg["period"], timeframe)

    # L4: Synthetic intraday fallback — generate from daily OHLCV when Yahoo fails
    if not bars and timeframe not in DAILY_TIMEFRAMES:
        logger.info(
            "No intraday data from Yahoo, generating synthetic from daily",
            symbol=symbol, timeframe=timeframe,
        )
        # Fetch daily bars (uses its own 4-layer cache so no redundant API calls)
        daily_bars = await fetch_stock_history(symbol, "1D")
        if daily_bars:
            is_set = symbol.upper().endswith(".BK")
            bars = _generate_synthetic_intraday(daily_bars, timeframe, is_set=is_set)

    if bars:
        asyncio.create_task(_save_bars_to_db(bars, symbol, timeframe))
        try:
            r = await get_redis()
            await r.setex(cache_key, ttl, json.dumps([b.model_dump() for b in bars]))
        except Exception:
            pass

    return bars


async def fetch_yahoo_bars(
    symbol: str, timeframe: str, period: Optional[str] = None
) -> list[dict]:
    """Fetch OHLCV bars and return DB row dicts.

    Used by fetch_stock_history() L3 and seed_history.py backfill.
    Tries Yahoo Finance first; falls back to Stooq for US stocks if Yahoo fails.

    Args:
        symbol:    Ticker (e.g. "AAPL", "PTT.BK")
        timeframe: TF key (e.g. "1D")
        period:    Override period (e.g. "2y" for longer backfill).
                   Defaults to TF_CONFIG[timeframe]["period"].
    """
    # Import here to avoid circular dependency
    from services.stock_service import TF_CONFIG, DAILY_TIMEFRAMES

    cfg = TF_CONFIG.get(timeframe, {})
    _period   = period or cfg.get("period", "1y")
    _interval = cfg.get("interval", "1d")

    bars = await _fetch_yahoo_direct(symbol, _interval, _period, timeframe)

    # Fallback: Stooq for US daily/weekly/monthly when Yahoo is unavailable
    if not bars and "." not in symbol and timeframe in DAILY_TIMEFRAMES:
        logger.info("Yahoo unavailable, trying Stooq", symbol=symbol, timeframe=timeframe)
        bars = await _fetch_stooq_direct(symbol, _period, timeframe)

    return _bars_to_db_rows(bars, symbol, timeframe)


async def request_data_fetch(symbol: str, data_type: str = "all", *, timeframe: str | None = None):
    """Request that Celery fetch data for a symbol. Non-blocking, deduplicated.

    Used by API endpoints to trigger background data fetches when cache misses occur.
    Uses a dedup key in Redis (30s TTL) to prevent thundering herd of identical requests.

    Args:
        symbol: Stock symbol (e.g., "AAPL", "PTT.BK")
        data_type: "all" (default), "quote", "history", "fundamentals"
        timeframe: Optional timeframe for history fetches (e.g., "1h", "4h", "1D")

    Sends a direct Celery task to the on_demand_listener worker.
    """
    try:
        r = await get_redis()
        tf_suffix = f":{timeframe}" if timeframe else ""
        dedup_key = f"fetch_request:{symbol.upper()}:{data_type}{tf_suffix}"

        # Set with NX=True (only set if not exists) + 30s expiry
        # This ensures identical concurrent requests only trigger ONE fetch
        was_set = await r.set(dedup_key, "1", ex=30, nx=True)

        if was_set:
            # Send direct Celery task (sync import is safe in async context)
            from workers.on_demand_listener import process_fetch_request
            process_fetch_request.delay(symbol.upper(), data_type, timeframe)
            logger.debug("Data fetch requested", symbol=symbol, data_type=data_type, timeframe=timeframe)
    except Exception as e:
        logger.warning("request_data_fetch failed", symbol=symbol, error=str(e))
