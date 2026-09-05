"""The last two places the portfolio book could still state a wrong number.

* bd:shotockviz-la4 — the equity curve (`/portfolio/performance`, the third
  `/portfolio` surface, feeding the Dashboard sparkline) did
  `total_value += price * qty` across every symbol with NO currency conversion
  at all, while the header total on the same screen was correctly normalised to
  THB. Rule 4 forbids that addition; this surface never got the fold.
  It cannot be fixed with historical rates — those are deliberately not
  backfilled — so it is fixed by converting the whole curve at ONE current rate
  and SAYING so (`fx_basis`), which is a claim the data supports.

* bd:shotockviz-7ju — `build_holdings` took a position's currency from the
  FIRST transaction for that symbol. One symbol recorded once in THB and once in
  USD therefore produced a `cost_basis` that summed two different units, and the
  FX conversion inherited the error silently. Rule 5: the write path refuses,
  the read path excludes and names.
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.routes import portfolio_performance as perf_route
from api.routes.portfolio import add_transaction, get_analytics, update_transaction
from api.routes.portfolio_performance import get_portfolio_performance
from models.portfolio import Currency, Transaction, TransactionType
from models.schemas import TransactionCreate, TransactionUpdate
from services import portfolio_service

from tests.test_portfolio_fx import _Txn
from tests.test_portfolio_valuation import _FakeRedis, _redis_store

# 1 THB in USD -> 35 THB per USD, the same fixture the FX suite uses.
FX_QUOTE = {"symbol": "THBUSD=X", "price": 1.0 / 35.0}
RATE = 35.0

D2 = date.today() - timedelta(days=2)
D1 = date.today() - timedelta(days=1)
D0 = date.today()


async def _seed(db, user, rows, when=None):
    """rows: (symbol, type, qty, price, currency, fx_rate)."""
    for symbol, type_, qty, price, currency, fx_rate in rows:
        db.add(Transaction(
            user_id=user.id,
            symbol=symbol,
            type=TransactionType[type_],
            qty=qty,
            price=price,
            fee=0.0,
            currency=Currency[currency],
            fx_rate=fx_rate,
            date=when or D2,
        ))
    await db.flush()


def _bars(closes: dict[date, float]) -> list[dict]:
    return [{"time": d.isoformat(), "open": c, "high": c, "low": c, "close": c, "volume": 0}
            for d, c in closes.items()]


async def _curve(db, user, histories, fx_quote=FX_QUOTE, period="1M"):
    async def _read_history(symbol, tf):
        return histories.get(symbol, [])

    with patch("services.stock_service.read_history", _read_history), \
         patch("services.stock_service.request_data_fetch", AsyncMock()), \
         patch("api.routes.portfolio_performance.fx_quote_cached",
               AsyncMock(return_value=fx_quote)):
        return await get_portfolio_performance(period=period, user=user, db=db)


# ─────────────────────────────────────────────────────────────────────────────
# bd:shotockviz-la4 — the equity curve
# ─────────────────────────────────────────────────────────────────────────────

async def test_the_equity_curve_converts_instead_of_adding_thb_and_usd_raw(test_db, test_user):
    """The bead itself. 100 PTT.BK @ ฿40 + 10 NVDA @ $110 is ฿4,000 + ฿38,500 =
    ฿42,500 — not the 4,000 + 1,100 = 5,100 the old line produced."""
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 100.0, 35.0, "THB", 1.0),
        ("NVDA", "BUY", 10.0, 100.0, "USD", 30.0),
    ])
    result = await _curve(test_db, test_user, {
        "PTT.BK": _bars({D2: 36.0, D1: 38.0, D0: 40.0}),
        "NVDA": _bars({D2: 100.0, D1: 105.0, D0: 110.0}),
    })

    values = {p["date"]: p["value"] for p in result["points"]}
    assert values[D0.isoformat()] == pytest.approx(100 * 40.0 + 10 * 110.0 * RATE)
    assert values[D1.isoformat()] == pytest.approx(100 * 38.0 + 10 * 105.0 * RATE)
    # The number the old code would have produced, explicitly excluded.
    assert values[D0.isoformat()] != pytest.approx(100 * 40.0 + 10 * 110.0)


async def test_a_mixed_curve_declares_that_it_used_one_constant_rate(test_db, test_user):
    """A curve converted at today's rate is NOT what the book was worth in THB
    on those dates. It may only be published if it says which basis it is on."""
    await _seed(test_db, test_user, [("NVDA", "BUY", 10.0, 100.0, "USD", 30.0)])
    result = await _curve(test_db, test_user, {"NVDA": _bars({D1: 105.0, D0: 110.0})})

    assert result["base_currency"] == "THB"
    assert result["fx_basis"] == portfolio_service.CURVE_BASIS_CONSTANT_RATE
    assert result["fx_estimated"] is False               # a live quote was available
    assert [(r["currency"], r["source"], r["rate"]) for r in result["fx_rates"]] == [
        ("USD", "live", RATE)]
    # bd:shotockviz-ss3 — and it says which way up it read the pair.
    assert result["fx_rates"][0]["quote_orientation"] == portfolio_service.ORIENTATION_RECIPROCAL


async def test_a_thb_only_curve_claims_no_fx_basis_at_all(test_db, test_user):
    """Nothing was converted, so there is nothing to qualify — the common Thai
    book must not grow a constant-rate caveat it does not need."""
    await _seed(test_db, test_user, [("PTT.BK", "BUY", 100.0, 35.0, "THB", 1.0)])
    result = await _curve(test_db, test_user, {"PTT.BK": _bars({D1: 38.0, D0: 40.0})})

    assert result["fx_basis"] == portfolio_service.CURVE_BASIS_SINGLE_CURRENCY
    assert result["fx_rates"] == []
    assert result["fx_estimated"] is False
    assert {p["value"] for p in result["points"]} == {3800.0, 4000.0}


async def test_an_estimated_rate_is_carried_onto_the_curve_not_hidden(test_db, test_user):
    """Cold THBUSD=X — the normal off-hours state. The curve still draws, at the
    fallback rate, and is marked estimated rather than looking observed."""
    await _seed(test_db, test_user, [("NVDA", "BUY", 10.0, 100.0, "USD", None)])
    result = await _curve(test_db, test_user, {"NVDA": _bars({D0: 110.0})}, fx_quote=None)

    assert result["fx_estimated"] is True
    assert result["fx_rates"][0]["source"] == "fallback"
    assert result["fx_rates"][0]["quote_orientation"] is None
    assert result["points"][-1]["value"] == pytest.approx(10 * 110.0 * 33.0)


async def test_the_curve_and_the_header_total_agree_on_the_same_book(test_db, test_user):
    """The property bd:shotockviz-la4 is really about: with today's close equal
    to today's quote, the last point of the sparkline and the total printed next
    to it are the same number. They used to differ by the whole FX conversion."""
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 100.0, 35.0, "THB", 1.0),
        ("NVDA", "BUY", 10.0, 100.0, "USD", 30.0),
    ])
    quotes = {
        "PTT.BK": {"symbol": "PTT.BK", "price": 40.0},
        "NVDA": {"symbol": "NVDA", "price": 110.0},
        portfolio_service.FX_QUOTE_SYMBOL: FX_QUOTE,
    }
    with patch("services.stock_service.get_redis",
               AsyncMock(return_value=_FakeRedis(_redis_store(quotes)))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()):
        analytics = await get_analytics(user=test_user, db=test_db)

    curve = await _curve(test_db, test_user, {
        "PTT.BK": _bars({D0: 40.0}),
        "NVDA": _bars({D0: 110.0}),
    })

    assert curve["points"][-1]["date"] == D0.isoformat()
    assert curve["points"][-1]["value"] == pytest.approx(analytics.total_value)
    assert curve["base_currency"] == analytics.base_currency


async def test_an_unstatable_symbol_removes_the_whole_day_not_just_its_term(test_db, test_user):
    """Dropping one position's term out of a time series makes the line fall on
    the day it appears, which reads as a realised loss that never happened. So
    the DAY goes, and the culprit is named in the payload instead. Same rule the
    route already applied to an unpriced symbol."""
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 100.0, 35.0, "THB", 1.0),
        ("NVDA", "BUY", 10.0, 100.0, "USD", 30.0),
        ("NVDA", "BUY", 100.0, 35.0, "THB", 1.0),   # legacy conflict, rule 5
    ])
    result = await _curve(test_db, test_user, {
        "PTT.BK": _bars({D1: 38.0, D0: 40.0}),
        "NVDA": _bars({D1: 105.0, D0: 110.0}),
    })

    assert result["currency_conflict_symbols"] == ["NVDA"]
    assert result["excluded_symbols"] == ["NVDA"]
    # NVDA is held on every day of the window, so no day can be stated. The
    # curve declines entirely rather than drawing a PTT.BK-only line that the
    # user would read as the whole book.
    assert result["points"] == []


async def test_a_symbol_that_is_no_longer_held_cannot_break_the_curve(test_db, test_user):
    """The exclusion is per-day and driven by what was HELD that day, so a
    conflicted position that nets to zero costs the user nothing but a note."""
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 100.0, 35.0, "THB", 1.0),
        ("NVDA", "BUY", 10.0, 100.0, "USD", 30.0),
        ("NVDA", "SELL", 10.0, 100.0, "THB", 1.0),
    ])
    result = await _curve(test_db, test_user, {
        "PTT.BK": _bars({D1: 38.0, D0: 40.0}),
        "NVDA": _bars({D1: 105.0, D0: 110.0}),
    })

    assert result["currency_conflict_symbols"] == ["NVDA"]
    assert {p["value"] for p in result["points"]} == {3800.0, 4000.0}


async def test_no_transactions_still_returns_the_full_shape(test_db, test_user):
    result = await _curve(test_db, test_user, {})
    for key in ("points", "base_currency", "fx_basis", "fx_rates", "fx_estimated",
                "fx_unavailable_symbols", "currency_conflict_symbols", "excluded_symbols"):
        assert key in result, key
    assert result["points"] == []


# ─────────────────────────────────────────────────────────────────────────────
# bd:shotockviz-7ju — one symbol, one currency
# ─────────────────────────────────────────────────────────────────────────────

def test_a_symbol_in_two_currencies_no_longer_inherits_the_first_ones_unit():
    """The fold used to answer "USD" here and hand back a cost basis of
    1,000 + 3,500 as if both were dollars."""
    holdings = portfolio_service.build_holdings([
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0),
        _Txn("NVDA", "BUY", 100.0, 35.0, currency="THB"),
    ])
    h = holdings["NVDA"]
    assert h.currency_conflict is True
    assert h.currencies == {"USD", "THB"}


def test_a_consistent_symbol_is_not_flagged():
    holdings = portfolio_service.build_holdings([
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0),
        _Txn("NVDA", "BUY", 5.0, 120.0, currency="USD", fx_rate=32.0),
        _Txn("PTT.BK", "BUY", 100.0, 35.0),
    ])
    assert holdings["NVDA"].currency_conflict is False
    assert holdings["PTT.BK"].currency_conflict is False


def test_a_conflicted_position_states_no_money_at_all_and_is_excluded_by_name():
    """Not priced, not valued, not summed — and visible, so the user can go fix
    the rows. Silence here is what let the mixed cost basis through."""
    fx = portfolio_service.fx_resolver({
        "USD": portfolio_service.FxRate(currency="USD", rate=RATE, source="live")})
    holdings = portfolio_service.build_holdings([
        _Txn("PTT.BK", "BUY", 100.0, 35.0),
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0),
        _Txn("NVDA", "BUY", 100.0, 35.0, currency="THB"),
    ])
    valued = portfolio_service.value_holdings(
        holdings, {"PTT.BK": {"price": 38.0}, "NVDA": {"price": 110.0}}, fx=fx)
    row = {v.symbol: v for v in valued}["NVDA"]

    assert row.currency_conflict is True
    assert row.currencies == ["THB", "USD"]
    assert row.avg_cost is None and row.cost_basis is None
    assert row.current_price is None and row.current_value is None
    assert row.cost_basis_base is None and row.current_value_base is None
    assert row.unrealized_pl is None

    totals = portfolio_service.summarize(valued)
    assert totals.currency_conflict_symbols == ["NVDA"]
    # Not miscounted as "waiting for a price" — waiting will never fix it.
    assert totals.unpriced_symbols == []
    assert totals.total_value == pytest.approx(3800.0)   # PTT.BK alone
    assert totals.total_cost == pytest.approx(3500.0)


async def test_the_api_reports_the_conflict_rather_than_a_number(test_db, test_user):
    await _seed(test_db, test_user, [("NVDA", "BUY", 10.0, 100.0, "USD", 30.0)])
    await _seed(test_db, test_user, [("NVDA", "BUY", 100.0, 35.0, "THB", 1.0)], when=D1)

    with patch("services.stock_service.get_redis",
               AsyncMock(return_value=_FakeRedis(_redis_store({"NVDA": {"price": 110.0}})))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()):
        analytics = await get_analytics(user=test_user, db=test_db)

    assert analytics.currency_conflict_symbols == ["NVDA"]
    assert analytics.total_value == 0.0
    assert analytics.has_pending_prices is False
    row = analytics.holdings[0]
    assert row.currency_conflict is True
    assert row.avg_cost is None
    assert sorted(row.currencies) == ["THB", "USD"]


# ── the write path: refuse, loudly ───────────────────────────────────────────

async def _add(db, user, **kwargs):
    store = _redis_store({portfolio_service.FX_QUOTE_SYMBOL: FX_QUOTE})
    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("workers.symbol_registrar.register_symbol", MagicMock()):
        return await add_transaction(body=TransactionCreate(**kwargs), user=user, db=db)


async def test_a_conflicting_transaction_is_rejected_with_409_not_absorbed(test_db, test_user):
    await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=10, price=100,
               currency="USD", date=D0)

    with pytest.raises(HTTPException) as exc:
        await _add(test_db, test_user, symbol="nvda", type="BUY", qty=100, price=35,
                   currency="THB", date=D0)

    assert exc.value.status_code == 409
    # Loud means actionable: it names the symbol, both currencies, and the fix.
    assert "NVDA" in exc.value.detail
    assert "USD" in exc.value.detail and "THB" in exc.value.detail


async def test_the_same_currency_is_still_accepted(test_db, test_user):
    await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=10, price=100,
               currency="USD", date=D0)
    txn = await _add(test_db, test_user, symbol="NVDA", type="SELL", qty=5, price=120,
                     currency="USD", date=D0)
    assert txn.id is not None


async def test_a_different_symbol_in_another_currency_is_none_of_its_business(test_db, test_user):
    await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=10, price=100,
               currency="USD", date=D0)
    txn = await _add(test_db, test_user, symbol="PTT.BK", type="BUY", qty=100, price=35,
                     currency="THB", date=D0)
    assert txn.currency == Currency.THB


async def test_another_users_rows_do_not_constrain_this_user(test_db, test_user):
    from core.security import hash_password
    from models.user import User

    other = User(email="other@example.com", password_hash=hash_password("x"),
                 display_name="Other", is_active=True)
    test_db.add(other)
    await test_db.flush()
    await _seed(test_db, other, [("NVDA", "BUY", 10.0, 100.0, "USD", 30.0)])

    txn = await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=100, price=35,
                     currency="THB", date=D0)
    assert txn.currency == Currency.THB


async def test_editing_a_transaction_into_a_conflicting_currency_is_refused(test_db, test_user):
    """The edit route can break a symbol exactly as easily as an insert."""
    first = await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=10, price=100,
                       currency="USD", date=D0)
    second = await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=5, price=120,
                        currency="USD", date=D0)

    with pytest.raises(HTTPException) as exc:
        await update_transaction(txn_id=second.id, body=TransactionUpdate(currency="THB"),
                                 user=test_user, db=test_db)
    assert exc.value.status_code == 409
    assert first.currency == Currency.USD


async def test_editing_the_only_row_of_a_symbol_may_change_its_currency(test_db, test_user):
    """Nothing to conflict with — the row being edited is excluded from the check,
    so correcting a mis-entered currency stays possible."""
    only = await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=10, price=100,
                      currency="USD", date=D0)
    updated = await update_transaction(txn_id=only.id, body=TransactionUpdate(currency="THB"),
                                       user=test_user, db=test_db)
    assert str(getattr(updated.currency, "value", updated.currency)) == "THB"


async def test_the_route_module_reads_the_fx_quote_through_the_shared_path():
    """bd:shotockviz-la4 guard: three surfaces, one way of reading the rate. A
    private copy in this module is how they drifted apart before."""
    from api.routes import portfolio as portfolio_route
    assert perf_route.fx_quote_cached is portfolio_route.fx_quote_cached
