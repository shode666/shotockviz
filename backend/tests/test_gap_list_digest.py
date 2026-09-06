"""Tests for workers.gap_list_digest — bd:shotockviz-06z.

Structure mirrors test_sr_proximity_digest.py: pure-function tests against
fixed fixture data (no DB), then integration tests against a file-based
sqlite DB + a tiny real-semantics fake Redis (not a mock that always says
"ok"), so the run-lock test actually proves the SETNX guard, not just that
it was called.

🔴 No test in this file ever calls the real Telegram API: `httpx.post` is
always patched to a MagicMock before `send_gap_list_digest` runs, and every
assertion about "a message was sent" reads `mock_post.call_count` /
`mock_post.call_args`, never a live network response.
"""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from core.database import Base
from models.portfolio import Currency, Transaction, TransactionType
from models.user import User
from models.watchlist import Watchlist, WatchlistItem
from workers.gap_list_digest import (
    GAP_LIST_MAX_SYMBOLS_PER_MESSAGE,
    build_gap_list_message,
    compute_gap_list,
    send_gap_list_digest,
)

# bd:shotockviz-3fx-style gate (reused predicate, see gap_list_digest.py
# docstring) — every test that invokes the real task must pin a weekday that
# is a trading day in America/New_York, or the whole file goes red every
# Saturday/Sunday. 2026-09-07 12:30 UTC = Monday 08:30 in New York.
TRADING_MONDAY_UTC_ISO = "2026-09-07T12:30:00+00:00"
# 2026-09-06 12:30 UTC = Sunday 08:30 in New York — a non-trading day.
NON_TRADING_SUNDAY_UTC_ISO = "2026-09-06T12:30:00+00:00"


def _quote(price: float, change_pct: float, **over) -> dict:
    d = {"price": price, "change_pct": change_pct}
    d.update(over)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# compute_gap_list — pure, fixed fixture data
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeGapList:
    def test_symbol_with_no_cached_quote_is_skipped(self):
        results = compute_gap_list({"AAPL"}, {})
        assert results == []

    def test_symbol_with_none_quote_is_skipped(self):
        results = compute_gap_list({"AAPL"}, {"AAPL": None})
        assert results == []

    def test_fund_nav_quote_is_excluded_even_though_present(self):
        """bd:shotockviz-ubw's fund_payload_to_quote forces change_pct=0.0
        for every NAV — showing that here would misrepresent 'not
        applicable' as 'measured, flat'. Excluded by `type`, not by the
        (misleading) numeric value."""
        results = compute_gap_list(
            {"KFLTF70"},
            {"KFLTF70": {"price": 12.34, "change_pct": 0.0, "type": "fund_nav"}},
        )
        assert results == []

    def test_zero_price_is_not_usable(self):
        results = compute_gap_list({"XYZ"}, {"XYZ": _quote(0.0, 3.0)})
        assert results == []

    def test_negative_price_is_not_usable(self):
        results = compute_gap_list({"XYZ"}, {"XYZ": _quote(-1.0, 3.0)})
        assert results == []

    def test_missing_change_pct_is_skipped(self):
        results = compute_gap_list({"XYZ"}, {"XYZ": {"price": 10.0}})
        assert results == []

    def test_included_symbol_carries_symbol_price_and_change_pct(self):
        results = compute_gap_list({"AAPL"}, {"AAPL": _quote(150.0, 5.0)})
        assert results == [{"symbol": "AAPL", "price": 150.0, "change_pct": 5.0}]

    def test_sorted_by_absolute_gap_descending_not_signed(self):
        """A -8% gap must rank above a +3% gap — magnitude, not direction."""
        quotes = {
            "A": _quote(10.0, 3.0),
            "B": _quote(20.0, -8.0),
            "C": _quote(30.0, 1.0),
        }
        results = compute_gap_list({"A", "B", "C"}, quotes)
        assert [r["symbol"] for r in results] == ["B", "A", "C"]

    def test_a_mixed_book_only_the_freshly_quoted_symbols_survive(self):
        """The Thai-close / US-open structural filter described in the
        module docstring: a symbol with no entry in quotes_by_symbol
        (e.g. its quote:{symbol} key expired hours ago) never appears,
        without any exchange/market special-casing in this function."""
        quotes = {"AAPL": _quote(150.0, 2.0)}  # "PTT.BK" deliberately absent
        results = compute_gap_list({"AAPL", "PTT.BK"}, quotes)
        assert [r["symbol"] for r in results] == ["AAPL"]


