"""Tests for cache_and_publish_history()'s sibling `:ts` key — bd:shotockviz-5e7.1.

`ohlcv:{symbol}:{tf}` stays a bare JSON *list* (never wrapped in a dict):
`services/cache_orchestrator.py` and `workers/on_demand_listener.py` (both
out of this bd's file scope) `setex` that SAME key with a raw
`json.dumps(bars)` list, and `workers/alert_checker.py:_load_daily_bars`
hard-gates on `isinstance(bars, list)` — a wrapped payload would silently
stop every indicator alert (golden/death cross, RSI) the moment
history_prefetcher's write won the race. The real fetch time goes into a
companion key instead: `history_ts_key(cache_key)` = `{cache_key}:ts`,
holding `{"ts": <epoch seconds>}` (same shape `cache_and_publish_quotes()`
uses for quotes, line ~36 above it in the same file).

RED-proof: before this bd's change, `workers/helpers/cache_publisher.py`
had no `history_ts_key` symbol at all and `cache_and_publish_history()`
called `redis_client.setex` exactly once. Every test below failed before
this iteration — the two `history_ts_key` tests with
`ImportError: cannot import name 'history_ts_key'`, and
`test_sibling_ts_key_is_written_alongside_bars` /
`test_sibling_ts_value_is_a_real_epoch_second_int` /
`test_sibling_key_uses_the_same_ttl_as_the_primary_key` with
`AssertionError` / `KeyError` because `r.store` only ever contained the
one primary key.
"""
from __future__ import annotations

import json
import time

from workers.helpers.cache_publisher import cache_and_publish_history, history_ts_key

_SAMPLE_BARS = [
    {"time": "2026-01-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100},
]


class FakeRedis:
    def __init__(self):
        self.store: dict[str, tuple[int, str]] = {}
        self.published: list[tuple[str, str]] = []

    def setex(self, key, ttl, value):
        self.store[key] = (ttl, value)

    def publish(self, channel, message):
        self.published.append((channel, message))


class TestHistoryTsKey:
    def test_ts_key_is_suffix_of_primary_key(self):
        assert history_ts_key("ohlcv:AAPL:1D") == "ohlcv:AAPL:1D:ts"

    def test_ts_key_is_distinct_per_symbol_and_timeframe(self):
        assert history_ts_key("ohlcv:AAPL:1D") != history_ts_key("ohlcv:AAPL:1W")
        assert history_ts_key("ohlcv:AAPL:1D") != history_ts_key("ohlcv:MSFT:1D")


class TestCacheAndPublishHistoryStampsTs:
    def test_sibling_ts_key_is_written_alongside_bars(self):
        r = FakeRedis()
        cache_and_publish_history(r, "ohlcv:AAPL:1D", _SAMPLE_BARS, ttl=21600)

        assert "ohlcv:AAPL:1D" in r.store
        assert "ohlcv:AAPL:1D:ts" in r.store

    def test_primary_key_still_holds_a_bare_list_not_a_dict(self):
        """alert_checker._load_daily_bars hard-gates on isinstance(bars,
        list) — this contract must never regress to a wrapped dict."""
        r = FakeRedis()
        cache_and_publish_history(r, "ohlcv:AAPL:1D", _SAMPLE_BARS, ttl=21600)

        _, primary_raw = r.store["ohlcv:AAPL:1D"]
        decoded = json.loads(primary_raw)
        assert isinstance(decoded, list)
        assert decoded == _SAMPLE_BARS

    def test_sibling_ts_value_is_a_real_epoch_second_int(self, monkeypatch):
        monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
        r = FakeRedis()
        cache_and_publish_history(r, "ohlcv:AAPL:1D", _SAMPLE_BARS, ttl=21600)

        _, sibling_raw = r.store["ohlcv:AAPL:1D:ts"]
        assert json.loads(sibling_raw) == {"ts": 1_700_000_000}

    def test_sibling_key_uses_the_same_ttl_as_the_primary_key(self):
        r = FakeRedis()
        cache_and_publish_history(r, "ohlcv:AAPL:1D", _SAMPLE_BARS, ttl=999)

        assert r.store["ohlcv:AAPL:1D"][0] == 999
        assert r.store["ohlcv:AAPL:1D:ts"][0] == 999

    def test_no_bars_writes_neither_key(self):
        """Existing early-return contract (`if not bars: return`) must
        cover the sibling key too — no data means no timestamp claim."""
        r = FakeRedis()
        cache_and_publish_history(r, "ohlcv:AAPL:1D", [], ttl=21600)

        assert r.store == {}

    def test_ts_advances_between_two_successive_writes(self, monkeypatch):
        """The property pipeline_health actually depends on: a live
        stamp, not a value frozen at import time."""
        r = FakeRedis()
        monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
        cache_and_publish_history(r, "ohlcv:AAPL:1D", _SAMPLE_BARS, ttl=21600)
        first = json.loads(r.store["ohlcv:AAPL:1D:ts"][1])["ts"]

        monkeypatch.setattr(time, "time", lambda: 1_700_003_600.0)
        cache_and_publish_history(r, "ohlcv:AAPL:1D", _SAMPLE_BARS, ttl=21600)
        second = json.loads(r.store["ohlcv:AAPL:1D:ts"][1])["ts"]

        assert second - first == 3600
