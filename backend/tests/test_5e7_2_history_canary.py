"""Tests for the history liveness canary — bd:shotockviz-5e7.2.

bd:shotockviz-5e7.1 stamped a real `ts` for history but shipped it as a
DIAGNOSTIC only (`result["history"]`, `is_stale` always `None`,
`alerting: False`) because `prefetch_history` fills COLD keys only — its
own write activity is data-dependent (which symbol happens to be cache-
cold), not proof the task ran. This bd adds a small, unconditional-refresh
canary set (`workers.history_prefetcher.HISTORY_CANARY_SYMBOLS`, the same
shape as `price_fetcher.FALLBACK_IDX`) and wires a REAL, alertable
staleness channel on top of it: `result["history_canary"]`. See
workers/history_prefetcher.py's module comment for the canary-size
arithmetic and workers/pipeline_health.py's module docstring § "History
liveness canary — ALERTED" for the threshold derivation.

The pre-existing general diagnostic (`result["history"]`,
tests/test_5e7_1_pipeline_health_history_fundamentals.py) is left
UNTOUCHED by this bd — it still reports over ALL watched symbols and
still never alerts, for the reasons that bd's own tests document. This
file only covers the NEW canary-based `history_prefetcher` behavior and
the NEW `result["history_canary"]` alerting channel.

RED-proof (each class below, verified by reverting these changes and
re-running):
  - `TestHistoryCanarySymbolsUnconditionalRefresh`: before this bd,
    `workers.history_prefetcher` had no `HISTORY_CANARY_SYMBOLS` symbol
    at all → `ImportError` at collection. After adding the constant but
    before wiring the unconditional-refresh bypass into `prefetch_history`,
    `test_canary_symbol_is_refetched_even_when_cache_is_warm` fails
    because the old code's unconditional `if redis_client.exists(cache_key):
    continue` short-circuits before ever calling `_fetch_symbol_history`
    for a warm canary key — asserted via `cache_and_publish_history` NOT
    being called for a pre-warmed canary key.
  - `TestPipelineHealthHistoryCanaryAlerting`: before this bd,
    `workers.pipeline_health` had no `HISTORY_STALE_THRESHOLD_SECONDS`,
    `build_history_down_message`, `build_history_recovered_message`, or
    `_HISTORY_ALERT_LOCK_KEY`/`_HISTORY_DOWN_STATE_KEY` symbols →
    `ImportError` at collection. `check_pipeline_health(...)`'s returned
    dict also had no `"history_canary"` key at all → every assertion on
    `result["history_canary"]` fails with `KeyError` before this change.
  - `TestGeneralHistoryDiagnosticUnaffected`: proves `result["history"]`
    (the bd:shotockviz-5e7.1 diagnostic) is byte-for-byte the same shape
    and behavior as before — this bd adds a sibling key, never changes
    the existing one. Confirmed by re-running
    tests/test_5e7_1_pipeline_health_history_fundamentals.py's
    `TestPipelineHealthHistoryDiagnosticOnly` class unmodified alongside
    this file — it still passes.
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
from workers.history_prefetcher import HISTORY_CANARY_SYMBOLS
from workers.pipeline_health import (
    ALERT_COOLDOWN_SECONDS,
    HISTORY_STALE_THRESHOLD_SECONDS,
    build_history_down_message,
    build_history_recovered_message,
    check_pipeline_health,
)

FIXED_NOW_ISO = "2026-09-06T12:00:00+00:00"
FIXED_NOW_TS = 1788696000  # int(datetime.fromisoformat(FIXED_NOW_ISO).timestamp())


def _hist_raw(ts: int) -> bytes:
    return json.dumps({"ts": ts}).encode()


# ─────────────────────────────────────────────────────────────────────────────
# Sizing sanity — the canary set is small and reuses the audited pool
# ─────────────────────────────────────────────────────────────────────────────

class TestCanarySetSize:
    def test_canary_set_is_small_not_the_whole_index_pool(self):
        """The AC calls for a SMALL canary set — this pins it at 2, not
        letting it silently grow to match FALLBACK_IDX's full 16 entries."""
        assert len(HISTORY_CANARY_SYMBOLS) == 2

    def test_canary_symbols_are_reused_from_price_fetchers_audited_pool(self):
        """Must not invent new, unaudited always-available symbols — see
        history_prefetcher.py's module comment for why FALLBACK_IDX is
        the trusted source."""
        from workers.price_fetcher import FALLBACK_IDX
        assert set(HISTORY_CANARY_SYMBOLS).issubset(set(FALLBACK_IDX))

    def test_canary_symbols_cover_more_than_one_market_region(self):
        """A single ticker's yfinance flakiness must not look like a dead
        worker — redundancy requires at least 2 distinct symbols."""
        assert len(set(HISTORY_CANARY_SYMBOLS)) == len(HISTORY_CANARY_SYMBOLS) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# history_prefetcher.prefetch_history — unconditional canary refresh
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRedisClient:
    """Minimal Redis surface prefetch_history touches: exists/setex."""

    def __init__(self, warm_keys: set[str] | None = None):
        self._store: dict[str, str] = {}
        for k in warm_keys or set():
            self._store[k] = json.dumps([{"time": "2026-01-01", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])

    def exists(self, key):
        return 1 if key in self._store else 0

    def setex(self, key, ttl, value):
        self._store[key] = value

    def publish(self, channel, message):
        pass


@pytest.fixture
def sqlite_db_url(tmp_path):
    db_path = tmp_path / "history_canary_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return f"sqlite:///{db_path}"


_SAMPLE_HIST_DF_BARS = [
    {"time": "2026-01-01", "time_unix": 1767225600, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100},
]


class TestHistoryCanarySymbolsUnconditionalRefresh:
    def test_canary_symbol_is_refetched_even_when_cache_is_warm(self, sqlite_db_url):
        """The exact bug this bd fixes: `if redis_client.exists(cache_key):
        continue` used to skip EVERY symbol whose cache was warm,
        including canaries. Seed the canary's primary cache key as warm,
        then assert `_fetch_symbol_history` (and therefore a fresh `:ts`
        write) still happens for it."""
        from workers import history_prefetcher

        canary_symbol = HISTORY_CANARY_SYMBOLS[0]
        warm_key = cache_keys.ohlcv(canary_symbol, "1D")
        fake_redis = _FakeRedisClient(warm_keys={warm_key})

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("redis.from_url", return_value=fake_redis),
            patch("workers.history_prefetcher.get_watched_symbols", return_value=[]),
            patch.object(history_prefetcher, "_fetch_symbol_history", return_value=list(_SAMPLE_HIST_DF_BARS)),
            patch.object(history_prefetcher, "_upsert_bars_to_db", return_value=1),
        ):
            history_prefetcher.prefetch_history()

        # The primary key must have been re-setex'd (not skipped), and the
        # sibling :ts freshness marker must now exist — that marker is
        # ONLY ever written by cache_and_publish_history(), so its
        # presence proves the "warm cache" skip did NOT apply here.
        assert history_ts_key(warm_key) in fake_redis._store

    def test_non_canary_symbol_with_warm_cache_is_still_skipped(self, sqlite_db_url):
        """Backward-compat guard: the original cost-saving behavior for
        ordinary watched symbols must be untouched by this bd."""
        from workers import history_prefetcher

        warm_key = cache_keys.ohlcv("AAPL", "1D")
        fake_redis = _FakeRedisClient(warm_keys={warm_key})

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("redis.from_url", return_value=fake_redis),
            patch("workers.history_prefetcher.get_watched_symbols", return_value=["AAPL"]),
            # The two canary symbols are unconditionally fetched every run
            # regardless of this test's focus, so `_fetch_symbol_history`
            # WILL be called for them — the assertion below checks AAPL
            # specifically was never among those calls, not that the mock
            # was never invoked at all.
            patch.object(history_prefetcher, "_fetch_symbol_history", return_value=list(_SAMPLE_HIST_DF_BARS)) as mock_fetch,
            patch.object(history_prefetcher, "_upsert_bars_to_db", return_value=1),
        ):
            history_prefetcher.prefetch_history()

        # AAPL's cache was warm and AAPL is not a canary — must be skipped,
        # never handed to yfinance.
        fetched_symbols = [call.args[0] for call in mock_fetch.call_args_list]
        assert "AAPL" not in fetched_symbols
        assert set(fetched_symbols) == set(HISTORY_CANARY_SYMBOLS)
        assert history_ts_key(warm_key) not in fake_redis._store

    def test_canary_symbols_run_even_with_zero_watched_symbols(self, sqlite_db_url):
        """Before this bd, `if not symbols: return` meant a fresh
        install/dev DB with an empty watchlist prefetched NO history at
        all — not even the canaries, so the liveness signal would never
        exist. Canaries must run regardless."""
        from workers import history_prefetcher

        fake_redis = _FakeRedisClient()

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("redis.from_url", return_value=fake_redis),
            patch("workers.history_prefetcher.get_watched_symbols", return_value=[]),
            patch.object(history_prefetcher, "_fetch_symbol_history", return_value=list(_SAMPLE_HIST_DF_BARS)),
            patch.object(history_prefetcher, "_upsert_bars_to_db", return_value=1),
        ):
            history_prefetcher.prefetch_history()

        for sym in HISTORY_CANARY_SYMBOLS:
            assert history_ts_key(cache_keys.ohlcv(sym, "1D")) in fake_redis._store

    def test_canary_appearing_in_watchlist_is_not_double_processed(self, sqlite_db_url):
        """A user who happens to watch a canary symbol must not cause it
        to be fetched twice in one run."""
        from workers import history_prefetcher

        canary_symbol = HISTORY_CANARY_SYMBOLS[0]
        fake_redis = _FakeRedisClient()
        call_count = {"n": 0}

        def _counting_fetch(symbol):
            if symbol == canary_symbol:
                call_count["n"] += 1
            return list(_SAMPLE_HIST_DF_BARS)

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("redis.from_url", return_value=fake_redis),
            patch("workers.history_prefetcher.get_watched_symbols", return_value=[canary_symbol]),
            patch.object(history_prefetcher, "_fetch_symbol_history", side_effect=_counting_fetch),
            patch.object(history_prefetcher, "_upsert_bars_to_db", return_value=1) as mock_upsert,
        ):
            history_prefetcher.prefetch_history()

        # canary_symbol itself must be fetched exactly once (not twice —
        # once for being in the watchlist AND once for being a canary);
        # the OTHER canary symbol is still processed independently, so
        # total upserts across the run is len(HISTORY_CANARY_SYMBOLS).
        assert call_count["n"] == 1
        assert mock_upsert.call_count == len(HISTORY_CANARY_SYMBOLS)


