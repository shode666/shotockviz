"""bd:shotockviz-wx3 — an indicator alert must not re-fire against one bar.

bd:shotockviz-rdu stopped a standing price alert on a Thai fund re-notifying
hourly against a NAV published once a day. The 5 indicator types have the
identical shape and were left uncovered: bd:shotockviz-1sf made them evaluate
CLOSED bars only, so the value they compare is a daily bar's derived
indicator, which by construction does not move intraday. These types are used
more than price alerts on funds, so the live impact was larger.

The mechanism could not simply be reused. rdu compared the value's as-of to
`triggered_at` (when we fired), which works only because a quote's `ts` is
roughly "now". A closed daily bar's timestamp is a date in the PAST, so that
comparison is false from the first fire and would have turned every indicator
alert into fire-once-forever. wx3 added `alerts.triggered_data_at` — the
as-of of the data we fired on — so like is compared with like.
"""
from datetime import datetime, timedelta, timezone

import pytest

from workers.alert_checker import _bar_value_ts


# ── the bar as-of parser ────────────────────────────────────────────────────

def test_the_real_cached_bar_shape_parses_to_utc_midnight():
    """The daily payload actually in Redis today uses a `time` date string —
    verified live: {'time': '2026-09-04', 'open': ..., 'close': ...}."""
    got = _bar_value_ts({"time": "2026-09-04", "close": 230.36})
    assert got == datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_time_unix_is_preferred_when_present():
    got = _bar_value_ts({"time_unix": 1788494400, "time": "1970-01-01"})
    assert got == datetime.fromtimestamp(1788494400, tz=timezone.utc)


def test_a_bar_date_is_in_the_past_which_is_the_whole_reason_for_the_new_column():
    """Guards the reasoning, not just the parse: if this were comparable to
    `triggered_at` the way a quote's `ts` is, wx3 would not have needed a
    column. Assert the premise explicitly so a future reader cannot 'simplify'
    the gate back onto `triggered_at`."""
    bar_ts = _bar_value_ts({"time": "2026-09-04"})
    fired_at = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    assert bar_ts < fired_at, (
        "a closed daily bar's timestamp is older than the moment we fire on "
        "it — comparing it against triggered_at would refuse every re-fire"
    )


@pytest.mark.parametrize("bar", [
    {}, {"time": None}, {"time": 12345}, {"time": "not-a-date"},
    {"time_unix": "abc"}, {"time_unix": float("nan")},
])
def test_unparseable_bars_return_none_and_fall_back_to_cooldown_only(bar):
    assert _bar_value_ts(bar) is None


def test_an_explicit_timezone_in_the_string_is_respected_not_overwritten():
    got = _bar_value_ts({"time": "2026-09-04T00:00:00+07:00"})
    assert got == datetime(2026, 9, 4, tzinfo=timezone(timedelta(hours=7)))


# ── the claim guard, against a real DB ──────────────────────────────────────

