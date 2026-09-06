"""The remaining portfolio-side beads: the closed side of the book, and four
guards that stop it from stating a number it cannot support.

* bd:shotockviz-tmz — there was no realized P&L and no closed-trade record at
  all: the product reported unrealized P&L on open positions only, so a swing
  trader could not see what his finished trades actually made. The decision that
  matters is the COST FLOW: moving weighted average, argued in
  services/portfolio_service.py rule 6 (one book, one cost flow; a DATE-only
  ledger with no lot id cannot answer FIFO deterministically).
* bd:shotockviz-fin — a THIRD "is this position closed" threshold (a bare 0.001
  in `portfolio_performance.compute_holdings_on`) against `QTY_EPSILON` = 1e-6,
  so a fractional position between them was open on one screen and closed on the
  curve of the same book.
* bd:shotockviz-jgn — `fx_complete` was never reset on a full close, so a
  position closed entirely and reopened with lots that ALL carry rates still
  reported `fx_pl = None` forever.
* bd:shotockviz-mh1 — `FX_PLAUSIBLE_RANGE` is what makes a quote's orientation
  self-deciding (rule 4 / FX-4); a currency added to the enum without a band
  fails SILENTLY (every quote becomes "no rate"). Enforced at import now.
* bd:shotockviz-ace — qty / price / fee: which values are a transaction at all.
* bd:shotockviz-3p6 — the portfolio route accepted a bare ambiguous Thai symbol
  and said nothing while the registrar quietly refused to resolve it.
* bd:shotockviz-ayz — the cleanup for the rows the pre-m6q registrar wrote.
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from api.routes.portfolio import add_transaction, get_analytics, get_realized
from api.routes.portfolio_performance import get_portfolio_performance
from core.symbol_utils import ambiguous_bare_symbol_detail
from models.portfolio import Currency, Transaction, TransactionType
from models.schemas import TransactionCreate, TransactionUpdate
from services import portfolio_service

from tests.test_portfolio_fx import _Txn
from tests.test_portfolio_valuation import _FakeRedis, _no_corporate_actions, _redis_store

D0 = date(2024, 1, 1)
FX_QUOTE = {"symbol": "THBUSD=X", "price": 1.0 / 35.0}   # 35 THB per USD
RATE = 35.0


def _realized(*txns):
    """Fold raw transactions straight into the realized book."""
    return portfolio_service.build_realized(portfolio_service.build_holdings(txns))


async def _seed(db, user, rows):
    """rows: (symbol, type, qty, price, fee, currency, fx_rate, when)."""
    for symbol, type_, qty, price, fee, currency, fx_rate, when in rows:
        db.add(Transaction(
            user_id=user.id, symbol=symbol, type=TransactionType[type_],
            qty=qty, price=price, fee=fee, currency=Currency[currency],
            fx_rate=fx_rate, date=when,
        ))
    await db.flush()


async def _analytics(db, user, quotes):
    store = _redis_store({**quotes, portfolio_service.FX_QUOTE_SYMBOL: FX_QUOTE})
    with patch("services.stock_service.get_redis",
               AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()), \
         _no_corporate_actions():
        return await get_analytics(user=user, db=db)


async def _add(db, user, **kwargs):
    store = _redis_store({portfolio_service.FX_QUOTE_SYMBOL: FX_QUOTE})
    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("workers.symbol_registrar.register_symbol", MagicMock()):
        return await add_transaction(body=TransactionCreate(**kwargs), user=user, db=db)


# ═════════════════════════════════════════════════════════════════════════════
# bd:shotockviz-tmz — realized P&L on moving weighted-average cost
# ═════════════════════════════════════════════════════════════════════════════

def test_a_round_trip_reports_what_it_actually_made():
    """Buy 100 @ ฿35 + ฿100 commission, sell 100 @ ฿40 − ฿100 commission.
    Breakeven is ฿36.00, not ฿35.00, and the trade made ฿300, not ฿500."""
    book = _realized(
        _Txn("PTT.BK", "BUY", 100.0, 35.0, fee=100.0, when=D0),
        _Txn("PTT.BK", "SELL", 100.0, 40.0, fee=100.0, when=D0 + timedelta(days=4)),
    )
    assert book.total_trades == 1
    trade = book.closed_positions[0]
    assert trade.symbol == "PTT.BK"
    assert trade.qty == pytest.approx(100.0)
    assert trade.entry_price == pytest.approx(36.0)   # buy fee is IN the cost
    assert trade.exit_price == pytest.approx(40.0)    # gross of the sell fee
    assert trade.fees == pytest.approx(100.0)         # which is here, and only here
    assert trade.realized_pl == pytest.approx(300.0)
    assert trade.holding_days == 4
    assert book.realized_pl == pytest.approx(300.0)
    assert book.realized_fees == pytest.approx(100.0)


def test_a_partial_sale_releases_average_cost_not_the_oldest_lot():
    """THE cost-flow decision, stated as a number. Buy 100 @ ฿30 then 100 @ ฿40,
    sell 100 @ ฿50: average cost releases ฿3,500 (P&L ฿1,500). FIFO would
    release the ฿30 lot and claim ฿2,000 — a different answer for the same
    trade, and one the remaining position's ฿35 avg cost would then contradict."""
    holdings = portfolio_service.build_holdings([
        _Txn("PTT.BK", "BUY", 100.0, 30.0, when=D0),
        _Txn("PTT.BK", "BUY", 100.0, 40.0, when=D0 + timedelta(days=1)),
        _Txn("PTT.BK", "SELL", 100.0, 50.0, when=D0 + timedelta(days=2)),
    ])
    sale = holdings["PTT.BK"].sales[0]
    assert sale.cost_released == pytest.approx(3500.0)
    assert sale.realized_pl == pytest.approx(1500.0)
    assert sale.realized_pl != pytest.approx(2000.0)   # the FIFO answer
    # And the shares still held stay on the same cost flow — the two halves of
    # the book still add up to the cost that went in.
    assert holdings["PTT.BK"].avg_cost == pytest.approx(35.0)
    assert holdings["PTT.BK"].cost_basis == pytest.approx(3500.0)


