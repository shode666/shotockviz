"""Tests for workers.housekeeping.run_housekeeping — bd:shotockviz-s3k.

Two defects reproduced + fixed here:
  1. `ohlcv_bars` retention (5m/1d rules) used `time < NOW() - INTERVAL`
     against `time_unix` (a BigInteger of unix seconds, not a timestamp)
     -> raised on every real-DB run -> retention silently deleted zero
     rows, forever. A retention test that only checks "it ran without
     raising" would NOT catch this; it must assert the row count actually
     dropped.
  2. All rules shared one `engine.begin()` transaction, so one rule
     raising rolled back a DIFFERENT, otherwise-successful rule too.

Same monkeypatch-sync-engine-to-SQLite pattern as
tests/test_sr_auto_pivot.py's `sync_sqlite_engine` fixture — housekeeping
uses a sync sqlalchemy engine built from `core.config.settings`, which is
also patched here.
"""
from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import create_engine, text

from core.database import Base
from models.ohlcv import OHLCVBar  # noqa: F401 — registers ohlcv_bars on Base.metadata

from workers.housekeeping import RETENTION_CONFIG_KEY, run_housekeeping


class _FakeRedis:
    """Only implements .get() for RETENTION_CONFIG_KEY — all housekeeping needs."""

    def __init__(self, payload: str | None = None):
        self._payload = payload

    def get(self, key):
        return self._payload if key == RETENTION_CONFIG_KEY else None


@pytest.fixture
def hk_sqlite_engine(monkeypatch, tmp_path):
    """File-backed SQLite DB (housekeeping uses sync create_engine per call,
    ':memory:' loses state across connections) standing in for dev Postgres."""
    db_path = tmp_path / "housekeeping_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    class _FakeSettings:
        sync_database_url = f"sqlite:///{db_path}"
        redis_url = "redis://fake-not-used"

    import core.config as core_config
    monkeypatch.setattr(core_config, "settings", _FakeSettings())

    import redis as redis_lib
    monkeypatch.setattr(redis_lib, "from_url", lambda *a, **k: _FakeRedis(None))

    yield engine
    engine.dispose()


def _insert_ohlcv_row(engine, symbol: str, timeframe: str, time_unix: int, close: float = 100.0):
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO ohlcv_bars "
            "(symbol, timeframe, time_unix, time_str, open, high, low, close, volume) "
            "VALUES (:symbol, :timeframe, :time_unix, :time_str, :open, :high, :low, :close, :volume)"
        ), {
            "symbol": symbol, "timeframe": timeframe, "time_unix": time_unix,
            "time_str": str(time_unix), "open": close, "high": close, "low": close,
            "close": close, "volume": 1000,
        })


def _row_count(engine, timeframe: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM ohlcv_bars WHERE timeframe = :tf"), {"tf": timeframe}
        ).scalar()


def _set_policy(monkeypatch, policy: list[dict]):
    """DEFAULT_POLICY includes a '1m' rule against stock_prices_1m using
    Postgres-only `NOW() - INTERVAL` syntax, which SQLite (this test's
    stand-in engine) cannot parse — that rule already worked fine against
    real Postgres pre-fix and is not part of bd:shotockviz-s3k, so these
    tests set an explicit ohlcv_bars-only policy rather than relying on
    the default and tripping an unrelated dialect mismatch."""
    import redis as redis_lib
    monkeypatch.setattr(redis_lib, "from_url", lambda *a, **k: _FakeRedis(json.dumps(policy)))


class TestHousekeepingActuallyDeletes:
    """Regression guard for defect #1 — asserts a real row-count drop, not
    just 'the task returned without raising' (a passing task that deletes
    zero rows is exactly the bug that shipped)."""

    def test_1d_rule_deletes_rows_past_730_day_retention(self, hk_sqlite_engine, monkeypatch):
        engine = hk_sqlite_engine
        _set_policy(monkeypatch, [{"resolution": "1d", "max_age_days": 730}])

        now = int(time.time())
        stale_ts = now - (800 * 86400)   # older than 730-day 1d retention
        fresh_ts = now - (1 * 86400)     # well within retention
        _insert_ohlcv_row(engine, "TEST.SEED", "1D", stale_ts)
        _insert_ohlcv_row(engine, "TEST.SEED", "1D", fresh_ts)

        assert _row_count(engine, "1D") == 2  # before

        result = run_housekeeping()

        assert _row_count(engine, "1D") == 1  # after — only the fresh row survives
        assert result["deleted_total"] == 1
        assert result.get("rule_errors", []) == []

    def test_5m_rule_deletes_rows_past_90_day_retention(self, hk_sqlite_engine, monkeypatch):
        engine = hk_sqlite_engine
        _set_policy(monkeypatch, [{"resolution": "5m", "max_age_days": 90}])

        now = int(time.time())
        stale_ts = now - (120 * 86400)   # older than 90-day 5m retention
        fresh_ts = now - (1 * 86400)
        _insert_ohlcv_row(engine, "TEST.SEED", "5m", stale_ts)
        _insert_ohlcv_row(engine, "TEST.SEED", "5m", fresh_ts)

        assert _row_count(engine, "5m") == 2  # before

        result = run_housekeeping()

        assert _row_count(engine, "5m") == 1  # after
        assert result["deleted_total"] == 1
        assert result.get("rule_errors", []) == []

    def test_no_eligible_rows_deletes_zero_and_says_so(self, hk_sqlite_engine, monkeypatch):
        """Zero deleted is only correct when there is nothing eligible —
        distinguishes 'nothing to delete' from the silent-no-op bug."""
        engine = hk_sqlite_engine
        _set_policy(monkeypatch, [{"resolution": "1d", "max_age_days": 730}])

        fresh_ts = int(time.time()) - (1 * 86400)
        _insert_ohlcv_row(engine, "TEST.SEED", "1D", fresh_ts)

        result = run_housekeeping()

        assert _row_count(engine, "1D") == 1  # untouched
        assert result["deleted_total"] == 0
        assert result.get("rule_errors", []) == []


class TestHousekeepingRuleIsolation:
    """Regression guard for defect #2 — one rule raising must not roll back
    or block a different rule's successful delete."""

    def test_one_failing_rule_does_not_roll_back_a_different_successful_rule(
        self, hk_sqlite_engine, monkeypatch,
    ):
        engine = hk_sqlite_engine
        now = int(time.time())
        stale_1d = now - (800 * 86400)
        _insert_ohlcv_row(engine, "TEST.SEED", "1D", stale_1d)

        # "5m" rule is deliberately malformed (non-numeric max_age_days ->
        # raises inside that rule's own try block) and is listed BEFORE the
        # working "1d" rule, so a shared-transaction bug would roll back
        # the 1d delete too.
        broken_policy = [
            {"resolution": "5m", "max_age_days": "not-a-number"},
            {"resolution": "1d", "max_age_days": 730},
        ]
        import redis as redis_lib
        monkeypatch.setattr(
            redis_lib, "from_url", lambda *a, **k: _FakeRedis(json.dumps(broken_policy)),
        )

        result = run_housekeeping()

        # The broken 5m rule failed and was recorded...
        assert any(e["resolution"] == "5m" for e in result["rule_errors"])
        # ...but the 1d rule's delete still committed.
        assert _row_count(engine, "1D") == 0
        assert result["deleted_total"] == 1
