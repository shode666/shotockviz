"""Open risk — bd:shotockviz-43y (services/portfolio_service.py rule 8).

What is under test is not "does it subtract". It is the three claims the number
would be dishonest without:

  1. A position with NO STOP is excluded and named, never risk 0.00. Zero says
     "this name risks nothing"; an un-stopped position is the one whose loss
     this module cannot bound at all. It is the fabricated-loss bug of
     bd:shotockviz-2w8 with its sign flipped, and `stop_coverage_pct` is what
     stops a small total over a mostly-unstopped book reading as a safe one.

  2. A stop converts at the CURRENT rate on BOTH ends of the distance, never at
     the lots' historical rates. A stop is a future price; rule 4 / FX-1 forbids
     inventing the rate it would be realized at, so risk is a constant-rate
     statement (the equity curve's basis, bd:shotockviz-la4) and carries no
     currency component — `fx_pl_base` already reports that once.

  3. Inclusion is READ OFF `summarize`, never re-decided, so this cannot become
     a fifth surface that disagrees with the other four about one book.

`portfolio_service` is ORM-agnostic (see its module docstring), so these fakes
are plain objects: this is a test of the arithmetic, not of SQLAlchemy.
"""
import pytest

from services import portfolio_service as ps


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


def _book(txns, quotes, stops=None, fx=None):
    """The exact pipeline /portfolio/analytics runs, end to end."""
    holdings = ps.active_holdings(ps.build_holdings(txns))
    valued = ps.value_holdings(holdings, quotes, fx=fx)
    totals = ps.summarize(valued)
    return valued, totals, ps.build_open_risk(valued, totals, stops)


def _reasons(risk):
    return {e.symbol: e.reason for e in risk.excluded}


def _by_symbol(risk):
    return {p.symbol: p for p in risk.positions}


def _usd_fx(rate=33.0):
    return ps.fx_resolver({"USD": ps.FxRate("USD", rate, "live")})


# ─────────────────────────────────────────────────────────────────────────────
# The number itself
# ─────────────────────────────────────────────────────────────────────────────

def test_open_risk_is_the_distance_from_the_mark_to_the_stop_times_size():
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0)]
    _, totals, risk = _book(
        txns, {"PTT.BK": {"price": 40.0}}, stops={"PTT.BK": [35.0]}
    )

    p = _by_symbol(risk)["PTT.BK"]
    assert p.stop_distance == pytest.approx(5.0)          # 40 − 35, per share
    assert p.stop_distance_pct == pytest.approx(12.5)     # of the 40 mark
    assert p.open_risk == pytest.approx(5_000.0)          # × 1000 shares
    assert p.open_risk_base == pytest.approx(5_000.0)     # THB book, rate 1.0
    assert risk.open_risk == pytest.approx(5_000.0)
    assert risk.basis == ps.RISK_BASIS_MARK_TO_STOP
    assert risk.excluded == []

    # Marked, not entered: the position is 10 above a 30 entry, so risk from the
    # mark (5,000) is NOT risk from entry (which would be −5,000, a locked gain).
    assert p.stop_above_cost is True
    assert risk.total_value == totals.total_value


def test_risk_is_a_fraction_of_the_same_denominator_allocation_uses():
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),     # value 40,000
        _Txn("KBANK.BK", "BUY", 100, 100.0),   # value 12,000
    ]
    _, totals, risk = _book(
        txns,
        {"PTT.BK": {"price": 40.0}, "KBANK.BK": {"price": 120.0}},
        stops={"PTT.BK": [35.0], "KBANK.BK": [110.0]},
    )

    assert risk.total_value == pytest.approx(52_000.0) == totals.total_value
    assert risk.open_risk == pytest.approx(5_000.0 + 1_000.0)
    assert risk.risk_pct_of_book == pytest.approx(6_000 / 52_000 * 100)
    assert risk.stop_coverage_pct == pytest.approx(100.0)
    assert risk.uncovered_value == pytest.approx(0.0)
    # The total is exactly the rows under it — a header that disagrees with its
    # own table is how this book got into trouble before (bd:shotockviz-la4).
    assert sum(p.open_risk_base for p in risk.positions) == pytest.approx(risk.open_risk)