def test_a_sell_commission_is_never_charged_to_the_shares_still_held():
    """bd:shotockviz-fww's rule, now visible: the ฿100 exit fee lands in realized
    P&L and leaves the open position's cost basis alone."""
    holdings = portfolio_service.build_holdings([
        _Txn("PTT.BK", "BUY", 200.0, 35.0, when=D0),
        _Txn("PTT.BK", "SELL", 100.0, 40.0, fee=100.0, when=D0 + timedelta(days=1)),
    ])
    h = holdings["PTT.BK"]
    assert h.cost_basis == pytest.approx(3500.0)   # 100 shares still at ฿35
    assert h.avg_cost == pytest.approx(35.0)
    assert h.sales[0].realized_pl == pytest.approx(400.0)  # 4000 − 3500 − 100
    assert h.realized_fees == pytest.approx(100.0)


def test_a_scale_out_is_realized_money_before_the_position_closes():
    """Half sold, half held. The money taken off the table is real and is
    counted; the round trip is not finished and is NOT counted as a closed
    trade. That is why the two totals are reported separately."""
    book = _realized(
        _Txn("PTT.BK", "BUY", 200.0, 35.0, when=D0),
        _Txn("PTT.BK", "SELL", 100.0, 40.0, when=D0 + timedelta(days=1)),
    )
    assert book.realized_pl == pytest.approx(500.0)
    assert book.total_trades == 0
    assert book.closed_positions == []
    assert book.closed_positions_pl == pytest.approx(0.0)


def test_a_symbol_bought_closed_and_bought_again_is_two_trades():
    book = _realized(
        _Txn("PTT.BK", "BUY", 100.0, 30.0, when=D0),
        _Txn("PTT.BK", "SELL", 100.0, 35.0, when=D0 + timedelta(days=2)),
        _Txn("PTT.BK", "BUY", 100.0, 40.0, when=D0 + timedelta(days=10)),
        _Txn("PTT.BK", "SELL", 100.0, 38.0, when=D0 + timedelta(days=12)),
    )
    assert book.total_trades == 2
    assert sorted(t.realized_pl for t in book.closed_positions) == [
        pytest.approx(-200.0), pytest.approx(500.0)]
    # The second trip's holding period starts at ITS buy, not the first one's.
    latest = book.closed_positions[0]           # most recent first
    assert latest.closed_on == D0 + timedelta(days=12)
    assert latest.holding_days == 2
    assert book.wins == 1 and book.losses == 1


