"""bd:shotockviz-f14.1 — "as-of is still missing on screener computed
columns and the news list", news slice.

`workers/news_fetcher.py`'s `_fetch_news_for_symbol` now stamps a
`ts` (epoch seconds it fetched the RSS feed) alongside the article list
in the `news:{symbol}` Redis key, same pattern as `cache_publisher.py`
does for quotes. `api/routes/stocks/news_events.py`'s `GET /{symbol}/news`
must forward that as a real, distinct fact from each article's own
`published_at` — never conflate "how stale is this list" with "how old is
this headline".

Hermetic: `services.stock_service.get_redis` is patched with an in-memory
async fake (get/set only, the two calls this route path makes) — no live
Redis needed. `override_db` (conftest.py) satisfies `get_optional_user`'s
`Depends(get_db)` for the anonymous request path.

RED-proof (see Dave's hand-off report): before this bd's fix, the route
returned the cached JSON list AS the response body directly (a bare JSON
array), so `resp.json()["data"]` was a `list`, not a `dict` —
`test_ts_forwarded_from_cache_entry` failed with
`TypeError: list indices must be integers or slices, not str` on
`body["ts"]`, and `_fetch_news_for_symbol`'s written payload was a bare
list (no `ts` key at all), so
`test_news_fetcher_stamps_ts_at_write_time` failed on
`assert "ts" in cached_payload` — plain `AssertionError: False`.
"""
import json
import time as time_module

import pytest
from fastapi.testclient import TestClient

from core import cache_keys
from main import app

NEWS_PATH = "/api/v1/stocks/NVDA/news"

ARTICLE = {
    "title": "Nvidia beats earnings expectations",
    "url": "https://example.com/nvda-earnings",
    "source": "Reuters",
    "published_at": "Fri, 01 Jan 2026 09:00:00 GMT",
    "summary": "...",
}


class FakeRedis:
    """Just enough of redis.asyncio for the news read path: get + set."""

    def __init__(self, values: dict[str, str] | None = None):
        self.values = values or {}
        self.set_calls: list[str] = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None, nx=None):
        self.set_calls.append(key)
        return True


async def _async_return(value):
    return value


@pytest.mark.usefixtures("override_db")
class TestNewsRouteTs:
    def test_ts_forwarded_from_cache_entry(self, monkeypatch):
        """New-shape cache entry {"articles": [...], "ts": N} -> the route
        forwards both, and articles keep their own `published_at` untouched
        (list-level ts and per-article published_at are different fields)."""
        key = cache_keys.news("NVDA")
        fetched_at = 1_700_000_000
        fake = FakeRedis(values={
            key: json.dumps({"articles": [ARTICLE], "ts": fetched_at}),
        })
        monkeypatch.setattr("services.stock_service.get_redis", lambda: _async_return(fake))

        resp = TestClient(app).get(NEWS_PATH)

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["ts"] == fetched_at
        assert body["articles"] == [ARTICLE]
        assert body["articles"][0]["published_at"] == ARTICLE["published_at"]

    def test_legacy_bare_list_cache_entry_gets_ts_none_not_fabricated(self, monkeypatch):
        """A cache entry written before this bd (bare list, no ts) can
        still be live within its 30min TTL right after deploy. Must be
        read honestly — ts is genuinely unknown for that entry, not
        invented from e.g. the current time."""
        key = cache_keys.news("NVDA")
        fake = FakeRedis(values={key: json.dumps([ARTICLE])})
        monkeypatch.setattr("services.stock_service.get_redis", lambda: _async_return(fake))

        resp = TestClient(app).get(NEWS_PATH)

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["articles"] == [ARTICLE]
        assert body["ts"] is None

    def test_cache_miss_returns_empty_articles_and_ts_none(self, monkeypatch):
        """No cached news at all -> empty list + ts None (nothing was
        fetched yet, so there is nothing to date). Also triggers the
        on-demand Celery fetch, stubbed out here."""
        fake = FakeRedis(values={})
        monkeypatch.setattr("services.stock_service.get_redis", lambda: _async_return(fake))
        monkeypatch.setattr("workers.news_fetcher.fetch_news_on_demand.delay", lambda *a, **kw: None)

        resp = TestClient(app).get(NEWS_PATH)

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["articles"] == []
        assert body["ts"] is None


class FakeFeed:
    """Just enough of a feedparser FeedParserDict for `_fetch_news_for_symbol`:
    truthy, has `.entries`."""

    def __init__(self, entries):
        self.entries = entries

    def __bool__(self):
        return True


class FakeSyncRedis:
    """Just enough of the sync `redis` client `_fetch_news_for_symbol` uses
    (it's called from a Celery task, not the async API path)."""

    def __init__(self):
        self.store: dict[str, tuple[int, str]] = {}

    def setex(self, key, ttl, value):
        self.store[key] = (ttl, value)


class TestNewsFetcherStampsTs:
    def test_news_fetcher_stamps_ts_at_write_time(self, monkeypatch):
        """`_fetch_news_for_symbol` must cache {"articles": [...], "ts": N}
        with N = the real fetch time, not a bare article list."""
        from workers import news_fetcher

        fixed_now = 1_800_000_000
        monkeypatch.setattr(time_module, "time", lambda: fixed_now)
        monkeypatch.setattr(
            "feedparser.parse",
            lambda url: FakeFeed([{
                "title": "Nvidia rallies on AI demand",
                "link": "https://example.com/nvda",
                "source": {"title": "Bloomberg"},
                "published": "Fri, 01 Jan 2026 09:00:00 GMT",
                "summary": "...",
            }]),
        )
        redis_client = FakeSyncRedis()

        count = news_fetcher._fetch_news_for_symbol("NVDA", redis_client)

        assert count == 1
        key = cache_keys.news("NVDA")
        assert key in redis_client.store
        _ttl, raw = redis_client.store[key]
        cached_payload = json.loads(raw)
        assert "ts" in cached_payload
        assert cached_payload["ts"] == fixed_now
        assert cached_payload["articles"][0]["title"] == "Nvidia rallies on AI demand"
        # per-article published_at must survive untouched, distinct from
        # the list-level fetch-time ts
        assert cached_payload["articles"][0]["published_at"] == "Fri, 01 Jan 2026 09:00:00 GMT"

    def test_news_fetcher_stamps_ts_even_when_no_articles_found(self, monkeypatch):
        """Empty result set (no news) is still a valid, real fetch — it
        must still get a real ts, not be skipped/left un-stamped."""
        from workers import news_fetcher

        fixed_now = 1_800_000_500
        monkeypatch.setattr(time_module, "time", lambda: fixed_now)
        monkeypatch.setattr("feedparser.parse", lambda url: FakeFeed([]))
        redis_client = FakeSyncRedis()

        count = news_fetcher._fetch_news_for_symbol("EMPTYCO", redis_client)

        assert count == 0
        key = cache_keys.news("EMPTYCO")
        _ttl, raw = redis_client.store[key]
        cached_payload = json.loads(raw)
        assert cached_payload["articles"] == []
        assert cached_payload["ts"] == fixed_now
