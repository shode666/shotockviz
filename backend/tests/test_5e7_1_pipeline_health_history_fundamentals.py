"""Tests for pipeline_health's extension to fundamentals + history —
bd:shotockviz-5e7.1.

bd:shotockviz-5e7 shipped staleness detection for price quotes only.
This bd added a real `ts` to `fundamentals:{symbol}` (fundamentals_fetcher.py)
and a sibling `{ohlcv_key}:ts` to history (cache_publisher.py). See
workers/pipeline_health.py's module docstring § "bd:shotockviz-5e7.1" for
the full derivation of what follows:

  - Fundamentals IS alerted (Telegram, same lock/cooldown/recovery shape
    as price quotes) — `prefetch_fundamentals` has no cache-freshness
    gate at all, so ITS canary (every active non-FUND/non-CRYPTO symbol)
    legitimately advances every 4h beat, unconditionally. Threshold
    21600s (measured 14400s cadence + assumed 50% margin).

  - History is DIAGNOSTIC ONLY — no lock/down-state keys, no Telegram
    call, `is_stale` deliberately left `None`. `prefetch_history` fills
    cold keys only, so there is no trustworthy non-noisy threshold to
    alert on (see module docstring for the full "why").

Pure-function tests need no I/O. Integration tests reuse
test_5e7_pipeline_health.py's `_FakeRedis` + file-based sqlite pattern,
extended with a `stocks` row (fundamentals canary source) and
watchlist/transaction rows (history canary source).

RED-proof: before this bd's change, `workers.pipeline_health` had no
`FUNDAMENTALS_STALE_THRESHOLD_SECONDS`, `build_fundamentals_down_message`,
`build_fundamentals_recovered_message`, `_newest_ts`, or
`_get_fundamentals_canary_symbols` symbols at all — every test below
failed at collection with `ImportError` before this iteration.
`check_pipeline_health(...)`'s returned dict also had no `"fundamentals"`
or `"history"` key, so `TestPipelineHealthFundamentalsAlerting` and
`TestPipelineHealthHistoryDiagnosticOnly` failed with `KeyError`.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from core import cache_keys
from core.database import Base
from models.user import User
from workers.helpers.cache_publisher import history_ts_key
from workers.pipeline_health import (
    ALERT_COOLDOWN_SECONDS,
    FUNDAMENTALS_STALE_THRESHOLD_SECONDS,
    _newest_ts,
    build_fundamentals_down_message,
    build_fundamentals_recovered_message,
    check_pipeline_health,
)

FIXED_NOW_ISO = "2026-09-06T12:00:00+00:00"
FIXED_NOW_TS = 1788696000  # int(datetime.fromisoformat(FIXED_NOW_ISO).timestamp())


def _fund_raw(ts: int) -> bytes:
    return json.dumps({"symbol": "NVDA", "pe_ratio": 45.2, "ts": ts}).encode()


def _hist_raw(ts: int) -> bytes:
    return json.dumps({"ts": ts}).encode()


# ─────────────────────────────────────────────────────────────────────────────
# _newest_ts — pure
# ─────────────────────────────────────────────────────────────────────────────

class TestNewestTs:
    def test_none_when_nothing_parses(self):
        assert _newest_ts([None, b"not-json"]) is None

    def test_takes_the_max_not_the_first(self):
        raw = [_hist_raw(100), _hist_raw(500), _hist_raw(200)]
        assert _newest_ts(raw) == 500

    def test_ignores_entries_with_no_ts_field(self):
        raw = [json.dumps({"no_ts_here": 1}).encode(), _hist_raw(300)]
        assert _newest_ts(raw) == 300


# ─────────────────────────────────────────────────────────────────────────────
# Fundamentals message builders — pure
# ─────────────────────────────────────────────────────────────────────────────

class TestFundamentalsMessageBuilders:
    def test_down_message_reports_age_in_hours(self):
        msg = build_fundamentals_down_message(age_seconds=3 * 3600)
        assert "3" in msg

    def test_recovered_message_is_distinct_from_down_message(self):
        assert build_fundamentals_recovered_message() != build_fundamentals_down_message(7200)

    def test_fundamentals_messages_are_distinct_from_price_messages(self):
        from workers.pipeline_health import build_down_message, build_recovered_message
        assert build_fundamentals_down_message(3600) != build_down_message(3600)
        assert build_fundamentals_recovered_message() != build_recovered_message()


# ─────────────────────────────────────────────────────────────────────────────
# Integration — full task against fake redis + file-based sqlite DB
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRedis:
    """Same real-enough SETNX/GET/DELETE/MGET semantics as
    test_5e7_pipeline_health.py's fixture, generalized to hold BOTH the
    price-quote canaries and the new fundamentals/history canaries in one
    flat key/value store (mget just looks each key up)."""

    def __init__(self, values: dict[str, bytes] | None = None):
        self._store: dict[str, bytes] = dict(values or {})

    def mget(self, keys):
        return [self._store.get(k) for k in keys]

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    def get(self, key):
        return self._store.get(key)

    def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)


def _fresh_price_quotes():
    from workers.price_fetcher import FALLBACK_IDX
    return {cache_keys.quote(s): json.dumps({"price": 1, "ts": FIXED_NOW_TS - 5}).encode() for s in FALLBACK_IDX}


@pytest.fixture
def sqlite_db_url(tmp_path):
    db_path = tmp_path / "pipeline_health_ext_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(User(email="live@example.com", password_hash="x", display_name="Live", telegram_chat_id="9001"))
        db.commit()

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO stocks (symbol, name, market, is_active) VALUES "
            "('NVDA', 'Nvidia', 'US', true)"
        ))
        conn.execute(text(
            "INSERT INTO watchlists (id, user_id, name, sort_order) VALUES (1, 1, 'Main', 0)"
        ))
        conn.execute(text(
            "INSERT INTO watchlist_items (watchlist_id, symbol, sort_order) VALUES (1, 'AAPL', 0)"
        ))
    engine.dispose()
    return f"sqlite:///{db_path}"


def _run(sqlite_db_url, fake_redis, mock_post, now_iso=FIXED_NOW_ISO):
    with (
        patch("core.config.settings.database_url", sqlite_db_url),
        patch("core.config.settings.telegram_bot_token", "fake-token"),
        patch("redis.from_url", return_value=fake_redis),
        patch("httpx.post", mock_post),
    ):
        return check_pipeline_health(now_utc_iso=now_iso)


class TestPipelineHealthFundamentalsAlerting:
    def test_stale_fundamentals_sends_one_alert(self, sqlite_db_url):
        values = _fresh_price_quotes()
        values[cache_keys.fundamentals("NVDA")] = _fund_raw(
            FIXED_NOW_TS - FUNDAMENTALS_STALE_THRESHOLD_SECONDS - 1
        )
        fake_redis = _FakeRedis(values)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(sqlite_db_url, fake_redis, mock_post)

        assert result["fundamentals"]["is_stale"] is True
        assert mock_post.call_count == 1
        sent_text = mock_post.call_args.kwargs["json"]["text"]
        assert "พื้นฐาน" in sent_text

    def test_fresh_fundamentals_sends_nothing(self, sqlite_db_url):
        values = _fresh_price_quotes()
        values[cache_keys.fundamentals("NVDA")] = _fund_raw(FIXED_NOW_TS - 10)
        fake_redis = _FakeRedis(values)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(sqlite_db_url, fake_redis, mock_post)

        assert result["fundamentals"]["is_stale"] is False
        mock_post.assert_not_called()

    def test_second_stale_check_within_cooldown_sends_nothing_more(self, sqlite_db_url):
        values = _fresh_price_quotes()
        values[cache_keys.fundamentals("NVDA")] = _fund_raw(
            FIXED_NOW_TS - FUNDAMENTALS_STALE_THRESHOLD_SECONDS - 1
        )
        fake_redis = _FakeRedis(values)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        _run(sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1

        _run(sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1, "cooldown must suppress the repeat alert"

    def test_recovery_sends_recovered_message_and_resets_lock(self, sqlite_db_url):
        values = _fresh_price_quotes()
        values[cache_keys.fundamentals("NVDA")] = _fund_raw(
            FIXED_NOW_TS - FUNDAMENTALS_STALE_THRESHOLD_SECONDS - 1
        )
        fake_redis = _FakeRedis(values)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run(sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1

        fake_redis._store[cache_keys.fundamentals("NVDA")] = _fund_raw(FIXED_NOW_TS - 10)
        _run(sqlite_db_url, fake_redis, mock_post)

        assert mock_post.call_count == 2
        recovered_text = mock_post.call_args.kwargs["json"]["text"]
        assert recovered_text == build_fundamentals_recovered_message()

    def test_price_and_fundamentals_alerts_are_independent(self, sqlite_db_url):
        """A stale fundamentals canary with FRESH price quotes must still
        alert — the two pipelines don't share a lock/down-state."""
        from workers.price_fetcher import FALLBACK_IDX
        values = {cache_keys.quote(s): json.dumps({"price": 1, "ts": FIXED_NOW_TS - 5}).encode() for s in FALLBACK_IDX}
        values[cache_keys.fundamentals("NVDA")] = _fund_raw(
            FIXED_NOW_TS - FUNDAMENTALS_STALE_THRESHOLD_SECONDS - 1
        )
        fake_redis = _FakeRedis(values)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(sqlite_db_url, fake_redis, mock_post)

        assert result["is_stale"] is False  # price quotes: healthy
        assert result["fundamentals"]["is_stale"] is True  # fundamentals: down
        assert mock_post.call_count == 1
        assert "พื้นฐาน" in mock_post.call_args.kwargs["json"]["text"]


