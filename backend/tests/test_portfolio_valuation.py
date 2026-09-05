"""Money-correctness tests for the portfolio book.

Covers three beads that all live on the same code path:

* bd:shotockviz-2w8 — `portfolio.py` added `cost_basis` unconditionally but
  `current_value` only `if current_value`, so a holding with no cached quote
  contributed 0 to value and its full cost to cost: a fabricated loss equal to
  that position's whole market value. That is the *normal* state for a Thai book
  after 16:30 ICT and at the 20:00 US pre-market check.
* bd:shotockviz-msg — `dashboard.py` built the same book with different rules
  (`max(qty, 1)` on SELL, a 0.001 active threshold, opposite cache-miss
  handling), so the two screens could state different P&L for the same book at
  the same instant.
* bd:shotockviz-fww — `fee` was stored and never read, so every P&L was
  optimistic by the accumulated commission.

Accounting rules under test (defined in services/portfolio_service.py):
  BUY  fee -> capitalised into cost basis (avg_cost = real breakeven).
  SELL fee -> realized side (`Holding.realized_fees`), never charged to the
              cost basis of the shares still held.
  No usable quote (missing, non-numeric, or <= 0) -> position excluded from
              BOTH sides of the total, never valued at zero.
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from api.routes.dashboard import _build_portfolio_summary
from api.routes.portfolio import get_analytics
from core import cache_keys
from models.portfolio import Currency, Transaction, TransactionType
from services import portfolio_service


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _FakeTxn:
    """Minimal stand-in for models.portfolio.Transaction (service is ORM-agnostic)."""

    def __init__(self, symbol, type_, qty, price, fee=0.0, currency="THB"):
        self.symbol = symbol
        self.type = TransactionType[type_]
        self.qty = qty
        self.price = price
        self.fee = fee
        self.currency = currency


class _FakePipeline:
    def __init__(self, store):
        self._store = store
        self._keys = []

    def get(self, key):
        self._keys.append(key)
        return self

    async def execute(self):
        return [self._store.get(k) for k in self._keys]


class _FakeRedis:
    """Just enough of redis.asyncio for portfolio.py's two pipeline stages."""

    def __init__(self, store):
        self._store = store

    def pipeline(self):
        return _FakePipeline(self._store)


def _redis_store(quotes: dict) -> dict:
    """Build a raw Redis store keyed exactly like core.cache_keys.quote()."""
    import json
    return {cache_keys.quote(sym): json.dumps(q) for sym, q in quotes.items()}


async def _seed(db, user, rows):
    # Distinct, increasing dates: the routes read transactions
    # `.order_by(Transaction.date)` and the BUY must fold before the SELL.
    for i, (symbol, type_, qty, price, fee) in enumerate(rows):
        db.add(Transaction(
            user_id=user.id,
            symbol=symbol,
            type=TransactionType[type_],
            qty=qty,
            price=price,
            fee=fee,
            currency=Currency.THB,
            date=date(2024, 1, 1) + timedelta(days=i),
        ))
    await db.flush()


# A partially-cached book: PTT.BK and AOT.BK priced, CPALL.BK not.
#   PTT.BK  : 100 @ 35.00 + 100 fee -> cost 3,600 ; quote 38.00 -> value 3,800
#   CPALL.BK: 200 @ 60.00 + 200 fee -> cost 12,200 ; NO QUOTE
#   AOT.BK  :  50 @ 60.00 +   0 fee -> cost 3,000 ; quote 60.00 -> value 3,000 (P&L exactly 0.0)
PARTIAL_BOOK = [
    ("PTT.BK", "BUY", 100.0, 35.00, 100.0),
    ("CPALL.BK", "BUY", 200.0, 60.00, 200.0),
    ("AOT.BK", "BUY", 50.0, 60.00, 0.0),
]
PARTIAL_QUOTES = {
    "PTT.BK": {"symbol": "PTT.BK", "price": 38.00, "change_pct": 1.2},
    "AOT.BK": {"symbol": "AOT.BK", "price": 60.00, "change_pct": 0.0},
}
EXPECTED_VALUE = 3800.0 + 3000.0   # 6,800 — priced positions only
EXPECTED_COST = 3600.0 + 3000.0    # 6,600 — CPALL's 12,200 excluded too
EXPECTED_PL = 200.0