def test_realized_pl_converts_at_the_rate_at_disposal():
    """Bought 10 NVDA @ $100 when the dollar was ฿30, sold @ $110 at ฿40.
    In THB the trade made ฿14,000: ฿4,000 of market move and ฿10,000 of
    currency. Converting both sides at one rate would hide the second half —
    the same structural blindness bd:shotockviz-fnn removed from the open side."""
    book = _realized(
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0, when=D0),
        _Txn("NVDA", "SELL", 10.0, 110.0, currency="USD", fx_rate=40.0,
             when=D0 + timedelta(days=1)),
    )
    trade = book.closed_positions[0]
    assert trade.realized_pl == pytest.approx(100.0)          # native USD
    assert trade.realized_pl_base == pytest.approx(14000.0)   # THB
    assert book.realized_pl == pytest.approx(14000.0)


def test_a_disposal_with_no_rate_is_unknown_not_zero():
    """No rate on the SELL row -> the THB result of that trade is not knowable.
    It is named and left out, never counted as a zero-value trade."""
    book = _realized(
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0, when=D0),
        _Txn("NVDA", "SELL", 10.0, 110.0, currency="USD", fx_rate=None,
             when=D0 + timedelta(days=1)),
    )
    assert book.closed_positions[0].realized_pl == pytest.approx(100.0)  # native still true
    assert book.closed_positions[0].realized_pl_base is None
    assert book.realized_unavailable_symbols == ["NVDA"]
    assert book.realized_pl == pytest.approx(0.0) and book.counted_sales == 0
    assert book.total_trades == 0            # cannot be judged win or loss
    assert book.win_rate is None


def test_a_lot_bought_without_a_rate_makes_its_disposal_unconvertible_too():
    """The cost side has to be complete as well — half of a THB answer is not
    an answer."""
    book = _realized(
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=None, when=D0),
        _Txn("NVDA", "SELL", 10.0, 110.0, currency="USD", fx_rate=40.0,
             when=D0 + timedelta(days=1)),
    )
    assert book.closed_positions[0].realized_pl_base is None
    assert book.realized_unavailable_symbols == ["NVDA"]


def test_win_rate_and_profit_factor_are_stated_on_closed_trips():
    """Two wins (+฿1,000, +฿500) and one loss (−฿1,000): 2/3 = 66.67% and a
    profit factor of 1.5."""
    rows = []
    for i, (symbol, exit_price) in enumerate(
            [("AAA.BK", 160.0), ("BBB.BK", 140.0), ("CCC.BK", 155.0)]):
        rows.append(_Txn(symbol, "BUY", 100.0, 150.0, when=D0 + timedelta(days=2 * i)))
        rows.append(_Txn(symbol, "SELL", 100.0, exit_price,
                         when=D0 + timedelta(days=2 * i + 1)))
    book = _realized(*rows)

    assert book.total_trades == 3
    assert (book.wins, book.losses, book.scratches) == (2, 1, 0)
    assert book.win_rate == pytest.approx(66.67, abs=0.01)
    assert book.gross_profit == pytest.approx(1500.0)
    assert book.gross_loss == pytest.approx(1000.0)
    assert book.profit_factor == pytest.approx(1.5)


def test_profit_factor_is_undefined_rather_than_infinite_without_a_loss():
    book = _realized(
        _Txn("PTT.BK", "BUY", 100.0, 30.0, when=D0),
        _Txn("PTT.BK", "SELL", 100.0, 35.0, when=D0 + timedelta(days=1)),
    )
    assert book.profit_factor is None
    assert book.win_rate == pytest.approx(100.0)


def test_a_break_even_trade_is_a_scratch_not_a_win():
    book = _realized(
        _Txn("PTT.BK", "BUY", 100.0, 35.0, when=D0),
        _Txn("PTT.BK", "SELL", 100.0, 35.0, when=D0 + timedelta(days=1)),
    )
    assert (book.wins, book.losses, book.scratches) == (0, 0, 1)
    assert book.total_trades == 1
    assert book.win_rate == pytest.approx(0.0)   # in the denominator only


