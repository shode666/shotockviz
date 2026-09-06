"""Allocation (FR-PORT-002) — bd:shotockviz-916.

What is under test is not "does it divide": it is that the pie cannot state a
different book from the header above it, and cannot make an excluded position
look like a worthless one.

The three exclusions of services/portfolio_service.py (rule 2 unpriced, rule 4
no FX rate, rule 5 currency conflict) each get NO SLICE and a named reason. A 0%
wedge would be the pie-chart form of the fabricated-loss bug bd:shotockviz-2w8
removed: it reads as "this name is worth nothing" when the truth is "we cannot
say what it is worth".

The denominator is `PortfolioTotals.total_value` — the market value of exactly
the positions `summarize` included — so `sum(slice.value_base) == total_value`
holds by construction, and a renderer drawing arcs from `value_base` closes.

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


def _book(txns, quotes, fx=None):
    """The exact pipeline /portfolio/analytics runs, end to end."""
    holdings = ps.active_holdings(ps.build_holdings(txns))
    valued = ps.value_holdings(holdings, quotes, fx=fx)
    totals = ps.summarize(valued)
    return valued, totals, ps.build_allocation(valued, totals)


def _weights(alloc):
    return {s.symbol: s.weight_pct for s in alloc.slices}


def _reasons(alloc):
    return {e.symbol: e.reason for e in alloc.excluded}


# ─────────────────────────────────────────────────────────────────────────────
# The invariant: the pie and the header are the same book
# ─────────────────────────────────────────────────────────────────────────────

def test_slices_sum_to_the_stated_total_and_to_100_pct():
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),
        _Txn("KBANK.BK", "BUY", 100, 100.0),
    ]
    _, totals, alloc = _book(
        txns, {"PTT.BK": {"price": 40.0}, "KBANK.BK": {"price": 120.0}}
    )

    # 40,000 + 12,000 = 52,000
    assert alloc.total_value == pytest.approx(52_000.0)
    assert alloc.total_value == totals.total_value          # the header's number
    assert sum(s.value_base for s in alloc.slices) == pytest.approx(alloc.total_value)
    assert sum(s.weight_pct for s in alloc.slices) == pytest.approx(100.0)
    assert _weights(alloc) == pytest.approx(
        {"PTT.BK": 40_000 / 52_000 * 100, "KBANK.BK": 12_000 / 52_000 * 100}
    )
    assert alloc.basis == ps.ALLOCATION_BASIS_CURRENT_VALUE
    assert alloc.excluded == []


def test_heaviest_first_so_the_concentration_question_is_read_from_the_top():
    txns = [
        _Txn("AAA.BK", "BUY", 10, 10.0),
        _Txn("BBB.BK", "BUY", 10, 100.0),
        _Txn("CCC.BK", "BUY", 10, 50.0),
    ]
    _, _, alloc = _book(
        txns,
        {"AAA.BK": {"price": 10.0}, "BBB.BK": {"price": 100.0}, "CCC.BK": {"price": 50.0}},
    )
    assert [s.symbol for s in alloc.slices] == ["BBB.BK", "CCC.BK", "AAA.BK"]
    assert alloc.top_weight_pct == pytest.approx(100 / 160 * 100)


def test_weights_are_of_market_value_not_of_cost():
    """A position bought cheap and now large must weigh what it is worth today."""
    txns = [
        _Txn("PTT.BK", "BUY", 100, 10.0),    # cost 1,000, now worth 10,000
        _Txn("KBANK.BK", "BUY", 100, 90.0),  # cost 9,000, now worth 10,000
    ]
    _, _, alloc = _book(
        txns, {"PTT.BK": {"price": 100.0}, "KBANK.BK": {"price": 100.0}}
    )
    assert _weights(alloc) == pytest.approx({"PTT.BK": 50.0, "KBANK.BK": 50.0})


# ─────────────────────────────────────────────────────────────────────────────
# Exclusions — named, never drawn at 0%
# ─────────────────────────────────────────────────────────────────────────────

def test_unpriced_position_gets_no_slice_and_is_named():
    """bd:shotockviz-2w8 in pie form. The normal Thai book after 16:30 ICT."""
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),
        _Txn("KBANK.BK", "BUY", 100, 100.0),
    ]
    _, totals, alloc = _book(txns, {"PTT.BK": {"price": 40.0}, "KBANK.BK": None})

    assert [s.symbol for s in alloc.slices] == ["PTT.BK"]
    assert _reasons(alloc) == {"KBANK.BK": ps.EXCLUDED_UNPRICED}
    # The one that is priced is 100% OF WHAT CAN BE STATED, and the denominator
    # says so: it is 40,000, not the 52,000 the whole book would be worth.
    assert alloc.total_value == pytest.approx(40_000.0) == totals.total_value
    assert alloc.slices[0].weight_pct == pytest.approx(100.0)
    # Never a zero-area wedge for the excluded name.
    assert all(s.value_base > 0 for s in alloc.slices)


def test_a_zero_price_quote_is_bad_data_not_a_zero_slice():
    """Rule 3 — 0.0 is not a market price, so the position is excluded, not drawn
    as an empty wedge."""
    txns = [_Txn("PTT.BK", "BUY", 10, 30.0), _Txn("BAD.BK", "BUY", 10, 30.0)]
    _, _, alloc = _book(txns, {"PTT.BK": {"price": 40.0}, "BAD.BK": {"price": 0.0}})
    assert [s.symbol for s in alloc.slices] == ["PTT.BK"]
    assert _reasons(alloc) == {"BAD.BK": ps.EXCLUDED_UNPRICED}


def test_currency_conflict_gets_no_slice_and_is_named():
    """Rule 5 / bd:shotockviz-7ju — the cost basis mixes units, so nothing about
    the position is expressible; a slice would need a number that does not exist."""
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),
        _Txn("NVDA", "BUY", 10, 100.0, currency="USD", fx_rate=33.0),
        _Txn("NVDA", "BUY", 10, 100.0, currency="THB"),
    ]
    _, _, alloc = _book(
        txns,
        {"PTT.BK": {"price": 40.0}, "NVDA": {"price": 150.0}},
        fx=ps.fx_resolver({"USD": ps.FxRate("USD", 33.0, "live")}),
    )
    assert [s.symbol for s in alloc.slices] == ["PTT.BK"]
    assert _reasons(alloc) == {"NVDA": ps.EXCLUDED_CURRENCY_CONFLICT}
    assert alloc.total_value == pytest.approx(40_000.0)


def test_priced_but_unconvertible_position_gets_no_slice_and_is_named():
    """Rule 4 / bd:shotockviz-sbe — a USD position with no rate cannot be added
    to a THB denominator raw, so it is excluded by name rather than mixed in."""
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),
        _Txn("NVDA", "BUY", 10, 100.0, currency="USD"),
    ]
    # No fx resolver at all -> only the base currency resolves (default_fx).
    _, _, alloc = _book(txns, {"PTT.BK": {"price": 40.0}, "NVDA": {"price": 150.0}})
    assert [s.symbol for s in alloc.slices] == ["PTT.BK"]
    assert _reasons(alloc) == {"NVDA": ps.EXCLUDED_FX_UNAVAILABLE}


def test_an_all_unpriced_book_has_no_slices_and_no_top_weight():
    """A percentage of nothing is undefined, not 0 — `top_weight_pct` is None
    rather than a number that would read as 'perfectly diversified'."""
    txns = [_Txn("PTT.BK", "BUY", 1000, 30.0), _Txn("KBANK.BK", "BUY", 100, 100.0)]
    _, _, alloc = _book(txns, {"PTT.BK": None, "KBANK.BK": None})

    assert alloc.slices == []
    assert alloc.total_value == 0.0
    assert alloc.top_weight_pct is None
    assert _reasons(alloc) == {
        "PTT.BK": ps.EXCLUDED_UNPRICED,
        "KBANK.BK": ps.EXCLUDED_UNPRICED,
    }


def test_an_empty_book_is_empty_not_broken():
    _, _, alloc = _book([], {})
    assert alloc.slices == []
    assert alloc.excluded == []
    assert alloc.top_weight_pct is None


# ─────────────────────────────────────────────────────────────────────────────
# FX — the weights are of CONVERTED value (bd:shotockviz-sbe / -fnn)
# ─────────────────────────────────────────────────────────────────────────────

def test_a_mixed_book_weighs_converted_value_not_raw_native_amounts():
    """The bug this guards: 300 USD and 300 THB are not the same slice."""
    txns = [
        _Txn("PTT.BK", "BUY", 10, 30.0),                                  # 300 THB
        _Txn("NVDA", "BUY", 3, 100.0, currency="USD", fx_rate=33.0),      # 300 USD
    ]
    _, totals, alloc = _book(
        txns,
        {"PTT.BK": {"price": 30.0}, "NVDA": {"price": 100.0}},
        fx=ps.fx_resolver({"USD": ps.FxRate("USD", 33.0, "live")}),
    )
    # NVDA is 300 * 33 = 9,900 THB; PTT.BK is 300 THB. Total 10,200.
    assert alloc.total_value == pytest.approx(10_200.0) == totals.total_value
    assert _weights(alloc) == pytest.approx(
        {"NVDA": 9_900 / 10_200 * 100, "PTT.BK": 300 / 10_200 * 100}
    )
    assert [s.symbol for s in alloc.slices] == ["NVDA", "PTT.BK"]
    assert alloc.slices[0].currency == "USD"


def test_an_estimated_rate_is_carried_onto_the_allocation():
    """The weights are only as good as the rate the denominator used."""
    txns = [
        _Txn("PTT.BK", "BUY", 10, 30.0),
        _Txn("NVDA", "BUY", 3, 100.0, currency="USD", fx_rate=33.0),
    ]
    _, _, alloc = _book(
        txns,
        {"PTT.BK": {"price": 30.0}, "NVDA": {"price": 100.0}},
        fx=ps.fx_resolver({"USD": ps.FxRate("USD", 33.0, "fallback")}),
    )
    assert alloc.fx_estimated is True

    _, _, live = _book(
        txns,
        {"PTT.BK": {"price": 30.0}, "NVDA": {"price": 100.0}},
        fx=ps.fx_resolver({"USD": ps.FxRate("USD", 33.0, "live")}),
    )
    assert live.fx_estimated is False


# ─────────────────────────────────────────────────────────────────────────────
# Corporate actions — a qualification travels with the slice (rule 7)
# ─────────────────────────────────────────────────────────────────────────────

def test_split_and_rights_flags_travel_onto_the_slice():
    """These qualify a position that IS counted (rule 7), so they must reach the
    chart's own labels rather than only the table's."""
    txns = [_Txn("PTT.BK", "BUY", 10, 30.0)]
    holdings = ps.active_holdings(ps.build_holdings(txns))
    holdings["PTT.BK"].split_adjusted = True
    holdings["PTT.BK"].rights_unstatable = True
    valued = ps.value_holdings(holdings, {"PTT.BK": {"price": 30.0}})
    alloc = ps.build_allocation(valued, ps.summarize(valued))

    assert alloc.slices[0].split_adjusted is True
    assert alloc.slices[0].rights_unstatable is True


# ─────────────────────────────────────────────────────────────────────────────
# One book, one inclusion decision
# ─────────────────────────────────────────────────────────────────────────────

def test_allocation_never_re_decides_inclusion():
    """Every symbol in the book appears exactly once: as a slice or as a named
    exclusion. Nothing is silently absent — that absence is the bug the bead is
    about."""
    txns = [
        _Txn("PTT.BK", "BUY", 1000, 30.0),
        _Txn("KBANK.BK", "BUY", 100, 100.0),                            # unpriced
        _Txn("NVDA", "BUY", 10, 100.0, currency="USD"),                 # no rate
        _Txn("AAPL", "BUY", 10, 100.0, currency="USD", fx_rate=33.0),
        _Txn("AAPL", "BUY", 10, 100.0, currency="THB"),                 # conflict
    ]
    _, totals, alloc = _book(
        txns,
        {
            "PTT.BK": {"price": 40.0},
            "KBANK.BK": None,
            "NVDA": {"price": 150.0},
            "AAPL": {"price": 150.0},
        },
    )
    accounted = {s.symbol for s in alloc.slices} | {e.symbol for e in alloc.excluded}
    assert accounted == {"PTT.BK", "KBANK.BK", "NVDA", "AAPL"}
    assert len(alloc.slices) + len(alloc.excluded) == 4  # no symbol counted twice
    assert {s.symbol for s in alloc.slices} == set(totals.priced_symbols)
