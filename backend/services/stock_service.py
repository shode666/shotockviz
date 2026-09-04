"""Stock data fetching service — main facade.

This module is the public API for stock data operations. It coordinates:
  - Cache orchestration (via cache_orchestrator.py)
  - Database helpers (via db_helpers.py)
  - Data providers (Yahoo Finance, Stooq)
  - Read-only endpoints for CQRS architecture

Data flow for OHLCV history (4-layer cache):
  1. Redis  (L1, hot)  — short TTL, shared per symbol+timeframe
  2. PostgreSQL / TimescaleDB (L2, warm) — persistent, shared across users
  3. External source (L3) — called only when DB is empty:
       • Yahoo Finance v8 API (query2 + cookie/crumb auth)
       • Stooq fallback for US stocks (no rate limits, no API key)
  4. Synthetic intraday (L4) — generated from daily data when L3 fails
       • Deterministic Brownian bridge ensures consistent results
       • Useful for Thai stocks (.BK) with limited intraday availability
"""
import asyncio
import json
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import select

from core.config import settings
from core.logger import get_logger
from core.database import AsyncSessionLocal
from core import cache_keys
from core.redis import get_redis as _get_shared_redis
from models.schemas import OHLCVBar
from models.ohlcv import OHLCVBar as OHLCVBarModel

# Import from sub-modules
from services.providers.yahoo_provider import search_yahoo_direct as _search_yahoo_direct
from services.db_helpers import _aggregate_4h, _bars_to_db_rows
from services.cache_orchestrator import (
    fetch_stock_history,
    fetch_quote_now,
    fetch_stock_fundamentals,
    fetch_yahoo_bars,
    request_data_fetch,
)

# Re-export sub-module functions for backward compatibility
__all__ = [
    "get_redis",
    "fetch_yahoo_bars",
    "fetch_stock_history",
    "fetch_quote_now",
    "fetch_stock_fundamentals",
    "search_stocks",
    "read_quote",
    "read_history",
    "read_fundamentals",
    "request_data_fetch",
    "_cache_quote_background",
    "TF_CONFIG",
    "DAILY_TIMEFRAMES",
    "_aggregate_4h",
    "_bars_to_db_rows",
]

logger = get_logger(__name__)

_redis_client = None

# ── Timeframe config ──────────────────────────────────────────────────────
TF_CONFIG = {
    "1m":  {"interval": "1m",  "period": "1d"},
    "5m":  {"interval": "5m",  "period": "5d"},
    "15m": {"interval": "15m", "period": "15d"},
    "1h":  {"interval": "1h",  "period": "60d"},
    "4h":  {"interval": "1h",  "period": "120d"},   # 1h bars aggregated to 4h
    "1D":  {"interval": "1d",  "period": "1y"},
    "1W":  {"interval": "1wk", "period": "3y"},
    "1M":  {"interval": "1mo", "period": "10y"},
}

# Timeframes that use "YYYY-MM-DD" strings (required by lightweight-charts)
DAILY_TIMEFRAMES = {"1D", "1W", "1M"}


async def get_redis() -> aioredis.Redis:
    """Get or create the global Redis client.

    Prefers the shared connection pool from ``core.redis`` (created by
    ``init_redis()`` in the app lifespan with explicit connect/socket
    timeouts, bd:deps-2026-09 S0) so this module shares one pool with the
    rest of the app instead of opening its own unbounded connection.
    Falls back to a locally-cached, lazily-created client — the previous
    behavior, unchanged — when ``core.redis`` hasn't been initialised
    (e.g. this module used outside the FastAPI app lifespan).
    """
    global _redis_client
    try:
        return await _get_shared_redis()
    except RuntimeError:
        pass
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def search_stocks(query: str) -> list[dict]:
    """Search stocks by symbol or name."""
    cache_key = cache_keys.search(query)
    try:
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    results = await _search_yahoo_direct(query)
    if results:
        try:
            r = await get_redis()
            await r.setex(cache_key, 86400, json.dumps(results))
        except Exception:
            pass

    return results


# ── PURE READ-ONLY API (NO EXTERNAL FETCHES) ────────────────────────────────────
#
# These functions implement the "read-only" backend requirement:
# NO API endpoint should call external APIs directly. All data comes from
# Redis (L1) → PostgreSQL (L2) only. If data is missing, trigger a Celery
# task via request_data_fetch() and return empty/pending.


async def read_quote(symbol: str) -> dict | None:
    """Read quote from Redis cache ONLY. Returns None on cache miss.

    Never calls external APIs. Used by GET /{symbol}/quote endpoint.
    If data is missing, endpoint should call request_data_fetch() to trigger
    a background Celery task.
    """
    try:
        r = await get_redis()
        cached = await r.get(cache_keys.quote(symbol))
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return None


async def read_history(symbol: str, tf: str) -> list[dict]:
    """Read OHLCV bars from Redis → PostgreSQL. Never calls external APIs.

    L1: Redis cache (fast)
    L2: PostgreSQL ohlcv_bars table (persistent)

    Returns list of dicts matching OHLCVBar schema:
        [{"time": "2025-03-01" or 1234567890, "open": 100.0, "high": ..., ...}]

    Returns empty list if no data found.
    """
    try:
        r = await get_redis()
        cached = await r.get(cache_keys.ohlcv(symbol, tf))
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    # L2: PostgreSQL ohlcv_bars table
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OHLCVBarModel)
                .where(
                    OHLCVBarModel.symbol == symbol.upper(),
                    OHLCVBarModel.timeframe == tf
                )
                .order_by(OHLCVBarModel.time_unix.asc())
                .limit(500)
            )
            bars = result.scalars().all()
            if bars:
                return [b.to_api_dict() for b in bars]
    except Exception as e:
        logger.debug("read_history PostgreSQL error", symbol=symbol, tf=tf, error=str(e))
        pass

    return []


async def read_fundamentals(symbol: str) -> dict | None:
    """Read fundamentals from Redis cache ONLY.

    Returns dict matching StockFundamentals schema or None if not cached.
    Never calls external APIs.

    Note: Negative cache (empty object) is stored as "__null__" to distinguish
    from actual "not fetched yet" state.
    """
    try:
        r = await get_redis()
        cached = await r.get(cache_keys.fundamentals(symbol))
        if cached:
            data = json.loads(cached)
            # Skip negative cache sentinel
            if data != "__null__":
                return data
    except Exception:
        pass
    return None


async def _cache_quote_background(symbol: str) -> None:
    """Background coroutine: fetch quote from Yahoo Finance and cache in Redis.

    Called via asyncio.create_task() so it does not block the request path.
    Silently skips if a quote is already cached (race-condition guard).

    Used by main.py startup warmup and by fetch_quote_now() as a fallback.
    """
    try:
        cache_key = cache_keys.quote(symbol)
        r = await get_redis()
        # Skip if another task already populated the cache
        if await r.get(cache_key):
            return
        quote = await fetch_quote_now(symbol)
        if quote:
            await r.setex(cache_key, 60, quote.model_dump_json())
            logger.info("Background quote cached", symbol=symbol)
    except Exception as e:
        logger.debug("Background quote fetch failed", symbol=symbol, error=str(e))