class TestPipelineHealthHistoryDiagnosticOnly:
    def test_history_status_present_but_never_alerts(self, sqlite_db_url):
        """Even a wildly stale (or totally absent) history canary must
        send zero Telegram messages — see module docstring § History."""
        values = _fresh_price_quotes()
        # No history ts key seeded at all: total silence for history.
        fake_redis = _FakeRedis(values)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(sqlite_db_url, fake_redis, mock_post)

        assert "history" in result
        assert result["history"]["is_stale"] is None  # deliberately unclassified
        assert result["history"]["alerting"] is False
        mock_post.assert_not_called()

    def test_history_reports_age_when_a_sibling_ts_key_exists(self, sqlite_db_url):
        values = _fresh_price_quotes()
        values[history_ts_key(cache_keys.ohlcv("AAPL", "1D"))] = _hist_raw(FIXED_NOW_TS - 40)
        fake_redis = _FakeRedis(values)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(sqlite_db_url, fake_redis, mock_post)

        assert result["history"]["has_data"] is True
        assert result["history"]["age_seconds"] == 40
        assert result["history"]["is_stale"] is None
        mock_post.assert_not_called()

    def test_extremely_stale_history_still_sends_nothing(self, sqlite_db_url):
        """The exact 'no false alarm on a legitimately quiet period'
        requirement: even a multi-day-old history canary must not page
        anyone, because no threshold for it is trusted (see module
        docstring)."""
        values = _fresh_price_quotes()
        values[history_ts_key(cache_keys.ohlcv("AAPL", "1D"))] = _hist_raw(FIXED_NOW_TS - 10 * 86400)
        fake_redis = _FakeRedis(values)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(sqlite_db_url, fake_redis, mock_post)

        assert result["history"]["age_seconds"] == 10 * 86400
        assert result["history"]["is_stale"] is None
        mock_post.assert_not_called()


class TestPipelineHealthPriceResultUnaffected:
    """Backward-compat guard: the flat top-level price-quote keys
    (has_data/newest_ts/age_seconds/is_stale) that
    tests/test_5e7_pipeline_health.py asserts on directly must be
    untouched by this bd's additions — they gain SIBLING keys
    (fundamentals/history), never a shape change."""

    def test_price_flat_keys_survive_alongside_new_nested_keys(self, sqlite_db_url):
        fake_redis = _FakeRedis(_fresh_price_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(sqlite_db_url, fake_redis, mock_post)

        assert set(["has_data", "newest_ts", "age_seconds", "is_stale"]).issubset(result.keys())
        assert result["is_stale"] is False
        assert "fundamentals" in result
        assert "history" in result
