"""Shared helper: cache data in Redis and publish to price_updates channel.

Provides a single implementation for the cache-then-publish pattern
used by price_fetcher, fund_fetcher, history_prefetcher, and on_demand_listener.
"""
from __future__ import annotations

import json
import time

from core import cache_keys
from core.logger import get_logger

logger = get_logger(__name__)


def cache_and_publish_quotes(
    quotes: dict[str, dict],
    redis_client,
    ttl: int = 120,
    channel: str = "price_updates",
) -> int:
    """Write quote data to Redis cache and publish update notifications.

    Args:
        quotes: {symbol: {price, change, change_pct, volume, ...}}
        redis_client: Active Redis connection.
        ttl: Cache TTL in seconds (default 120 = 2x task interval).
        channel: Redis pub/sub channel name.

    Returns:
        Number of quotes cached.
    """
    count = 0
    for sym, data in quotes.items():
        payload = {**data, "type": "price_update", "ts": int(time.time())}
        encoded = json.dumps(payload)
        redis_client.setex(cache_keys.quote(sym), ttl, encoded)
        redis_client.publish(channel, encoded)
        count += 1
    return count


def history_ts_key(cache_key: str) -> str:
    """Sibling freshness-marker key for an `ohlcv:{symbol}:{tf}` entry.

    bd:shotockviz-5e7.1 — the primary key stays a bare JSON *list*, never a
    `{..., "ts": ...}` wrapper like `cache_and_publish_quotes()` uses for
    quotes. Two writers outside this bd's file boundary `setex` that SAME
    `ohlcv:{symbol}:{tf}` key with a raw `json.dumps(bars)` list —
    `services/cache_orchestrator.py` (`fetch_stock_history`'s L2 fill and
    the asyncio on-demand fallback) and `workers/on_demand_listener.py`
    (`_fetch_history`) — and `workers/alert_checker.py:_load_daily_bars`
    reads it back with `isinstance(bars, list)` as a hard gate: if this
    key ever held a dict instead of a list, every indicator alert
    (golden/death cross, RSI) would silently stop evaluating the moment
    history_prefetcher's write won the race, with no exception raised
    anywhere. None of those three files are in this bd's scope, so the
    payload shape is left exactly alone; the real fetch timestamp goes in
    this companion key instead, as `{"ts": <epoch seconds>}` — same field
    name/shape `cache_and_publish_quotes()` writes for quotes, so
    `workers.pipeline_health._parse_ts()` can parse either canary with
    the same function.

    Compat: only `cache_and_publish_history()` (i.e. only
    `history_prefetcher.py`) ever writes this key. The other two writers
    named above never touch it, so a symbol last refreshed via one of
    THOSE paths has no companion key at all, or one that lags behind the
    primary key's actual freshness — a reader must treat "missing" as
    "unknown, not an error" (never fabricate a value), same convention
    `_parse_ts`/`compute_staleness` already use for a missing/malformed
    quote. Keys already in Redis when this deploys simply have no
    companion key until this symbol's next history_prefetcher-driven
    write; nothing needs flushing, it self-heals within one TTL window.
    """
    return f"{cache_key}:ts"


def cache_and_publish_history(
    redis_client,
    cache_key: str,
    bars: list[dict],
    ttl: int = 21600,
    channel: str = "price_updates",
    symbol: str = "*",
    timeframe: str = "1D",
) -> None:
    """Cache OHLCV bars and publish data_ready notification.

    Args:
        redis_client: Active Redis connection.
        cache_key: Redis key for this history data.
        bars: List of OHLCV bar dicts.
        ttl: Cache TTL in seconds (default 6 hours).
        channel: Redis pub/sub channel.
        symbol: Symbol for notification.
        timeframe: Timeframe for notification.
    """
    if not bars:
        return

    redis_client.setex(cache_key, ttl, json.dumps(bars))
    # bd:shotockviz-5e7.1 — real server fetch time in a sibling key; see
    # history_ts_key() docstring for why this is not embedded in `bars`
    # itself. Same TTL as the primary key so the two expire together.
    redis_client.setex(
        history_ts_key(cache_key), ttl, json.dumps({"ts": int(time.time())})
    )

    try:
        msg = {
            "type": "data_ready",
            "data_type": "history",
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(bars),
        }
        redis_client.publish(channel, json.dumps(msg))
    except Exception as e:
        logger.debug("Failed to publish data_ready", error=str(e))
