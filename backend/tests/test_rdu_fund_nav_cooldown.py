"""bd:shotockviz-rdu — a standing PRICE_ABOVE/PRICE_BELOW alert on a Thai
fund re-fires every cooldown window (60 min, `settings.alert_cooldown_minutes`)
against a NAV that only changes once a day (T+1, `fund_fetcher` runs once at
19:00 ICT). Up to ~24 identical Telegram messages for one crossing event.
Equity alerts don't have this problem because the live quote's own `ts`
advances far faster than the cooldown window; a fund's `ts` does not advance
until the next day's fetch.

Fix (option (a) — see workers/alert_checker.py::claim_alert docstring for
the reasoning that decided it over option (b), refusing to arm fund price
alerts): `claim_alert()` now ALSO requires the compared value's own as-of
(`ts` on the quote-shaped dict — forwarded from `fund_payload_to_quote()`
for funds, stamped by `cache_and_publish_quotes()` for equities) to be
newer than the alert's own last `triggered_at`, on top of (not instead of)
the existing wall-clock cooldown. No new cooldown constant, no new column —
`triggered_at` is reused for both purposes it already had the data for.

Every test here either passes `claim_alert()` an explicit `now`/`value_ts`
(fully clock-injected, no real-wall-clock dependency), or rewinds
`triggered_at` by a controlled offset from `datetime.now()` — the exact
idiom `tests/test_alert_checker_idempotency.py` already uses to simulate
"cooldown has elapsed" without a real wait. No test depends on live data,
another test's rows, or which real calendar day it runs on.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core import cache_keys
from core.config import settings
from core.database import Base
from models.alert import Alert, AlertChannel, AlertStatus, AlertType
from models.user import User
from workers.alert_checker import check_all_alerts, claim_alert

FUND_SYMBOL = "SCBS&P500"
EQUITY_SYMBOL = "NVDA"


@pytest.fixture
def sqlite_db_url(tmp_path):
    """One FUND PRICE_ABOVE alert, condition permanently satisfiable
    (threshold 10.0, fake NAV 12.0) — same file-based-sqlite pattern as
    test_alert_checker_idempotency.py so the sync engine check_all_alerts()
    creates internally sees the same rows across repeated calls."""
    db_path = tmp_path / "rdu_fund_cooldown_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = User(
            email="rdufundtest@example.com",
            password_hash="x",
            display_name="RDU Fund Test User",
            telegram_chat_id="999000111",
        )
        db.add(user)
        db.flush()

        fund_alert = Alert(
            user_id=user.id,
            symbol=FUND_SYMBOL,
            alert_type=AlertType.PRICE_ABOVE,
            condition="ABOVE",
            value=10.0,
            is_active=True,
            status=AlertStatus.ACTIVE,
            channel=AlertChannel.TELEGRAM,
        )
        db.add(fund_alert)
        db.commit()

    engine.dispose()
    return f"sqlite:///{db_path}"


def _fake_redis_fund(nav_ts: int, nav: float = 12.0):
    """quote:{symbol} misses (funds are not dual-written into it since
    bd:shotockviz-3ir); fund:{symbol} carries a NAV above the alert's
    threshold, stamped with a fixed `ts` — exactly the shape
    `services/fund_quote.py::fund_payload_to_quote()` reads."""
    fund_payload = json.dumps({
        "symbol": FUND_SYMBOL,
        "nav": nav,
        "date": "2026-09-05",
        "ts": nav_ts,
    }).encode()

    def _get(key):
        if key == cache_keys.quote(FUND_SYMBOL):
            return None
        if key == cache_keys.fund(FUND_SYMBOL):
            return fund_payload
        return None

    r = MagicMock()
    r.get.side_effect = _get
    r.publish.return_value = 1
    return r


def _rewind_triggered_at(engine, symbol: str, minutes: int):
    """Simulate "time has passed since the last fire" without a real
    wait — same technique test_alert_checker_idempotency.py's
    test_second_fire_after_cooldown_elapses_re_notifies already uses."""
    with Session(engine) as db:
        db.query(Alert).filter(Alert.symbol == symbol).update(
            {"triggered_at": datetime.now(timezone.utc) - timedelta(minutes=minutes)}
        )
        db.commit()


class TestFundAlertRefiresAtMostOncePerNav:
    """The bead's own reproduction, at the `check_all_alerts()` /
    Telegram-send level."""

    def test_24_hourly_ticks_against_unchanged_nav_send_one_message_not_24(
        self, sqlite_db_url
    ):
        """The core claim of this bead: 24 hourly checks against ONE NAV
        publication (fund_fetcher runs once a day) must produce exactly
        ONE Telegram send, not one per elapsed cooldown."""
        fixed_nav_ts = int(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc).timestamp())
        fake_redis = _fake_redis_fund(nav_ts=fixed_nav_ts)
        engine = create_engine(sqlite_db_url)

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", return_value=fake_redis),
            patch("httpx.post") as mock_post,
        ):
            mock_post.return_value = MagicMock(status_code=200)

            for _hour in range(24):
                check_all_alerts()
                # Wall-clock cooldown alone would allow the NEXT tick to
                # re-fire — only the (unchanged) NAV ts should stop it.
                _rewind_triggered_at(
                    engine, FUND_SYMBOL, settings.alert_cooldown_minutes + 1
                )

        engine.dispose()
        assert mock_post.call_count == 1, (
            f"expected exactly 1 Telegram send across 24 hourly ticks "
            f"against an unchanged NAV, got {mock_post.call_count} — a "
            f"fund alert is re-firing once per cooldown instead of once "
            f"per NAV publication"
        )

    def test_nav_actually_updating_the_next_day_does_re_fire(self, sqlite_db_url):
        """Must not become a one-shot: once fund_fetcher writes a
        genuinely NEW NAV (a later `ts`), the alert is eligible again —
        proving this is option (a), not option (b) in disguise."""
        day1_ts = int(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc).timestamp())
        day2_ts = int(datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc).timestamp())
        engine = create_engine(sqlite_db_url)

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", return_value=_fake_redis_fund(nav_ts=day1_ts)),
            patch("httpx.post") as mock_post,
        ):
            mock_post.return_value = MagicMock(status_code=200)
            check_all_alerts()  # day 1 fire
        assert mock_post.call_count == 1

        _rewind_triggered_at(engine, FUND_SYMBOL, settings.alert_cooldown_minutes + 1)

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", return_value=_fake_redis_fund(nav_ts=day2_ts)),
            patch("httpx.post") as mock_post2,
        ):
            mock_post2.return_value = MagicMock(status_code=200)
            check_all_alerts()  # day 2 fire — genuinely new NAV

        engine.dispose()
        assert mock_post2.call_count == 1

    def test_cooldown_still_applies_within_the_same_nav(self, sqlite_db_url):
        """Even the first re-check inside the cooldown window (condition
        held, same NAV, `triggered_at` NOT rewound) must not re-fire —
        pre-existing cooldown behaviour, unchanged by this bead, checked
        here so the new value_ts gate is proven additive."""
        fixed_ts = int(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc).timestamp())

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", return_value=_fake_redis_fund(nav_ts=fixed_ts)),
            patch("httpx.post") as mock_post,
        ):
            mock_post.return_value = MagicMock(status_code=200)
            check_all_alerts()
            check_all_alerts()  # same tick basically, cooldown not elapsed

        assert mock_post.call_count == 1


class TestClaimAlertValueTsGate:
    """Unit-level tests directly against claim_alert()'s new `value_ts`/
    `now` parameters — isolates the eligibility rule from Celery/Redis/
    Telegram plumbing entirely. `now` is always passed explicitly."""

    @pytest.fixture
    def alert_id(self, sqlite_db_url):
        engine = create_engine(sqlite_db_url)
        with Session(engine) as db:
            aid = db.query(Alert).filter(Alert.symbol == FUND_SYMBOL).one().id
        engine.dispose()
        return aid

    def test_first_claim_wins_regardless_of_value_ts(self, sqlite_db_url, alert_id):
        engine = create_engine(sqlite_db_url)
        base = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        with Session(engine) as db:
            won = claim_alert(db, alert_id, value_ts=base, now=base)
        engine.dispose()
        assert won is True

    def test_second_claim_same_value_ts_after_cooldown_elapsed_is_refused(
        self, sqlite_db_url, alert_id
    ):
        engine = create_engine(sqlite_db_url)
        t0 = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(minutes=settings.alert_cooldown_minutes + 1)
        with Session(engine) as db:
            assert claim_alert(db, alert_id, value_ts=t0, now=t0) is True
            # Wall-clock cooldown alone has elapsed (t1 - t0 > cooldown)
            # but the compared value (value_ts) is UNCHANGED — this is
            # the bead's exact defect shape.
            won = claim_alert(db, alert_id, value_ts=t0, now=t1)
        engine.dispose()
        assert won is False

    def test_second_claim_newer_value_ts_after_cooldown_elapsed_wins(
        self, sqlite_db_url, alert_id
    ):
        engine = create_engine(sqlite_db_url)
        t0 = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(minutes=settings.alert_cooldown_minutes + 1)
        t2 = t1 + timedelta(minutes=1)  # a genuinely newer compared value
        with Session(engine) as db:
            assert claim_alert(db, alert_id, value_ts=t0, now=t0) is True
            won = claim_alert(db, alert_id, value_ts=t2, now=t1)
        engine.dispose()
        assert won is True

    def test_value_ts_none_falls_back_to_cooldown_only_behaviour(
        self, sqlite_db_url, alert_id
    ):
        """No freshness signal available (indicator alerts today, or any
        quote payload missing `ts`) must behave EXACTLY as before this
        bead — cooldown alone decides eligibility. Guards against the
        fix silently becoming mandatory and breaking a caller that has
        no `ts` to give it."""
        engine = create_engine(sqlite_db_url)
        t0 = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(minutes=settings.alert_cooldown_minutes + 1)
        with Session(engine) as db:
            assert claim_alert(db, alert_id, value_ts=None, now=t0) is True
            won = claim_alert(db, alert_id, value_ts=None, now=t1)
        engine.dispose()
        assert won is True


class TestEquityAlertUnaffected:
    """Equities aren't funds: the live quote's own `ts` advances on every
    fetch cycle (~1-6 min), far faster than the 60-min cooldown, so
    gating on value_ts must NOT change equity behaviour — this is the
    existing, deliberately-kept "re-notify while condition holds" design
    (see workers/alert_checker.py's module docstring)."""

    @pytest.fixture
    def equity_sqlite_db_url(self, tmp_path):
        db_path = tmp_path / "rdu_equity_unaffected_test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(
                email="rduequitytest@example.com",
                password_hash="x",
                display_name="RDU Equity Test User",
                telegram_chat_id="999000222",
            )
            db.add(user)
            db.flush()
            alert = Alert(
                user_id=user.id,
                symbol=EQUITY_SYMBOL,
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

    def test_equity_alert_still_refires_every_cooldown_when_quote_refreshes(
        self, equity_sqlite_db_url
    ):
        engine = create_engine(equity_sqlite_db_url)

        # bd:shotockviz-wx3 — the quote's `ts` must ACTUALLY advance between
        # ticks, which is what this test claims to simulate. It previously
        # used `int(now)`, and all three ticks ran inside the same wall-clock
        # second, so every tick saw a byte-identical quote. That passed only
        # because bd:shotockviz-rdu compared the quote's `ts` against
        # `triggered_at` (which the loop rewinds 61 minutes), never against
        # the quote it last fired on. Once wx3 made the comparison
        # like-for-like, the unfaithful simulation showed up as a failure —
        # correctly: re-notifying on a byte-identical cached quote is exactly
        # the noise these beads remove. Advancing by 5 minutes per tick
        # matches the real fetch cadence the docstring above describes.
        tick = {"n": 0}

        def _fresh_equity_redis(*_a, **_k):
            base = int(datetime.now(timezone.utc).timestamp())
            r = MagicMock()
            r.get.return_value = json.dumps(
                {"price": 150.0, "ts": base + tick["n"] * 300}
            ).encode()
            r.publish.return_value = 1
            tick["n"] += 1
            return r

        with (
            patch("core.config.settings.database_url", equity_sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", side_effect=_fresh_equity_redis),
            patch("httpx.post") as mock_post,
        ):
            mock_post.return_value = MagicMock(status_code=200)
            for _ in range(3):
                check_all_alerts()
                _rewind_triggered_at(
                    engine, EQUITY_SYMBOL, settings.alert_cooldown_minutes + 1
                )

        engine.dispose()
        assert mock_post.call_count == 3, (
            f"expected 3 Telegram sends across 3 cooldown-elapsed ticks "
            f"with a genuinely refreshing quote, got {mock_post.call_count} "
            f"— equity 'standing alert re-notifies while condition holds' "
            f"behaviour must not regress"
        )
