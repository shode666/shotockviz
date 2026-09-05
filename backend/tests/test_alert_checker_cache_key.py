"""Regression test for bd:shotockviz-983 — alert_checker.py hand-built its
Redis quote key ("cache:quote:{sym}") instead of going through
core.cache_keys.quote() (which produces "quote:{sym}", the format
workers/helpers/cache_publisher.py:38 actually writes under). The prefix
mismatch meant the checker read a Redis key that never existed, so every
alert on every cycle silently no-op'd via `if not cached: continue` — no
log, no error, no metric.

This test fails if a future change re-introduces a hand-built key: it
asserts the *exact* key `redis.get()` was called with, both against the
single source of truth (`cache_keys.quote()`) and against a hardcoded
literal, so a hand-rolled string that happens to still match
`cache_keys.quote()`'s current output would still be caught the moment
the format in cache_keys.py changes but the hand-rolled copy doesn't.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core import cache_keys
from core.database import Base
from models.alert import Alert, AlertChannel, AlertStatus, AlertType
from models.user import User
from workers.alert_checker import check_all_alerts


@pytest.fixture
def sqlite_db_url(tmp_path):
    """Same pattern as test_alert_checker_idempotency.py's fixture — a
    file-based sqlite DB so the sync engine check_all_alerts() creates
    internally sees the same rows."""
    db_path = tmp_path / "alert_checker_cache_key_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = User(
            email="cachekeytest@example.com",
            password_hash="x",
            display_name="Cache Key Test User",
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
            channel=AlertChannel.EMAIL,  # no Telegram send needed for this test
        )
        db.add(alert)
        db.commit()

    engine.dispose()
    return f"sqlite:///{db_path}"


def test_alert_checker_looks_up_quote_via_cache_keys_builder(sqlite_db_url):
    """The only correct key is cache_keys.quote("NVDA") == "quote:NVDA".
    A hand-built f"cache:quote:{symbol}" (the actual bug) or any other
    drifted prefix must fail this assertion.
    """
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps({"price": 150.0}).encode()
    fake_redis.publish.return_value = 1

    with (
        patch("core.config.settings.database_url", sqlite_db_url),
        patch("redis.from_url", return_value=fake_redis),
    ):
        check_all_alerts()

    assert fake_redis.get.call_count == 1
    called_key = fake_redis.get.call_args.args[0]

    # Against the single source of truth...
    assert called_key == cache_keys.quote("NVDA")
    # ...and pinned to the literal format, so a change to cache_keys.py
    # that silently drifts the format is also caught here.
    assert called_key == "quote:NVDA"
    # The historical bug's exact wrong key must NOT be what was queried.
    assert called_key != "cache:quote:NVDA"


def test_alert_checker_logs_on_cache_miss(sqlite_db_url):
    """bd:shotockviz-983 — a cache miss must be visible (structlog
    warning), not a silent `continue`. Does not test retry/backfill
    behaviour (explicitly out of scope).

    structlog is configured with PrintLoggerFactory (core/logger.py), not
    stdlib logging, so pytest's `caplog` fixture cannot observe it —
    patching `workers.alert_checker.logger` directly is the reliable way
    to assert a log call happened.
    """
    fake_redis = MagicMock()
    fake_redis.get.return_value = None  # cache miss

    with (
        patch("core.config.settings.database_url", sqlite_db_url),
        patch("redis.from_url", return_value=fake_redis),
        patch("workers.alert_checker.logger") as mock_logger,
    ):
        check_all_alerts()

    assert mock_logger.warning.call_count == 1, (
        f"expected exactly one warning log on cache miss, "
        f"got calls: {mock_logger.warning.call_args_list}"
    )
    warning_msg = mock_logger.warning.call_args.args[0]
    assert "no cached quote" in warning_msg.lower()
    warning_kwargs = mock_logger.warning.call_args.kwargs
    assert warning_kwargs["symbol"] == "NVDA"
    assert warning_kwargs["cache_key"] == "quote:NVDA"
