"""Tests for the atomic-claim idempotency fix in workers/alert_checker.py —
bd:features-2026-09 slice 3 (Sara ADR-T3).

Two "concurrent-style" calls to `check_all_alerts()` against one ACTIVE
alert must result in exactly ONE Telegram send — the atomic conditional
UPDATE (`WHERE status='ACTIVE' AND is_active=true`) is the dedupe key.
Uses a file-based sqlite DB (not in-memory) so the sync engine
`check_all_alerts()` creates internally sees the same rows across calls;
redis + httpx are mocked (no real network/broker).
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.database import Base
from models.alert import Alert, AlertChannel, AlertStatus, AlertType
from models.user import User
from workers.alert_checker import _send_telegram_alert, check_all_alerts, claim_alert


@pytest.fixture
def sqlite_db_url(tmp_path):
    db_path = tmp_path / "alert_checker_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = User(
            email="alertuser@example.com",
            password_hash="x",
            display_name="Alert User",
            telegram_chat_id="128845067",
        )
        db.add(user)
        db.flush()

        alert = Alert(
            user_id=user.id,
            symbol="NVDA",
            alert_type=AlertType.PRICE_ABOVE,
            condition="ABOVE",
            value=100.0,
            is_active=True,
            status=AlertStatus.ACTIVE,
            channel=AlertChannel.TELEGRAM,
        )
        db.add(alert)
        db.commit()

    engine.dispose()
    return f"sqlite:///{db_path}"


def _fake_redis():
    """Minimal redis stand-in: quote is always above the alert threshold."""
    import json
    r = MagicMock()
    r.get.return_value = json.dumps({"price": 150.0}).encode()
    r.publish.return_value = 1
    return r


class TestClaimAlertRace:
    """Direct unit test of the atomic-claim mechanism itself — simulates the
    exact race Sara identified: two sessions both already hold the alert as
    ACTIVE in memory (both "read" it before either committed a flip), then
    both attempt the claim. Exactly one must win."""

    def test_two_sessions_race_to_claim_same_alert_only_one_wins(self, sqlite_db_url):
        """Quinn Finding (Critical) — the original version of this test
        called `claim_alert()` sequentially in one thread, which would pass
        identically against the OLD racy read-then-write code too (it never
        actually exercised a race). Fixed: two REAL OS threads, synchronized
        with a `threading.Barrier(2)` so both threads call `claim_alert()`
        at (as close to) the same instant as Python can arrange, each with
        its own `Session`/connection against the same underlying DB file.

        Caveat (documented per Quinn's ask, not duplicating her work): this
        is SQLite, not Postgres. SQLite serializes concurrent writers via
        its own file lock (busy-timeout, not MVCC row-locks) rather than
        Postgres's row-level locking — a WEAKER mechanism than what
        production actually runs on. This test proves `claim_alert()`'s
        SQL-level guard (`WHERE status='ACTIVE'`) correctly rejects a
        second claim even when two threads race to call it concurrently;
        it does NOT prove Postgres-specific concurrent-transaction
        behavior. Quinn's own follow-up (flagged in her review) is the
        live-Postgres load test that closes that gap — this test and hers
        are complementary, not overlapping.
        """
        engine = create_engine(sqlite_db_url, connect_args={"timeout": 30})
        with Session(engine) as db:
            alert_id = db.query(Alert).one().id

        barrier = threading.Barrier(2)
        results = {}

        def _claim(name: str):
            # Own Session/connection per thread — Sessions are not
            # thread-safe to share, and this also models two truly
            # independent processes (two overlapping celery-beat/retry
            # runs), each with its own DB connection.
            session = Session(engine)
            try:
                barrier.wait(timeout=5)  # force both threads to call
                                          # claim_alert() at the same instant
                results[name] = claim_alert(session, alert_id)
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_claim, "a"), pool.submit(_claim, "b")]
            for f in futures:
                f.result(timeout=10)

        engine.dispose()

        won = [results["a"], results["b"]]
        assert won.count(True) == 1, f"expected exactly one winner, got {results}"
        assert won.count(False) == 1

    def test_claim_on_already_triggered_alert_never_wins(self, sqlite_db_url):
        engine = create_engine(sqlite_db_url)
        with Session(engine) as db:
            alert_id = db.query(Alert).one().id
            assert claim_alert(db, alert_id) is True
            # Second claim attempt against the same now-TRIGGERED row.
            assert claim_alert(db, alert_id) is False
        engine.dispose()


class TestConcurrentTriggerIsIdempotent:
    def test_two_overlapping_calls_send_telegram_exactly_once(self, sqlite_db_url):
        """Quinn Finding (Critical) — was two sequential calls in one
        thread (would pass against the old racy code too). Fixed: two real
        threads, `threading.Barrier(2)` forces both to enter
        `check_all_alerts()` at the same instant, each opening its own
        engine/session internally (exactly as two real overlapping
        celery-beat ticks / a retried task would). SQLite-vs-Postgres
        caveat documented on `TestClaimAlertRace` above applies here too."""
        barrier = threading.Barrier(2)

        def _run():
            barrier.wait(timeout=5)
            check_all_alerts()

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", return_value=_fake_redis()),
            patch("httpx.post") as mock_post,
        ):
            mock_post.return_value = MagicMock(status_code=200)

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(_run), pool.submit(_run)]
                for f in futures:
                    f.result(timeout=10)

            assert mock_post.call_count == 1
            sent_chat_id = mock_post.call_args.kwargs["json"]["chat_id"]
            assert sent_chat_id == "128845067"

    def test_alert_ends_up_triggered_and_inactive(self, sqlite_db_url):
        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", return_value=_fake_redis()),
            patch("httpx.post", return_value=MagicMock(status_code=200)),
        ):
            check_all_alerts()

        engine = create_engine(sqlite_db_url)
        with Session(engine) as db:
            alert = db.query(Alert).one()
            assert alert.status == AlertStatus.TRIGGERED
            assert alert.is_active is False
            assert alert.triggered_at is not None
        engine.dispose()


class TestSendTelegramAlertRetryExhausted:
    """Chris Finding 3 (05-dave-telegram-bot.md fix round) — the
    retry-exhausted path in `_send_telegram_alert` (R1, 04-sara-telegram-
    spec.md §9: 1 retry then log ERROR, no outbox) was untested."""

    def test_both_attempts_fail_logs_error_and_does_not_raise(self, sqlite_db_url):
        engine = create_engine(sqlite_db_url)
        with Session(engine) as db:
            alert = db.query(Alert).one()

            with (
                patch("core.config.settings.telegram_bot_token", "fake-token"),
                patch("httpx.post") as mock_post,
            ):
                mock_post.return_value = MagicMock(status_code=400, text="Bad Request: chat not found")
                # Must not raise — a lost send is an accepted at-most-once
                # risk (R1), not a task-crashing error.
                _send_telegram_alert(db, alert, 150.0)

                assert mock_post.call_count == 2

    def test_both_attempts_raise_http_error_logs_error_and_does_not_raise(self, sqlite_db_url):
        engine = create_engine(sqlite_db_url)
        with Session(engine) as db:
            alert = db.query(Alert).one()

            with (
                patch("core.config.settings.telegram_bot_token", "fake-token"),
                patch("httpx.post", side_effect=httpx.ConnectError("Connection refused")),
            ):
                # Should swallow the network error after exhausting retries,
                # not propagate and crash the celery task.
                _send_telegram_alert(db, alert, 150.0)