# ─────────────────────────────────────────────────────────────────────────────
# bd:shotockviz-fww — commission
# ─────────────────────────────────────────────────────────────────────────────

def test_buy_fee_is_capitalised_into_cost_basis():
    holdings = portfolio_service.build_holdings([
        _FakeTxn("PTT.BK", "BUY", 100.0, 35.00, fee=100.0),
    ])
    h = holdings["PTT.BK"]
    assert h.cost_basis == pytest.approx(3600.0)   # 3,500 + 100 fee
    assert h.avg_cost == pytest.approx(36.00)      # real breakeven, not 35.00


def test_sell_fee_hits_realized_not_the_remaining_cost_basis():
    holdings = portfolio_service.build_holdings([
        _FakeTxn("NVDA", "BUY", 10.0, 100.00, fee=25.0),
        _FakeTxn("NVDA", "SELL", 4.0, 110.00, fee=15.0),
    ])
    h = holdings["NVDA"]
    # avg cost (102.5) includes the buy fee and is unchanged by the sale
    assert h.avg_cost == pytest.approx(102.5)
    assert h.qty == pytest.approx(6.0)
    # 1,025 - (4 x 102.5) = 615 — the sell fee must NOT be charged to the
    # shares still held; it belongs to realized P&L.
    assert h.cost_basis == pytest.approx(615.0)
    assert h.realized_fees == pytest.approx(15.0)


async def test_fee_bearing_buy_and_sell_reaches_the_analytics_response(test_db, test_user):
    """End-to-end through the route: P&L is 45, not the fee-blind 60."""
    await _seed(test_db, test_user, [
        ("NVDA", "BUY", 10.0, 100.00, 25.0),
        ("NVDA", "SELL", 4.0, 110.00, 15.0),
    ])
    store = _redis_store({"NVDA": {"symbol": "NVDA", "price": 110.00}})

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()):
        result = await get_analytics(user=test_user, db=test_db)

    holding = result.holdings[0]
    assert holding.avg_cost == pytest.approx(102.5)
    assert result.total_cost == pytest.approx(615.0)
    assert result.total_value == pytest.approx(660.0)   # 6 x 110
    assert result.unrealized_pl == pytest.approx(45.0)  # was 60.0 while fee was ignored


# ─────────────────────────────────────────────────────────────────────────────
# bd:shotockviz-2w8 — a cache miss must not fabricate a loss
# ─────────────────────────────────────────────────────────────────────────────

def test_unpriced_position_is_excluded_from_both_sides():
    holdings = portfolio_service.build_holdings([
        _FakeTxn(s, t, q, p, f) for s, t, q, p, f in PARTIAL_BOOK
    ])
    valued = portfolio_service.value_holdings(holdings, PARTIAL_QUOTES)
    totals = portfolio_service.summarize(valued)

    assert totals.total_value == pytest.approx(EXPECTED_VALUE)
    assert totals.total_cost == pytest.approx(EXPECTED_COST)
    assert totals.unpriced_symbols == ["CPALL.BK"]
    # The old rule (cost in, value out) produced -12,000 here.
    assert totals.unrealized_pl == pytest.approx(EXPECTED_PL)
    assert totals.unrealized_pl > 0


@pytest.mark.parametrize("bad_quote", [
    None,
    {},
    {"price": None},
    {"price": 0.0},      # a zero price is bad data, not a worthless position
    {"price": -1.0},
    {"price": "n/a"},
])
def test_unusable_quote_never_values_a_position_at_zero(bad_quote):
    holdings = portfolio_service.build_holdings([_FakeTxn("PTT.BK", "BUY", 100.0, 35.0)])
    valued = portfolio_service.value_holdings(holdings, {"PTT.BK": bad_quote})
    totals = portfolio_service.summarize(valued)

    assert valued[0].priced is False
    assert valued[0].current_value is None
    assert totals.total_value == 0.0
    assert totals.total_cost == 0.0     # excluded from BOTH sides
    assert totals.unrealized_pl == 0.0  # no fabricated loss
    assert totals.unpriced_symbols == ["PTT.BK"]