# ─────────────────────────────────────────────────────────────────────────────
# build_gap_list_message — pure
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildGapListMessage:
    def test_empty_results_with_nonempty_book_says_so_explicitly(self):
        """The 'say so, don't fabricate' requirement: no results but a
        non-empty book must NOT read like '0 gaps found' — it must state
        that no fresh price was available."""
        msg = build_gap_list_message([], book_count=12, today_str="06/09")
        assert "ยังไม่มีราคาสด" in msg
        assert "12" in msg

    def test_with_results_shows_symbol_price_and_signed_pct(self):
        results = [{"symbol": "AAPL", "price": 150.0, "change_pct": 5.25}]
        msg = build_gap_list_message(results, book_count=3, today_str="06/09")
        assert "🟢 AAPL  150.00  (+5.25%)" in msg

    def test_negative_gap_uses_red_emoji_and_no_plus_sign(self):
        results = [{"symbol": "TSLA", "price": 200.0, "change_pct": -4.1}]
        msg = build_gap_list_message(results, book_count=1, today_str="06/09")
        assert "🔴 TSLA  200.00  (-4.10%)" in msg
        assert "+  -4.10" not in msg  # no stray plus sign on a negative

    def test_footer_states_priced_count_over_book_count(self):
        results = [{"symbol": "AAPL", "price": 150.0, "change_pct": 1.0}]
        msg = build_gap_list_message(results, book_count=40, today_str="06/09")
        assert "มีราคาสด 1 จาก 40 รายการ" in msg

    def test_truncates_at_the_message_length_cap(self):
        results = [
            {"symbol": f"SYM{i}", "price": 10.0, "change_pct": float(30 - i)}
            for i in range(GAP_LIST_MAX_SYMBOLS_PER_MESSAGE + 5)
        ]
        msg = build_gap_list_message(results, book_count=len(results), today_str="06/09")
        assert msg.count("SYM") == GAP_LIST_MAX_SYMBOLS_PER_MESSAGE
        assert "…และอีก 5 ตัว" in msg