def test_selling_more_than_the_book_records_buying_is_flagged_not_absorbed():
    """The cost of shares there is no record of buying cannot be stated, so the
    realized figure is overstated. Say so instead of printing a windfall."""
    book = _realized(
        _Txn("PTT.BK", "BUY", 100.0, 35.0, when=D0),
        _Txn("PTT.BK", "SELL", 150.0, 40.0, when=D0 + timedelta(days=1)),
    )
    assert book.oversold_symbols == ["PTT.BK"]


def test_a_currency_conflicted_symbol_states_no_realized_pl_either():
    """Rule 5: rows that mix units have no cost, therefore no realized P&L."""
    book = _realized(
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0, when=D0),
        _Txn("NVDA", "BUY", 100.0, 35.0, currency="THB", when=D0 + timedelta(days=1)),
        _Txn("NVDA", "SELL", 10.0, 110.0, currency="USD", fx_rate=40.0,
             when=D0 + timedelta(days=2)),
    )
    assert book.currency_conflict_symbols == ["NVDA"]
    assert book.closed_positions == []
    assert book.realized_pl == pytest.approx(0.0)


def test_an_untouched_book_reports_no_realized_pl_at_all():
    """Nothing sold. `counted_sales == 0` is what lets the API print nothing
    instead of a ฿0.00 that would read as "your closed trades made nothing"."""
    book = _realized(_Txn("PTT.BK", "BUY", 100.0, 35.0, when=D0))
    assert book.counted_sales == 0
    assert book.total_trades == 0
    assert book.win_rate is None and book.profit_factor is None


# ── the two API surfaces ─────────────────────────────────────────────────────

async def test_the_analytics_payload_carries_the_realized_summary(test_db, test_user):
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 100.0, 35.0, 100.0, "THB", 1.0, D0),
        ("PTT.BK", "SELL", 100.0, 40.0, 100.0, "THB", 1.0, D0 + timedelta(days=4)),
        ("KBANK.BK", "BUY", 100.0, 120.0, 0.0, "THB", 1.0, D0 + timedelta(days=5)),
    ])
    analytics = await _analytics(test_db, test_user, {"KBANK.BK": {"price": 130.0}})

    assert analytics.realized_pl == pytest.approx(300.0)
    assert analytics.realized_fees == pytest.approx(100.0)
    assert analytics.closed_positions_pl == pytest.approx(300.0)
    assert analytics.total_trades == 1
    assert analytics.win_rate == pytest.approx(100.0)
    assert analytics.profit_factor is None
    assert analytics.realized_unavailable_symbols == []
    # The open position is untouched by any of this.
    assert [h.symbol for h in analytics.holdings] == ["KBANK.BK"]
    assert analytics.unrealized_pl == pytest.approx(1000.0)


async def test_analytics_prints_nothing_rather_than_zero_when_nothing_is_closed(
        test_db, test_user):
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 100.0, 35.0, 0.0, "THB", 1.0, D0),
    ])
    analytics = await _analytics(test_db, test_user, {"PTT.BK": {"price": 38.0}})
    assert analytics.realized_pl is None
    assert analytics.closed_positions_pl is None
    assert analytics.total_trades == 0


async def test_the_realized_endpoint_is_the_closed_trade_record(test_db, test_user):
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 100.0, 35.0, 100.0, "THB", 1.0, D0),
        ("PTT.BK", "SELL", 100.0, 40.0, 100.0, "THB", 1.0, D0 + timedelta(days=4)),
    ])
    with _no_corporate_actions():
        book = await get_realized(user=test_user, db=test_db)

    assert book.base_currency == "THB"
    assert book.cost_flow == "moving_average"      # declared, not implied
    assert book.total_trades == 1
    row = book.closed_positions[0]
    assert (row.symbol, row.qty) == ("PTT.BK", 100.0)
    assert row.opened_on == D0 and row.closed_on == D0 + timedelta(days=4)
    assert row.holding_days == 4
    assert row.entry_price == pytest.approx(36.0)
    assert row.exit_price == pytest.approx(40.0)
    assert row.realized_pl == pytest.approx(300.0)
    assert row.realized_pl_pct == pytest.approx(8.33, abs=0.01)


