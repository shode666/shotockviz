"""Concentration LIMIT — bd:shotockviz-649 ("concentration as a limit, not
just a display").

bd:shotockviz-916 shipped the % breakdown (`build_allocation`); this is the
follow-on that answers the position-sizing question directly instead of
making him re-read a donut every session: did any name cross a threshold he
set.

What is under test is not "does it compare a percentage to another
percentage". It is the three claims the feature would be dishonest without:

  1. A position `build_allocation` could not price/convert/state at all (rule
     2 unpriced, rule 4 fx_unavailable, rule 5 currency_conflict) has NO %, so
     it can be neither "under the limit" (a false-safe reading manufactured
     from an unknown — the fabricated-loss bug of rule 2 with its sign
     flipped) nor "over the limit" (inventing a number rule 4 / FX-1
     forbids). It is `not_checked`, named, with the SAME reason
     `build_allocation` gave it — never re-decided.

  2. The boundary is `>`, not `>=`: a position sitting exactly ON the limit
     has not crossed it.

  3. A breach carries an ACTIONABLE number, not just a restated fact:
     `trim_value_base` is how much BASE value to sell to land the position
     exactly back on the limit, accounting for the fact that selling shrinks
     the denominator too (this book has no cash leg — see
     services/portfolio_service.py's "ACTIONABILITY" note).

`portfolio_service` is ORM-agnostic (see its module docstring), so these fakes
are plain objects: this is a test of the arithmetic, not of SQLAlchemy.
"""
from unittest.mock import AsyncMock, patch

import pytest

from api.routes.portfolio import get_analytics
from services import portfolio_service as ps
from tests.test_portfolio_valuation import _FakeRedis, _no_corporate_actions, _redis_store


class _Txn:
    """Minimal transaction. `type`/`currency` are read via getattr/.value."""

    def __init__(self, symbol, type_, qty, price, fee=0.0, currency="THB", fx_rate=None):
        self.symbol = symbol
        self.type = type_
        self.qty = qty
        self.price = price
        self.fee = fee
        self.currency = currency
        self.fx_rate = fx_rate
        self.date = None


def _allocation(txns, quotes, fx=None):
    """The exact pipeline /portfolio/analytics runs, end to end, up to the pie."""
    holdings = ps.active_holdings(ps.build_holdings(txns))
    valued = ps.value_holdings(holdings, quotes, fx=fx)
    totals = ps.summarize(valued)
    return ps.build_allocation(valued, totals)


def _reasons(check):
    return {e.symbol: e.reason for e in check.not_checked}


def _by_symbol(check):
    return {b.symbol: b for b in check.breaches}


# ─────────────────────────────────────────────────────────────────────────────
# The number itself
# ─────────────────────────────────────────────────────────────────────────────

def test_no_breach_when_every_slice_is_under_the_limit():
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),     # 40,000 / 52,000 = 76.9%
        _Txn("KBANK.BK", "BUY", 100, 100.0),   # 12,000 / 52,000 = 23.1%
    ]
    alloc = _allocation(txns, {"PTT.BK": {"price": 40.0}, "KBANK.BK": {"price": 120.0}})
    check = ps.build_concentration_check(alloc, limit_pct=90.0)

    assert check.breaches == []
    assert check.breached is False
    assert check.limit_pct == 90.0
    assert check.not_checked == []


def test_a_slice_over_the_limit_is_named_with_its_excess():
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),     # 40,000 / 52,000 = 76.92%
        _Txn("KBANK.BK", "BUY", 100, 100.0),   # 12,000 / 52,000 = 23.08%
    ]
    alloc = _allocation(txns, {"PTT.BK": {"price": 40.0}, "KBANK.BK": {"price": 120.0}})
    check = ps.build_concentration_check(alloc, limit_pct=50.0)

    assert [b.symbol for b in check.breaches] == ["PTT.BK"]
    b = _by_symbol(check)["PTT.BK"]
    assert b.weight_pct == pytest.approx(40_000 / 52_000 * 100)
    assert b.limit_pct == 50.0
    assert b.excess_pct == pytest.approx(b.weight_pct - 50.0)
    assert b.value_base == pytest.approx(40_000.0)
    assert b.currency == "THB"
    assert check.breached is True


def test_exactly_on_the_limit_is_not_a_breach():
    """The boundary is `>`, not `>=` — sitting exactly on the limit has not
    crossed it. 50% at a 50% limit must not appear."""
    txns = [
        _Txn("A.BK", "BUY", 100, 10.0),   # 1,000 / 2,000 = 50%
        _Txn("B.BK", "BUY", 100, 10.0),   # 1,000 / 2,000 = 50%
    ]
    alloc = _allocation(txns, {"A.BK": {"price": 10.0}, "B.BK": {"price": 10.0}})
    check = ps.build_concentration_check(alloc, limit_pct=50.0)

    assert check.breaches == []