# ─────────────────────────────────────────────────────────────────────────────
# Integration — full task against a file-based sqlite DB + fake redis
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRedis:
    """Real SETNX/MGET semantics — same shape as
    test_sr_proximity_digest.py's fake, so the run-lock test proves the
    guard rather than just proving a mock was called."""

    def __init__(self, quotes: dict[str, bytes] | None = None):
        self._store: dict[str, bytes] = {}
        self._quotes = quotes or {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    def mget(self, keys):
        return [self._quotes.get(k) for k in keys]


def _raw_quote(price: float, change_pct: float = 0.0, **over) -> bytes:
    d = {"price": price, "change_pct": change_pct}
    d.update(over)
    return json.dumps(d).encode()


@pytest.fixture
def gap_db(tmp_path):
    """u1: watchlist AAPL + open holding NVDA (2 sources, union = 2 book
    symbols, proving 'holds or watches' is a union not either alone).
    u2: no chat id -> must never be messaged.
    u3: chat id but empty watchlist AND no transactions -> empty book,
        skipped silently (no message, not an empty-book message)."""
    db_path = tmp_path / "gap_list_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        u1 = User(email="u1@example.com", password_hash="x", display_name="U1", telegram_chat_id="1001")
        u2_no_chat = User(email="u2@example.com", password_hash="x", display_name="U2", telegram_chat_id=None)
        u3_empty_book = User(email="u3@example.com", password_hash="x", display_name="U3", telegram_chat_id="1003")
        db.add_all([u1, u2_no_chat, u3_empty_book])
        db.flush()

        wl1 = Watchlist(user_id=u1.id, name="Main")
        db.add(wl1)
        db.flush()
        db.add(WatchlistItem(watchlist_id=wl1.id, symbol="AAPL"))

        db.add(Transaction(
            user_id=u1.id, symbol="NVDA", type=TransactionType.BUY,
            qty=10, price=100.0, fee=0.0, currency=Currency.USD,
            fx_rate=35.0, date=date(2026, 8, 1),
        ))
        db.commit()

    engine.dispose()
    return f"sqlite:///{db_path}"


def _run_digest(db_url, fake_redis, mock_post, now_utc_iso=TRADING_MONDAY_UTC_ISO):
    with (
        patch("core.config.settings.database_url", db_url),
        patch("core.config.settings.telegram_bot_token", "fake-token"),
        patch("redis.from_url", return_value=fake_redis),
        patch("httpx.post", mock_post),
    ):
        send_gap_list_digest(now_utc_iso=now_utc_iso)


class TestBookIsWatchlistUnionHoldings:
    def test_only_u1_is_messaged_with_both_sources_in_book(self, gap_db):
        fake_redis = _FakeRedis(quotes={
            "quote:AAPL": _raw_quote(150.0, 2.0),
            "quote:NVDA": _raw_quote(118.4, -1.5),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(gap_db, fake_redis, mock_post)

        assert mock_post.call_count == 1
        assert mock_post.call_args.kwargs["json"]["chat_id"] == "1001"
        text = mock_post.call_args.kwargs["json"]["text"]
        assert "AAPL" in text
        assert "NVDA" in text

    def test_watchlist_only_symbol_and_holding_only_symbol_both_appear(self, gap_db):
        """Proves union, not 'whichever source is checked first': AAPL
        comes ONLY from the watchlist row, NVDA comes ONLY from the
        Transaction row. If the implementation read just one source this
        test fails on whichever symbol that source doesn't carry."""
        fake_redis = _FakeRedis(quotes={
            "quote:AAPL": _raw_quote(150.0, 2.0),
            "quote:NVDA": _raw_quote(118.4, -1.5),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(gap_db, fake_redis, mock_post)

        text = mock_post.call_args.kwargs["json"]["text"]
        assert "🟢 AAPL  150.00  (+2.00%)" in text
        assert "🔴 NVDA  118.40  (-1.50%)" in text


class TestEmptyBookSkippedSilently:
    def test_user_with_no_watchlist_and_no_holdings_gets_no_message(self, gap_db):
        fake_redis = _FakeRedis(quotes={
            "quote:AAPL": _raw_quote(150.0, 2.0),
            "quote:NVDA": _raw_quote(118.4, -1.5),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(gap_db, fake_redis, mock_post)

        chat_ids_messaged = {c.kwargs["json"]["chat_id"] for c in mock_post.call_args_list}
        assert "1003" not in chat_ids_messaged
        assert "1002" not in chat_ids_messaged  # u2 has no chat id at all


class TestNoFreshQuoteReportsHonestly:
    def test_book_nonempty_but_no_quotes_cached_sends_the_explicit_not_ready_message(self, gap_db):
        """Neither AAPL nor NVDA has a live quote (e.g. fetch_prices hasn't
        reached the US slot yet this minute) — u1 must still get a message,
        and it must say data isn't ready, not silence and not a fabricated
        0% gap."""
        fake_redis = _FakeRedis(quotes={})  # nothing cached
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(gap_db, fake_redis, mock_post)

        assert mock_post.call_count == 1
        text = mock_post.call_args.kwargs["json"]["text"]
        assert "ยังไม่มีราคาสด" in text


class TestFundFallback:
    def test_thai_fund_watchlist_symbol_is_read_via_fund_key_but_excluded_from_output(self, gap_db, tmp_path):
        """bd:shotockviz-ubw: the fund: key IS consulted (so a future
        change to fund gap semantics has data to work with), but a NAV is
        still excluded from THIS digest's output (see compute_gap_list) —
        proves both halves in one integration pass."""
        engine = create_engine(gap_db)
        with Session(engine) as db:
            u1 = db.query(User).filter_by(email="u1@example.com").one()
            wl = db.query(Watchlist).filter_by(user_id=u1.id).one()
            db.add(WatchlistItem(watchlist_id=wl.id, symbol="KFLTF70"))
            db.commit()
        engine.dispose()

        fake_redis = _FakeRedis(quotes={
            "quote:AAPL": _raw_quote(150.0, 2.0),
            "quote:NVDA": _raw_quote(118.4, -1.5),
            # deliberately NO "quote:KFLTF70" — only the fund: key exists
            "fund:KFLTF70": json.dumps({"nav": 9.5, "date": "2026-09-05", "ts": 1788600000}).encode(),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(gap_db, fake_redis, mock_post)

        text = mock_post.call_args.kwargs["json"]["text"]
        assert "KFLTF70" not in text
        # the other two symbols are unaffected by the fund lookup
        assert "AAPL" in text and "NVDA" in text


class TestTradingDayGate:
    def test_sunday_does_not_send_at_all(self, gap_db):
        fake_redis = _FakeRedis(quotes={
            "quote:AAPL": _raw_quote(150.0, 2.0),
            "quote:NVDA": _raw_quote(118.4, -1.5),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(gap_db, fake_redis, mock_post, now_utc_iso=NON_TRADING_SUNDAY_UTC_ISO)
        assert mock_post.call_count == 0


class TestRunLockDedupe:
    def test_calling_twice_same_day_sends_once(self, gap_db):
        fake_redis = _FakeRedis(quotes={
            "quote:AAPL": _raw_quote(150.0, 2.0),
            "quote:NVDA": _raw_quote(118.4, -1.5),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(gap_db, fake_redis, mock_post)
        _run_digest(gap_db, fake_redis, mock_post)  # same fake_redis instance = same lock store
        assert mock_post.call_count == 1


class TestTelegramTokenGuard:
    def test_missing_token_skips_entire_task_no_redis_call(self, gap_db):
        fake_redis = _FakeRedis()
        with (
            patch("core.config.settings.database_url", gap_db),
            patch("core.config.settings.telegram_bot_token", ""),
            patch("redis.from_url", return_value=fake_redis) as mock_from_url,
        ):
            send_gap_list_digest(now_utc_iso=TRADING_MONDAY_UTC_ISO)
        mock_from_url.assert_not_called()


class TestBatchQueryNoNPlus1:
    def test_three_select_statements_plus_one_mget(self, gap_db):
        """Q1 eligible users, Q2 watchlist rows, Q3 transactions — one round
        trip each, not per-user — same discipline sr_proximity_digest's own
        TestBatchQueryNoNPlus1 asserts."""
        fake_redis = _FakeRedis(quotes={
            "quote:AAPL": _raw_quote(150.0, 2.0),
            "quote:NVDA": _raw_quote(118.4, -1.5),
        })
        fake_redis.mget = MagicMock(side_effect=fake_redis.mget)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        statements = []
        engine = create_engine(gap_db)
        event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, *a: statements.append(statement))

        with (
            patch("core.config.settings.database_url", gap_db),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", return_value=fake_redis),
            patch("httpx.post", mock_post),
            patch("sqlalchemy.create_engine", return_value=engine),
        ):
            send_gap_list_digest(now_utc_iso=TRADING_MONDAY_UTC_ISO)

        select_statements = [s for s in statements if "SELECT" in s.upper()]
        assert len(select_statements) == 3, select_statements
        assert fake_redis.mget.call_count == 1
        engine.dispose()
