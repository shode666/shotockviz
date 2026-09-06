"""bd:shotockviz-f14 — GET /{symbol}/quote's fund-NAV fallback branch (L1.5)
didn't forward `ts`, even though `fund_fetcher.py:424` stamps a real one
into `fund:{symbol}` and the sibling batch endpoint's own fund_nav branch
(`GET /quotes`, same file) already forwards it via `fund_data.get("ts", 0)`.
A fund symbol reached through this single-quote path therefore had no way
to say how old its NAV was — `getPriceFreshness()` (statusBar.ts,
bd:shotockviz-09j) receives `ts=None` and reports "unknown" for a number
that is, in fact, knowable.

Hermetic: `services.stock_service.get_redis` and `.read_quote` are patched
so no live Redis is needed. No DB dependency on this route.

RED-proof: before this bd's fix, the fund_nav branch's returned dict had no
"ts" key at all, so `test_single_quote_fund_nav_forwards_ts` failed with
`KeyError: 'ts'` (see Dave's hand-off report for the actual run).
"""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.middleware.rate_limit import RateLimitMiddleware
from core import cache_keys
from main import app

SINGLE_PATH = "/api/v1/stocks/SCBS&P500/quote"

FUND_PAYLOAD = {"nav": 12.3456, "date": "2026-09-05", "ts": 1_757_030_400}


class FakeStockRedis:
    def __init__(self, values: dict[str, str]):
        self.values = values

    async def get(self, key):
        return self.values.get(key)


class FakeRateLimitRedis:
    """Just enough of redis.asyncio for RateLimitMiddleware — same shape as
    test_quotes_rate_limit.py's FakeRedis (this endpoint sits behind the
    same middleware, which needs a working Redis of its own regardless of
    what stock_service.get_redis is patched to)."""

    async def incr(self, key):
        return 1

    async def expire(self, key, ttl):
        return True

    async def ttl(self, key):
        return 42


@pytest.fixture
def fake_rate_limit_redis():
    fake = FakeRateLimitRedis()
    async def _get_redis(_self):
        return fake
    with patch.object(RateLimitMiddleware, "get_redis", _get_redis):
        yield fake


@pytest.fixture
def stub_no_quote_cache(monkeypatch):
    """Force the L1 `read_quote()` miss so the handler falls through to the
    L1.5 fund-NAV branch under test."""
    async def _none(*a, **kw):
        return None
    monkeypatch.setattr("services.stock_service.read_quote", _none)


def test_single_quote_fund_nav_forwards_ts(monkeypatch, stub_no_quote_cache, fake_rate_limit_redis):
    fake = FakeStockRedis({cache_keys.fund("SCBS&P500"): json.dumps(FUND_PAYLOAD)})

    async def _get_redis():
        return fake
    monkeypatch.setattr("services.stock_service.get_redis", _get_redis)

    resp = TestClient(app).get(SINGLE_PATH)

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["type"] == "fund_nav"
    assert body["price"] == 12.3456
    assert body["ts"] == 1_757_030_400