@pytest.fixture
def db_and_alert(tmp_path):
    """A file-backed sqlite DB with one armed VOLUME_SPIKE alert."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from core.database import Base
    from models.user import User
    from models.alert import Alert, AlertType

    url = f"sqlite:///{tmp_path/'wx3.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            email="wx3@example.com",
            password_hash="x",
            display_name="wx3",
        )
        db.add(user)
        db.flush()
        alert = Alert(
            user_id=user.id, symbol="ZZWX3", alert_type=AlertType.VOLUME_SPIKE,
            condition="above", value=3.0, is_active=True,
        )
        db.add(alert)
        db.commit()
        alert_id = alert.id
    return engine, alert_id


def _claim(engine, alert_id, *, value_ts, now):
    from sqlalchemy.orm import Session
    from workers.alert_checker import claim_alert

    with Session(engine) as db:
        return claim_alert(db, alert_id, value_ts=value_ts, now=now)


def test_a_full_day_of_ticks_on_one_closed_bar_fires_once_not_twenty_four(db_and_alert):
    """The bead's own number. Before wx3 this produced one notification per
    cooldown window for the whole day against a bar that never changed."""
    engine, alert_id = db_and_alert
    bar_ts = _bar_value_ts({"time": "2026-09-04"})
    start = datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)

    wins = sum(
        1 for h in range(24)
        if _claim(engine, alert_id, value_ts=bar_ts, now=start + timedelta(hours=h))
    )
    assert wins == 1, f"expected 1 notification across 24 hourly ticks, got {wins}"


def test_the_next_days_bar_is_eligible_again(db_and_alert):
    """The guard must not turn a standing alert back into a one-shot — that
    is the bug bd:shotockviz-93h exists to remove."""
    engine, alert_id = db_and_alert
    day1 = _bar_value_ts({"time": "2026-09-04"})
    day2 = _bar_value_ts({"time": "2026-09-05"})
    t0 = datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)

    assert _claim(engine, alert_id, value_ts=day1, now=t0) is True
    assert _claim(engine, alert_id, value_ts=day1, now=t0 + timedelta(hours=6)) is False
    assert _claim(engine, alert_id, value_ts=day2, now=t0 + timedelta(hours=24)) is True


def test_the_cooldown_still_applies_within_one_bar_change(db_and_alert):
    """A new bar does not bypass the wall-clock cooldown — the two conditions
    are ANDed, not alternatives."""
    engine, alert_id = db_and_alert
    day1 = _bar_value_ts({"time": "2026-09-04"})
    day2 = _bar_value_ts({"time": "2026-09-05"})
    t0 = datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)

    assert _claim(engine, alert_id, value_ts=day1, now=t0) is True
    # a genuinely newer bar, but only one minute later
    assert _claim(engine, alert_id, value_ts=day2, now=t0 + timedelta(minutes=1)) is False


def test_triggered_data_at_is_recorded_not_left_null(db_and_alert):
    from sqlalchemy.orm import Session
    from models.alert import Alert

    engine, alert_id = db_and_alert
    bar_ts = _bar_value_ts({"time": "2026-09-04"})
    assert _claim(engine, alert_id, value_ts=bar_ts,
                  now=datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)) is True
    with Session(engine) as db:
        stored = db.get(Alert, alert_id).triggered_data_at
    assert stored is not None
    assert stored.replace(tzinfo=timezone.utc) == bar_ts


def test_a_none_value_ts_leaves_the_column_alone_instead_of_fabricating_one(db_and_alert):
    """Clobbering it with `now` would invent an as-of the data never had, and
    would then wrongly block the next real bar."""
    from sqlalchemy.orm import Session
    from models.alert import Alert

    engine, alert_id = db_and_alert
    assert _claim(engine, alert_id, value_ts=None,
                  now=datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)) is True
    with Session(engine) as db:
        assert db.get(Alert, alert_id).triggered_data_at is None


def test_a_new_bar_still_wins_when_we_fired_LATER_in_the_day_than_the_bar_it_replaces(
    db_and_alert,
):
    """The case that actually separates `triggered_data_at` from `triggered_at`,
    and the normal one in production.

    Bars are stamped at the start of their day but we fire during the FOLLOWING
    session, so `triggered_at` is later than the next bar's own timestamp.
    Comparing the new bar against `triggered_at` (bd:shotockviz-rdu's shape)
    then refuses it forever; comparing it against the as-of we actually fired
    on lets it through exactly once.

    Without this test the whole wx3 change passes a mutation that reverts it —
    proven: swapping the column back to `triggered_at` left the rest of this
    file green.
    """
    engine, alert_id = db_and_alert
    day1 = _bar_value_ts({"time": "2026-09-04"})   # 2026-09-04 00:00Z
    day2 = _bar_value_ts({"time": "2026-09-05"})   # 2026-09-05 00:00Z

    # fire on day1's bar, but LATE on the 5th — after day2's bar timestamp
    fired = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    assert _claim(engine, alert_id, value_ts=day1, now=fired) is True
    assert fired > day2, "premise: we fired later in the day than the next bar's stamp"

    # day2's bar is genuinely new data and must be eligible once cooldown passes
    assert _claim(
        engine, alert_id, value_ts=day2, now=fired + timedelta(hours=2)
    ) is True, (
        "a newer bar was refused — the guard is comparing against when we "
        "fired instead of against the data we fired on"
    )
