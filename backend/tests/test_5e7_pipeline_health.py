"""Tests for workers.pipeline_health — bd:shotockviz-5e7.

"nothing tells the user the data pipeline has died": /api/health and
celery-stats prove a worker answered a ping, not that price_fetcher is
actually producing fresh quotes. This module detects staleness of the
one signal price_fetcher's own round-robin guarantees fresh 24/7 (the
"Overview"/"Crypto" always-on slots — see module docstring in
workers/pipeline_health.py for the full derivation) and fires a Telegram
alert on the ok->stale transition, with a cooldown so an ongoing outage
doesn't spam, plus a recovery message on the stale->ok transition.

Pure-function tests (compute_staleness, message builders) need no I/O.
Integration tests use the same pattern as test_sr_proximity_digest.py:
a tiny real-semantics fake Redis (not a mock that always says "ok", so
the SETNX cooldown guard is actually proven) + a file-based sqlite DB +
httpx.post replaced with a MagicMock so NO test in this file can ever
reach the real Telegram API, even though the real dev DB (outside this
file-based sqlite fixture) has a live telegram_chat_id for user 1.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.database import Base
from models.user import User
from workers.pipeline_health import (
    ALERT_COOLDOWN_SECONDS,
    STALE_THRESHOLD_SECONDS,
    build_down_message,
    build_recovered_message,
    check_pipeline_health,
    compute_staleness,
)

FIXED_NOW_ISO = "2026-09-06T12:00:00+00:00"
FIXED_NOW_TS = 1788696000  # int(datetime.fromisoformat(FIXED_NOW_ISO).timestamp())


def _quote_raw(ts: int) -> bytes:
    return json.dumps({"price": 100.0, "ts": ts}).encode()


# ─────────────────────────────────────────────────────────────────────────────
# compute_staleness — pure
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeStaleness:
    def test_no_canary_data_at_all_is_not_stale_cold_start(self):
        """Empty cache (fresh boot, before any warm-up) must not read as an
        outage — that is what /api/system/ready already covers."""
        status = compute_staleness([None, None], now_ts=FIXED_NOW_TS)
        assert status["has_data"] is False
        assert status["is_stale"] is False

    def test_fresh_quote_just_under_threshold_is_not_stale(self):
        raw = [_quote_raw(FIXED_NOW_TS - (STALE_THRESHOLD_SECONDS - 1))]
        status = compute_staleness(raw, now_ts=FIXED_NOW_TS)
        assert status["has_data"] is True
        assert status["is_stale"] is False

    def test_exactly_at_threshold_is_not_yet_stale(self):
        """Boundary is exclusive: age > threshold, not >=, so a canary that
        refreshes exactly on the worst-case round-robin gap never flaps."""
        raw = [_quote_raw(FIXED_NOW_TS - STALE_THRESHOLD_SECONDS)]
        status = compute_staleness(raw, now_ts=FIXED_NOW_TS)
        assert status["is_stale"] is False

    def test_one_second_past_threshold_is_stale(self):
        raw = [_quote_raw(FIXED_NOW_TS - STALE_THRESHOLD_SECONDS - 1)]
        status = compute_staleness(raw, now_ts=FIXED_NOW_TS)
        assert status["has_data"] is True
        assert status["is_stale"] is True
        assert status["age_seconds"] == STALE_THRESHOLD_SECONDS + 1

    def test_takes_the_newest_of_several_canaries_not_the_first(self):
        """One symbol failing to fetch this cycle (yfinance per-symbol
        try/except) must not falsely trip the alarm while a sibling canary
        is fresh."""
        raw = [
            _quote_raw(FIXED_NOW_TS - 5000),  # stale on its own
            _quote_raw(FIXED_NOW_TS - 10),    # fresh
            None,                              # missing entirely
        ]
        status = compute_staleness(raw, now_ts=FIXED_NOW_TS)
        assert status["is_stale"] is False
        assert status["age_seconds"] == 10

    def test_malformed_json_entry_is_ignored_not_fatal(self):
        raw = [b"not-json", _quote_raw(FIXED_NOW_TS - 5)]
        status = compute_staleness(raw, now_ts=FIXED_NOW_TS)
        assert status["has_data"] is True
        assert status["age_seconds"] == 5

    def test_entry_with_no_ts_field_is_ignored(self):
        raw = [json.dumps({"price": 1.0}).encode()]
        status = compute_staleness(raw, now_ts=FIXED_NOW_TS)
        assert status["has_data"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Message builders — pure
# ─────────────────────────────────────────────────────────────────────────────

class TestMessageBuilders:
    def test_down_message_reports_age_in_minutes(self):
        msg = build_down_message(age_seconds=930)  # 15.5 min
        assert "15" in msg

    def test_recovered_message_is_distinct_from_down_message(self):
        assert build_recovered_message() != build_down_message(700)


# ─────────────────────────────────────────────────────────────────────────────
# Integration — full task against fake redis + file-based sqlite DB
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRedis:
    """Real enough SETNX/GET/DELETE semantics to prove the cooldown guard —
    same rationale as test_sr_proximity_digest.py's _FakeRedis. `ex` is
    accepted but not auto-expired; tests simulate cooldown expiry by
    deleting the lock key directly (see test_second_stale_check_after_
    cooldown_expiry_alerts_again), same technique used throughout this
    suite to avoid a real sleep()."""

    def __init__(self, quotes: dict[str, bytes] | None = None):
        self._store: dict[str, bytes] = {}
        self._quotes = quotes or {}

    def mget(self, keys):
        return [self._quotes.get(k) for k in keys]

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


@pytest.fixture
def sqlite_db_url(tmp_path):
    db_path = tmp_path / "pipeline_health_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all([
            User(email="live@example.com", password_hash="x", display_name="Live", telegram_chat_id="9001"),
            User(email="nochatid@example.com", password_hash="x", display_name="NoChat", telegram_chat_id=None),
            User(email="inactive@example.com", password_hash="x", display_name="Inactive",
                 telegram_chat_id="9002", is_active=False),
        ])
        db.commit()
    engine.dispose()
    return f"sqlite:///{db_path}"


def _stale_quotes():
    from workers.price_fetcher import FALLBACK_IDX
    from core import cache_keys
    # every canary quote is far older than STALE_THRESHOLD_SECONDS
    return {cache_keys.quote(s): _quote_raw(FIXED_NOW_TS - 999_999) for s in FALLBACK_IDX}


def _fresh_quotes():
    from workers.price_fetcher import FALLBACK_IDX
    from core import cache_keys
    return {cache_keys.quote(s): _quote_raw(FIXED_NOW_TS - 5) for s in FALLBACK_IDX}


def _run(sqlite_db_url, fake_redis, mock_post, now_iso=FIXED_NOW_ISO):
    with (
        patch("core.config.settings.database_url", sqlite_db_url),
        patch("core.config.settings.telegram_bot_token", "fake-token"),
        patch("redis.from_url", return_value=fake_redis),
        patch("httpx.post", mock_post),
    ):
        return check_pipeline_health(now_utc_iso=now_iso)


class TestFreshPipelineSendsNothing:
    def test_fresh_canaries_send_no_message(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes=_fresh_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        result = _run(sqlite_db_url, fake_redis, mock_post)
        assert result["is_stale"] is False
        mock_post.assert_not_called()


class TestStaleTransitionAlerts:
    def test_first_stale_check_sends_exactly_one_alert_to_eligible_users_only(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes=_stale_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        result = _run(sqlite_db_url, fake_redis, mock_post)

        assert result["is_stale"] is True
        assert mock_post.call_count == 1
        sent_payload = mock_post.call_args.kwargs["json"]
        assert sent_payload["chat_id"] == "9001"  # only the active user WITH a chat id
        assert "🔴" in sent_payload["text"] or "หยุด" in sent_payload["text"]

    def test_second_stale_check_within_cooldown_sends_nothing_more(self, sqlite_db_url):
        """One ongoing outage must not become N messages."""
        fake_redis = _FakeRedis(quotes=_stale_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        _run(sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1

        _run(sqlite_db_url, fake_redis, mock_post)  # still stale, still within cooldown
        assert mock_post.call_count == 1, "cooldown must suppress the repeat alert"

    def test_second_stale_check_after_cooldown_expiry_alerts_again(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes=_stale_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        _run(sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1

        # Simulate ALERT_COOLDOWN_SECONDS having elapsed (no real sleep —
        # same technique as test_sr_proximity_digest.py's fake-redis tests).
        fake_redis.delete("lock:pipeline_health:price_quotes:alert")

        _run(sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 2, "a reminder must go out once the cooldown has elapsed"

    def test_no_telegram_token_configured_does_not_send_and_does_not_raise(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes=_stale_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", ""),
            patch("redis.from_url", return_value=fake_redis),
            patch("httpx.post", mock_post),
        ):
            result = check_pipeline_health(now_utc_iso=FIXED_NOW_ISO)
        assert result["is_stale"] is True
        mock_post.assert_not_called()

    def test_no_eligible_recipient_sends_nothing_proof_by_user_row_with_no_chat_id(self, tmp_path):
        """Second proof channel required by the task: a DB with zero users
        carrying a telegram_chat_id must produce zero send attempts even
        though the pipeline is stale."""
        db_path = tmp_path / "no_recipients.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(User(email="onlyone@example.com", password_hash="x",
                         display_name="OnlyOne", telegram_chat_id=None))
            db.commit()
        engine.dispose()

        fake_redis = _FakeRedis(quotes=_stale_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        result = _run(f"sqlite:///{db_path}", fake_redis, mock_post)

        assert result["is_stale"] is True
        mock_post.assert_not_called()


class TestRecoveryTransition:
    def test_recovery_after_outage_sends_one_recovered_message_and_resets_lock(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes=_stale_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run(sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 1  # the down alert

        fake_redis._quotes = _fresh_quotes()
        _run(sqlite_db_url, fake_redis, mock_post)
        assert mock_post.call_count == 2  # + one recovery message
        recovered_text = mock_post.call_args.kwargs["json"]["text"]
        assert recovered_text == build_recovered_message()

    def test_a_new_outage_after_recovery_is_not_suppressed_by_the_old_lock(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes=_stale_quotes())
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run(sqlite_db_url, fake_redis, mock_post)          # outage #1 alert
        fake_redis._quotes = _fresh_quotes()
        _run(sqlite_db_url, fake_redis, mock_post)          # recovery
        assert mock_post.call_count == 2

        fake_redis._quotes = _stale_quotes()
        _run(sqlite_db_url, fake_redis, mock_post)          # outage #2 — must alert immediately
        assert mock_post.call_count == 3, (
            "recovery must clear the cooldown lock, or a second real outage "
            "goes unreported until the first outage's cooldown window happens to expire"
        )
