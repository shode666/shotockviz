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
