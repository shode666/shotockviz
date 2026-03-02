"""
Cache Service — Redis read-through layer with SingleFlight + Stale-While-Revalidate.

Public surface
--------------
    get(redis, key)                → CacheResult | None
    set(redis, key, value, ttl)    → None
    delete(redis, key)             → None
    get_or_fetch(...)              → SWR helper (see docstring)

Design
------
SingleFlight (distributed lock)
  Before fetching from a provider, acquire a short-lived lock on
  ``lock:{key}``.  Concurrent requests that find the lock held:
    - have stale data → return stale immediately
    - have no data    → return None (caller returns 202 / waits)
  The winner fetches from the provider, writes to Redis, and releases.

Stale-While-Revalidate (SWR)
  ``get_or_fetch`` checks whether the cached value is fresh or stale.
  A value is "stale" when its shadow key ``{key}:stale_at`` does not
  exist (shadow key has a shorter TTL equal to the desired refresh
  interval, while the real key lives longer as the stale fallback).
  On stale: return the value immediately + fire background refresh task.

CacheResult
  Wraps the decoded value together with the layer that served it
  (CachedLayer.REDIS) so callers can populate ResponseMeta.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from redis.asyncio import Redis

import core.cache_keys as ck
from core.logger import get_logger
from core.ttl_policy import LOCK_TTL
from schemas.common import CachedLayer

logger = get_logger(__name__)


# ── Result type ──────────────────────────────────────────────────────────────

@dataclass
class CacheResult:
    """Decoded Redis value with metadata."""
    value: Any
    layer: CachedLayer = CachedLayer.REDIS
    is_stale: bool = False


# ── Primitives ───────────────────────────────────────────────────────────────

async def get(redis: Redis, key: str) -> CacheResult | None:
    """
    Read a JSON-encoded value from Redis.

    Returns ``None`` on miss or decode error.
    The caller should check ``result.is_stale`` when stale-awareness matters
    (use ``get_swr`` instead for automatic stale detection).
    """
    try:
        raw = await redis.get(key)
        if raw is None:
            return None
        return CacheResult(value=json.loads(raw))
    except Exception as exc:
        logger.warning("cache.get failed", key=key, error=str(exc))
        return None


async def set(redis: Redis, key: str, value: Any, ttl: int) -> None:
    """
    Write a JSON-encoded value to Redis with a TTL (seconds).

    Silent on error — a write failure is non-fatal (the next request
    will re-fetch from the provider).
    """
    try:
        await redis.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:
        logger.warning("cache.set failed", key=key, error=str(exc))


async def delete(redis: Redis, key: str) -> None:
    """Delete a key.  Silent on error."""
    try:
        await redis.delete(key)
    except Exception as exc:
        logger.warning("cache.delete failed", key=key, error=str(exc))


# ── Stale-While-Revalidate ───────────────────────────────────────────────────

_STALE_SUFFIX = ":fresh"
"""
Shadow key suffix.  The shadow key has a shorter TTL equal to the desired
refresh cadence.  When the shadow key expires (but the main key is still
alive), the value is considered stale.
"""


async def get_swr(redis: Redis, key: str) -> CacheResult | None:
    """
    SWR-aware read.

    Returns:
      None            → cache miss (no data at all)
      result (fresh)  → result.is_stale == False
      result (stale)  → result.is_stale == True  (shadow key expired)
    """
    result = await get(redis, key)
    if result is None:
        return None
    shadow = await redis.exists(key + _STALE_SUFFIX)
    result.is_stale = not bool(shadow)
    return result


async def set_swr(
    redis: Redis,
    key: str,
    value: Any,
    ttl: int,
    fresh_ttl: int,
) -> None:
    """
    Write value with two TTLs:
      - ``ttl``       → how long to serve as stale fallback
      - ``fresh_ttl`` → how long to consider it fresh (≤ ttl)

    When the shadow key expires, ``get_swr`` marks the value stale.
    """
    await set(redis, key, value, ttl)
    try:
        await redis.set(key + _STALE_SUFFIX, "1", ex=fresh_ttl)
    except Exception as exc:
        logger.warning("cache.set_swr shadow failed", key=key, error=str(exc))


# ── SingleFlight lock ────────────────────────────────────────────────────────

async def acquire_lock(redis: Redis, data_key: str) -> bool:
    """
    Try to acquire the SingleFlight lock for ``data_key``.

    Returns True if the lock was acquired (this coroutine is the "winner"
    and should fetch from the provider).
    Returns False if another coroutine already holds the lock.
    """
    lock_key = ck.lock(data_key)
    try:
        acquired = await redis.set(lock_key, "1", nx=True, ex=LOCK_TTL)
        return bool(acquired)
    except Exception as exc:
        logger.warning("acquire_lock failed", lock_key=lock_key, error=str(exc))
        return True  # Fail open: let this coroutine try the fetch


async def release_lock(redis: Redis, data_key: str) -> None:
    """Release the SingleFlight lock."""
    await delete(redis, ck.lock(data_key))


# ── High-level helper: get_or_fetch ─────────────────────────────────────────

async def get_or_fetch(
    redis: Redis,
    key: str,
    fetcher: Callable[[], Awaitable[Any]],
    ttl: int,
    *,
    fresh_ttl: int | None = None,
) -> CacheResult:
    """
    Read-through cache with SingleFlight and optional SWR.

    Algorithm
    ---------
    1. Check Redis (SWR-aware if ``fresh_ttl`` is provided).
    2. If fresh → return immediately.
    3. If stale → return stale value AND fire background refresh.
    4. If miss  → try to acquire lock.
       - Lock acquired → fetch from provider, write to cache, release.
       - Lock not acquired (another winner) → return None-wrapped result
         so the caller can respond with 202 / wait / serve stale.

    Parameters
    ----------
    fetcher
        Async callable with no arguments that returns the raw value
        (dict / list) to store.  Called at most once per lock window.
    fresh_ttl
        If provided, ``set_swr`` is used and values are checked for
        staleness.  ``fresh_ttl`` must be ≤ ``ttl``.
    """
    use_swr = fresh_ttl is not None

    # ── 1. Check cache ───────────────────────────────────────────────────────
    if use_swr:
        cached = await get_swr(redis, key)
    else:
        cached = await get(redis, key)

    # ── 2. Fresh hit ─────────────────────────────────────────────────────────
    if cached is not None and not cached.is_stale:
        return cached

    # ── 3. Stale hit → serve stale + background refresh ──────────────────────
    if cached is not None and cached.is_stale:
        async def _bg_refresh() -> None:
            if not await acquire_lock(redis, key):
                return  # Another winner is already refreshing
            try:
                fresh = await fetcher()
                if fresh is not None:
                    if use_swr:
                        await set_swr(redis, key, fresh, ttl, fresh_ttl)  # type: ignore[arg-type]
                    else:
                        await set(redis, key, fresh, ttl)
            except Exception as exc:
                logger.warning("bg_refresh failed", key=key, error=str(exc))
            finally:
                await release_lock(redis, key)

        asyncio.create_task(_bg_refresh())
        return cached  # is_stale=True

    # ── 4. Miss → SingleFlight fetch ─────────────────────────────────────────
    if not await acquire_lock(redis, key):
        # Another coroutine is fetching; return None so caller can decide
        return CacheResult(value=None, is_stale=True)

    try:
        fresh_value = await fetcher()
        if fresh_value is None:
            return CacheResult(value=None)

        if use_swr:
            await set_swr(redis, key, fresh_value, ttl, fresh_ttl)  # type: ignore[arg-type]
        else:
            await set(redis, key, fresh_value, ttl)

        logger.info("cache.fetched_and_stored", key=key)
        return CacheResult(value=fresh_value, layer=CachedLayer.PROVIDER)

    except Exception as exc:
        logger.error("get_or_fetch.fetcher failed", key=key, error=str(exc))
        return CacheResult(value=None)
    finally:
        await release_lock(redis, key)
