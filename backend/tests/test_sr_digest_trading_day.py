"""bd:shotockviz-3fx — the S/R digest must not send on a non-trading day.

On Sunday 2026-09-06 the digest sent a full "ก่อน US pre-market" message
listing 4 symbols. No market opens on a Sunday, so there was no session for
the reader to act before.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from workers.sr_proximity_digest import SLOT_MARKET_TZ, is_trading_day_for_slot


def _utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# The two real firing times, expressed in UTC:
#   09:30 ICT = 02:30 UTC   (sr-digest-set-open)
#   19:30 ICT = 12:30 UTC   (sr-digest-us-premarket)
SET_SLOT_UTC = (2, 30)
US_SLOT_UTC = (12, 30)


@pytest.mark.parametrize("slot,hh,mm", [
    ("set_open", *SET_SLOT_UTC),
    ("us_premarket", *US_SLOT_UTC),
])
@pytest.mark.parametrize("day,weekday_name", [
    (7, "Monday"),   # 2026-09-07
    (8, "Tuesday"),
    (9, "Wednesday"),
    (10, "Thursday"),
    (11, "Friday"),
])
def test_weekdays_send(slot, hh, mm, day, weekday_name):
    now = _utc(2026, 9, day, hh, mm)
    assert now.astimezone(SLOT_MARKET_TZ[slot]).strftime("%A") == weekday_name
    assert is_trading_day_for_slot(slot, now) is True


@pytest.mark.parametrize("slot,hh,mm", [
    ("set_open", *SET_SLOT_UTC),
    ("us_premarket", *US_SLOT_UTC),
])
@pytest.mark.parametrize("day,weekday_name", [(5, "Saturday"), (6, "Sunday")])
def test_weekends_skip(slot, hh, mm, day, weekday_name):
    """2026-09-05 is a Saturday and 2026-09-06 a Sunday — the actual day the
    user received a digest."""
    now = _utc(2026, 9, day, hh, mm)
    assert now.astimezone(SLOT_MARKET_TZ[slot]).strftime("%A") == weekday_name
    assert is_trading_day_for_slot(slot, now) is False


def test_the_exact_message_the_user_received_would_now_be_suppressed():
    """2026-09-06 12:30 ICT — the 'ก่อน US pre-market (06/09)' digest."""
    sunday_1230_ict = datetime(2026, 9, 6, 12, 30, tzinfo=ZoneInfo("Asia/Bangkok"))
    assert is_trading_day_for_slot("us_premarket", sunday_1230_ict) is False


def test_us_slot_uses_us_calendar_not_the_server_calendar():
    """A time that is Monday in Bangkok but still Sunday in New York must be
    treated as a non-trading day for the US slot — that is the whole reason
    each slot carries its own exchange timezone rather than sharing one."""
    monday_0600_ict = datetime(2026, 9, 7, 6, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
    assert monday_0600_ict.astimezone(ZoneInfo("America/New_York")).strftime("%A") == "Sunday"
    assert is_trading_day_for_slot("us_premarket", monday_0600_ict) is False
    # ...and the SET slot at that same instant is a trading day.
    assert is_trading_day_for_slot("set_open", monday_0600_ict) is True


def test_unknown_slot_fails_open():
    """A slot name this module does not know is a scheduling mistake; sending
    surfaces it, silence would hide it forever."""
    assert is_trading_day_for_slot("asia_open", _utc(2026, 9, 6, 12, 30)) is True


def test_holidays_are_explicitly_not_covered():
    """Documents the known gap rather than pretending it is handled: SET is
    closed on 2026-12-07 (a Monday, substitution day for Constitution Day),
    and this predicate still returns True because no holiday calendar exists
    anywhere in this codebase. If a calendar is ever added, this test should
    flip and this docstring should go away."""
    set_holiday_monday = datetime(2026, 12, 7, 9, 30, tzinfo=ZoneInfo("Asia/Bangkok"))
    assert set_holiday_monday.strftime("%A") == "Monday"
    assert is_trading_day_for_slot("set_open", set_holiday_monday) is True