def test_biggest_risk_first_because_that_is_the_one_acted_on():
    txns = [
        _Txn("SMALL.BK", "BUY", 100, 10.0),
        _Txn("BIG.BK", "BUY", 1000, 10.0),
    ]
    _, _, risk = _book(
        txns,
        {"SMALL.BK": {"price": 12.0}, "BIG.BK": {"price": 12.0}},
        stops={"SMALL.BK": [11.0], "BIG.BK": [11.0]},
    )
    assert [p.symbol for p in risk.positions] == ["BIG.BK", "SMALL.BK"]


# ─────────────────────────────────────────────────────────────────────────────
# Claim 1 — no stop is NOT zero risk
# ─────────────────────────────────────────────────────────────────────────────

def test_a_position_with_no_stop_is_named_not_counted_as_zero():
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),     # stopped:   value 40,000
        _Txn("KBANK.BK", "BUY", 100, 100.0),   # unstopped: value 12,000
    ]
    _, _, risk = _book(
        txns,
        {"PTT.BK": {"price": 40.0}, "KBANK.BK": {"price": 120.0}},
        stops={"PTT.BK": [35.0]},
    )

    assert _reasons(risk) == {"KBANK.BK": ps.EXCLUDED_NO_STOP}
    assert "KBANK.BK" not in _by_symbol(risk)
    # Not a 0.00 row: it has no row. And the coverage says so out loud, so the
    # 5,000 below cannot be read as "the whole book risks 5,000".
    assert risk.open_risk == pytest.approx(5_000.0)
    assert risk.covered_value == pytest.approx(40_000.0)
    assert risk.uncovered_value == pytest.approx(12_000.0)
    assert risk.stop_coverage_pct == pytest.approx(40_000 / 52_000 * 100)
    assert risk.stop_coverage_pct < 100.0


def test_a_book_with_no_stops_at_all_reports_zero_coverage_not_zero_risk_quietly():
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0)]
    _, _, risk = _book(txns, {"PTT.BK": {"price": 40.0}}, stops={})

    assert risk.open_risk == 0.0            # nothing was counted...
    assert risk.positions == []             # ...because nothing could be
    assert risk.stop_coverage_pct == pytest.approx(0.0)
    assert risk.uncovered_value == pytest.approx(40_000.0)
    assert _reasons(risk) == {"PTT.BK": ps.EXCLUDED_NO_STOP}


def test_percentages_are_none_not_zero_when_the_book_states_nothing():
    """A percentage of nothing is undefined — same doctrine as
    Allocation.top_weight_pct and ClosedTrade.realized_pl_pct."""
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0)]
    _, totals, risk = _book(txns, {"PTT.BK": None}, stops={"PTT.BK": [35.0]})

    assert totals.total_value == 0.0
    assert risk.risk_pct_of_book is None
    assert risk.stop_coverage_pct is None
    assert _reasons(risk) == {"PTT.BK": ps.EXCLUDED_UNPRICED}


# ─────────────────────────────────────────────────────────────────────────────
# Claim 2 — the FX rate a stop converts at
# ─────────────────────────────────────────────────────────────────────────────

def test_a_stop_converts_at_the_current_rate_not_at_the_lots_historical_rate():
    # Bought 10 @ 100 USD when THB/USD was 30; today the rate is 33.
    txns = [_Txn("NVDA", "BUY", 10, 100.0, currency="USD", fx_rate=30.0)]
    valued, totals, risk = _book(
        txns, {"NVDA": {"price": 120.0}}, stops={"NVDA": [110.0]}, fx=_usd_fx(33.0)
    )

    v = valued[0]
    assert v.cost_basis_base == pytest.approx(30_000.0)   # cost at ITS rate (rule 4/FX-2)
    assert v.current_value_base == pytest.approx(39_600.0)  # value at today's

    p = _by_symbol(risk)["NVDA"]
    assert p.open_risk == pytest.approx(100.0)             # (120 − 110) × 10, USD
    assert p.open_risk_base == pytest.approx(3_300.0)      # × 33, today's rate
    assert p.open_risk_base != pytest.approx(3_000.0)      # NOT × 30, the lot rate

    # The identity that makes it a constant-rate statement: both ends of the
    # distance are marked at the same rate, so the number carries no FX at all.
    assert p.open_risk_base == pytest.approx(
        v.current_value_base - 110.0 * 10 * 33.0
    )
    assert risk.open_risk == pytest.approx(3_300.0)
    assert totals.total_value == pytest.approx(39_600.0)