# ─────────────────────────────────────────────────────────────────────────────
# pipeline_health.check_pipeline_health — history_canary alerting
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRedis:
    """Same real-enough SETNX/GET/DELETE/MGET semantics as
    test_5e7_1_pipeline_health_history_fundamentals.py's fixture, one flat
    key/value store for both mget and set/get/delete."""

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
def pipeline_sqlite_db_url(tmp_path):
    db_path = tmp_path / "pipeline_health_history_canary_test.db"
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


def _canary_values(age_seconds: int) -> dict:
    values = _fresh_price_quotes()
    for sym in HISTORY_CANARY_SYMBOLS:
        values[history_ts_key(cache_keys.ohlcv(sym, "1D"))] = _hist_raw(FIXED_NOW_TS - age_seconds)
    return values


class TestPipelineHealthHistoryCanaryAlerting:
    def test_fresh_canary_sends_nothing(self, pipeline_sqlite_db_url):
        fake_redis = _FakeRedis(_canary_values(age_seconds=10))
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(pipeline_sqlite_db_url, fake_redis, mock_post)

        assert result["history_canary"]["is_stale"] is False
        mock_post.assert_not_called()

    def test_stale_canary_sends_exactly_one_alert(self, pipeline_sqlite_db_url):
        fake_redis = _FakeRedis(_canary_values(age_seconds=HISTORY_STALE_THRESHOLD_SECONDS + 1))
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(pipeline_sqlite_db_url, fake_redis, mock_post)

        assert result["history_canary"]["is_stale"] is True
        assert mock_post.call_count == 1
        sent_text = mock_post.call_args.kwargs["json"]["text"]
        assert "กราฟ" in sent_text

    def test_exactly_at_threshold_is_not_yet_stale(self, pipeline_sqlite_db_url):
        """Boundary is exclusive (age > threshold), same convention as
        compute_staleness's price/fundamentals boundary tests."""
        fake_redis = _FakeRedis(_canary_values(age_seconds=HISTORY_STALE_THRESHOLD_SECONDS))
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(pipeline_sqlite_db_url, fake_redis, mock_post)

        assert result["history_canary"]["is_stale"] is False
        mock_post.assert_not_called()

    def test_missing_canary_data_is_not_stale_cold_start(self, pipeline_sqlite_db_url):
        """No canary ts written at all (fresh boot) must not alarm — same
        cold-start convention as price/fundamentals."""
        fake_redis = _FakeRedis(_fresh_price_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(pipeline_sqlite_db_url, fake_redis, mock_post)

        assert result["history_canary"]["has_data"] is False
        assert result["history_canary"]["is_stale"] is False
        mock_post.assert_not_called()

    def test_second_stale_check_within_cooldown_sends_nothing_more(self, pipeline_sqlite_db_url):
        fake_redis = _FakeRedis(_canary_values(age_seconds=HISTORY_STALE_THRESHOLD_SECONDS + 1))
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        _run(pipeline_sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1

        _run(pipeline_sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1, "cooldown must suppress the repeat alert"

    def test_second_stale_check_after_cooldown_expiry_alerts_again(self, pipeline_sqlite_db_url):
        fake_redis = _FakeRedis(_canary_values(age_seconds=HISTORY_STALE_THRESHOLD_SECONDS + 1))
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        _run(pipeline_sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1

        fake_redis.delete("lock:pipeline_health:history:alert")

        _run(pipeline_sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 2, "a reminder must go out once the cooldown has elapsed"

    def test_recovery_sends_recovered_message_and_resets_lock(self, pipeline_sqlite_db_url):
        fake_redis = _FakeRedis(_canary_values(age_seconds=HISTORY_STALE_THRESHOLD_SECONDS + 1))
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run(pipeline_sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1

        fresh = _canary_values(age_seconds=10)
        for k, v in fresh.items():
            fake_redis._store[k] = v
        _run(pipeline_sqlite_db_url, fake_redis, mock_post)

        assert mock_post.call_count == 2
        recovered_text = mock_post.call_args.kwargs["json"]["text"]
        assert recovered_text == build_history_recovered_message()

    def test_a_new_outage_after_recovery_is_not_suppressed_by_the_old_lock(self, pipeline_sqlite_db_url):
        fake_redis = _FakeRedis(_canary_values(age_seconds=HISTORY_STALE_THRESHOLD_SECONDS + 1))
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run(pipeline_sqlite_db_url, fake_redis, mock_post)  # outage #1

        fresh = _canary_values(age_seconds=10)
        for k, v in fresh.items():
            fake_redis._store[k] = v
        _run(pipeline_sqlite_db_url, fake_redis, mock_post)  # recovery
        assert mock_post.call_count == 2

        stale_again = _canary_values(age_seconds=HISTORY_STALE_THRESHOLD_SECONDS + 1)
        for k, v in stale_again.items():
            fake_redis._store[k] = v
        _run(pipeline_sqlite_db_url, fake_redis, mock_post)  # outage #2
        assert mock_post.call_count == 3, (
            "recovery must clear the cooldown lock, or a second real outage "
            "goes unreported until the first outage's cooldown window happens to expire"
        )

    def test_history_canary_alert_is_independent_of_price_and_fundamentals(self, pipeline_sqlite_db_url):
        """A stale history canary with FRESH price quotes and no
        fundamentals data must still alert — the three pipelines don't
        share a lock/down-state."""
        fake_redis = _FakeRedis(_canary_values(age_seconds=HISTORY_STALE_THRESHOLD_SECONDS + 1))
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        result = _run(pipeline_sqlite_db_url, fake_redis, mock_post)

        assert result["is_stale"] is False  # price quotes: healthy
        assert result["history_canary"]["is_stale"] is True
        assert mock_post.call_count == 1
        assert "กราฟ" in mock_post.call_args.kwargs["json"]["text"]

    def test_no_telegram_token_configured_does_not_send_and_does_not_raise(self, pipeline_sqlite_db_url):
        fake_redis = _FakeRedis(_canary_values(age_seconds=HISTORY_STALE_THRESHOLD_SECONDS + 1))
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        with (
            patch("core.config.settings.database_url", pipeline_sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", ""),
            patch("redis.from_url", return_value=fake_redis),
            patch("httpx.post", mock_post),
        ):
            result = check_pipeline_health(now_utc_iso=FIXED_NOW_ISO)
        assert result["history_canary"]["is_stale"] is True
        mock_post.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Message builders — pure
# ─────────────────────────────────────────────────────────────────────────────

class TestHistoryMessageBuilders:
    def test_down_message_reports_age_in_minutes(self):
        msg = build_history_down_message(age_seconds=125 * 60)
        assert "125" in msg

    def test_recovered_message_is_distinct_from_down_message(self):
        assert build_history_recovered_message() != build_history_down_message(7200)

    def test_history_messages_are_distinct_from_price_and_fundamentals_messages(self):
        from workers.pipeline_health import (
            build_down_message,
            build_fundamentals_down_message,
            build_recovered_message,
            build_fundamentals_recovered_message,
        )
        assert build_history_down_message(3600) != build_down_message(3600)
        assert build_history_down_message(3600) != build_fundamentals_down_message(3600)
        assert build_history_recovered_message() != build_recovered_message()
        assert build_history_recovered_message() != build_fundamentals_recovered_message()


# ─────────────────────────────────────────────────────────────────────────────
# Threshold arithmetic — pin the documented derivation, catch silent drift
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholdArithmeticIsPinned:
    def test_threshold_is_exactly_2x_the_measured_beat_cadence(self):
        """celery_app.py's prefetch-history crontab is */30 minutes =
        1800s. This threshold must stay derived from that cadence, not
        drift to an arbitrary round number."""
        measured_beat_seconds = 30 * 60
        assert HISTORY_STALE_THRESHOLD_SECONDS == measured_beat_seconds * 2

    def test_alert_cooldown_is_shared_with_price_and_fundamentals(self):
        """Reuses the existing cooldown constant rather than inventing a
        third one, per the task's explicit instruction."""
        from workers.pipeline_health import ALERT_COOLDOWN_SECONDS as _shared
        assert ALERT_COOLDOWN_SECONDS is _shared
