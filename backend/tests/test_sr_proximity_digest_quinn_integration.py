"""Quinn (QA) Phase 3b integration review — bd:features-2026-09 iter 8,
outputs/features-2026-09/18-quinn-sr-proximity-review.md.

Adversarial follow-up to Dave's test_sr_proximity_digest.py. Covers:
1. Full multi-user flow (A near S/R, B nothing near, C no chat_id, D no
   watchlist) in ONE run — Dave's fixture never has all 4 personas present
   simultaneously in a single assertion.
2. REAL concurrent SETNX race (two OS threads + threading.Barrier, same
   pattern as test_alert_checker_idempotency.py's claim_alert race test) —
   Dave's run-lock test only calls _run_digest() twice *sequentially* in
   one thread, which would also pass against a naively-racy
   check-then-set lock. This proves the SETNX itself, under a real race,
   sends exactly once.
3. Duplicate/overlapping S/R levels — manual_import + auto_pivot rows at
   the exact same price (same "line") and at different prices (different
   lines) for the same symbol — confirm no double-count / no crash / no
   silently-merged-away legitimate second line.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.database import Base
from models.sr_level import SRLevel
from models.user import User
from models.watchlist import Watchlist, WatchlistItem
from workers.sr_proximity_digest import send_sr_proximity_digest


def _quote(price: float) -> bytes:
    return json.dumps({"price": price}).encode()


class _RealLockFakeRedis:
    """SETNX with an actual internal threading.Lock — models real Redis's
    atomicity for the check-and-set, so a race test against this fixture
    proves the WORKER's use of the lock (claim-before-send ordering), not
    an artifact of a non-atomic test double."""

    def __init__(self, quotes: dict[str, bytes] | None = None):
        self._store: dict[str, bytes] = {}
        self._quotes = quotes or {}
        self._mutex = threading.Lock()

    def set(self, key, value, nx=False, ex=None):
        with self._mutex:
            if nx and key in self._store:
                return False
            self._store[key] = value
            return True

    def mget(self, keys):
        return [self._quotes.get(k) for k in keys]


@pytest.fixture
def multi_user_db(tmp_path):
    """4 users matching the task's exact personas:
    A — watchlist symbol within 5% of a manual_import level (gets a real digest)
    B — watchlist symbol, but nothing within 5% of any level (gets the "nothing near" message)
    C — watchlist + symbols near a level, but NO telegram_chat_id (must get nothing)
    D — telegram_chat_id set, but NO watchlist at all (must get nothing)
    """
    db_path = tmp_path / "quinn_sr_digest.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user_a = User(email="a@example.com", password_hash="x", display_name="A", telegram_chat_id="2001")
        user_b = User(email="b@example.com", password_hash="x", display_name="B", telegram_chat_id="2002")
        user_c = User(email="c@example.com", password_hash="x", display_name="C", telegram_chat_id=None)
        user_d = User(email="d@example.com", password_hash="x", display_name="D", telegram_chat_id="2004")
        db.add_all([user_a, user_b, user_c, user_d])
        db.flush()

        wl_a = Watchlist(user_id=user_a.id, name="A-Main")
        wl_b = Watchlist(user_id=user_b.id, name="B-Main")
        wl_c = Watchlist(user_id=user_c.id, name="C-Main")
        # D deliberately gets NO Watchlist row at all.
        db.add_all([wl_a, wl_b, wl_c])
        db.flush()

        db.add_all([
            WatchlistItem(watchlist_id=wl_a.id, symbol="AOT.BK"),   # near a level
            WatchlistItem(watchlist_id=wl_b.id, symbol="PTT.BK"),   # no level nearby
            WatchlistItem(watchlist_id=wl_c.id, symbol="AOT.BK"),   # near a level, but no chat_id
        ])

        db.add_all([
            SRLevel(symbol="AOT.BK", price=60.00, level_type="support", source="manual_import"),
            SRLevel(symbol="PTT.BK", price=999.00, level_type="resistance", source="auto_pivot"),
        ])
        db.commit()
        ids = (user_a.id, user_b.id, user_c.id, user_d.id)

    engine.dispose()
    return f"sqlite:///{db_path}", ids


def _run(sqlite_db_url, slot, fake_redis, mock_post):
    with (
        patch("core.config.settings.database_url", sqlite_db_url),
        patch("core.config.settings.telegram_bot_token", "fake-token"),
        patch("redis.from_url", return_value=fake_redis),
        patch("httpx.post", mock_post),
    ):
        send_sr_proximity_digest(slot)


class TestFullMultiUserFlow:
    def test_a_gets_digest_b_gets_no_proximity_c_and_d_get_nothing(self, multi_user_db):
        sqlite_db_url, _ = multi_user_db
        fake_redis = _RealLockFakeRedis(quotes={
            "cache:quote:AOT.BK": _quote(61.25),   # (60-61.25)/60 = 2.08% -> match
            "cache:quote:PTT.BK": _quote(35.00),   # nowhere near 999.00 -> no match
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run(sqlite_db_url, "set_open", fake_redis, mock_post)

        # Exactly 2 sends: A (real digest) + B ("no proximity" message).
        # C (no chat_id) and D (no watchlist) must NEVER appear.
        assert mock_post.call_count == 2, [c.kwargs["json"] for c in mock_post.call_args_list]

        sent_by_chat_id = {c.kwargs["json"]["chat_id"]: c.kwargs["json"]["text"] for c in mock_post.call_args_list}
        assert set(sent_by_chat_id) == {"2001", "2002"}
        assert "AOT.BK" in sent_by_chat_id["2001"]
        assert "แนวรับ 60.00" in sent_by_chat_id["2001"]
        assert sent_by_chat_id["2002"] == "📊 วันนี้ไม่มีหุ้นใกล้ S/R (ก่อน SET เปิด)"


class TestRealConcurrentRunLockRace:
    def test_two_real_threads_race_the_setnx_only_one_sends(self, multi_user_db):
        """Two REAL OS threads call send_sr_proximity_digest('set_open')
        at (as close to) the same instant via threading.Barrier(2) — the
        same pattern Quinn required for claim_alert's race test
        (test_alert_checker_idempotency.py). Both threads share the SAME
        fake_redis instance (models 2 celery-beat ticks / retry hitting
        the same real Redis), and its .set() is internally lock-protected
        to emulate Redis's atomic SETNX. Exactly one set of messages must
        be sent — the OTHER thread must see rowcount-equivalent "already
        ran" and return before touching the DB or Telegram.
        """
        sqlite_db_url, _ = multi_user_db
        fake_redis = _RealLockFakeRedis(quotes={
            "cache:quote:AOT.BK": _quote(61.25),
            "cache:quote:PTT.BK": _quote(35.00),
        })
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        barrier = threading.Barrier(2)

        def _tick():
            barrier.wait(timeout=5)
            _run(sqlite_db_url, "set_open", fake_redis, mock_post)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_tick), pool.submit(_tick)]
            for f in futures:
                f.result(timeout=10)

        # 2 users get a message per real run (A + B) -> exactly one winning
        # tick must produce exactly 2 sends total, not 4 (double-fire) and
        # not 0 (both blocked).
        assert mock_post.call_count == 2, (
            f"expected exactly 2 sends from exactly one winning tick, got "
            f"{mock_post.call_count}: {[c.kwargs['json'] for c in mock_post.call_args_list]}"
        )


class TestOverlappingManualAndAutoPivotLevels:
    def test_same_price_manual_and_auto_pivot_both_appear_as_separate_lines(self, tmp_path):
        """Spec §3 says nothing about de-duplicating manual_import vs
        auto_pivot rows that happen to land on the exact same price for
        the same symbol/level_type — the code (compute_proximity_for_user)
        iterates SRLevel rows independently with no merge step. Verify
        that behavior explicitly (not implicitly assumed): a manual_import
        row and an auto_pivot row at the SAME price on the SAME symbol
        both surface as separate match entries -> the digest message
        shows the SAME level line TWICE. Documented as a finding, not
        silently accepted."""
        db_path = tmp_path / "dup_levels.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            user = User(email="dup@example.com", password_hash="x", display_name="Dup", telegram_chat_id="3001")
            db.add(user)
            db.flush()
            wl = Watchlist(user_id=user.id, name="Main")
            db.add(wl)
            db.flush()
            db.add(WatchlistItem(watchlist_id=wl.id, symbol="AOT.BK"))
            db.add_all([
                SRLevel(symbol="AOT.BK", price=60.00, level_type="support", source="manual_import"),
                SRLevel(symbol="AOT.BK", price=60.00, level_type="support", source="auto_pivot"),  # same line, both sources
                SRLevel(symbol="AOT.BK", price=63.50, level_type="resistance", source="auto_pivot"),  # different line
            ])
            db.commit()
        engine.dispose()

        sqlite_db_url = f"sqlite:///{db_path}"
        fake_redis = _RealLockFakeRedis(quotes={"cache:quote:AOT.BK": _quote(61.25)})
        mock_post = MagicMock(return_value=MagicMock(status_code=200))
        _run(sqlite_db_url, "set_open", fake_redis, mock_post)

        assert mock_post.call_count == 1
        text = mock_post.call_args.kwargs["json"]["text"]

        # FINDING: the identical (price, level_type) pair from 2 different
        # sources renders as 2 near-identical lines in one message. Assert
        # the current (undeduplicated) behavior explicitly.
        assert text.count("แนวรับ 60.00") == 2, (
            "expected finding confirmed: manual_import + auto_pivot at the "
            "same price/level_type both render as separate lines (no "
            "cross-source de-dup) -- text was:\n" + text
        )
        # The genuinely different line (resistance 63.50) must also appear.
        assert "แนวต้าน 63.50" in text