# ─────────────────────────────────────────────────────────────────────────────
# The actionable half: trim_value_base
# ─────────────────────────────────────────────────────────────────────────────

def test_trim_value_base_lands_exactly_on_the_limit_accounting_for_the_shrinking_denominator():
    """The naive `value - limit% * value` answer is WRONG here: selling shares
    also shrinks `total_value` (this book has no cash leg), so a one-sided
    calculation would undershoot the trim needed. 100,000 total, one position
    at 80,000 (80%), limit 50%:

        sold = (80,000 - 0.5 * 100,000) / (1 - 0.5) = 30,000 / 0.5 = 60,000

    Check: (80,000 - 60,000) / (100,000 - 60,000) = 20,000 / 40,000 = 50%. """
    txns = [
        _Txn("BIG.BK", "BUY", 1000, 80.0),    # 80,000
        _Txn("SMALL.BK", "BUY", 1000, 20.0),  # 20,000
    ]
    alloc = _allocation(txns, {"BIG.BK": {"price": 80.0}, "SMALL.BK": {"price": 20.0}})
    check = ps.build_concentration_check(alloc, limit_pct=50.0)

    b = _by_symbol(check)["BIG.BK"]
    assert b.trim_value_base == pytest.approx(60_000.0)
    # The naive (wrong) one-sided answer would have been 30,000 — assert we are
    # NOT that, so a regression to the simpler-looking formula cannot pass.
    assert b.trim_value_base != pytest.approx(30_000.0)

    remaining_value = b.value_base - b.trim_value_base
    remaining_total = alloc.total_value - b.trim_value_base
    assert remaining_value / remaining_total * 100 == pytest.approx(50.0)


def test_trim_value_base_is_never_negative():
    """Unreachable given the `weight_pct > limit_pct` guard, but a formula
    fed a limit right at the edge must not hand back a negative "sell"
    instruction."""
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0)]
    alloc = _allocation(txns, {"PTT.BK": {"price": 40.0}})
    check = ps.build_concentration_check(alloc, limit_pct=1.0)
    assert all(b.trim_value_base >= 0.0 for b in check.breaches)


def test_worst_breach_first_because_that_is_the_one_acted_on():
    txns = [
        _Txn("SMALL.BK", "BUY", 100, 10.0),   # 1,000
        _Txn("MEDIUM.BK", "BUY", 300, 10.0),  # 3,000
        _Txn("BIG.BK", "BUY", 600, 10.0),     # 6,000
    ]
    alloc = _allocation(
        txns,
        {"SMALL.BK": {"price": 10.0}, "MEDIUM.BK": {"price": 10.0}, "BIG.BK": {"price": 10.0}},
    )
    check = ps.build_concentration_check(alloc, limit_pct=5.0)
    assert [b.symbol for b in check.breaches] == ["BIG.BK", "MEDIUM.BK", "SMALL.BK"]


# ─────────────────────────────────────────────────────────────────────────────
# Claim 1 — an excluded position has no %, so it is neither safe nor breached
# ─────────────────────────────────────────────────────────────────────────────

def test_an_unpriced_position_is_not_checked_never_counted_as_compliant():
    """rule 2. If it were silently treated as 0%, it would read as 'safe' —
    the fabricated-loss bug of bd:shotockviz-2w8 with its sign flipped."""
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),
        _Txn("KBANK.BK", "BUY", 100, 100.0),
    ]
    alloc = _allocation(txns, {"PTT.BK": {"price": 40.0}, "KBANK.BK": None})
    check = ps.build_concentration_check(alloc, limit_pct=10.0)

    assert _reasons(check) == {"KBANK.BK": ps.EXCLUDED_UNPRICED}
    assert "KBANK.BK" not in _by_symbol(check)
    # PTT.BK is 100% of what CAN be stated and IS over a 10% limit.
    assert [b.symbol for b in check.breaches] == ["PTT.BK"]


def test_a_currency_conflicted_position_is_not_checked_and_not_invented_as_breached():
    """rule 5. It has no cost, therefore no %, therefore it cannot be said to
    have crossed a threshold either — the mirror failure mode."""
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),
        _Txn("MIXED.BK", "BUY", 10, 10.0, currency="THB"),
        _Txn("MIXED.BK", "BUY", 10, 10.0, currency="USD", fx_rate=33.0),
    ]
    alloc = _allocation(
        txns,
        {"PTT.BK": {"price": 40.0}, "MIXED.BK": {"price": 10.0}},
        fx=ps.fx_resolver({"USD": ps.FxRate("USD", 33.0, "live")}),
    )
    check = ps.build_concentration_check(alloc, limit_pct=1.0)

    assert _reasons(check) == {"MIXED.BK": ps.EXCLUDED_CURRENCY_CONFLICT}
    assert "MIXED.BK" not in _by_symbol(check)