async def test_partially_cached_portfolio_reports_no_phantom_loss(test_db, test_user):
    await _seed(test_db, test_user, PARTIAL_BOOK)
    store = _redis_store(PARTIAL_QUOTES)

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()):
        result = await get_analytics(user=test_user, db=test_db)

    assert result.total_value == pytest.approx(EXPECTED_VALUE)
    assert result.total_cost == pytest.approx(EXPECTED_COST)
    assert result.unrealized_pl == pytest.approx(EXPECTED_PL)
    assert result.unrealized_pl_pct == pytest.approx(3.03, abs=0.01)
    assert result.has_pending_prices is True

    rows = {h.symbol: h for h in result.holdings}
    # the unpriced position is still shown, explicitly as "no price"
    assert rows["CPALL.BK"].current_price is None
    assert rows["CPALL.BK"].current_value is None
    assert rows["CPALL.BK"].unrealized_pl is None
    assert rows["CPALL.BK"].qty == pytest.approx(200.0)
    assert rows["CPALL.BK"].avg_cost == pytest.approx(61.0)  # incl. fee
    # a genuine zero P&L is reported as 0.0, not swallowed into None by `if x:`
    assert rows["AOT.BK"].unrealized_pl == 0.0
    assert rows["AOT.BK"].unrealized_pl_pct == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# bd:shotockviz-msg — Dashboard and Portfolio must agree
# ─────────────────────────────────────────────────────────────────────────────

async def test_dashboard_and_portfolio_agree_on_a_partially_cached_book(test_db, test_user):
    await _seed(test_db, test_user, PARTIAL_BOOK)
    store = _redis_store(PARTIAL_QUOTES)

    async def _fake_fast_quote(symbol):
        return PARTIAL_QUOTES.get(symbol)  # None for CPALL.BK and THBUSD=X

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()):
        analytics = await get_analytics(user=test_user, db=test_db)

    with patch("api.routes.dashboard._fast_quote", _fake_fast_quote):
        summary, misses = await _build_portfolio_summary(test_user, test_db)

    assert summary is not None
    assert summary["total_value"] == pytest.approx(analytics.total_value)
    assert summary["total_cost"] == pytest.approx(analytics.total_cost)
    assert summary["unrealized_pl"] == pytest.approx(analytics.unrealized_pl)
    assert summary["unrealized_pl_pct"] == pytest.approx(analytics.unrealized_pl_pct)
    assert summary["has_pending_prices"] == analytics.has_pending_prices
    assert misses == ["CPALL.BK"]


def test_fractional_position_keeps_its_true_average_cost():
    """dashboard.py divided by `max(qty, 1)`: for a 0.5-share position that
    halved avg cost and left the remaining cost basis overstated (80 vs 60)."""
    holdings = portfolio_service.build_holdings([
        _FakeTxn("AAPL", "BUY", 0.5, 200.0),
        _FakeTxn("AAPL", "SELL", 0.2, 220.0),
    ])
    h = holdings["AAPL"]
    assert h.avg_cost == pytest.approx(200.0)
    assert h.qty == pytest.approx(0.3)
    assert h.cost_basis == pytest.approx(60.0)


def test_sell_without_a_position_does_not_divide_by_zero():
    """The only thing `max(qty, 1)` was load-bearing for — replaced by an
    explicit qty guard in Holding.avg_cost."""
    holdings = portfolio_service.build_holdings([_FakeTxn("PTT.BK", "SELL", 10.0, 35.0)])
    h = holdings["PTT.BK"]
    assert h.qty == pytest.approx(-10.0)
    assert h.cost_basis == pytest.approx(0.0)
    assert portfolio_service.active_holdings(holdings) == {}


def test_fully_sold_position_drops_out_of_both_screens():
    holdings = portfolio_service.build_holdings([
        _FakeTxn("PTT.BK", "BUY", 100.0, 35.0, fee=100.0),
        _FakeTxn("PTT.BK", "SELL", 100.0, 40.0, fee=100.0),
    ])
    assert portfolio_service.active_holdings(holdings) == {}
    assert holdings["PTT.BK"].realized_fees == pytest.approx(100.0)
