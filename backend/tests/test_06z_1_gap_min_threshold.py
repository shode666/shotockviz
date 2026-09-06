"""bd:shotockviz-06z.1 — "gap list has no per-user magnitude threshold — every
symbol in the book is listed daily".

bd:shotockviz-06z shipped `send_gap_list_digest` with NO magnitude filter at
all, by design (see workers/gap_list_digest.py's module docstring) — every
symbol with a fresh quote is ranked and shown, capped at
`GAP_LIST_MAX_SYMBOLS_PER_MESSAGE` purely for Telegram length. This adds
`users.gap_min_pct` (nullable, no invented default) as the per-user
threshold the parent bd deliberately left as an open question, without
regressing the "no invented number" discipline: `None` reproduces the
original behaviour exactly.

Under test:
  1. `compute_gap_list(..., min_gap_pct=None)` is byte-for-byte the old
     behaviour (no test in test_gap_list_digest.py needed to change for
     this bd — verified by running that file unmodified, see hand-off).
  2. `compute_gap_list(..., min_gap_pct=X)` drops symbols below X and keeps
     symbols at/above it (boundary inclusive — a gap exactly AT the
     threshold is still "at least X%"), and filters on MAGNITUDE, not
     signed value (a -3% move clears a 2% minimum same as +3%).
  3. `build_gap_list_message` states the threshold when one is set, and
     — the acceptance criterion's second half — explicitly names the cap
     (not a threshold) as the reason for truncation when NO threshold is
     set and the cap still cuts the list.
  4. End to end: two users with different `gap_min_pct` (one set, one
     NULL) against the SAME quote batch get DIFFERENT messages, and the
     per-user column is read in the SAME query as `telegram_chat_id` — no
     4th SELECT (test_gap_list_digest.py's TestBatchQueryNoNPlus1 already
     pins this task at exactly 3; a per-user threshold that cost a 4th
     query would be exactly the regression that test exists to catch, so
     it is re-asserted here against the two-different-thresholds fixture
     specifically, not just the single-threshold-less fixture that test
     already uses).
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from core.database import Base
from models.user import User
from models.watchlist import Watchlist, WatchlistItem
from workers.gap_list_digest import (
    GAP_LIST_MAX_SYMBOLS_PER_MESSAGE,
    build_gap_list_message,
    compute_gap_list,
    send_gap_list_digest,
)

# Same trading-day anchor as test_gap_list_digest.py (kept as a local literal,
# not an import, so this file has no fixture-import coupling to that one —
# see module docstring).
TRADING_MONDAY_UTC_ISO = "2026-09-07T12:30:00+00:00"


def _quote(price: float, change_pct: float, **over) -> dict:
    d = {"price": price, "change_pct": change_pct}
    d.update(over)
    return d


def _raw_quote(price: float, change_pct: float = 0.0, **over) -> bytes:
    return json.dumps(_quote(price, change_pct, **over)).encode()


# ─────────────────────────────────────────────────────────────────────────────
# compute_gap_list — filtering
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeGapListThreshold:
    def test_default_none_reproduces_the_original_no_filter_behaviour(self):
        """RED against any implementation that changed the parameter's
        default: a tiny 0.01% move must still survive when no threshold is
        given, exactly as bd:shotockviz-06z shipped it."""
        results = compute_gap_list({"AAPL"}, {"AAPL": _quote(150.0, 0.01)})
        assert [r["symbol"] for r in results] == ["AAPL"]

    def test_a_move_below_the_threshold_is_dropped(self):
        """RED against the pre-06z.1 signature: `min_gap_pct` did not exist
        as a parameter at all, so this call raised TypeError. RED against a
        backwards-wired filter (e.g. dropping ABOVE instead of below):
        TSLA at -3.0% would wrongly disappear instead of AAPL at 0.5%."""
        quotes = {"AAPL": _quote(150.0, 0.5), "TSLA": _quote(200.0, -3.0)}
        results = compute_gap_list({"AAPL", "TSLA"}, quotes, min_gap_pct=2.0)
        assert [r["symbol"] for r in results] == ["TSLA"]

    def test_a_move_exactly_at_the_threshold_is_kept_inclusive_boundary(self):
        results = compute_gap_list({"AAPL"}, {"AAPL": _quote(150.0, 2.0)}, min_gap_pct=2.0)
        assert [r["symbol"] for r in results] == ["AAPL"]

    def test_threshold_applies_to_magnitude_not_signed_value(self):
        """RED against `change_pct < min_gap_pct` (a signed compare): a
        -3.0 move would wrongly fail `-3.0 < 2.0` -> True -> dropped, even
        though a 3% MOVE (down) is exactly what a 2% minimum should keep."""
        results = compute_gap_list({"TSLA"}, {"TSLA": _quote(200.0, -3.0)}, min_gap_pct=2.0)
        assert [r["symbol"] for r in results] == ["TSLA"]

    def test_a_high_threshold_can_empty_the_list_without_erroring(self):
        results = compute_gap_list({"AAPL"}, {"AAPL": _quote(150.0, 0.3)}, min_gap_pct=10.0)
        assert results == []


# ─────────────────────────────────────────────────────────────────────────────
# build_gap_list_message — threshold line + cap-vs-filter disclosure
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildGapListMessageThreshold:
    def test_no_threshold_states_nothing_about_a_threshold(self):
        results = [{"symbol": "AAPL", "price": 150.0, "change_pct": 5.0}]
        msg = build_gap_list_message(results, book_count=1, today_str="06/09")
        assert "เกณฑ์ขั้นต่ำ" not in msg

    def test_a_set_threshold_is_stated_in_the_message(self):
        results = [{"symbol": "AAPL", "price": 150.0, "change_pct": 5.0}]
        msg = build_gap_list_message(
            results, book_count=1, today_str="06/09", min_gap_pct=3.0,
        )
        assert "เกณฑ์ขั้นต่ำที่ตั้งไว้: ≥3.0%" in msg

    def test_cap_truncation_with_no_threshold_says_the_cap_is_not_a_filter(self):
        """The exact acceptance criterion: 'if the cap is doing the
        filtering, say so in the message'. RED against bd:shotockviz-06z's
        original message body, which only ever said '…และอีก N ตัว' with
        no mention of the cap being a length guard — neither string
        asserted below existed in that output at all."""
        results = [
            {"symbol": f"SYM{i}", "price": 10.0, "change_pct": float(30 - i)}
            for i in range(GAP_LIST_MAX_SYMBOLS_PER_MESSAGE + 5)
        ]
        msg = build_gap_list_message(results, book_count=len(results), today_str="06/09")
        assert "…และอีก 5 ตัว" in msg  # unchanged from bd:shotockviz-06z
        assert "จำกัดความยาวข้อความ ไม่ใช่เกณฑ์คัดกรอง" in msg
        assert "ยังไม่ได้ตั้งเกณฑ์" in msg

    def test_cap_truncation_with_a_threshold_does_not_carry_the_no_filter_caveat(self):
        """When a real threshold already narrowed the list, truncation past
        the cap is an ordinary length guard — the 'you have no filter set'
        caveat must not appear (it would be false)."""
        results = [
            {"symbol": f"SYM{i}", "price": 10.0, "change_pct": float(30 - i)}
            for i in range(GAP_LIST_MAX_SYMBOLS_PER_MESSAGE + 5)
        ]
        msg = build_gap_list_message(
            results, book_count=len(results), today_str="06/09", min_gap_pct=1.0,
        )
        assert "…และอีก 5 ตัว" in msg
        assert "ยังไม่ได้ตั้งเกณฑ์" not in msg

    def test_no_results_with_a_threshold_still_states_the_threshold(self):
        msg = build_gap_list_message([], book_count=5, today_str="06/09", min_gap_pct=4.0)
        assert "ยังไม่มีราคาสด" in msg
        assert "เกณฑ์ขั้นต่ำที่ตั้งไว้: ≥4.0%" in msg


# ─────────────────────────────────────────────────────────────────────────────
# Integration — per-user column reaches both pure functions end to end,
# two users with DIFFERENT thresholds against the SAME quote batch, no 4th
# query.
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRedis:
    """Same real SETNX/MGET semantics as test_gap_list_digest.py's fake."""

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


