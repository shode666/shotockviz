"""bd:shotockviz-f14.2 — "the fundamentals as-of does not say whether it is
a real stamp or a TTL guess".

bd:shotockviz-5e7.1 made `workers/fundamentals_fetcher.py` (out of this
bd's scope, unchanged) stamp a real `ts` into every `fundamentals:{symbol}`
payload it writes. Two other writers of that same key never stamped one:
`workers/on_demand_listener.py::_fetch_fundamentals` and
`services/cache_orchestrator.py`'s two fundamentals write sites
(`fetch_stock_fundamentals`'s own cache-fill, and the Celery-down asyncio
fallback branch of `_asyncio_fetch_fallback`). Because all three writers
now stamp, `api/routes/stocks/fundamentals.py`'s TTL-derived
`_fundamentals_as_of_ts()` estimate is dead code and has been deleted
rather than labelled (bd's stated preference — "a guess you can remove
beats a guess you have to explain").

Hermetic: yfinance/httpx and Redis are all faked — no live network or
Redis needed anywhere in this file.

RED-proof (all four classes below, run against the pre-fix tree):
  - TestOnDemandListenerStampsRealTs: `StockFundamentals(...)` inside
    `_fetch_fundamentals` was built with no `ts=` kwarg, so the cached
    JSON blob never had a `"ts"` key at all — `payload["ts"]` raised
    `KeyError`.
  - TestCacheOrchestratorDirectFetchStampsRealTs /
    TestCacheOrchestratorAsyncioFallbackStampsRealTs: same shape of
    failure — `fetch_stock_fundamentals` and the asyncio-fallback branch
    both cached `fundamentals.model_dump_json()` straight from the
    provider's return value, which has `ts=None` (the provider layer
    never sets it), so `payload["ts"]` was `None`, not the frozen `ts`
    these tests assert.
  - TestInferenceDeleted: `api.routes.stocks.fundamentals` still exported
    `_fundamentals_as_of_ts` and `FUNDAMENTALS_CACHE_TTL_SECONDS`, and a
    payload with no `ts` but a live remaining TTL got a non-None,
    TTL-derived `ts` back from the endpoint — the opposite of what
    `test_ts_is_none_even_with_live_ttl_once_inference_is_gone` asserts.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core import cache_keys


# ─────────────────────────────────────────────────────────────────────────
# workers/on_demand_listener.py::_fetch_fundamentals
# ─────────────────────────────────────────────────────────────────────────

class _FakeCeleryRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def setex(self, key, ttl, value):
        self.store[key] = value

    def publish(self, channel, message):
        pass


class _FakeTicker:
    def __init__(self, info):
        self.info = info


_SAMPLE_INFO = {
    "trailingPE": 18.4, "priceToBook": 3.1, "trailingEps": 4.2,
    "dividendYield": 0.02, "marketCap": 500_000_000,
    "beta": 0.9, "fiftyTwoWeekHigh": 40.0, "fiftyTwoWeekLow": 20.0,
    "averageVolume": 1_000_000,
}


class TestOnDemandListenerStampsRealTs:
    def test_fetched_fundamentals_carry_a_real_ts(self, monkeypatch):
        from workers import on_demand_listener

        monkeypatch.setattr(
            "yfinance.Ticker", lambda _sym: _FakeTicker(dict(_SAMPLE_INFO))
        )
        monkeypatch.setattr("time.time", lambda: 1_700_000_000.0)

        fake_redis = _FakeCeleryRedis()
        ok = on_demand_listener._fetch_fundamentals("PTT.BK", fake_redis)

        assert ok is True
        payload = json.loads(fake_redis.store[cache_keys.fundamentals("PTT.BK")])
        assert payload["ts"] == 1_700_000_000
        assert payload["pe_ratio"] == 18.4


# ─────────────────────────────────────────────────────────────────────────
# services/cache_orchestrator.py — fetch_stock_fundamentals (direct fetch)
# ─────────────────────────────────────────────────────────────────────────

class _FakeAsyncRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value


async def _make_fundamentals_no_ts(symbol: str):
    from models.schemas import StockFundamentals
    return StockFundamentals(symbol=symbol, pe_ratio=22.1, market_cap=99.0)


class TestCacheOrchestratorDirectFetchStampsRealTs:
    @pytest.mark.asyncio
    async def test_fetch_stock_fundamentals_stamps_real_ts(self, monkeypatch):
        from services import cache_orchestrator

        fake_redis = _FakeAsyncRedis()
        monkeypatch.setattr(cache_orchestrator, "get_redis", lambda: _areturn(fake_redis))
        monkeypatch.setattr(cache_orchestrator, "_fetch_fundamentals_direct", _make_fundamentals_no_ts)
        monkeypatch.setattr("time.time", lambda: 1_700_000_500.0)

        result = await cache_orchestrator.fetch_stock_fundamentals("NVDA")

        assert result.ts == 1_700_000_500
        cached = json.loads(fake_redis.store[cache_keys.fundamentals("NVDA")])
        assert cached["ts"] == 1_700_000_500
        assert cached["pe_ratio"] == 22.1


# ─────────────────────────────────────────────────────────────────────────
# services/cache_orchestrator.py — _asyncio_fetch_fallback (Celery-down path)
# ─────────────────────────────────────────────────────────────────────────

class TestCacheOrchestratorAsyncioFallbackStampsRealTs:
    @pytest.mark.asyncio
    async def test_asyncio_fallback_stamps_real_ts(self, monkeypatch):
        from services import cache_orchestrator

        fake_redis = _FakeAsyncRedis()
        monkeypatch.setattr(cache_orchestrator, "get_redis", lambda: _areturn(fake_redis))
        monkeypatch.setattr(cache_orchestrator, "_fetch_fundamentals_direct", _make_fundamentals_no_ts)
        monkeypatch.setattr("time.time", lambda: 1_700_001_000.0)

        # No quote/history side-effects for this assertion: isolate to the
        # fundamentals branch only.
        async def _no_quote(*_a, **_kw):
            return None
        monkeypatch.setattr(cache_orchestrator, "_fetch_quote_direct", _no_quote)

        await cache_orchestrator._asyncio_fetch_fallback("NVDA", "fundamentals", None)

        cached = json.loads(fake_redis.store[cache_keys.fundamentals("NVDA")])
        assert cached["ts"] == 1_700_001_000


async def _areturn(value):
    return value


# ─────────────────────────────────────────────────────────────────────────
# api/routes/stocks/fundamentals.py — inference path deleted, not labelled
# ─────────────────────────────────────────────────────────────────────────

FUNDAMENTALS_PATH = "/api/v1/stocks/NVDA/fundamentals"

RAW_FUNDAMENTALS_NO_TS = {
    "symbol": "NVDA",
    "pe_ratio": 45.2,
    "pb_ratio": 30.1,
    "eps": 2.5,
    "dividend_yield": 0.001,
    "market_cap": 3_000_000_000_000,
    "beta": 1.6,
    "week_52_high": 150.0,
    "week_52_low": 60.0,
    "avg_volume": 250_000_000,
    # deliberately no "ts" key — simulates a payload from a pre-deploy
    # writer, or one of the two writers this bd fixes, cached before the
    # fix rolled out.
}


class _FakeRedisWithTtl:
    """Same shape as test_f14_fundamentals_ts.py's FakeRedis — carries a
    LIVE remaining TTL alongside a ts-less payload, which is exactly the
    input the now-deleted TTL inference used to key off of."""

    def __init__(self, values: dict[str, str], ttls: dict[str, int]):
        self.values = values
        self.ttls = ttls

    async def get(self, key):
        return self.values.get(key)

    async def ttl(self, key):
        return self.ttls.get(key, -2)


@pytest.mark.usefixtures("override_db")
class TestInferenceDeleted:
    def test_ts_is_none_even_with_live_ttl_once_inference_is_gone(self, monkeypatch):
        """900s elapsed out of a live 14400s TTL used to produce a
        TTL-derived ts (see test_f14_fundamentals_ts.py, now updated for
        this bd). Once the inference path is deleted, a payload with no
        stamped ts must return ts=None regardless of how much TTL is
        left — never fabricated from the key's own expiry."""
        key = cache_keys.fundamentals("NVDA")
        fake = _FakeRedisWithTtl(
            values={key: json.dumps(RAW_FUNDAMENTALS_NO_TS)},
            ttls={key: 13500},
        )
        monkeypatch.setattr("services.stock_service.get_redis", lambda: _areturn(fake))

        resp = TestClient(_import_app()).get(FUNDAMENTALS_PATH)

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["pe_ratio"] == 45.2
        assert body["ts"] is None

    def test_inference_symbols_removed_from_route_module(self):
        """`_fundamentals_as_of_ts` and `FUNDAMENTALS_CACHE_TTL_SECONDS`
        must be gone, not merely unused — a guess you can remove beats a
        guess you have to explain (bd AC)."""
        from api.routes.stocks import fundamentals as fundamentals_route

        assert not hasattr(fundamentals_route, "_fundamentals_as_of_ts")
        assert not hasattr(fundamentals_route, "FUNDAMENTALS_CACHE_TTL_SECONDS")

    def test_real_stamp_still_passes_through_unchanged(self, monkeypatch):
        """Control case: a writer that DID stamp ts must still be
        returned as-is, unaffected by the inference deletion."""
        key = cache_keys.fundamentals("NVDA")
        payload = {**RAW_FUNDAMENTALS_NO_TS, "ts": 1_700_000_000}
        fake = _FakeRedisWithTtl(values={key: json.dumps(payload)}, ttls={key: 13500})
        monkeypatch.setattr("services.stock_service.get_redis", lambda: _areturn(fake))

        resp = TestClient(_import_app()).get(FUNDAMENTALS_PATH)

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["ts"] == 1_700_000_000


def _import_app():
    from main import app
    return app