def test_all_three_summarize_exclusions_are_inherited_with_their_own_reasons():
    txns = [
        _Txn("UNPRICED.BK", "BUY", 100, 10.0),
        _Txn("NVDA", "BUY", 10, 100.0, currency="USD", fx_rate=30.0),  # no rate today
        _Txn("MIXED.BK", "BUY", 10, 10.0, currency="THB"),
        _Txn("MIXED.BK", "BUY", 10, 10.0, currency="USD", fx_rate=30.0),
        _Txn("OK.BK", "BUY", 100, 10.0),
    ]
    alloc = _allocation(
        txns,
        {
            "UNPRICED.BK": None,
            "NVDA": {"price": 120.0},
            "MIXED.BK": {"price": 10.0},
            "OK.BK": {"price": 12.0},
        },
    )
    check = ps.build_concentration_check(alloc, limit_pct=1.0)

    assert _reasons(check) == {
        "UNPRICED.BK": ps.EXCLUDED_UNPRICED,
        "NVDA": ps.EXCLUDED_FX_UNAVAILABLE,
        "MIXED.BK": ps.EXCLUDED_CURRENCY_CONFLICT,
    }
    # OK.BK is the only one with a %, and it is over the 1% limit.
    assert [b.symbol for b in check.breaches] == ["OK.BK"]


def test_an_all_excluded_book_reports_nothing_rather_than_a_false_all_clear():
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0), _Txn("KBANK.BK", "BUY", 100, 100.0)]
    alloc = _allocation(txns, {"PTT.BK": None, "KBANK.BK": None})
    check = ps.build_concentration_check(alloc, limit_pct=10.0)

    assert check.breaches == []
    assert check.breached is False
    assert set(_reasons(check)) == {"PTT.BK", "KBANK.BK"}


def test_an_empty_book_is_empty_not_broken():
    alloc = _allocation([], {})
    check = ps.build_concentration_check(alloc, limit_pct=25.0)
    assert check.breaches == []
    assert check.not_checked == []


# ─────────────────────────────────────────────────────────────────────────────
# The route: default limit, given limit, and validation
# ─────────────────────────────────────────────────────────────────────────────

async def test_the_route_applies_the_default_limit_when_none_is_given(test_db, test_user):
    from datetime import date
    from models.portfolio import Transaction, TransactionType

    test_db.add(Transaction(
        user_id=test_user.id, symbol="PTT.BK", type=TransactionType.BUY,
        qty=1000, price=30.0, fee=0.0, date=date(2024, 1, 1),
    ))
    await test_db.flush()
    store = _redis_store({"PTT.BK": {"symbol": "PTT.BK", "price": 40.0}})

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()), \
         _no_corporate_actions():
        analytics = await get_analytics(user=test_user, db=test_db)

    assert analytics.concentration is not None
    assert analytics.concentration.limit_pct == ps.DEFAULT_CONCENTRATION_LIMIT_PCT
    # One position, 100% of the book, over the 25% default -> a breach.
    assert [b.symbol for b in analytics.concentration.breaches] == ["PTT.BK"]
    assert analytics.concentration.breaches[0].weight_pct == pytest.approx(100.0)


async def test_the_route_applies_the_callers_own_limit(test_db, test_user):
    from datetime import date
    from models.portfolio import Transaction, TransactionType

    test_db.add(Transaction(
        user_id=test_user.id, symbol="PTT.BK", type=TransactionType.BUY,
        qty=1000, price=30.0, fee=0.0, date=date(2024, 1, 1),
    ))
    await test_db.flush()
    store = _redis_store({"PTT.BK": {"symbol": "PTT.BK", "price": 40.0}})

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()), \
         _no_corporate_actions():
        analytics = await get_analytics(user=test_user, db=test_db, concentration_limit_pct=99.0)

    # 100% > 99% is still a breach, but the limit carried through is the
    # caller's own, not the default.
    assert analytics.concentration.limit_pct == 99.0
    assert [b.symbol for b in analytics.concentration.breaches] == ["PTT.BK"]


async def test_the_route_422s_on_an_out_of_range_limit_instead_of_silently_clamping(
    test_db, test_user,
):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_analytics(user=test_user, db=test_db, concentration_limit_pct=150.0)
    assert exc_info.value.status_code == 422


async def test_direct_callers_omitting_the_new_param_are_unaffected():
    """bd:shotockviz-649 must not break the ~30 existing direct calls to this
    coroutine across test_portfolio_fx.py / test_portfolio_valuation.py /
    test_portfolio_currency_and_curve.py / test_portfolio_realized_and_guards.py
    that never pass `concentration_limit_pct` at all. This is exactly why the
    new parameter is a plain `None` default and not `fastapi.Query(...)` — see
    the comment on `get_analytics`."""
    # Calling with a bogus db/user would fail on the DB query first, so this
    # is really just asserting the signature accepts the omission without
    # TypeError — the money-path coverage above proves the value is honoured.
    import inspect
    sig = inspect.signature(get_analytics)
    assert sig.parameters["concentration_limit_pct"].default is None
