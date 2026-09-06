"""bd:shotockviz-rwq — the beat schedule's crontab hours are ICT, not UTC.

Celery evaluates `crontab()` against `conf.timezone`, which this app sets to
`settings.tz` = "Asia/Bangkok". Every entry below was previously written as
if it were UTC (with a `# = HH:MM ICT` comment doing the conversion), so all
of them fired 7 hours early — the S/R digest reached the user at 02:30 and
12:30 ICT instead of 09:30 and 19:30, on a Sunday.

These tests assert the *intent* (the ICT wall-clock time each job is supposed
to run at) rather than re-stating the literal `hour=` value, so that if
someone "converts to UTC" again the test says which job broke and what time
it was supposed to run.
"""
from zoneinfo import ZoneInfo

import pytest

from workers.celery_app import celery_app


# job name -> (ICT hour, ICT minute, why this time)
EXPECTED_ICT = {
    "db-housekeeping": (3, 0, "overnight, outside every market session"),
    "fetch-fund-navs": (19, 0, "SEC publishes Thai fund NAV T+1, evening ICT"),
    "fetch-corporate-actions": (2, 0, "after US close (04:00 ICT is next-day; 02:00 is mid-session-free)"),
    "fetch-financials-history": (1, 0, "overnight batch"),
    "fetch-earnings-events": (6, 0, "after US close, before SET pre-open"),
    "compute-auto-pivots": (18, 0, "after SET close 16:30, before US open 21:30"),
    "sr-digest-set-open": (9, 30, "30 min before SET opens at 10:00"),
    "sr-digest-us-premarket": (19, 30, "30 min before US pre-market at 20:00"),
    "gap-list-digest": (20, 0, "the trader's own US pre-market check habit, not a lead time"),
}


def test_celery_timezone_is_ict():
    """The premise every other assertion here rests on."""
    assert celery_app.conf.timezone == "Asia/Bangkok"


@pytest.mark.parametrize("name,expected", sorted(EXPECTED_ICT.items()))
def test_crontab_hour_is_ict_wall_clock(name, expected):
    hour, minute, why = expected
    entry = celery_app.conf.beat_schedule[name]
    sched = entry["schedule"]
    assert sched.hour == {hour}, f"{name} should run at {hour:02d}:{minute:02d} ICT ({why})"
    assert sched.minute == {minute}, f"{name} should run at {hour:02d}:{minute:02d} ICT ({why})"


def test_no_crontab_entry_is_seven_hours_off_its_ict_intent():
    """Regression guard for the exact failure mode: the UTC equivalent of the
    intended ICT time must NOT be what is configured."""
    ict = ZoneInfo("Asia/Bangkok")  # UTC+7, no DST
    for name, (hour, minute, _why) in EXPECTED_ICT.items():
        utc_equivalent = (hour - 7) % 24
        actual = next(iter(celery_app.conf.beat_schedule[name]["schedule"].hour))
        assert actual != utc_equivalent or hour == utc_equivalent, (
            f"{name} is set to hour={actual}, which is the UTC conversion of "
            f"{hour:02d}:{minute:02d} ICT — but crontab is evaluated in "
            f"{ict.key}, so it will fire 7 hours early."
        )


def test_sr_digest_slots_are_thirty_minutes_before_their_market_opens():
    """The whole point of the digest (spec §2) — assert the '30 minutes
    before' relationship, not just the literal clock times."""
    set_open_ict = 10 * 60          # SET opens 10:00 ICT
    us_premarket_ict = 20 * 60      # US pre-market starts 20:00 ICT

    for name, market_open_min in (
        ("sr-digest-set-open", set_open_ict),
        ("sr-digest-us-premarket", us_premarket_ict),
    ):
        sched = celery_app.conf.beat_schedule[name]["schedule"]
        fires_at = next(iter(sched.hour)) * 60 + next(iter(sched.minute))
        assert market_open_min - fires_at == 30, (
            f"{name} fires {market_open_min - fires_at} min before the market "
            f"opens; the spec says 30."
        )
