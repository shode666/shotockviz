"""
Shared async Redis client.

A single connection pool is created at startup and reused for the lifetime
of the process — no per-request reconnect overhead.

Usage
-----
    from core.redis import get_redis

    redis = await get_redis()
    await redis.set("key", "value", ex=60)

Lifespan
--------
Call ``init_redis()`` from the FastAPI lifespan startup hook and
``close_redis()`` from the shutdown hook (already wired in main.py via
``lifespan``).  During tests, the fixture calls these directly.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from redis.asyncio import Redis

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

# Module-level singleton — set by init_redis(), cleared by close_redis()
_redis: Redis | None = None


async def init_redis() -> None:
    """Create the connection pool.  Call once at application startup."""
    global _redis
    _redis = await aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,   # All values come back as str, not bytes
        socket_connect_timeout=3,
        socket_timeout=3,
        health_check_interval=30,
    )
    # Verify connectivity early so we fail fast on misconfiguration
    await _redis.ping()
    logger.info("Redis connected", url=settings.redis_url)


async def close_redis() -> None:
    """Close the connection pool.  Call once at application shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed")


async def get_redis() -> Redis:
    """
    Return the shared Redis client.

    Raises ``RuntimeError`` if called before ``init_redis()``.
    Use as a FastAPI dependency via ``Depends(get_redis)``.
    """
    if _redis is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _redis
