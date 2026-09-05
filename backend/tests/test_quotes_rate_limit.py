"""bd:shotockviz-3du / CHRIS-11 — per-IP rate limit on the quote endpoints.

Hermetic: RateLimitMiddleware.get_redis is patched with an in-memory
counter, so these tests exercise the middleware's own logic (path match,
tier selection, window, 429 envelope) without a live Redis. The
end-to-end proof against the running dev stack (real Redis, real Caddy)
is curl evidence in the bd notes.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.middleware.rate_limit import RateLimitMiddleware
from core.security import create_access_token
from main import app

BATCH_PATH = "/api/v1/stocks/quotes?symbols=NVDA"
SINGLE_PATH = "/api/v1/stocks/NVDA/quote"


class FakeRedis:
    """Just enough of redis.asyncio for the middleware: incr/expire/ttl."""

    def __init__(self):
        self.counters: dict[str, int] = {}

    async def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key, ttl):
        return True

    async def ttl(self, key):
        return 42


@pytest.fixture
def fake_redis():
    fake = FakeRedis()
    async def _get_redis(_self):
        return fake
    with patch.object(RateLimitMiddleware, "get_redis", _get_redis):
        yield fake


@pytest.fixture
def stub_stock_service():
    """Quote handlers touch Redis/DB via stock_service — stub the reads so
    only the middleware behavior is under test."""
    async def _none(*a, **kw):
        return None
    with patch("services.stock_service.read_quote", _none), \
         patch("services.stock_service.get_redis", side_effect=RuntimeError("no redis in test")), \
         patch("services.stock_service.request_data_fetch", _none):
        yield


class TestQuotePathMatcher:
    def test_matches_batch_and_single(self):
        assert RateLimitMiddleware._is_quote_path("/api/v1/stocks/quotes")
        assert RateLimitMiddleware._is_quote_path("/api/v1/stocks/NVDA/quote")
        assert RateLimitMiddleware._is_quote_path("/api/v1/stocks/PTT.BK/quote")

    def test_does_not_match_other_routes(self):
        assert not RateLimitMiddleware._is_quote_path("/api/v1/stocks/NVDA/history")
        assert not RateLimitMiddleware._is_quote_path("/api/v1/auth/google")
        assert not RateLimitMiddleware._is_quote_path("/api/health")


class TestAnonQuoteRateLimit:
    def test_anon_limited_after_30_per_minute(self, fake_redis, stub_stock_service):
        client = TestClient(app)
        statuses = [
            client.get(BATCH_PATH).status_code
            for _ in range(RateLimitMiddleware.QUOTES_ANON_LIMIT + 1)
        ]
        assert all(s != 429 for s in statuses[:-1]), statuses
        assert statuses[-1] == 429

    def test_429_uses_envelope_and_retry_after(self, fake_redis, stub_stock_service):
        client = TestClient(app)
        for _ in range(RateLimitMiddleware.QUOTES_ANON_LIMIT):
            client.get(SINGLE_PATH)
        resp = client.get(SINGLE_PATH)
        assert resp.status_code == 429
        body = resp.json()
        assert body["data"] is None and "error" in body["meta"]
        assert resp.headers.get("retry-after") == "42"

    def test_single_and_batch_share_one_bucket(self, fake_redis, stub_stock_service):
        client = TestClient(app)
        for _ in range(RateLimitMiddleware.QUOTES_ANON_LIMIT):
            client.get(BATCH_PATH)
        assert client.get(SINGLE_PATH).status_code == 429


class TestAuthedQuoteRateLimit:
    def test_valid_bearer_gets_auth_tier_bucket(self, fake_redis, stub_stock_service):
        token = create_access_token({"sub": "1", "role": "user"})
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}
        # 31st authed request still fine (auth limit is 120)
        statuses = [
            client.get(BATCH_PATH, headers=headers).status_code
            for _ in range(RateLimitMiddleware.QUOTES_ANON_LIMIT + 1)
        ]
        assert all(s != 429 for s in statuses), statuses
        assert any(k.startswith("rate:quotes:auth:") for k in fake_redis.counters)

    def test_garbage_bearer_counts_as_anon(self, fake_redis, stub_stock_service):
        """An attacker cannot self-upgrade to the 120/min tier with a fake
        token — signature check gates the tier."""
        client = TestClient(app)
        headers = {"Authorization": "Bearer not-a-real-token"}
        for _ in range(RateLimitMiddleware.QUOTES_ANON_LIMIT):
            client.get(BATCH_PATH, headers=headers)
        assert client.get(BATCH_PATH, headers=headers).status_code == 429
        assert not any(k.startswith("rate:quotes:auth:") for k in fake_redis.counters)

    def test_authed_hits_limit_at_120(self, fake_redis, stub_stock_service):
        token = create_access_token({"sub": "1", "role": "user"})
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}
        for _ in range(RateLimitMiddleware.QUOTES_AUTH_LIMIT):
            client.get(BATCH_PATH, headers=headers)
        assert client.get(BATCH_PATH, headers=headers).status_code == 429
