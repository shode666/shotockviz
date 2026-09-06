"""Tests for workers/fundamentals_fetcher.py stamping a real `ts` —
bd:shotockviz-5e7.1.

`StockFundamentals` (models/schemas.py) already reserved an Optional
`ts` field for this (bd:shotockviz-f14), but nothing ever wrote it —
`api/routes/stocks/fundamentals.py`'s `data.get("ts")` was always None,
falling through to the (weaker) TTL-inferred estimate on every request.
This proves `prefetch_fundamentals` now sets `ts=int(time.time())` on
every successful fetch, giving pipeline_health a real signal to check.

Hermetic: yfinance, Redis, and the DB are all faked/seeded — no live
network or Postgres needed.

RED-proof: before this bd's change, `StockFundamentals(...)` inside
`prefetch_fundamentals` was constructed with no `ts=` kwarg, so the
cached JSON blob never had a `"ts"` key at all —
`test_cached_payload_carries_a_real_ts_field` failed with
`assert "ts" in payload` (KeyError on `payload["ts"]`), and
`test_ts_advances_between_two_successive_runs` failed the same way on
its first assertion, before this iteration.
"""
from __future__ import annotations

import json

from sqlalchemy import create_engine, text

from core.database import Base
from workers import fundamentals_fetcher


def _seed_one_active_us_stock(tmp_path):
    db_path = tmp_path / "fundamentals_ts_stamp_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO stocks (symbol, name, market, is_active) VALUES "
            "('NVDA', 'Nvidia', 'US', true)"
        ))
    engine.dispose()
    return f"sqlite:///{db_path}"


class _FakeTicker:
    def __init__(self, info):
        self.info = info


_SAMPLE_INFO = {
    "trailingPE": 45.2, "priceToBook": 30.1, "trailingEps": 2.5,
    "dividendYield": 0.001, "marketCap": 3_000_000_000_000,
    "beta": 1.6, "fiftyTwoWeekHigh": 150.0, "fiftyTwoWeekLow": 60.0,
    "averageVolume": 250_000_000,
}


class _FakeTickers:
    """Stands in for yfinance.Tickers(" ".join(symbols))."""

    def __init__(self, symbols_str):
        self.tickers = {s: _FakeTicker(dict(_SAMPLE_INFO)) for s in symbols_str.split()}


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def setex(self, key, ttl, value):
        self.store[key] = value

    def publish(self, channel, message):
        pass


def _run_prefetch(sqlite_url, fake_redis, frozen_time, monkeypatch):
    monkeypatch.setattr("core.config.settings.database_url", sqlite_url)
    monkeypatch.setattr("redis.from_url", lambda *_a, **_kw: fake_redis)
    monkeypatch.setattr("yfinance.Tickers", lambda syms: _FakeTickers(syms))
    monkeypatch.setattr("time.time", lambda: frozen_time)
    fundamentals_fetcher.prefetch_fundamentals()


class TestFundamentalsFetcherStampsRealTs:
    def test_cached_payload_carries_a_real_ts_field(self, tmp_path, monkeypatch):
        sqlite_url = _seed_one_active_us_stock(tmp_path)
        fake_redis = _FakeRedis()

        _run_prefetch(sqlite_url, fake_redis, 1_700_000_000.0, monkeypatch)

        cached = fake_redis.store.get("fundamentals:NVDA")
        assert cached is not None
        payload = json.loads(cached)
        assert payload["ts"] == 1_700_000_000
        assert payload["pe_ratio"] == 45.2

    def test_ts_advances_between_two_successive_runs(self, tmp_path, monkeypatch):
        """The exact property pipeline_health's fundamentals check
        depends on: a live stamp that moves forward on each successful
        run, not a value fixed once at import/construction time."""
        sqlite_url = _seed_one_active_us_stock(tmp_path)
        fake_redis = _FakeRedis()

        _run_prefetch(sqlite_url, fake_redis, 1_700_000_000.0, monkeypatch)
        first_ts = json.loads(fake_redis.store["fundamentals:NVDA"])["ts"]

        _run_prefetch(sqlite_url, fake_redis, 1_700_014_400.0, monkeypatch)  # +4h
        second_ts = json.loads(fake_redis.store["fundamentals:NVDA"])["ts"]

        assert second_ts - first_ts == 14400

    def test_no_active_symbols_writes_nothing_not_even_a_ts(self, tmp_path, monkeypatch):
        """Empty `stocks` table (nothing active/non-FUND/non-CRYPTO) must
        short-circuit before ever touching Redis — same "cold start is
        not an outage" convention pipeline_health itself uses."""
        db_path = tmp_path / "empty.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        engine.dispose()
        fake_redis = _FakeRedis()

        _run_prefetch(f"sqlite:///{db_path}", fake_redis, 1_700_000_000.0, monkeypatch)

        assert fake_redis.store == {}
