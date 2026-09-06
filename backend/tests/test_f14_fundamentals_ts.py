"""bd:shotockviz-f14 — "no cached number says how old it is", fundamentals slice.

`workers/fundamentals_fetcher.py` (out of scope for this bd) never stamps a
`ts` into the cached `fundamentals:{symbol}` payload the way
`cache_publisher.py` does for quotes. `api/routes/stocks/fundamentals.py`
recovers it read-side from the key's remaining TTL instead (fixed 14400s
`setex`, so `elapsed = 14400 - remaining_ttl`).

Hermetic: `services.stock_service.get_redis` is patched with an in-memory
fake exposing just `get`/`ttl` — no live Redis needed. `override_db`
(conftest.py) satisfies `get_optional_user`'s `Depends(get_db)` for the
anonymous request path.

RED-proof (see Dave's hand-off report): before this bd's fix,
`StockFundamentals` had no `ts` field at all, so the response body never
carried the key these tests assert on — `test_ts_derived_from_remaining_ttl`
and `test_ts_present_when_no_ttl_metadata_is_stale` both failed with
`KeyError: 'ts'` / `assert None == <int>`, and the endpoint had nothing to
patch `.ttl(...)` against (the route never called it), so the "ttl -2 -> ts
is None" test failed for the opposite reason: it asserted a behavior with
no code path to reach.
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from core import cache_keys
from main import app

FUNDAMENTALS_PATH = "/api/v1/stocks/NVDA/fundamentals"

RAW_FUNDAMENTALS = {
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
}


class FakeRedis:
    """Just enough of redis.asyncio for the fundamentals read path: get + ttl."""

    def __init__(self, values: dict[str, str], ttls: dict[str, int]):
        self.values = values
        self.ttls = ttls

    async def get(self, key):
        return self.values.get(key)

    async def ttl(self, key):
        return self.ttls.get(key, -2)


@pytest.fixture
def stub_request_fetch(monkeypatch):
    """Fundamentals cache-miss path calls request_data_fetch — no-op it so a
    miss test doesn't try to touch Celery."""
    async def _noop(*a, **kw):
        return None
    monkeypatch.setattr("services.stock_service.request_data_fetch", _noop)


@pytest.mark.usefixtures("override_db")
class TestFundamentalsTsFromTtl:
    def test_ts_derived_from_remaining_ttl(self, monkeypatch):
        """900s have elapsed out of the 14400s TTL (remaining=13500) -> the
        response's ts should be ~900s in the past, not absent/None."""
        key = cache_keys.fundamentals("NVDA")
        fake = FakeRedis(
            values={key: json.dumps(RAW_FUNDAMENTALS)},
            ttls={key: 13500},
        )
        monkeypatch.setattr("services.stock_service.get_redis", lambda: _async_return(fake))

        before = int(time.time())
        resp = TestClient(app).get(FUNDAMENTALS_PATH)
        after = int(time.time())

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["pe_ratio"] == 45.2
        assert "ts" in body
        assert body["ts"] is not None
        expected = before - 900
        # allow a couple seconds of test-runtime slack on both ends
        assert expected - 2 <= body["ts"] <= (after - 900) + 2

    def test_ts_none_when_ttl_metadata_missing(self, monkeypatch):
        """Key has data but no expiry info (ttl() returns -2, e.g. it expired
        in the gap between the read_fundamentals() call and this one) ->
        ts must be None, never a guessed number."""
        key = cache_keys.fundamentals("NVDA")
        fake = FakeRedis(
            values={key: json.dumps(RAW_FUNDAMENTALS)},
            ttls={},  # .get(key, -2) -> -2, "key gone"
        )
        monkeypatch.setattr("services.stock_service.get_redis", lambda: _async_return(fake))

        resp = TestClient(app).get(FUNDAMENTALS_PATH)

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["pe_ratio"] == 45.2  # data itself still served
        assert body["ts"] is None

    def test_ts_none_on_cache_miss(self, monkeypatch, stub_request_fetch):
        """No cached fundamentals at all -> the existing all-null shell,
        and ts is None (nothing to derive an age from)."""
        fake = FakeRedis(values={}, ttls={})
        monkeypatch.setattr("services.stock_service.get_redis", lambda: _async_return(fake))

        resp = TestClient(app).get(FUNDAMENTALS_PATH)

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["pe_ratio"] is None
        assert body["ts"] is None


async def _async_return(value):
    return value
