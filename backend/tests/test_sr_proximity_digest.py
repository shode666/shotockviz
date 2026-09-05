"""Tests for workers.sr_proximity_digest — bd:features-2026-09 iter 8
(16-sara-sr-proximity-digest-spec.md §7).

Pure-function tests (proximity math, message builder) use fixed fixture
data, no DB needed — same pattern as test_sr_auto_pivot.py. Integration
tests use a file-based sqlite DB (not in-memory) so the sync engine the
task creates internally sees the same rows, same pattern as
test_alert_checker_idempotency.py's sqlite_db_url fixture. Redis is a
tiny real-semantics fake (not just a mock that always says "ok") so the
run-lock test actually proves the SETNX guard works, not just that it was
called.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from core.database import Base
from models.sr_level import SRLevel
from models.user import User
from models.watchlist import Watchlist, WatchlistItem
from workers.sr_proximity_digest import (
    PROXIMITY_PCT,
    build_digest_message,
    compute_proximity_for_user,
    send_sr_proximity_digest,
)


# ─────────────────────────────────────────────────────────────────────────────
# compute_proximity_for_user — pure, fixed fixture data
# ─────────────────────────────────────────────────────────────────────────────

class TestProximityBoundary:
    def test_exactly_5_0_pct_is_a_match_inclusive(self):
        levels = {"AOT.BK": [{"price": 100.0, "level_type": "support", "tag": None, "user_id": None}]}
        prices = {"AOT.BK": 95.0}  # (100-95)/100 = 0.05 exactly
        results = compute_proximity_for_user({"AOT.BK"}, levels, prices, user_id=1)
        assert len(results) == 1
        assert results[0]["matches"][0]["distance_pct"] == pytest.approx(PROXIMITY_PCT)

    def test_5_01_pct_is_not_a_match(self):
        levels = {"AOT.BK": [{"price": 100.0, "level_type": "support", "tag": None, "user_id": None}]}
        prices = {"AOT.BK": 94.99}  # (100-94.99)/100 = 0.0501
        results = compute_proximity_for_user({"AOT.BK"}, levels, prices, user_id=1)
        assert results == []

    def test_symbol_with_no_cached_quote_is_skipped(self):
        levels = {"AOT.BK": [{"price": 100.0, "level_type": "support", "tag": None, "user_id": None}]}
        results = compute_proximity_for_user({"AOT.BK"}, levels, {}, user_id=1)
        assert results == []


class TestProximityLevelScoping:
    def test_global_level_user_id_null_visible_to_everyone(self):
        levels = {"AOT.BK": [{"price": 60.0, "level_type": "support", "tag": None, "user_id": None}]}
        prices = {"AOT.BK": 61.0}
        for uid in (1, 2, 999):
            results = compute_proximity_for_user({"AOT.BK"}, levels, prices, user_id=uid)
            assert len(results) == 1, f"user {uid} should see the global level"

    def test_owned_level_visible_only_to_owner(self):
        levels = {"AOT.BK": [{"price": 60.0, "level_type": "support", "tag": None, "user_id": 1}]}
        prices = {"AOT.BK": 61.0}
        assert len(compute_proximity_for_user({"AOT.BK"}, levels, prices, user_id=1)) == 1
        assert compute_proximity_for_user({"AOT.BK"}, levels, prices, user_id=2) == []

    def test_multiple_matching_levels_sorted_by_distance_ascending(self):
        levels = {
            "AOT.BK": [
                {"price": 63.50, "level_type": "resistance", "tag": None, "user_id": None},
                {"price": 60.00, "level_type": "support", "tag": None, "user_id": None},
            ]
        }
        prices = {"AOT.BK": 61.25}
        results = compute_proximity_for_user({"AOT.BK"}, levels, prices, user_id=1)
        distances = [m["distance_pct"] for m in results[0]["matches"]]
        assert distances == sorted(distances)


# ─────────────────────────────────────────────────────────────────────────────
# build_digest_message — pure
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildDigestMessage:
    def test_no_matches_sends_fixed_no_proximity_message(self):
        msg = build_digest_message("set_open", [], watchlist_count=42, today_str="05/09")
        assert msg == "📊 วันนี้ไม่มีหุ้นใกล้ S/R (ก่อน SET เปิด)"

    def test_us_premarket_header(self):
        msg = build_digest_message("us_premarket", [], watchlist_count=1, today_str="05/09")
        assert "ก่อน US pre-market" in msg

    def test_with_matches_shows_emoji_sign_and_totals(self):
        results = [{
            "symbol": "AOT.BK",
            "price": 61.25,
            "matches": [
                {"level_type": "support", "price": 60.00, "tag": None, "distance_pct": 0.0208, "signed_pct": -2.0},
                {"level_type": "resistance", "price": 63.50, "tag": "W1 pivot", "distance_pct": 0.0354, "signed_pct": 3.7},
            ],
        }]
        msg = build_digest_message("set_open", results, watchlist_count=42, today_str="05/09")
        assert "🟢 แนวรับ 60.00 (-2.0%)" in msg
        assert "🔴 แนวต้าน 63.50 (+3.7%) (W1 pivot)" in msg
        assert "รวม 1 ตัว จาก watchlist 42 ตัว" in msg

    def test_truncates_at_20_symbols(self):
        results = [
            {"symbol": f"SYM{i}", "price": 10.0, "matches": [
                {"level_type": "support", "price": 9.5, "tag": None, "distance_pct": 0.01, "signed_pct": -1.0}
            ]}
            for i in range(25)
        ]
        msg = build_digest_message("set_open", results, watchlist_count=25, today_str="05/09")
        assert "…และอีก 5 ตัว" in msg
        assert msg.count("SYM") == 20


# ─────────────────────────────────────────────────────────────────────────────
# Integration — full task against a file-based sqlite DB + fake redis
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRedis:
    """Real SETNX/MGET semantics (not just a mock) — so the run-lock test
    actually proves the guard, and MGET reflects the seeded quote cache."""

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


def _quote(price: float) -> bytes:
    return json.dumps({"price": price}).encode()


@pytest.fixture
def sqlite_db_url(tmp_path):
    db_path = tmp_path / "sr_digest_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        u1 = User(email="u1@example.com", password_hash="x", display_name="U1", telegram_chat_id="1001")
        u2_no_chat = User(email="u2@example.com", password_hash="x", display_name="U2", telegram_chat_id=None)
        db.add_all([u1, u2_no_chat])
        db.flush()

        u3_empty_watchlist = User(email="u3@example.com", password_hash="x", display_name="U3", telegram_chat_id="1003")
        db.add(u3_empty_watchlist)
        db.flush()

        wl1 = Watchlist(user_id=u1.id, name="Main")
        wl3 = Watchlist(user_id=u3_empty_watchlist.id, name="Empty")
        db.add_all([wl1, wl3])
        db.flush()

        db.add_all([
            WatchlistItem(watchlist_id=wl1.id, symbol="AOT.BK"),
            WatchlistItem(watchlist_id=wl1.id, symbol="NVDA"),
        ])

        db.add_all([
            SRLevel(symbol="AOT.BK", price=60.00, level_type="support", source="manual_import"),
            SRLevel(symbol="AOT.BK", price=63.50, level_type="resistance", source="manual_import"),
            # user_created must NOT count per spec §3 — seeded far from
            # price too so it would never falsely match anyway, but the
            # source filter must exclude it even if it were close.
            SRLevel(symbol="AOT.BK", price=61.20, level_type="support", source="user_created"),
            SRLevel(symbol="NVDA", price=120.00, level_type="resistance", source="auto_pivot"),
        ])
        db.commit()

    engine.dispose()
    return f"sqlite:///{db_path}"


def _run_digest(sqlite_db_url, slot, fake_redis, mock_post):
    with (
        patch("core.config.settings.database_url", sqlite_db_url),
        patch("core.config.settings.telegram_bot_token", "fake-token"),
        patch("redis.from_url", return_value=fake_redis),
        patch("httpx.post", mock_post),
    ):
        send_sr_proximity_digest(slot)


class TestSkipCases:
    def test_no_chat_id_and_empty_watchlist_users_are_skipped_silently(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes={
            "cache:quote:AOT.BK": _quote(61.25),
            "cache:quote:NVDA": _quote(118.40),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(sqlite_db_url, "set_open", fake_redis, mock_post)

        # Only u1 (chat_id set + non-empty watchlist) gets a message.
        assert mock_post.call_count == 1
        assert mock_post.call_args.kwargs["json"]["chat_id"] == "1001"


class TestSourceFiltering:
    def test_user_created_level_does_not_count_toward_proximity(self, sqlite_db_url):
        # Price exactly matches the user_created level (61.20) but that
        # source must not be counted — only manual_import (60.00, 63.50)
        # and auto_pivot (120.00) should show up in the message.
        fake_redis = _FakeRedis(quotes={
            "cache:quote:AOT.BK": _quote(61.20),
            "cache:quote:NVDA": _quote(118.40),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(sqlite_db_url, "set_open", fake_redis, mock_post)

        text = mock_post.call_args.kwargs["json"]["text"]
        # The user_created level itself (price 61.20, would be a 0%-away
        # "match" if counted) must never appear as a level line — only the
        # current-price header line legitimately shows 61.20.
        assert "แนวรับ 61.20" not in text
        assert "60.00" in text
        assert "63.50" in text


class TestBatchQueryNoNPlus1:
    def test_two_dq_round_trips_plus_one_mget(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes={
            "cache:quote:AOT.BK": _quote(61.25),
            "cache:quote:NVDA": _quote(118.40),
        })
        fake_redis.mget = MagicMock(side_effect=fake_redis.mget)
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        # Count actual SQL statements sent to the sqlite engine — proves
        # Q1+Q2 batch design (spec §3), not one query per user/symbol.
        statements = []
        engine = create_engine(sqlite_db_url)
        event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, *a: statements.append(statement))

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("redis.from_url", return_value=fake_redis),
            patch("httpx.post", mock_post),
            patch("sqlalchemy.create_engine", return_value=engine),
        ):
            send_sr_proximity_digest("set_open")

        select_statements = [s for s in statements if "SELECT" in s.upper()]
        assert len(select_statements) == 2, select_statements
        assert fake_redis.mget.call_count == 1
        engine.dispose()


class TestRunLockDedupe:
    def test_calling_same_slot_twice_same_day_sends_once(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes={
            "cache:quote:AOT.BK": _quote(61.25),
            "cache:quote:NVDA": _quote(118.40),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        _run_digest(sqlite_db_url, "set_open", fake_redis, mock_post)
        _run_digest(sqlite_db_url, "set_open", fake_redis, mock_post)  # same fake_redis instance = same lock store

        assert mock_post.call_count == 1

    def test_different_slot_same_day_is_not_blocked_by_the_other_slots_lock(self, sqlite_db_url):
        fake_redis = _FakeRedis(quotes={
            "cache:quote:AOT.BK": _quote(61.25),
            "cache:quote:NVDA": _quote(118.40),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))

        _run_digest(sqlite_db_url, "set_open", fake_redis, mock_post)
        _run_digest(sqlite_db_url, "us_premarket", fake_redis, mock_post)

        assert mock_post.call_count == 2


class TestNoProximityMessageIntegration:
    def test_watchlist_but_nothing_near_sends_the_fixed_message(self, sqlite_db_url):
        # Prices far from every level -> no match, but u1 still has a
        # non-empty watchlist + chat_id, so must get the "no proximity"
        # message, not silence (spec user-confirmed decision).
        fake_redis = _FakeRedis(quotes={
            "cache:quote:AOT.BK": _quote(200.0),
            "cache:quote:NVDA": _quote(500.0),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run_digest(sqlite_db_url, "set_open", fake_redis, mock_post)

        assert mock_post.call_count == 1
        assert mock_post.call_args.kwargs["json"]["text"] == "📊 วันนี้ไม่มีหุ้นใกล้ S/R (ก่อน SET เปิด)"


class TestTelegramTokenGuard:
    def test_missing_token_skips_entire_task_no_redis_call(self, sqlite_db_url):
        fake_redis = _FakeRedis()
        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("core.config.settings.telegram_bot_token", ""),
            patch("redis.from_url", return_value=fake_redis) as mock_from_url,
        ):
            send_sr_proximity_digest("set_open")
        mock_from_url.assert_not_called()
