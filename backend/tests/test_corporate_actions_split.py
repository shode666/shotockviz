"""bd:shotockviz-eb1 — corporate actions must not fabricate money.

THE RULE UNDER TEST (services/corporate_actions.py):
    A split changes the UNITS a position is quoted in, not the money that was
    paid for it — raw transactions stay raw, the fold restates pre-ex-date lots
    at read time (qty ÷ factor, price × factor), and `qty*price` is INVARIANT.

The scenario that motivated the bead, with a known ratio, is
`TestTwoForOneSplit`: 100 shares bought at 50.00 on a 2:1 split. The market
quotes 25.00 afterwards, so the pre-fix book showed 100 × 25 = 2,500 against a
5,000 cost — a fabricated 50% loss on a position that did not move.

Also covers (bd:shotockviz-d71) `/api/health`'s celery liveness now being served
off the request path without changing what "ok" means.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from services import corporate_actions as ca
from services import portfolio_service
from models.portfolio import TransactionType


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _Txn:
    """Minimal stand-in for models.portfolio.Transaction, WITH a trade date.

    The date is what makes a lot restatable — `_FakeTxn` in
    test_portfolio_valuation.py deliberately has none, which is why every
    pre-existing test in this repo is unaffected by the split logic.
    """

    def __init__(self, symbol, type_, qty, price, when, fee=0.0, currency="THB"):
        self.symbol = symbol
        self.type = TransactionType[type_]
        self.qty = qty
        self.price = price
        self.fee = fee
        self.currency = currency
        self.date = when


def _split(ex_date: date, ratio: float) -> ca.SymbolActions:
    return ca.SymbolActions(splits=(ca.SplitEvent(ex_date=ex_date, ratio=ratio),))


EX = date(2025, 6, 2)          # the ex-date used throughout
BEFORE = date(2025, 5, 30)     # a trade date strictly before it
AFTER = date(2025, 6, 10)      # a trade date strictly after it


# ─────────────────────────────────────────────────────────────────────────────
# parse_actions — what counts as a position event and what does not
# ─────────────────────────────────────────────────────────────────────────────

class TestParseActions:
    def test_split_rows_are_parsed_and_sorted_by_ex_date(self):
        actions = ca.parse_actions([
            {"action_type": "SPLIT", "ex_date": "2025-06-02", "ratio": 0.5},
            {"action_type": "SPLIT", "ex_date": "2020-08-31", "ratio": 0.25},
        ])
        assert [s.ex_date for s in actions.splits] == [date(2020, 8, 31), EX]
        assert [s.ratio for s in actions.splits] == [0.25, 0.5]

    def test_dividends_are_not_position_events(self):
        """A cash dividend changes neither the share count nor the money paid."""
        actions = ca.parse_actions([
            {"action_type": "DIV", "ex_date": "2025-06-02", "value": 1.5},
        ])
        assert actions.splits == ()
        assert actions.has_rights is False

    def test_rights_are_flagged_never_applied(self):
        """No subscription record exists, so a RIGHTS action cannot be applied."""
        actions = ca.parse_actions([
            {"action_type": "RIGHTS", "ex_date": "2025-06-02", "ratio": 0.1,
             "value": 10.0},
        ])
        assert actions.splits == ()       # NOT turned into a split factor
        assert actions.has_rights is True  # but reported

    @pytest.mark.parametrize("ratio", [None, 0.0, -1.0, 1.0, "nonsense"])
    def test_unusable_split_ratio_is_dropped_not_defaulted(self, ratio):
        actions = ca.parse_actions([
            {"action_type": "SPLIT", "ex_date": "2025-06-02", "ratio": ratio},
        ])
        assert actions.splits == ()

    def test_unparseable_ex_date_is_dropped(self):
        actions = ca.parse_actions([
            {"action_type": "SPLIT", "ex_date": "not-a-date", "ratio": 0.5},
        ])
        assert actions.splits == ()


# ─────────────────────────────────────────────────────────────────────────────
# split_factor — the date boundary, and the `as_of` basis the curve needs
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitFactor:
    def test_lot_before_ex_date_is_restated(self):
        assert ca.split_factor(_split(EX, 0.5), BEFORE) == 0.5

    def test_lot_on_the_ex_date_is_already_post_split(self):
        """The ex-date IS the first session in new units — strict inequality."""
        assert ca.split_factor(_split(EX, 0.5), EX) == 1.0

    def test_lot_after_ex_date_is_untouched(self):
        assert ca.split_factor(_split(EX, 0.5), AFTER) == 1.0

    def test_successive_splits_compound(self):
        actions = ca.SymbolActions(splits=(
            ca.SplitEvent(date(2025, 1, 2), 0.5),    # 2:1
            ca.SplitEvent(date(2025, 6, 2), 0.25),   # 4:1
        ))
        assert ca.split_factor(actions, date(2024, 12, 1)) == pytest.approx(0.125)

    def test_as_of_excludes_a_split_that_had_not_happened_yet(self):
        """The equity-curve basis: on a day before the ex-date the raw close is
        in PRE-split units, so the share count multiplied by it must be too."""
        actions = _split(EX, 0.5)
        assert ca.split_factor(actions, BEFORE, as_of=date(2025, 6, 1)) == 1.0
        assert ca.split_factor(actions, BEFORE, as_of=EX) == 0.5

    def test_undated_lot_is_never_restated(self):
        assert ca.split_factor(_split(EX, 0.5), None) == 1.0

    def test_no_actions_is_the_identity(self):
        assert ca.split_factor(None, BEFORE) == 1.0
        assert ca.split_factor(ca.EMPTY, BEFORE) == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# The bead's scenario: a 2:1 split on a held symbol, known ratio 0.5
# ─────────────────────────────────────────────────────────────────────────────

class TestTwoForOneSplit:
    BOOK = [_Txn("AAA.BK", "BUY", 100.0, 50.00, BEFORE)]
    SPLITS = {"AAA.BK": _split(EX, 0.5)}
    QUOTE = {"AAA.BK": {"price": 25.00}}   # the market, post-split

    def test_unrestated_book_fabricates_a_fifty_percent_loss(self):
        """The bug, pinned so the fix cannot silently regress to it."""
        holdings = portfolio_service.build_holdings(self.BOOK)
        v = portfolio_service.value_holdings(holdings, self.QUOTE)[0]
        assert v.qty == 100.0
        assert v.current_value == pytest.approx(2500.0)
        assert v.unrealized_pl == pytest.approx(-2500.0)   # money that never moved
        assert v.unrealized_pl_pct == pytest.approx(-50.0)

    def test_restated_book_shows_the_position_flat(self):
        holdings = portfolio_service.build_holdings(self.BOOK, splits=self.SPLITS)
        h = holdings["AAA.BK"]
        assert h.qty == pytest.approx(200.0)          # 100 / 0.5
        assert h.avg_cost == pytest.approx(25.0)      # 50 * 0.5
        assert h.cost_basis == pytest.approx(5000.0)  # INVARIANT: no money moved
        assert h.split_adjusted is True

        v = portfolio_service.value_holdings(holdings, self.QUOTE)[0]
        assert v.current_value == pytest.approx(5000.0)
        assert v.unrealized_pl == pytest.approx(0.0)
        assert v.split_adjusted is True

    def test_cost_basis_including_commission_is_invariant(self):
        """Rule 1's capitalised buy fee rides through untouched — a split is not
        a transaction and pays no commission."""
        holdings = portfolio_service.build_holdings(
            [_Txn("AAA.BK", "BUY", 100.0, 50.00, BEFORE, fee=100.0)],
            splits=self.SPLITS,
        )
        h = holdings["AAA.BK"]
        assert h.cost_basis == pytest.approx(5100.0)   # unchanged by the split
        assert h.qty == pytest.approx(200.0)
        assert h.avg_cost == pytest.approx(25.5)       # 5,100 / 200

    def test_post_split_lot_is_left_alone_and_averages_correctly(self):
        """A book with one lot either side of the ex-date: only the older moves."""
        holdings = portfolio_service.build_holdings(
            [
                _Txn("AAA.BK", "BUY", 100.0, 50.00, BEFORE),   # -> 200 @ 25
                _Txn("AAA.BK", "BUY", 200.0, 25.00, AFTER),    # already new units
            ],
            splits=self.SPLITS,
        )
        h = holdings["AAA.BK"]
        assert h.qty == pytest.approx(400.0)
        assert h.cost_basis == pytest.approx(10000.0)
        assert h.avg_cost == pytest.approx(25.0)

    def test_four_for_one_known_ratio(self):
        holdings = portfolio_service.build_holdings(
            [_Txn("AAPL", "BUY", 10.0, 400.00, BEFORE, currency="USD")],
            splits={"AAPL": _split(EX, 0.25)},
        )
        h = holdings["AAPL"]
        assert h.qty == pytest.approx(40.0)
        assert h.avg_cost == pytest.approx(100.0)
        assert h.cost_basis == pytest.approx(4000.0)

    def test_omitting_splits_reproduces_the_previous_fold_exactly(self):
        """Regression guard for the ~40 existing build_holdings tests."""
        with_none = portfolio_service.build_holdings(self.BOOK)
        with_empty = portfolio_service.build_holdings(
            self.BOOK, splits={"AAA.BK": ca.EMPTY}
        )
        assert with_none["AAA.BK"].qty == with_empty["AAA.BK"].qty == 100.0
        assert with_empty["AAA.BK"].split_adjusted is False


# ─────────────────────────────────────────────────────────────────────────────
# A split moves no money — the realized side must not notice one
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitDoesNotTouchRealizedPl:
    def test_round_trip_across_a_split_reports_the_same_profit(self):
        # Bought 100 @ 50 (5,000) before a 2:1; sold the resulting 200 @ 30
        # (6,000) after it. Profit is 1,000 whichever units it is stated in.
        txns = [
            _Txn("AAA.BK", "BUY", 100.0, 50.00, BEFORE),
            _Txn("AAA.BK", "SELL", 200.0, 30.00, AFTER),
        ]
        holdings = portfolio_service.build_holdings(
            txns, splits={"AAA.BK": _split(EX, 0.5)}
        )
        book = portfolio_service.build_realized(holdings)
        assert book.realized_pl == pytest.approx(1000.0)
        assert book.total_trades == 1
        trade = book.closed_positions[0]
        assert trade.qty == pytest.approx(200.0)
        assert trade.entry_price == pytest.approx(25.0)   # post-split breakeven
        assert trade.exit_price == pytest.approx(30.0)

    def test_a_pre_split_sale_is_restated_with_its_lot(self):
        """Both legs pre-split: the profit is identical, the prices are halved."""
        txns = [
            _Txn("AAA.BK", "BUY", 100.0, 50.00, date(2025, 5, 1)),
            _Txn("AAA.BK", "SELL", 100.0, 60.00, date(2025, 5, 20)),
        ]
        book = portfolio_service.build_realized(
            portfolio_service.build_holdings(txns, splits={"AAA.BK": _split(EX, 0.5)})
        )
        assert book.realized_pl == pytest.approx(1000.0)   # 6,000 - 5,000
        trade = book.closed_positions[0]
        assert trade.qty == pytest.approx(200.0)
        assert trade.entry_price == pytest.approx(25.0)
        assert trade.exit_price == pytest.approx(30.0)


# ─────────────────────────────────────────────────────────────────────────────
# Dividends and rights
# ─────────────────────────────────────────────────────────────────────────────

class TestDividendAndRights:
    def test_a_dividend_never_touches_the_book(self):
        splits = {"AAA.BK": ca.parse_actions([
            {"action_type": "DIV", "ex_date": "2025-06-02", "value": 5.0},
        ])}
        h = portfolio_service.build_holdings(
            [_Txn("AAA.BK", "BUY", 100.0, 50.00, BEFORE)], splits=splits
        )["AAA.BK"]
        assert h.qty == 100.0
        assert h.cost_basis == pytest.approx(5000.0)
        assert h.split_adjusted is False

    def test_rights_are_reported_and_the_position_is_still_counted(self):
        """Unlike a missing FX rate this is not a reason to exclude the position:
        its cost basis is still a real number in a real currency. What is unknown
        is only whether the user subscribed."""
        splits = {"AAA.BK": ca.parse_actions([
            {"action_type": "RIGHTS", "ex_date": "2025-06-02", "ratio": 0.1},
        ])}
        holdings = portfolio_service.build_holdings(
            [_Txn("AAA.BK", "BUY", 100.0, 50.00, BEFORE)], splits=splits
        )
        assert holdings["AAA.BK"].rights_unstatable is True
        assert holdings["AAA.BK"].qty == 100.0   # NOT adjusted by 0.1

        valued = portfolio_service.value_holdings(holdings, {"AAA.BK": {"price": 50.0}})
        totals = portfolio_service.summarize(valued)
        assert totals.rights_unstatable_symbols == ["AAA.BK"]
        assert "AAA.BK" in totals.priced_symbols          # still counted
        assert totals.total_value == pytest.approx(5000.0)


# ─────────────────────────────────────────────────────────────────────────────
# The qualification reaches the totals
# ─────────────────────────────────────────────────────────────────────────────

class TestTotalsReportTheAdjustment:
    def test_split_adjusted_symbol_is_named_and_still_included(self):
        holdings = portfolio_service.build_holdings(
            [_Txn("AAA.BK", "BUY", 100.0, 50.00, BEFORE)],
            splits={"AAA.BK": _split(EX, 0.5)},
        )
        valued = portfolio_service.value_holdings(holdings, {"AAA.BK": {"price": 25.0}})
        totals = portfolio_service.summarize(valued)
        assert totals.split_adjusted_symbols == ["AAA.BK"]
        assert totals.priced_symbols == ["AAA.BK"]
        assert totals.unrealized_pl == pytest.approx(0.0)

    def test_an_unpriced_split_adjusted_symbol_is_still_named(self):
        """The flag is a qualification on the row, not a branch of the totals —
        it must survive every `continue` in summarize()."""
        holdings = portfolio_service.build_holdings(
            [_Txn("AAA.BK", "BUY", 100.0, 50.00, BEFORE)],
            splits={"AAA.BK": _split(EX, 0.5)},
        )
        totals = portfolio_service.summarize(
            portfolio_service.value_holdings(holdings, {"AAA.BK": None})
        )
        assert totals.split_adjusted_symbols == ["AAA.BK"]
        assert totals.unpriced_symbols == ["AAA.BK"]


# ─────────────────────────────────────────────────────────────────────────────
# Alert rebase — the ONE place a corporate action rewrites a user row
# ─────────────────────────────────────────────────────────────────────────────

class TestRebasePriceAlerts:
    """workers/corporate_actions_fetcher.rebase_price_alerts.

    Exercised against a mock connection: the SQL is Postgres-specific (enum
    ::text casts) and the value of these assertions is the GUARD SET and the
    arithmetic, not the driver.
    """

    @staticmethod
    def _conn(rows):
        conn = MagicMock()
        select_result = MagicMock()
        select_result.fetchall.return_value = rows
        conn.execute.return_value = select_result
        return conn

    def test_level_set_before_the_split_is_halved(self):
        from workers.corporate_actions_fetcher import rebase_price_alerts

        conn = self._conn([(7, 100.0)])
        assert rebase_price_alerts(conn, "AAA.BK", EX, 0.5) == 1

        update_call = conn.execute.call_args_list[-1]
        sql = str(update_call.args[0])
        params = update_call.args[1]
        assert "UPDATE alerts" in sql
        assert params["new_value"] == pytest.approx(50.0)   # 100 * 0.5
        assert params["ex_date"] == EX                      # units now stated
        assert params["id"] == 7

    def test_nothing_to_rebase_issues_no_update(self):
        from workers.corporate_actions_fetcher import rebase_price_alerts

        conn = self._conn([])
        assert rebase_price_alerts(conn, "AAA.BK", EX, 0.5) == 0
        assert conn.execute.call_count == 1   # the SELECT only

    def test_guards_are_all_present_in_the_select(self):
        from workers.corporate_actions_fetcher import rebase_price_alerts

        conn = self._conn([])
        rebase_price_alerts(conn, "AAA.BK", EX, 0.5)
        sql = str(conn.execute.call_args_list[0].args[0])
        params = conn.execute.call_args_list[0].args[1]

        # Idempotency: a row already stated in post-split units is out of scope,
        # which is what makes the DAILY re-run of the fetcher safe.
        assert "value_as_of < :ex_date" in sql
        # Units unknown -> decline rather than guess.
        assert "value_as_of IS NOT NULL" in sql
        # A fired alert is a historical record of what fired, not an instruction.
        assert "status::text = 'ACTIVE'" in sql
        # Only price-denominated levels.
        assert params["type_above"] == "PRICE_ABOVE"
        assert params["type_below"] == "PRICE_BELOW"
        assert params["symbol"] == "AAA.BK"

    def test_indicator_alert_types_are_never_rebased(self):
        """RSI thresholds, volume multipliers and crosses are not prices."""
        from workers.corporate_actions_fetcher import _PRICE_ALERT_TYPES

        assert set(_PRICE_ALERT_TYPES) == {"PRICE_ABOVE", "PRICE_BELOW"}
        for t in ("RSI_OVERBOUGHT", "RSI_OVERSOLD", "GOLDEN_CROSS",
                  "DEATH_CROSS", "VOLUME_SPIKE"):
            assert t not in _PRICE_ALERT_TYPES

    def test_a_missing_value_as_of_column_skips_instead_of_aborting(self):
        """Migration 20260906_0008 not applied yet: the split row itself must
        still be recorded, so the read-time portfolio fix is unaffected."""
        from workers.corporate_actions_fetcher import rebase_price_alerts

        conn = MagicMock()
        conn.execute.side_effect = Exception('column "value_as_of" does not exist')
        assert rebase_price_alerts(conn, "AAA.BK", EX, 0.5) == 0


# ─────────────────────────────────────────────────────────────────────────────
# bd:shotockviz-d71 — /api/health celery liveness off the request path
# ─────────────────────────────────────────────────────────────────────────────

class _FakeHealthRedis:
    def __init__(self, value=None):
        self.value = value
        self.setex_calls = []

    async def get(self, key):
        return self.value

    async def setex(self, key, ttl, value):
        self.setex_calls.append((key, ttl, value))
        self.value = value


class TestCeleryLivenessCaching:
    @pytest.mark.asyncio
    async def test_fresh_published_probe_is_served_without_probing(self, monkeypatch):
        import json
        from api.routes import system

        checked_at = datetime.now(timezone.utc).isoformat()
        fake = _FakeHealthRedis(json.dumps({"status": "ok", "checked_at": checked_at}))
        monkeypatch.setattr(system, "get_redis", lambda: _async(fake))

        def _boom():
            raise AssertionError("the 2s broadcast probe must not run inline")

        monkeypatch.setattr(system, "_check_celery_health", _boom)

        status, when = await system._celery_liveness()
        assert status == "ok"
        assert when == checked_at

    @pytest.mark.asyncio
    async def test_cold_cache_probes_inline_and_publishes(self, monkeypatch):
        from api.routes import system

        fake = _FakeHealthRedis(None)
        monkeypatch.setattr(system, "get_redis", lambda: _async(fake))
        monkeypatch.setattr(system, "_check_celery_health", lambda: "ok")

        status, when = await system._celery_liveness()
        assert status == "ok"
        assert fake.setex_calls, "the probe result must be published for other workers"
        key, ttl, _payload = fake.setex_calls[0]
        assert key == system._CELERY_PROBE_KEY
        assert ttl == system._CELERY_PROBE_TTL
        # A cold process must not claim "ok" it has not proven.
        assert datetime.fromisoformat(when) <= datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_a_stale_entry_is_still_served_and_a_refresh_is_scheduled(
        self, monkeypatch
    ):
        import json
        from api.routes import system

        old = (datetime.now(timezone.utc)
               - timedelta(seconds=system._CELERY_PROBE_REFRESH_AFTER + 5)).isoformat()
        fake = _FakeHealthRedis(json.dumps({"status": "ok", "checked_at": old}))
        monkeypatch.setattr(system, "get_redis", lambda: _async(fake))

        scheduled = []
        monkeypatch.setattr(system, "_schedule_celery_refresh",
                            lambda: scheduled.append(True))

        status, when = await system._celery_liveness()
        assert (status, when) == ("ok", old)     # served immediately, not re-probed
        assert scheduled == [True]

    @pytest.mark.asyncio
    async def test_redis_unavailable_falls_back_to_the_inline_probe(self, monkeypatch):
        """No shared cache -> the pre-d71 behaviour: slow, and correct."""
        from api.routes import system

        def _no_redis():
            raise RuntimeError("Redis not initialised")

        monkeypatch.setattr(system, "get_redis", lambda: _async_raise(_no_redis))
        monkeypatch.setattr(system, "_check_celery_health", lambda: "fail")

        status, _when = await system._celery_liveness()
        assert status == "fail"


async def _async(value):
    return value


async def _async_raise(fn):
    fn()