def test_an_estimated_rate_is_carried_into_the_risk_number():
    txns = [_Txn("NVDA", "BUY", 10, 100.0, currency="USD", fx_rate=30.0)]
    fx = ps.fx_resolver({"USD": ps.FxRate("USD", 33.0, "fallback")})
    _, _, risk = _book(
        txns, {"NVDA": {"price": 120.0}}, stops={"NVDA": [110.0]}, fx=fx
    )
    assert risk.fx_estimated is True
    assert _by_symbol(risk)["NVDA"].fx_estimated is True


# ─────────────────────────────────────────────────────────────────────────────
# Claim 3 — inclusion is read off `summarize`, never re-decided
# ─────────────────────────────────────────────────────────────────────────────

def test_the_three_summarize_exclusions_are_inherited_with_their_own_reasons():
    txns = [
        _Txn("UNPRICED.BK", "BUY", 100, 10.0),
        _Txn("NVDA", "BUY", 10, 100.0, currency="USD", fx_rate=30.0),  # no rate today
        _Txn("MIXED.BK", "BUY", 10, 10.0, currency="THB"),
        _Txn("MIXED.BK", "BUY", 10, 10.0, currency="USD", fx_rate=30.0),
        _Txn("OK.BK", "BUY", 100, 10.0),
    ]
    # `default_fx` resolves only THB, so NVDA is priced but not convertible.
    _, totals, risk = _book(
        txns,
        {
            "UNPRICED.BK": None,
            "NVDA": {"price": 120.0},
            "MIXED.BK": {"price": 10.0},
            "OK.BK": {"price": 12.0},
        },
        stops={
            # Every one of them HAS a stop — so the only thing that can keep
            # them out is the totals' own exclusion, which is the point.
            "UNPRICED.BK": [9.0], "NVDA": [110.0],
            "MIXED.BK": [9.0], "OK.BK": [11.0],
        },
    )

    assert _reasons(risk) == {
        "UNPRICED.BK": ps.EXCLUDED_UNPRICED,
        "NVDA": ps.EXCLUDED_FX_UNAVAILABLE,
        "MIXED.BK": ps.EXCLUDED_CURRENCY_CONFLICT,
    }
    assert [p.symbol for p in risk.positions] == ["OK.BK"]
    # And the exclusion sets are literally the totals' own lists.
    assert totals.unpriced_symbols == ["UNPRICED.BK"]
    assert totals.fx_unavailable_symbols == ["NVDA"]
    assert totals.currency_conflict_symbols == ["MIXED.BK"]


# ─────────────────────────────────────────────────────────────────────────────
# The stop-specific refusals
# ─────────────────────────────────────────────────────────────────────────────

def test_a_stop_at_or_above_the_mark_is_refused_not_summed_as_negative_risk():
    """A breached stop should already have fired. Folding its negative distance
    into the sum would let one stale stop mask real risk elsewhere."""
    txns = [
        _Txn("STALE.BK", "BUY", 1000, 30.0),
        _Txn("PTT.BK", "BUY", 1000, 30.0),
    ]
    _, _, risk = _book(
        txns,
        {"STALE.BK": {"price": 20.0}, "PTT.BK": {"price": 40.0}},
        stops={"STALE.BK": [25.0], "PTT.BK": [35.0]},   # 25 > the 20 mark
    )

    assert _reasons(risk) == {"STALE.BK": ps.EXCLUDED_STOP_NOT_BELOW_MARK}
    # The real 5,000 is intact — it was NOT netted down by a −5,000.
    assert risk.open_risk == pytest.approx(5_000.0)