async def test_the_realized_endpoint_is_empty_but_shaped_for_a_new_user(
        test_db, test_user):
    with _no_corporate_actions():
        book = await get_realized(user=test_user, db=test_db)
    assert book.closed_positions == []
    assert book.realized_pl is None
    assert book.total_trades == 0


# ═════════════════════════════════════════════════════════════════════════════
# bd:shotockviz-fin — one epsilon
# ═════════════════════════════════════════════════════════════════════════════

async def test_a_fractional_position_is_open_on_every_screen_or_none(test_db, test_user):
    """0.0005 of a share sits between the old 0.001 and QTY_EPSILON = 1e-6: the
    holdings table called it open and the equity curve called it closed."""
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 1.0, 100.0, 0.0, "THB", 1.0, D0),
        ("PTT.BK", "SELL", 0.9995, 100.0, 0.0, "THB", 1.0, D0),
    ])
    txns = (await test_db.execute(select(Transaction))).scalars().all()

    holdings = portfolio_service.build_holdings(txns)
    assert portfolio_service.active_holdings(holdings)["PTT.BK"].qty == pytest.approx(0.0005)

    async def _read_history(symbol, tf):
        return [{"time": D0.isoformat(), "open": 100.0, "high": 100.0,
                 "low": 100.0, "close": 100.0, "volume": 0}]

    with patch("services.stock_service.read_history", _read_history), \
         patch("services.stock_service.request_data_fetch", AsyncMock()), \
         patch("api.routes.portfolio_performance.fx_quote_cached",
               AsyncMock(return_value=FX_QUOTE)), \
         _no_corporate_actions():
        curve = await get_portfolio_performance(period="ALL", user=test_user, db=test_db)

    # The curve must still hold the position on the day it was bought.
    assert curve["points"], "the curve dropped a position the holdings table shows as open"
    assert curve["points"][0]["value"] == pytest.approx(0.05, abs=1e-9)


def test_the_curve_imports_the_epsilon_instead_of_restating_it():
    """A fourth copy of the number is how the third one happened."""
    import inspect

    from api.routes import portfolio_performance

    source = inspect.getsource(portfolio_performance.get_portfolio_performance)
    assert "0.001" not in source
    assert "portfolio_service.QTY_EPSILON" in source


# ═════════════════════════════════════════════════════════════════════════════
# bd:shotockviz-jgn — fx_complete must be released on a full close
# ═════════════════════════════════════════════════════════════════════════════

def test_closing_a_position_clears_the_fx_gap_its_old_lots_left():
    """A rateless lot is a fact about lots that are no longer held. Carrying it
    past the close made the reopened position claim it could not separate an FX
    return it demonstrably could."""
    holdings = portfolio_service.build_holdings([
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=None, when=D0),
        _Txn("NVDA", "SELL", 10.0, 110.0, currency="USD", fx_rate=30.0,
             when=D0 + timedelta(days=1)),
        _Txn("NVDA", "BUY", 5.0, 120.0, currency="USD", fx_rate=32.0,
             when=D0 + timedelta(days=2)),
    ])
    h = holdings["NVDA"]
    assert h.fx_complete is True
    assert h.cost_basis_base == pytest.approx(5 * 120.0 * 32.0)

    fx = portfolio_service.fx_resolver(
        {"USD": portfolio_service.FxRate(currency="USD", rate=RATE, source="live")})
    row = portfolio_service.value_holdings(holdings, {"NVDA": {"price": 130.0}}, fx=fx)[0]
    assert row.cost_basis_source == "historical"
    assert row.fx_pl_base is not None
    # (35 − 32) THB on each of the $600 of cost still held.
    assert row.fx_pl_base == pytest.approx(600.0 * (RATE - 32.0))


def test_an_open_position_with_a_rateless_lot_still_reports_the_gap():
    """The reset is on a FULL close only — nothing about the guard weakens the
    honest 'unknown' while those lots are still held."""
    holdings = portfolio_service.build_holdings([
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=None, when=D0),
        _Txn("NVDA", "SELL", 5.0, 110.0, currency="USD", fx_rate=30.0,
             when=D0 + timedelta(days=1)),
    ])
    assert holdings["NVDA"].fx_complete is False


