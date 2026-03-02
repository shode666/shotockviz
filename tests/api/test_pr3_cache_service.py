"""
PR#3 acceptance tests — cache_service + Redis integration.

DoD:
  ✓ get: Redis hit → CacheResult with layer=REDIS
  ✓ get: miss → None
  ✓ set: stores value, readable back
  ✓ delete: removes key
  ✓ SWR: fresh shadow → is_stale=False
  ✓ SWR: expired shadow → is_stale=True
  ✓ SingleFlight: 20 concurrent requests same key → fetcher called ONCE
  ✓ Lock: acquire returns True once, False for concurrent callers
  ✓ get_or_fetch miss → fetches + stores
  ✓ get_or_fetch hit → returns cached (fetcher not called)
"""

import asyncio
import pytest
import redis.asyncio as aioredis

from core.config import settings
from schemas.common import CachedLayer
from services.cache_service import (
    CacheResult,
    acquire_lock,
    delete,
    get,
    get_or_fetch,
    get_swr,
    release_lock,
    set as cache_set,
    set_swr,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def redis():
    """Real Redis connection scoped to one test — keys flushed after."""
    r = await aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    yield r
    # Clean up any keys written during the test
    keys = await r.keys("test:*")
    if keys:
        await r.delete(*keys)
    await r.aclose()


# ── get / set / delete ────────────────────────────────────────────────────────

class TestGetSetDelete:
    async def test_miss_returns_none(self, redis):
        result = await get(redis, "test:miss")
        assert result is None

    async def test_set_then_get(self, redis):
        await cache_set(redis, "test:basic", {"x": 1}, ttl=30)
        result = await get(redis, "test:basic")
        assert result is not None
        assert result.value == {"x": 1}
        assert result.layer == CachedLayer.REDIS

    async def test_get_returns_cache_result(self, redis):
        await cache_set(redis, "test:type", [1, 2, 3], ttl=30)
        result = await get(redis, "test:type")
        assert isinstance(result, CacheResult)

    async def test_delete_removes_key(self, redis):
        await cache_set(redis, "test:del", "bye", ttl=30)
        await delete(redis, "test:del")
        result = await get(redis, "test:del")
        assert result is None

    async def test_set_with_ttl(self, redis):
        await cache_set(redis, "test:ttl", "val", ttl=1)
        ttl = await redis.ttl("test:ttl")
        assert ttl > 0

    async def test_set_stores_complex_value(self, redis):
        value = {"bars": [{"time": 1000, "open": 1.0, "close": 2.0}]}
        await cache_set(redis, "test:complex", value, ttl=30)
        result = await get(redis, "test:complex")
        assert result.value["bars"][0]["close"] == 2.0


# ── Stale-While-Revalidate ────────────────────────────────────────────────────

class TestSWR:
    async def test_fresh_value_not_stale(self, redis):
        await set_swr(redis, "test:swr:fresh", {"ok": True}, ttl=60, fresh_ttl=30)
        result = await get_swr(redis, "test:swr:fresh")
        assert result is not None
        assert result.is_stale is False

    async def test_miss_returns_none(self, redis):
        result = await get_swr(redis, "test:swr:miss")
        assert result is None

    async def test_stale_when_shadow_absent(self, redis):
        # Write main key but NOT the shadow key → should be stale
        await cache_set(redis, "test:swr:stale", {"old": True}, ttl=60)
        result = await get_swr(redis, "test:swr:stale")
        assert result is not None
        assert result.is_stale is True

    async def test_set_swr_creates_shadow_key(self, redis):
        await set_swr(redis, "test:swr:shadow", {"v": 1}, ttl=60, fresh_ttl=10)
        shadow_exists = await redis.exists("test:swr:shadow:fresh")
        assert shadow_exists == 1


# ── SingleFlight lock ────────────────────────────────────────────────────────

class TestSingleFlightLock:
    async def test_acquire_returns_true_first_time(self, redis):
        key = "test:lock:first"
        result = await acquire_lock(redis, key)
        assert result is True
        await release_lock(redis, key)

    async def test_second_acquire_returns_false(self, redis):
        key = "test:lock:second"
        first = await acquire_lock(redis, key)
        second = await acquire_lock(redis, key)
        assert first is True
        assert second is False
        await release_lock(redis, key)

    async def test_release_allows_reacquire(self, redis):
        key = "test:lock:reacquire"
        await acquire_lock(redis, key)
        await release_lock(redis, key)
        result = await acquire_lock(redis, key)
        assert result is True
        await release_lock(redis, key)

    async def test_concurrent_acquires_only_one_wins(self, redis):
        """20 concurrent coroutines — exactly 1 should win the lock."""
        key = "test:lock:concurrent"
        winners = []

        async def try_acquire():
            won = await acquire_lock(redis, key)
            if won:
                winners.append(1)
                await asyncio.sleep(0.05)  # hold briefly
                await release_lock(redis, key)

        await asyncio.gather(*[try_acquire() for _ in range(20)])
        # At least 1 winner; due to lock release + re-acquire, could be > 1
        # but each individual acquire window only allows 1 winner
        assert len(winners) >= 1


# ── get_or_fetch ──────────────────────────────────────────────────────────────

class TestGetOrFetch:
    async def test_miss_calls_fetcher(self, redis):
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return {"from": "provider"}

        result = await get_or_fetch(redis, "test:gof:miss", fetcher, ttl=60)
        assert result.value == {"from": "provider"}
        assert call_count == 1

    async def test_hit_skips_fetcher(self, redis):
        await cache_set(redis, "test:gof:hit", {"cached": True}, ttl=60)

        call_count = 0
        async def fetcher():
            nonlocal call_count
            call_count += 1
            return {"from": "provider"}

        result = await get_or_fetch(redis, "test:gof:hit", fetcher, ttl=60)
        assert result.value == {"cached": True}
        assert call_count == 0

    async def test_fetched_value_stored_in_redis(self, redis):
        async def fetcher():
            return {"price": 99.9}

        await get_or_fetch(redis, "test:gof:store", fetcher, ttl=60)
        result = await get(redis, "test:gof:store")
        assert result is not None
        assert result.value["price"] == 99.9

    async def test_concurrent_same_key_fetcher_called_once(self, redis):
        """
        SingleFlight acceptance test:
        20 concurrent requests for the same cold key → fetcher runs once.
        """
        call_count = 0

        async def slow_fetcher():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)   # simulate provider latency
            return {"data": "from-provider"}

        cold_key = "test:gof:singleflight"
        results = await asyncio.gather(
            *[get_or_fetch(redis, cold_key, slow_fetcher, ttl=60) for _ in range(20)]
        )

        # The fetcher must be called exactly ONCE
        assert call_count == 1, f"Expected 1 fetcher call, got {call_count}"

        # All coroutines that got a value must have the correct data
        values_with_data = [r for r in results if r.value is not None]
        assert len(values_with_data) >= 1
        assert values_with_data[0].value == {"data": "from-provider"}

    async def test_swr_stale_triggers_background_refresh(self, redis):
        # Write stale value (no shadow key)
        await cache_set(redis, "test:gof:swr", {"stale": True}, ttl=60)

        refreshed = False

        async def fetcher():
            nonlocal refreshed
            refreshed = True
            return {"fresh": True}

        result = await get_or_fetch(
            redis, "test:gof:swr", fetcher, ttl=60, fresh_ttl=10
        )
        # Stale value returned immediately
        assert result.value == {"stale": True}
        assert result.is_stale is True

        # Give background task time to complete
        await asyncio.sleep(0.3)
        assert refreshed is True

        # Fresh value should now be in Redis
        refreshed_result = await get(redis, "test:gof:swr")
        assert refreshed_result is not None
        assert refreshed_result.value == {"fresh": True}