def test_a_stop_exactly_on_the_mark_is_refused_too():
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0)]
    _, _, risk = _book(
        txns, {"PTT.BK": {"price": 40.0}}, stops={"PTT.BK": [40.0]}
    )
    assert _reasons(risk) == {"PTT.BK": ps.EXCLUDED_STOP_NOT_BELOW_MARK}
    assert risk.positions == []


def test_two_stops_on_one_symbol_are_refused_rather_than_picked_between():
    """The write path prevents this (one position, one stop). If a row ever gets
    past it, picking the higher understates the risk — the dangerous direction —
    so the read path declines, exactly as rule 5 declines a mixed currency."""
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0)]
    _, _, risk = _book(
        txns, {"PTT.BK": {"price": 40.0}}, stops={"PTT.BK": [35.0, 38.0]}
    )
    assert _reasons(risk) == {"PTT.BK": ps.EXCLUDED_AMBIGUOUS_STOP}
    assert risk.open_risk == 0.0
    assert risk.stop_coverage_pct == pytest.approx(0.0)


def test_a_split_adjusted_position_cannot_state_the_units_its_stop_was_typed_in():
    """rule 7 / bd:shotockviz-eb1. The position is restated into today's units;
    `sr_levels` has no as-of date (unlike `alerts.value_as_of`), so nobody can
    say whether the stop predates the split. A 2:1 would state risk at 2x."""
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0)]
    holdings = ps.active_holdings(ps.build_holdings(txns))
    valued = ps.value_holdings(holdings, {"PTT.BK": {"price": 40.0}})
    valued[0].split_adjusted = True
    totals = ps.summarize(valued)

    risk = ps.build_open_risk(valued, totals, {"PTT.BK": [35.0]})
    assert _reasons(risk) == {"PTT.BK": ps.EXCLUDED_STOP_UNITS_UNKNOWN}
    assert risk.positions == []
    # Still counted in the book it is measured against — it is a real position
    # with a real value; only its RISK is unstatable.
    assert risk.total_value == pytest.approx(40_000.0)


def test_stop_above_cost_is_judged_against_the_real_breakeven_not_the_screen_price():
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0, fee=1_000.0)]  # avg cost 31.0
    _, _, risk = _book(
        txns, {"PTT.BK": {"price": 40.0}}, stops={"PTT.BK": [30.5]}
    )
    p = _by_symbol(risk)["PTT.BK"]
    # 30.5 is above the 30.0 screen price but BELOW the 31.0 real breakeven
    # (rule 1 capitalises the buy commission) — so this trade is not free yet.
    assert p.stop_above_cost is False
    assert p.open_risk_base == pytest.approx(9_500.0)


def test_an_empty_book_states_nothing_rather_than_zero_percent():
    _, totals, risk = _book([], {}, stops={})
    assert totals.total_value == 0.0
    assert risk.open_risk == 0.0
    assert risk.positions == []
    assert risk.excluded == []
    assert risk.risk_pct_of_book is None
    assert risk.stop_coverage_pct is None


def test_covered_plus_uncovered_is_the_whole_stated_book():
    txns = [
        _Txn("A.BK", "BUY", 100, 10.0),
        _Txn("B.BK", "BUY", 100, 10.0),
        _Txn("C.BK", "BUY", 100, 10.0),
    ]
    _, totals, risk = _book(
        txns,
        {"A.BK": {"price": 12.0}, "B.BK": {"price": 12.0}, "C.BK": {"price": 12.0}},
        stops={"A.BK": [11.0], "B.BK": [13.0]},  # B's stop is above the mark
    )
    assert risk.covered_value + risk.uncovered_value == pytest.approx(totals.total_value)
    assert _reasons(risk) == {
        "B.BK": ps.EXCLUDED_STOP_NOT_BELOW_MARK,
        "C.BK": ps.EXCLUDED_NO_STOP,
    }