def test_a_symbols_currency_history_survives_the_close():
    """Rule 5 judges a symbol over ALL of its rows, closed lots included — the
    close must not launder a mixed-currency history."""
    holdings = portfolio_service.build_holdings([
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0, when=D0),
        _Txn("NVDA", "SELL", 10.0, 110.0, currency="USD", fx_rate=30.0,
             when=D0 + timedelta(days=1)),
        _Txn("NVDA", "BUY", 100.0, 35.0, currency="THB", when=D0 + timedelta(days=2)),
    ])
    assert holdings["NVDA"].currency_conflict is True


# ═════════════════════════════════════════════════════════════════════════════
# bd:shotockviz-mh1 — a currency without a band cannot be added
# ═════════════════════════════════════════════════════════════════════════════

def test_a_currency_without_a_plausibility_band_is_refused():
    with pytest.raises(ValueError) as exc:
        portfolio_service.assert_currency_band_coverage(["THB", "USD", "JPY"])
    assert "JPY" in str(exc.value)
    assert "FX_PLAUSIBLE_RANGE" in str(exc.value)


def test_the_base_currency_needs_no_band():
    portfolio_service.assert_currency_band_coverage(["THB"])


def test_the_shipped_currency_enum_is_covered():
    portfolio_service.assert_currency_band_coverage(Currency)


def test_the_enum_module_runs_the_guard_at_import():
    """Enforcement, not documentation: the check has to fire where the enum is
    DEFINED, so a new member without a band stops the app from starting rather
    than making one screen quietly say 'no rate available' forever."""
    import inspect

    from models import portfolio as portfolio_model

    assert (portfolio_model.assert_currency_band_coverage
            is portfolio_service.assert_currency_band_coverage)
    assert "assert_currency_band_coverage(Currency)" in inspect.getsource(portfolio_model)


def test_a_band_still_has_to_sit_above_one():
    """The ss3 invariant is untouched by mh1 — a band straddling 1.0 makes the
    orientation of the pair undecidable again."""
    with patch.dict(portfolio_service.FX_PLAUSIBLE_RANGE, {"JPY": (0.5, 100.0)}):
        with pytest.raises(ValueError):
            portfolio_service._check_band_invariant()


# ═════════════════════════════════════════════════════════════════════════════
# bd:shotockviz-ace — what a transaction's numbers may be
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("field,value", [
    ("qty", 0.0),          # not an event
    ("qty", -10.0),        # direction is `type`, not a sign
    ("price", -1.0),       # never a price
    ("fee", -50.0),        # a rebate is not a commission (fww: it hits cost basis)
    ("qty", float("inf")),
    ("price", float("inf")),
    ("fee", float("nan")),
])
def test_a_transaction_cannot_be_created_with_that_value(field, value):
    payload = {"symbol": "PTT.BK", "type": "BUY", "qty": 10.0, "price": 35.0,
               "fee": 0.0, "date": D0, field: value}
    with pytest.raises(ValidationError):
        TransactionCreate(**payload)


@pytest.mark.parametrize("field,value", [
    ("qty", 0.0), ("qty", -1.0), ("price", -1.0), ("fee", -1.0),
])
def test_the_edit_route_holds_the_same_line(field, value):
    """`_ALLOWED_UPDATE_FIELDS` writes qty/price/fee straight onto the row, so an
    unvalidated PUT was a second door to the values the POST refuses."""
    with pytest.raises(ValidationError):
        TransactionUpdate(**{field: value})


def test_a_zero_price_buy_is_legal_because_bonus_shares_are_real():
    """Decision, not an oversight: a stock dividend / free allotment really is
    acquired at zero, and a SET book meets those."""
    txn = TransactionCreate(symbol="PTT.BK", type="BUY", qty=100.0, price=0.0,
                            fee=0.0, date=D0)
    assert txn.price == 0.0


