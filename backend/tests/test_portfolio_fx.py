"""FX-correctness tests for the portfolio book.

Two beads, one code path:

* bd:shotockviz-fnn — `dashboard.py:146` used a hardcoded `usd_to_thb = 33.0`
  whenever `THBUSD=X` was uncached (the normal off-hours state: 120 s TTL) and
  rendered the result to 2 dp with nothing marking it as a guess. And it
  converted cost AND value at the same current rate, so the currency component
  of a US position's THB return was structurally unrepresentable.
* bd:shotockviz-sbe — `/portfolio/analytics` summed THB and USD amounts raw
  while the dashboard normalised to THB, so a mixed book produced a header
  total that meant nothing, and the two screens disagreed.

The rule under test (services/portfolio_service.py rule 4):
  FX-1  a transaction stores the rate observed when it was recorded; a base
        currency (THB) transaction is 1.0 by definition; a row with no rate
        stays without one — historical rates are never backfilled or invented.
  FX-2  value converts at the current rate, cost at each lot's own stored rate
        when they all have one -> the FX component is separable. When a lot has
        no rate, cost falls back to the current rate and fx_pl is None (unknown),
        never 0.0 (a claim the currency did not move).
  FX-3  any rate that is not a live quote is marked `estimated`, and an
        implausible live quote is treated as bad data rather than as a rate.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.routes import portfolio as portfolio_route
from api.routes.dashboard import _build_portfolio_summary
from api.routes.portfolio import add_transaction, get_analytics
from models.portfolio import Currency, Transaction, TransactionType
from models.schemas import TransactionCreate
from services import portfolio_service

from tests.test_portfolio_valuation import _FakeRedis, _redis_store


# A live THBUSD=X price of 1/35 means 35 THB per USD.
FX_QUOTE_PRICE = 1.0 / 35.0
CURRENT_RATE = 35.0


class _Txn:
    """Minimal stand-in for models.portfolio.Transaction."""

    def __init__(self, symbol, type_, qty, price, fee=0.0, currency="THB",
                 fx_rate=None, when=date(2024, 1, 1)):
        self.symbol = symbol
        self.type = TransactionType[type_]
        self.qty = qty
        self.price = price
        self.fee = fee
        self.currency = currency
        self.fx_rate = fx_rate
        self.date = when


async def _seed(db, user, rows):
    """rows: (symbol, type, qty, price, fee, currency, fx_rate)."""
    for i, (symbol, type_, qty, price, fee, currency, fx_rate) in enumerate(rows):
        db.add(Transaction(
            user_id=user.id,
            symbol=symbol,
            type=TransactionType[type_],
            qty=qty,
            price=price,
            fee=fee,
            currency=Currency[currency],
            fx_rate=fx_rate,
            date=date(2024, 1, 1) + timedelta(days=i),
        ))
    await db.flush()


# A mixed-currency book, the case bd:shotockviz-sbe made meaningless.
#   PTT.BK (THB) : 100 @ 35 + 100 fee -> cost 3,600      ; quote 38 -> value 3,800
#   NVDA   (USD) :  10 @ 100, rate 30 -> cost $1,000 = ฿30,000 ; quote 110 -> $1,100
# At the current rate of 35 THB/USD:
MIXED_BOOK = [
    ("PTT.BK", "BUY", 100.0, 35.00, 100.0, "THB", None),
    ("NVDA", "BUY", 10.0, 100.00, 0.0, "USD", 30.0),
]
MIXED_QUOTES = {
    "PTT.BK": {"symbol": "PTT.BK", "price": 38.00},
    "NVDA": {"symbol": "NVDA", "price": 110.00},
    portfolio_service.FX_QUOTE_SYMBOL: {"symbol": "THBUSD=X", "price": FX_QUOTE_PRICE},
}
MIXED_VALUE_THB = 3800.0 + 1100.0 * CURRENT_RATE   # 42,300
MIXED_COST_THB = 3600.0 + 30000.0                  # 33,600 — NVDA at ITS OWN rate
MIXED_PL_THB = MIXED_VALUE_THB - MIXED_COST_THB    # 8,700
MIXED_MARKET_PL = 200.0 + 100.0 * CURRENT_RATE     # 3,700
MIXED_FX_PL = 1000.0 * CURRENT_RATE - 30000.0      # 5,000
RAW_SUM_VALUE = 3800.0 + 1100.0                    # 4,900 — the old, meaningless total


# ─────────────────────────────────────────────────────────────────────────────
# FX-3 — the rate itself
# ─────────────────────────────────────────────────────────────────────────────

def test_live_rate_is_the_reciprocal_of_the_thbusd_quote():
    assert portfolio_service.live_rate_from_thbusd(
        {"price": FX_QUOTE_PRICE}) == pytest.approx(35.0)


@pytest.mark.parametrize("quote", [
    None,
    {},
    {"price": None},
    {"price": 0.0},
    {"price": -0.03},
    {"price": "n/a"},
    {"price": 33.0},     # pair delivered the other way up -> 0.0303 THB/USD
    {"price": 0.5},      # -> 2 THB/USD, outside the plausible band
])
def test_an_unusable_or_implausible_quote_is_not_a_rate(quote):
    assert portfolio_service.live_rate_from_thbusd(quote) is None


def test_rate_chain_prefers_live_then_the_users_own_rate_then_the_constant():
    live = portfolio_service.resolve_fx("USD", live_rate=34.0, last_known=(30.0, "2026-01-02"))
    assert (live.rate, live.source, live.estimated) == (34.0, "live", False)

    known = portfolio_service.resolve_fx("USD", live_rate=None, last_known=(30.0, "2026-01-02"))
    assert (known.rate, known.source, known.estimated) == (30.0, "last_known", True)
    assert known.as_of == "2026-01-02"

    # The old silent 33.0 — still the last resort, but it can no longer be
    # mistaken for a real rate.
    fallback = portfolio_service.resolve_fx("USD", live_rate=None, last_known=None)
    assert (fallback.rate, fallback.source, fallback.estimated) == (33.0, "fallback", True)

    assert portfolio_service.resolve_fx("THB").source == "identity"
    assert portfolio_service.resolve_fx("THB").estimated is False


def test_last_known_rate_comes_from_the_users_own_most_recent_transaction():
    txns = [
        _Txn("NVDA", "BUY", 1, 100, currency="USD", fx_rate=30.0, when=date(2026, 1, 2)),
        _Txn("AAPL", "BUY", 1, 200, currency="USD", fx_rate=34.5, when=date(2026, 6, 1)),
        _Txn("PTT.BK", "BUY", 1, 35, currency="THB", when=date(2026, 7, 1)),
    ]
    assert portfolio_service.last_known_rate(txns, "USD") == (34.5, "2026-06-01")
    assert portfolio_service.last_known_rate(txns[:1], "EUR") is None


# ─────────────────────────────────────────────────────────────────────────────
# FX-1/FX-2 — a transaction WITH a stored rate
# ─────────────────────────────────────────────────────────────────────────────

def _value_one(txns, quotes, rate=CURRENT_RATE, source="live"):
    holdings = portfolio_service.build_holdings(txns)
    fx = portfolio_service.fx_resolver({
        "USD": portfolio_service.FxRate(currency="USD", rate=rate, source=source)
    })
    return portfolio_service.value_holdings(holdings, quotes, fx=fx)[0]


def test_stored_rate_makes_the_currency_return_separable():
    v = _value_one(
        [_Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0)],
        {"NVDA": {"price": 110.0}},
    )
    assert v.cost_basis == pytest.approx(1000.0)          # native, unchanged
    assert v.cost_basis_source == "historical"
    assert v.cost_basis_base == pytest.approx(30000.0)    # at the rate it was BOUGHT at
    assert v.current_value_base == pytest.approx(38500.0)  # at the CURRENT rate
    assert v.market_pl_base == pytest.approx(3500.0)      # $100 move x 35
    assert v.fx_pl_base == pytest.approx(5000.0)          # $1,000 x (35 - 30)
    # the whole point: the two components add up to the reported THB return
    assert v.market_pl_base + v.fx_pl_base == pytest.approx(v.unrealized_pl_base)
    assert v.avg_fx_rate == pytest.approx(30.0)


def test_a_sell_leaves_the_remaining_lots_historical_rate_intact():
    """The base cost basis is reduced by weighted average, exactly like the
    native one — the SELL's own rate belongs to realized P&L, not to the shares
    still held (rule 1)."""
    holdings = portfolio_service.build_holdings([
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0),
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=34.0),
        _Txn("NVDA", "SELL", 5.0, 120.0, currency="USD", fx_rate=36.0),
    ])
    h = holdings["NVDA"]
    assert h.fx_complete is True
    assert h.cost_basis == pytest.approx(1500.0)          # 15 shares x $100
    assert h.cost_basis_base == pytest.approx(48000.0)    # 32 avg x 1,500
    assert h.avg_fx_rate == pytest.approx(32.0)


def test_a_thb_transaction_needs_no_stored_rate():
    """The base currency is 1.0 by definition, so the entire pre-existing Thai
    book is FX-complete without a backfill and reports a 0.0 FX return — which
    here is a fact, not a guess."""
    holdings = portfolio_service.build_holdings([_Txn("PTT.BK", "BUY", 100.0, 35.0, fee=100.0)])
    h = holdings["PTT.BK"]
    assert h.fx_complete is True
    assert h.cost_basis_base == pytest.approx(3600.0)

    v = portfolio_service.value_holdings(holdings, {"PTT.BK": {"price": 38.0}})[0]
    assert v.cost_basis_source == "identity"
    assert v.fx_pl_base == pytest.approx(0.0)
    assert v.fx_estimated is False


# ─────────────────────────────────────────────────────────────────────────────
# FX-2 — a transaction WITHOUT a stored rate (every pre-existing USD row)
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_rate_reports_unknown_fx_return_never_zero():
    v = _value_one(
        [_Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=None)],
        {"NVDA": {"price": 110.0}},
    )
    assert v.cost_basis_source == "current_rate"
    assert v.cost_basis_base == pytest.approx(35000.0)   # today's rate — the old behaviour
    assert v.fx_pl_base is None                          # NOT 0.0
    assert v.unrealized_pl_base == pytest.approx(v.market_pl_base)


def test_one_rateless_lot_disqualifies_the_whole_position():
    holdings = portfolio_service.build_holdings([
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0),
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=None),
    ])
    assert holdings["NVDA"].fx_complete is False
    assert holdings["NVDA"].avg_fx_rate is None


def test_totals_decline_the_fx_split_when_any_position_cannot_supply_it():
    fx = portfolio_service.fx_resolver({
        "USD": portfolio_service.FxRate(currency="USD", rate=CURRENT_RATE, source="live")
    })
    holdings = portfolio_service.build_holdings([
        _Txn("PTT.BK", "BUY", 100.0, 35.0, fee=100.0),
        _Txn("AAPL", "BUY", 5.0, 200.0, currency="USD", fx_rate=None),
    ])
    totals = portfolio_service.summarize(
        portfolio_service.value_holdings(
            holdings, {"PTT.BK": {"price": 38.0}, "AAPL": {"price": 220.0}}, fx=fx)
    )
    assert totals.fx_pl is None              # unknown for the book as a whole
    assert totals.cost_basis_estimated is True
    assert totals.market_pl == pytest.approx(200.0 + 100.0 * CURRENT_RATE)
    assert totals.total_value == pytest.approx(3800.0 + 1100.0 * CURRENT_RATE)


def test_a_currency_with_no_rate_at_all_is_excluded_not_added_raw():
    """The honest decline. With no FX context a USD position cannot be stated in
    THB, so it leaves BOTH sides of the total and is named — the same doctrine as
    an unpriced position (rule 2), and the opposite of the old raw addition."""
    holdings = portfolio_service.build_holdings([
        _Txn("PTT.BK", "BUY", 100.0, 35.0, fee=100.0),
        _Txn("NVDA", "BUY", 10.0, 100.0, currency="USD", fx_rate=30.0),
    ])
    valued = portfolio_service.value_holdings(
        holdings, {"PTT.BK": {"price": 38.0}, "NVDA": {"price": 110.0}})
    totals = portfolio_service.summarize(valued)

    assert totals.fx_unavailable_symbols == ["NVDA"]
    assert totals.total_value == pytest.approx(3800.0)
    assert totals.total_cost == pytest.approx(3600.0)
    assert totals.total_value != pytest.approx(RAW_SUM_VALUE)


# ─────────────────────────────────────────────────────────────────────────────
# bd:shotockviz-sbe — the two screens on a mixed-currency book
# ─────────────────────────────────────────────────────────────────────────────

async def test_mixed_currency_book_is_normalised_and_both_screens_agree(test_db, test_user):
    await _seed(test_db, test_user, MIXED_BOOK)
    store = _redis_store(MIXED_QUOTES)

    async def _fake_fast_quote(symbol):
        return MIXED_QUOTES.get(symbol)

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()):
        analytics = await get_analytics(user=test_user, db=test_db)

    with patch("api.routes.dashboard._fast_quote", _fake_fast_quote):
        summary, misses = await _build_portfolio_summary(test_user, test_db)

    # 1. The total is a real THB total, not THB + USD added together.
    assert analytics.base_currency == "THB"
    assert analytics.total_value == pytest.approx(MIXED_VALUE_THB)
    assert analytics.total_cost == pytest.approx(MIXED_COST_THB)
    assert analytics.unrealized_pl == pytest.approx(MIXED_PL_THB)
    assert analytics.total_value != pytest.approx(RAW_SUM_VALUE)

    # 2. The currency component is visible and adds up.
    assert analytics.market_pl == pytest.approx(MIXED_MARKET_PL)
    assert analytics.fx_pl == pytest.approx(MIXED_FX_PL)
    assert analytics.market_pl + analytics.fx_pl == pytest.approx(analytics.unrealized_pl)
    assert analytics.fx_estimated is False          # a live quote was available
    assert analytics.cost_basis_estimated is False

    # 3. Dashboard states exactly the same book.
    assert summary is not None
    for key in ("total_value", "total_cost", "unrealized_pl", "unrealized_pl_pct",
                "market_pl", "fx_pl"):
        assert summary[key] == pytest.approx(getattr(analytics, key)), key
    assert summary["base_currency"] == analytics.base_currency
    assert summary["fx_estimated"] == analytics.fx_estimated
    assert misses == []

    # 4. Per-row native numbers are untouched (the holdings table still shows $).
    rows = {h.symbol: h for h in analytics.holdings}
    assert rows["NVDA"].current_value == pytest.approx(1100.0)
    assert rows["NVDA"].currency == "USD"
    assert rows["NVDA"].current_value_base == pytest.approx(38500.0)
    assert rows["NVDA"].fx_pl_base == pytest.approx(5000.0)
    assert rows["PTT.BK"].fx_pl_base == pytest.approx(0.0)


async def test_legacy_usd_position_declines_the_fx_return_on_both_screens(test_db, test_user):
    """A row created before `fx_rate` existed. Its FX return stays unavailable —
    the accepted cost of not backfilling history — and both screens say so
    instead of implying a number."""
    await _seed(test_db, test_user, [
        ("PTT.BK", "BUY", 100.0, 35.00, 100.0, "THB", None),
        ("NVDA", "BUY", 10.0, 100.00, 0.0, "USD", None),   # no rate recorded
    ])
    store = _redis_store(MIXED_QUOTES)

    async def _fake_fast_quote(symbol):
        return MIXED_QUOTES.get(symbol)

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()):
        analytics = await get_analytics(user=test_user, db=test_db)

    with patch("api.routes.dashboard._fast_quote", _fake_fast_quote):
        summary, _ = await _build_portfolio_summary(test_user, test_db)

    assert analytics.fx_pl is None
    assert analytics.cost_basis_estimated is True
    assert summary["fx_pl"] is None
    assert summary["cost_basis_estimated"] is True
    # Cost converted at today's rate — the pre-fix behaviour, now labelled.
    assert analytics.total_cost == pytest.approx(3600.0 + 1000.0 * CURRENT_RATE)
    assert summary["total_cost"] == pytest.approx(analytics.total_cost)
    row = {h.symbol: h for h in analytics.holdings}["NVDA"]
    assert row.cost_basis_source == "current_rate"
    assert row.fx_pl_base is None


async def test_no_fx_quote_falls_back_and_says_so_on_both_screens(test_db, test_user):
    """The bd:shotockviz-fnn case: THBUSD=X uncached (normal after 16:30 ICT).
    The 33.0 constant still exists, but it now arrives labelled `fallback` /
    `estimated` instead of as a 2-decimal fact."""
    await _seed(test_db, test_user, [("NVDA", "BUY", 10.0, 100.00, 0.0, "USD", None)])
    quotes_without_fx = {"NVDA": {"symbol": "NVDA", "price": 110.00}}
    store = _redis_store(quotes_without_fx)

    async def _fake_fast_quote(symbol):
        return quotes_without_fx.get(symbol)

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()) as fetch:
        analytics = await get_analytics(user=test_user, db=test_db)

    with patch("api.routes.dashboard._fast_quote", _fake_fast_quote):
        summary, misses = await _build_portfolio_summary(test_user, test_db)

    assert analytics.fx_estimated is True
    assert [(r.currency, r.source, r.rate) for r in analytics.fx_rates] == [("USD", "fallback", 33.0)]
    assert analytics.total_value == pytest.approx(1100.0 * 33.0)
    assert summary["fx_estimated"] is True
    assert summary["fx_rates"][0]["source"] == "fallback"
    assert summary["total_value"] == pytest.approx(analytics.total_value)
    # Both screens ask for the missing rate to be warmed for next time.
    assert portfolio_service.FX_QUOTE_SYMBOL in misses
    assert any(c.args[0] == portfolio_service.FX_QUOTE_SYMBOL for c in fetch.call_args_list)


async def test_the_users_own_recorded_rate_beats_the_hardcoded_constant(test_db, test_user):
    """With no live quote, a rate this user actually transacted at is a better
    estimate than a constant frozen in source — and is still marked estimated."""
    await _seed(test_db, test_user, [
        ("NVDA", "BUY", 10.0, 100.00, 0.0, "USD", 31.5),
    ])
    quotes_without_fx = {"NVDA": {"symbol": "NVDA", "price": 110.00}}
    store = _redis_store(quotes_without_fx)

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()):
        analytics = await get_analytics(user=test_user, db=test_db)

    assert [(r.currency, r.source, r.rate) for r in analytics.fx_rates] == [("USD", "last_known", 31.5)]
    assert analytics.fx_estimated is True
    assert analytics.total_value == pytest.approx(1100.0 * 31.5)
    # Cost is historical (the lot has a rate), so the FX split is still real:
    # the rate simply has not moved since, because it IS that rate.
    assert analytics.fx_pl == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# FX-1 — the write path
# ─────────────────────────────────────────────────────────────────────────────

def _today_ict() -> date:
    # Same convention as workers/fund_fetcher.py:146.
    return (datetime.now(timezone.utc) + timedelta(hours=7)).date()


async def _add(db, user, **kwargs):
    body = TransactionCreate(**kwargs)
    store = _redis_store({portfolio_service.FX_QUOTE_SYMBOL: {"price": FX_QUOTE_PRICE}})
    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("workers.symbol_registrar.register_symbol", MagicMock()):
        return await add_transaction(body=body, user=user, db=db)


async def test_a_new_usd_transaction_records_todays_rate(test_db, test_user):
    txn = await _add(test_db, test_user, symbol="nvda", type="BUY", qty=10, price=100,
                     currency="USD", date=_today_ict())
    assert txn.fx_rate == pytest.approx(CURRENT_RATE)


async def test_a_new_thb_transaction_records_the_identity_rate(test_db, test_user):
    txn = await _add(test_db, test_user, symbol="PTT.BK", type="BUY", qty=100, price=35,
                     currency="THB", date=date(2020, 5, 1))
    assert txn.fx_rate == 1.0   # by definition, and valid for any date


async def test_a_backdated_foreign_transaction_records_no_rate(test_db, test_user):
    """Stamping today's rate on a six-month-old trade would look like a recorded
    historical rate and silently poison the FX return — the same class of bug as
    the 33.0 constant. No observation exists, so nothing is stored."""
    txn = await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=10, price=100,
                     currency="USD", date=_today_ict() - timedelta(days=180))
    assert txn.fx_rate is None


async def test_an_explicitly_supplied_rate_is_kept_even_when_backdated(test_db, test_user):
    """The only route by which a back-dated foreign trade gets an FX return: the
    user supplies the rate they actually filled at."""
    txn = await _add(test_db, test_user, symbol="NVDA", type="BUY", qty=10, price=100,
                     currency="USD", date=_today_ict() - timedelta(days=180), fx_rate=32.25)
    assert txn.fx_rate == pytest.approx(32.25)


async def test_no_rate_is_invented_when_the_fx_cache_is_cold(test_db, test_user):
    """A cold cache must NOT persist the 33.0 fallback into the ledger. The
    fallback is a display-time estimate; a stored rate is a recorded fact."""
    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis({}))), \
         patch("workers.symbol_registrar.register_symbol", MagicMock()):
        txn = await add_transaction(
            body=TransactionCreate(symbol="NVDA", type="BUY", qty=10, price=100,
                                   currency="USD", date=_today_ict()),
            user=test_user, db=test_db,
        )
    assert txn.fx_rate is None
    assert portfolio_route.portfolio_service.FX_FALLBACK_RATES["USD"] == 33.0  # still only a display fallback


async def test_a_non_positive_supplied_rate_is_rejected():
    with pytest.raises(Exception):
        TransactionCreate(symbol="NVDA", type="BUY", qty=1, price=1,
                          currency="USD", date=date(2026, 1, 1), fx_rate=0)
