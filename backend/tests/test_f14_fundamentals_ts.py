"""bd:shotockviz-f14 — "no cached number says how old it is", fundamentals slice.

UPDATED by bd:shotockviz-f14.2: the TTL-derived inference this file
originally tested (`api/routes/stocks/fundamentals.py`'s now-deleted
`_fundamentals_as_of_ts`, keyed off the Redis key's remaining TTL) has
been removed — all three writers of `fundamentals:{symbol}` stamp a real
`ts` at write time now (`workers/fundamentals_fetcher.py`,
`workers/on_demand_listener.py:_fetch_fundamentals`,
`services/cache_orchestrator.py`'s two write sites), so a guess that can
be removed was removed rather than kept as a labelled fallback. See
`tests/test_f14_2_fundamentals_ts_writers.py` for the writer-side
RED-proof and the `TestInferenceDeleted` class that proves the deletion
itself (both the route's behavior and the removed module symbols).

`test_ts_derived_from_remaining_ttl` below is renamed to
`test_ts_stays_none_despite_live_remaining_ttl` and its assertion flipped
to match: a payload with no stamped `ts` now returns `ts=None`
regardless of how much TTL is left on the key, because there is no
inference left to derive one from.

Hermetic: `services.stock_service.get_redis` is patched with an in-memory
fake exposing just `get`/`ttl` — no live Redis needed. `override_db`
(conftest.py) satisfies `get_optional_user`'s `Depends(get_db)` for the
anonymous request path.

RED-proof (original, bd:shotockviz-f14): before that bd's fix,
`StockFundamentals` had no `ts` field at all, so the response body never
carried the key these tests assert on.

RED-proof (this update, bd:shotockviz-f14.2): before this update,
`test_ts_stays_none_despite_live_remaining_ttl` (as
`test_ts_derived_from_remaining_ttl`) asserted `body["ts"] is not None`
against a live TTL — which passed against the pre-fix inference and now
fails it (`assert None is not None`) once the inference path is
deleted; see `docker-compose ... pytest tests/test_f14_fundamentals_ts.py -q`
in Dave's f14.2 hand-off report for the actual run showing that single
failure isolated from the other two (unaffected) tests in this file.
"""
import json

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
    def test_ts_stays_none_despite_live_remaining_ttl(self, monkeypatch):
        """900s have elapsed out of a live 14400s TTL (remaining=13500) —
        that used to be enough for the now-deleted TTL inference to
        produce a non-None ts. With no cached `ts` field and the
        inference gone, the response must return ts=None: a live TTL is
        no longer treated as a signal for anything."""
        key = cache_keys.fundamentals("NVDA")
        fake = FakeRedis(
            values={key: json.dumps(RAW_FUNDAMENTALS)},
            ttls={key: 13500},
        )
        monkeypatch.setattr("services.stock_service.get_redis", lambda: _async_return(fake))

        resp = TestClient(app).get(FUNDAMENTALS_PATH)

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["pe_ratio"] == 45.2
        assert "ts" in body
        assert body["ts"] is None

    def test_ts_none_when_ttl_metadata_missing(self, monkeypatch):
        """Key has data but no expiry info (ttl() returns -2, e.g. it expired
        in the gap between the read_fundamentals() call and this one) ->
        ts must be None, never a guessed number. (Unaffected by the
        bd:shotockviz-f14.2 inference deletion: this was already the
        expected value, for a different reason before — the inference
        function used to also return None here.)"""
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