async def test_a_zero_cost_position_declines_to_state_a_return_percentage(
        test_db, test_user):
    """The consequence of the decision above, and the right one: a return on a
    zero cost basis is undefined, not infinite and not 0%."""
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 100.0, 0.0, 0.0, "THB", 1.0, D0),
    ])
    analytics = await _analytics(test_db, test_user, {"PTT.BK": {"price": 38.0}})
    row = analytics.holdings[0]
    assert row.cost_basis_base == pytest.approx(0.0)
    assert row.unrealized_pl == pytest.approx(3800.0)
    assert row.unrealized_pl_pct is None


def test_a_zero_fee_is_still_ordinary():
    assert TransactionCreate(symbol="PTT.BK", type="BUY", qty=1.0, price=1.0,
                             fee=0.0, date=D0).fee == 0.0


# ═════════════════════════════════════════════════════════════════════════════
# bd:shotockviz-3p6 — a bare ambiguous symbol on the portfolio route
# ═════════════════════════════════════════════════════════════════════════════

async def test_a_bare_ambiguous_symbol_is_refused_with_the_fix_in_the_message(
        test_db, test_user):
    """Before: 201, a `register_symbol` task that silently declined (m6q), and a
    position that never resolved to an instrument with nothing said to anyone."""
    with pytest.raises(HTTPException) as exc:
        await _add(test_db, test_user, symbol="SCB", type="BUY", qty=100, price=120,
                   currency="THB", date=D0)
    assert exc.value.status_code == 400
    assert "SCB.BK" in exc.value.detail


async def test_the_two_routes_tell_the_user_the_same_story(test_db, test_user):
    """One wording, one place — `watchlist.py` and `portfolio.py` refusing the
    same symbol differently would be its own bug."""
    with pytest.raises(HTTPException) as exc:
        await _add(test_db, test_user, symbol="tisco", type="BUY", qty=10, price=90,
                   currency="THB", date=D0)
    assert exc.value.detail == ambiguous_bare_symbol_detail("TISCO")


async def test_the_refusal_happens_before_anything_is_written(test_db, test_user):
    body = TransactionCreate(symbol="ASP", type="BUY", qty=10, price=10,
                             currency="THB", date=D0)
    with patch("workers.symbol_registrar.register_symbol") as registrar:
        with pytest.raises(HTTPException):
            await add_transaction(body=body, user=test_user, db=test_db)
        registrar.delay.assert_not_called()

    assert (await test_db.execute(select(Transaction))).scalars().all() == []


async def test_the_suffixed_symbol_is_accepted_exactly_as_before(test_db, test_user):
    txn = await _add(test_db, test_user, symbol="SCB.BK", type="BUY", qty=100,
                     price=120, currency="THB", date=D0)
    assert txn.symbol == "SCB.BK"


async def test_an_unrelated_symbol_is_none_of_this_guards_business(test_db, test_user):
    txn = await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=10,
                     price=100, currency="USD", date=D0)
    assert txn.symbol == "NVDA"


# ═════════════════════════════════════════════════════════════════════════════
# bd:shotockviz-ayz — the cleanup's selection rule
# ═════════════════════════════════════════════════════════════════════════════

class _StubResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _StubConn:
    """Just enough of a SQLAlchemy connection for `find_candidates`."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        return _StubResult(self._rows)


def test_the_cleanup_targets_only_rows_the_registrar_would_refuse_today():
    """The criterion is imported from the shipped gate, so the script cannot
    drift into deleting something the app would happily write."""
    from scripts.purge_ambiguous_stock_rows import find_candidates

    rows = [
        (1, "TISCO", "Tisco", "FUND"),      # the actual stale dev row
        (2, "SCB", "1249", "FUND"),         # same shape
        (3, "TISCO.BK", "Tisco Financial", "SET"),
        (4, "K-CHINA", "K China", "FUND"),  # an unambiguous fund code
        (5, "AAPL", "Apple Inc.", "US"),
        (6, "BTC-USD", "Bitcoin", "CRYPTO"),
    ]
    picked = {c["symbol"] for c in find_candidates(_StubConn(rows))}
    assert picked == {"TISCO", "SCB"}
    assert all(c["classified_now"] == "AMBIGUOUS" for c in find_candidates(_StubConn(rows)))