@pytest.fixture
def threshold_db(tmp_path):
    """u_filtered: gap_min_pct=2.0, watchlist AAPL (0.5% today, below
    threshold) + NVDA (-3.0%, above). u_unfiltered: gap_min_pct left NULL
    (never set), same two symbols — must see BOTH."""
    db_path = tmp_path / "gap_threshold_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        u_filtered = User(
            email="filtered@example.com", password_hash="x", display_name="Filtered",
            telegram_chat_id="2001", gap_min_pct=2.0,
        )
        u_unfiltered = User(
            email="unfiltered@example.com", password_hash="x", display_name="Unfiltered",
            telegram_chat_id="2002",
        )
        db.add_all([u_filtered, u_unfiltered])
        db.flush()

        for u in (u_filtered, u_unfiltered):
            wl = Watchlist(user_id=u.id, name="Main")
            db.add(wl)
            db.flush()
            db.add(WatchlistItem(watchlist_id=wl.id, symbol="AAPL"))
            db.add(WatchlistItem(watchlist_id=wl.id, symbol="NVDA"))
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


class TestPerUserThresholdEndToEnd:
    def test_the_users_own_threshold_is_applied_not_a_shared_one(self, threshold_db):
        """RED against a global (non-per-user) threshold, or against the
        column never being read at all: before this bd, EVERY user's
        message would contain both AAPL and NVDA — this proves
        u_filtered's message drops AAPL (0.5% < 2.0%) while u_unfiltered's
        keeps it."""
        fake_redis = _FakeRedis(quotes={
            "quote:AAPL": _raw_quote(150.0, 0.5),
            "quote:NVDA": _raw_quote(118.4, -3.0),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(threshold_db, fake_redis, mock_post)

        by_chat_id = {c.kwargs["json"]["chat_id"]: c.kwargs["json"]["text"] for c in mock_post.call_args_list}
        assert mock_post.call_count == 2

        filtered_text = by_chat_id["2001"]
        assert "NVDA" in filtered_text
        assert "AAPL" not in filtered_text
        assert "เกณฑ์ขั้นต่ำที่ตั้งไว้: ≥2.0%" in filtered_text

        unfiltered_text = by_chat_id["2002"]
        assert "AAPL" in unfiltered_text
        assert "NVDA" in unfiltered_text
        assert "เกณฑ์ขั้นต่ำ" not in unfiltered_text

    def test_still_exactly_three_select_statements_with_two_different_thresholds(self, threshold_db):
        """Re-asserts test_gap_list_digest.py's TestBatchQueryNoNPlus1
        invariant specifically against a fixture where `gap_min_pct`
        actually varies per row — the case most likely to tempt a
        per-user follow-up query that test's own (thresholdless) fixture
        would never exercise."""
        fake_redis = _FakeRedis(quotes={
            "quote:AAPL": _raw_quote(150.0, 0.5),
            "quote:NVDA": _raw_quote(118.4, -3.0),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        statements = []
        engine = create_engine(threshold_db)
        event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, *a: statements.append(statement))

        with (
            patch("core.config.settings.database_url", threshold_db),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", return_value=fake_redis),
            patch("httpx.post", mock_post),
            patch("sqlalchemy.create_engine", return_value=engine),
        ):
            send_gap_list_digest(now_utc_iso=TRADING_MONDAY_UTC_ISO)

        select_statements = [s for s in statements if "SELECT" in s.upper()]
        assert len(select_statements) == 3, select_statements
        engine.dispose()
