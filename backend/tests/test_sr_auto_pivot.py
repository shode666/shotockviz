"""Unit + integration tests for workers.sr_auto_pivot — bd:features-2026-09
slice A, per Tara §1.3 DoD: "unit test of fractal + cluster + classify +
select with a fixed fixture bar array (pure function, no DB needed);
integration test proving G1 (symbol with manual -> 0 auto rows)".

Pure-function tests use fixed fixture arrays (no DB) — same pattern as
srLevelColor.test.ts / test_symbol_utils.py. Integration tests use an
in-memory SQLite session, same pattern as test_import_sr_levels.py's
sr_test_db fixture, monkeypatching create_engine so sr_auto_pivot's sync
engine points at the SQLite file instead of a real Postgres connection.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.database import Base
from models.sr_level import SRLevel
from workers.sr_auto_pivot import (
    FRACTAL_K,
    CLUSTER_TOLERANCE,
    classify_and_select,
    cluster_pivots,
    compute_auto_pivots,
    detect_fractals,
)


# ─────────────────────────────────────────────────────────────────────────────
# detect_fractals — pure, fixed fixture bars
# ─────────────────────────────────────────────────────────────────────────────

def _bars(highs: list[float], lows: list[float]) -> list[dict]:
    assert len(highs) == len(lows)
    return [{"high": h, "low": l, "close": (h + l) / 2} for h, l in zip(highs, lows)]


class TestDetectFractals:
    def test_single_clean_swing_high_confirmed(self):
        # index 5 is a clean local max with 5 bars on each side, k=5 exactly
        # confirms it (n = 11 = 2k+1).
        highs = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10]
        lows = [h - 1 for h in highs]
        bars = _bars(highs, lows)
        swing_highs, swing_lows = detect_fractals(bars, k=5)
        assert swing_highs == [20]

    def test_single_clean_swing_low_confirmed(self):
        lows = [10, 9, 8, 7, 6, 1, 6, 7, 8, 9, 10]
        highs = [l + 1 for l in lows]
        bars = _bars(highs, lows)
        swing_highs, swing_lows = detect_fractals(bars, k=5)
        assert swing_lows == [1]

    def test_last_k_bars_never_confirm(self):
        """A spike in the last k bars must NOT be reported — it can't be
        confirmed without k bars of "future" data (Tara §1.3: unconfirmed
        pivot is not tradeable)."""
        highs = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 100]  # spike at the very last bar
        lows = [h - 1 for h in highs]
        bars = _bars(highs, lows)
        swing_highs, _ = detect_fractals(bars, k=5)
        assert 100 not in swing_highs

    def test_first_k_bars_never_confirm(self):
        highs = [100, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10]  # spike at the very first bar
        lows = [h - 1 for h in highs]
        bars = _bars(highs, lows)
        swing_highs, _ = detect_fractals(bars, k=5)
        assert 100 not in swing_highs

    def test_ties_are_not_pivots_strict_inequality(self):
        """Two equal peaks — neither one is `>` the other, so strict `>`
        means NEITHER confirms as a swing high (deterministic, no
        double-counting a flat top)."""
        highs = [10, 11, 12, 13, 14, 20, 15, 14, 20, 12, 11, 10]
        lows = [h - 1 for h in highs]
        bars = _bars(highs, lows)
        swing_highs, _ = detect_fractals(bars, k=5)
        assert 20 not in swing_highs

    def test_too_few_bars_returns_empty(self):
        bars = _bars([10, 11, 12], [9, 10, 11])
        swing_highs, swing_lows = detect_fractals(bars, k=5)
        assert swing_highs == []
        assert swing_lows == []

    def test_default_k_is_5(self):
        assert FRACTAL_K == 5


# ─────────────────────────────────────────────────────────────────────────────
# cluster_pivots — pure, fixed fixture prices
# ─────────────────────────────────────────────────────────────────────────────

class TestClusterPivots:
    def test_empty_input(self):
        assert cluster_pivots([]) == []

    def test_single_price_single_cluster(self):
        assert cluster_pivots([100.0]) == [(100.0, 1)]

    def test_within_tolerance_merges(self):
        # 100, 100.5, 100.9 — all within 1.0% of a running mean starting at 100
        result = cluster_pivots([100.0, 100.5, 100.9], tol=0.010)
        assert len(result) == 1
        mean, strength = result[0]
        assert strength == 3
        assert mean == pytest.approx((100.0 + 100.5 + 100.9) / 3)

    def test_outside_tolerance_splits(self):
        # 100 and 200 — nowhere near 1.0% of each other
        result = cluster_pivots([100.0, 200.0], tol=0.010)
        assert result == [(100.0, 1), (200.0, 1)]

    def test_sorted_ascending_regardless_of_input_order(self):
        result = cluster_pivots([200.0, 100.0], tol=0.010)
        assert result == [(100.0, 1), (200.0, 1)]

    def test_works_for_low_price_thai_stock_and_high_price_us_stock_same_code(self):
        """1.0% of ~35 THB and 1.0% of ~180 USD both cluster correctly with
        the exact same relative-tolerance code (Tara §1.3 rationale)."""
        thai = cluster_pivots([35.0, 35.2, 35.3], tol=0.010)
        us = cluster_pivots([180.0, 181.5, 181.8], tol=0.010)
        assert len(thai) == 1 and thai[0][1] == 3
        assert len(us) == 1 and us[0][1] == 3

    def test_default_tolerance_is_1_percent(self):
        assert CLUSTER_TOLERANCE == 0.010


# ─────────────────────────────────────────────────────────────────────────────
# classify_and_select — pure, fixed fixture clusters
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyAndSelect:
    def test_below_close_is_support_above_is_resistance(self):
        close = 100.0
        clusters_hi = [(110.0, 2)]
        clusters_lo = [(90.0, 3)]
        rows = classify_and_select(clusters_hi, clusters_lo, close)
        types = {r["price"]: r["level_type"] for r in rows}
        assert types[90.0] == "support"
        assert types[110.0] == "resistance"

    def test_dead_band_discards(self):
        """Within ±0.25% of close — must not appear as either support or
        resistance."""
        close = 100.0
        clusters_hi = [(100.1, 5)]  # within 0.25%
        clusters_lo = [(99.9, 5)]   # within 0.25%
        rows = classify_and_select(clusters_hi, clusters_lo, close)
        assert rows == []

    def test_selection_caps_at_top_3_per_side_by_strength(self):
        close = 100.0
        # 5 resistance candidates, strengths 1..5 — only top 3 by strength
        clusters_hi = [(110.0 + i, s) for i, s in enumerate([1, 2, 3, 4, 5])]
        rows = classify_and_select([], clusters_hi, close, top_n=3)
        assert len(rows) == 3
        strengths_selected = sorted(
            [c for c in clusters_hi if c[0] in {r["price"] for r in rows}],
            key=lambda c: c[1],
        )
        assert [s for _, s in strengths_selected] == [3, 4, 5]

    def test_tie_break_by_distance_then_price(self):
        close = 100.0
        # Two support candidates with equal strength — closer to close wins.
        clusters_lo = [(80.0, 2), (95.0, 2)]
        rows = classify_and_select([], clusters_lo, close, top_n=1)
        assert len(rows) == 1
        assert rows[0]["price"] == 95.0

    def test_tag_numbering_by_distance_closest_is_1(self):
        close = 100.0
        clusters_hi = [(120.0, 5), (105.0, 5), (110.0, 5)]
        rows = classify_and_select([], clusters_hi, close, top_n=3)
        by_tag = {r["tag"]: r["price"] for r in rows}
        assert by_tag["AUTO R1"] == 105.0  # closest
        assert by_tag["AUTO R2"] == 110.0
        assert by_tag["AUTO R3"] == 120.0  # farthest

    def test_max_six_rows_total(self):
        close = 100.0
        clusters_hi = [(110.0 + i, 1) for i in range(5)]
        clusters_lo = [(90.0 - i, 1) for i in range(5)]
        rows = classify_and_select(clusters_lo, clusters_hi, close, top_n=3)
        assert len(rows) <= 6

    def test_swing_high_cluster_can_become_support_if_below_close(self):
        """Classification is by relation to close, NOT by pivot origin type
        (Tara §1.3) — an old swing-high cluster that's now below close must
        classify as support."""
        close = 200.0
        clusters_hi = [(150.0, 3)]  # a "high" pivot but well below today's close
        rows = classify_and_select(clusters_hi, [], close)
        assert rows[0]["level_type"] == "support"


# ─────────────────────────────────────────────────────────────────────────────
# compute_auto_pivots task — integration (in-memory SQLite, sync engine)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sync_sqlite_engine(monkeypatch, tmp_path):
    """A file-backed SQLite DB (sr_auto_pivot uses sync sqlalchemy.create_engine,
    which needs a real DBAPI connection per call — in-memory ':memory:' would
    lose state between connections)."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    class _FakeSettings:
        sync_database_url = f"sqlite:///{db_path}"

    import workers.sr_auto_pivot as mod
    monkeypatch.setattr(mod, "get_watched_symbols", lambda fallback=None: ["AAPL"])

    # Patch the `create_engine`/`settings` import inside the task function's
    # local scope by patching the modules it imports from at call time.
    import core.config as core_config
    monkeypatch.setattr(core_config, "settings", _FakeSettings())

    yield engine
    engine.dispose()


def _insert_bars(engine, symbol: str, n: int, base: float = 100.0):
    """Insert `n` flat OHLCV daily bars (no fractals will confirm — used for
    guard tests where the pivot output itself doesn't matter)."""
    Session = sessionmaker(bind=engine)
    from models.ohlcv import OHLCVBar

    with Session() as session:
        for i in range(n):
            session.add(OHLCVBar(
                symbol=symbol, timeframe="1D", time_unix=i,
                time_str=f"2026-01-{(i % 28) + 1:02d}",
                open=base, high=base + 1, low=base - 1, close=base,
                volume=1000,
            ))
        session.commit()


def _insert_swing_bars(engine, symbol: str, n: int = 91):
    """Insert bars with ONE confirmed swing low (dip) and ONE confirmed
    swing high (peak), both far enough from the flat baseline (and from
    each other, and from the array edges) to clear k=5 fractal confirmation
    and the ±0.25% dead band around the final close (~100) — used by G1
    per-side truth-table tests (13-tara-g1-guard-revision.md §2.2), which
    need REAL non-flat data producing exactly one support + one resistance
    candidate (flat bars give zero fractals and are not load-bearing here,
    per the spec's DoD §5.1)."""
    assert n >= 91, "need room for a dip at i=20 and a peak at i=60, both k=5-confirmable"
    Session = sessionmaker(bind=engine)
    from models.ohlcv import OHLCVBar

    highs = [101.0] * n
    lows = [99.0] * n
    highs[60] = 130.0   # swing high -> resistance candidate (close ~100)
    lows[20] = 70.0      # swing low -> support candidate

    with Session() as session:
        for i in range(n):
            h, l = highs[i], lows[i]
            session.add(OHLCVBar(
                symbol=symbol, timeframe="1D", time_unix=i,
                time_str=f"2026-01-{(i % 28) + 1:02d}",
                open=100.0, high=h, low=l, close=100.0,
                volume=1000,
            ))
        session.commit()


class TestG1GuardPerSide:
    """bd:features-2026-09 iter 7 — G1 is now per-side, NOT whole-symbol
    (13-tara-g1-guard-revision.md §2.2 truth table). Each test below is one
    row of that truth table. All use _insert_swing_bars, which produces
    exactly one support candidate (price 70.0) and one resistance candidate
    (price 130.0) against close=100.0 — real fractal data, not flat bars
    (flat bars produce zero rows regardless of G1 and would not be
    load-bearing here, per the spec's DoD §5.1)."""

    def test_no_manual_both_sides_auto_write(self, sync_sqlite_engine):
        """Truth table row 1: no manual on either side -> both sides auto."""
        engine = sync_sqlite_engine
        _insert_swing_bars(engine, "AAPL")

        result = compute_auto_pivots()

        Session = sessionmaker(bind=engine)
        with Session() as session:
            auto_rows = session.execute(
                select(SRLevel).where(SRLevel.symbol == "AAPL", SRLevel.source == "auto_pivot")
            ).scalars().all()
        by_type = {r.level_type: r.price for r in auto_rows}

        assert by_type.get("support") == 70.0
        assert by_type.get("resistance") == 130.0
        assert result["rows_written"] == 2
        assert result["symbols_skipped"] == 0

    def test_manual_support_only_blocks_support_side_only(self, sync_sqlite_engine):
        """Truth table row 2: manual support present -> auto support NOT
        written, auto resistance IS written."""
        engine = sync_sqlite_engine
        _insert_swing_bars(engine, "AAPL")

        Session = sessionmaker(bind=engine)
        with Session() as session:
            session.add(SRLevel(symbol="AAPL", price=150.0, level_type="support", source="manual_import"))
            session.commit()

        result = compute_auto_pivots()

        with Session() as session:
            auto_rows = session.execute(
                select(SRLevel).where(SRLevel.symbol == "AAPL", SRLevel.source == "auto_pivot")
            ).scalars().all()
        by_type = {r.level_type: r.price for r in auto_rows}

        assert "support" not in by_type
        assert by_type.get("resistance") == 130.0
        assert result["rows_written"] == 1
        assert result["symbols_skipped"] == 0

    def test_manual_resistance_only_blocks_resistance_side_only(self, sync_sqlite_engine):
        """Truth table row 3: manual resistance present -> auto resistance
        NOT written, auto support IS written."""
        engine = sync_sqlite_engine
        _insert_swing_bars(engine, "AAPL")

        Session = sessionmaker(bind=engine)
        with Session() as session:
            session.add(SRLevel(symbol="AAPL", price=250.0, level_type="resistance", source="manual_import"))
            session.commit()

        result = compute_auto_pivots()

        with Session() as session:
            auto_rows = session.execute(
                select(SRLevel).where(SRLevel.symbol == "AAPL", SRLevel.source == "auto_pivot")
            ).scalars().all()
        by_type = {r.level_type: r.price for r in auto_rows}

        assert by_type.get("support") == 70.0
        assert "resistance" not in by_type
        assert result["rows_written"] == 1
        assert result["symbols_skipped"] == 0

    def test_manual_both_sides_blocks_all_auto_writes(self, sync_sqlite_engine):
        """Truth table row 4: manual on both sides -> zero auto rows
        written this run, but the task does NOT skip the symbol (G1 is not
        a skip anymore — DELETE still ran, rows_written == 0 is a real,
        counted outcome, not a guard-skip)."""
        engine = sync_sqlite_engine
        _insert_swing_bars(engine, "AAPL")

        Session = sessionmaker(bind=engine)
        with Session() as session:
            session.add_all([
                SRLevel(symbol="AAPL", price=150.0, level_type="support", source="manual_import"),
                SRLevel(symbol="AAPL", price=250.0, level_type="resistance", source="manual_import"),
            ])
            session.commit()

        result = compute_auto_pivots()

        with Session() as session:
            auto_rows = session.execute(
                select(SRLevel).where(SRLevel.symbol == "AAPL", SRLevel.source == "auto_pivot")
            ).scalars().all()

        assert auto_rows == []
        assert result["rows_written"] == 0
        assert result["symbols_skipped"] == 0

    def test_stale_auto_support_removed_when_manual_support_added(self, sync_sqlite_engine):
        """13-tara-g1-guard-revision.md §3 case B — this is the bug the
        revision fixes: an auto_pivot support row from a PREVIOUS run must
        be deleted this run once the user has since added a manual_import
        support row, even though auto no longer writes that side itself."""
        engine = sync_sqlite_engine
        _insert_swing_bars(engine, "AAPL")

        Session = sessionmaker(bind=engine)
        with Session() as session:
            # Simulate a stale row left over from a run before the manual
            # import existed.
            session.add(SRLevel(symbol="AAPL", price=65.0, level_type="support", source="auto_pivot"))
            session.commit()

        with Session() as session:
            session.add(SRLevel(symbol="AAPL", price=150.0, level_type="support", source="manual_import"))
            session.commit()

        result = compute_auto_pivots()

        with Session() as session:
            auto_rows = session.execute(
                select(SRLevel).where(SRLevel.symbol == "AAPL", SRLevel.source == "auto_pivot")
            ).scalars().all()
        by_type = {r.level_type: r.price for r in auto_rows}

        assert "support" not in by_type   # stale 65.0 row must be GONE, not left behind
        assert by_type.get("resistance") == 130.0
        assert result["rows_written"] == 1

class TestG2G3Guards:
    """bd:features-2026-09 iter5 — Chris review M1
    (10-chris-crypto-autopivot-review.md): G2/G3 previously had zero test
    coverage (mutation-confirmed: deleting either guard's `if`/`return None`
    left all 25 pre-existing tests green). Both tests below are proven
    load-bearing the same way G1/DELETE-scope were: temporarily delete the
    guard, watch the test fail, restore, confirm green."""

    def test_insufficient_bars_skips_symbol(self, sync_sqlite_engine):
        """G2 — fewer than MIN_BARS (60) daily bars -> skip, no rows written."""
        engine = sync_sqlite_engine
        _insert_bars(engine, "AAPL", n=59)  # MIN_BARS - 1

        result = compute_auto_pivots()

        assert result["symbols_skipped"] == 1
        assert result["rows_written"] == 0

    def test_exactly_min_bars_does_not_trigger_g2(self, sync_sqlite_engine):
        """Boundary check: exactly MIN_BARS bars must NOT be skipped by G2
        (only < MIN_BARS should trigger it) — flat bars produce 0 fractals
        so rows_written is legitimately 0 here, but symbols_skipped must
        also be 0 (this symbol was evaluated, not guard-skipped)."""
        engine = sync_sqlite_engine
        _insert_bars(engine, "AAPL", n=60)  # exactly MIN_BARS

        result = compute_auto_pivots()

        assert result["symbols_skipped"] == 0

    # NOTE: no test_null_close_skips_symbol here. `ohlcv_bars.close` is
    # `Column(Float, nullable=False)` (models/ohlcv.py:33) — a NULL close
    # cannot exist in a real table under this schema (DB-level NOT NULL,
    # not just an ORM-side check), so a test that tries to insert one would
    # either be rejected by the DB (proving nothing about the guard) or
    # require bypassing the schema entirely (a fake scenario — anti-puppet).
    # The `close is None` half of G3's condition is defensive-only against
    # non-ORM data paths this codebase doesn't have; the `close <= 0` half
    # below IS constructible against the real schema and is what's tested.

    def test_zero_close_skips_symbol(self, sync_sqlite_engine):
        """G3 — last bar's close is 0 (not just negative) -> skip."""
        engine = sync_sqlite_engine
        Session = sessionmaker(bind=engine)
        from models.ohlcv import OHLCVBar

        with Session() as session:
            for i in range(61):
                is_last = i == 60
                session.add(OHLCVBar(
                    symbol="AAPL", timeframe="1D", time_unix=i,
                    time_str=f"2026-01-{(i % 28) + 1:02d}",
                    open=100.0, high=101.0, low=99.0,
                    close=0.0 if is_last else 100.0,
                    volume=1000,
                ))
            session.commit()

        result = compute_auto_pivots()

        assert result["symbols_skipped"] == 1
        assert result["rows_written"] == 0

    def test_negative_close_skips_symbol(self, sync_sqlite_engine):
        """G3 — last bar's close is negative -> skip."""
        engine = sync_sqlite_engine
        Session = sessionmaker(bind=engine)
        from models.ohlcv import OHLCVBar

        with Session() as session:
            for i in range(61):
                is_last = i == 60
                session.add(OHLCVBar(
                    symbol="AAPL", timeframe="1D", time_unix=i,
                    time_str=f"2026-01-{(i % 28) + 1:02d}",
                    open=100.0, high=101.0, low=99.0,
                    close=-5.0 if is_last else 100.0,
                    volume=1000,
                ))
            session.commit()

        result = compute_auto_pivots()

        assert result["symbols_skipped"] == 1
        assert result["rows_written"] == 0


class TestDeleteScopedToAutoPivotOnly:
    def test_g1_per_side_still_deletes_stale_auto_but_spares_manual_and_user_created(self, sync_sqlite_engine):
        """bd:features-2026-09 iter7 — 13-tara-g1-guard-revision.md §3 case D.
        This test previously (iter5, whole-symbol G1) asserted the OPPOSITE:
        that a stale auto_pivot row survives untouched when manual_import
        exists, because G1 used to `return None` before the DELETE ever ran
        (Chris review M3, now superseded). Per-side G1 removed that
        early-return entirely — DELETE always runs. Bars here are flat ->
        classify_and_select produces 0 candidate rows regardless of any
        side-filtering, which isolates the DELETE-runs-unconditionally
        behavior on its own: the stale auto_pivot row must now be GONE,
        while manual_import/user_created must still survive (DELETE stays
        scoped to source='auto_pivot')."""
        engine = sync_sqlite_engine
        _insert_bars(engine, "AAPL", n=61)

        Session = sessionmaker(bind=engine)
        with Session() as session:
            session.add_all([
                SRLevel(symbol="AAPL", price=150.0, level_type="support", source="manual_import"),
                SRLevel(symbol="AAPL", price=250.0, level_type="resistance", source="user_created"),
                SRLevel(symbol="AAPL", price=140.0, level_type="support", source="auto_pivot"),
            ])
            session.commit()

        compute_auto_pivots()

        with Session() as session:
            rows = session.execute(select(SRLevel).where(SRLevel.symbol == "AAPL")).scalars().all()
            by_source_price = [(r.source, r.price) for r in rows if r.source == "auto_pivot"]
            by_source = {r.source: r.price for r in rows if r.source != "auto_pivot"}

        # Stale auto_pivot row must be gone — DELETE ran even though every
        # side happens to be manual-blocked / flat-produces-nothing here.
        assert by_source_price == []
        # manual_import/user_created must survive regardless (R0-guard).
        assert by_source["manual_import"] == 150.0
        assert by_source["user_created"] == 250.0

    def test_rerun_is_idempotent_only_auto_pivot_rows_replaced(self, sync_sqlite_engine, monkeypatch):
        """**This is the test that proves the DELETE WHERE-scope R0 guard
        under normal (rows-actually-produced) conditions** — complementary
        to the sibling test above, which proves the DELETE runs even when
        every produced row happens to be filtered out. No manual_import row
        this time — auto_pivot IS computed and replaced on rerun, without
        disturbing a user_created row for the same symbol."""
        engine = sync_sqlite_engine

        # Build bars with a real, confirmable swing so rows actually get
        # written (not flat bars).
        Session = sessionmaker(bind=engine)
        from models.ohlcv import OHLCVBar
        highs = [100.0] * 30 + [120.0] + [100.0] * 30
        lows = [h - 2 for h in highs]
        with Session() as session:
            for i, (h, l) in enumerate(zip(highs, lows)):
                session.add(OHLCVBar(
                    symbol="NVDA", timeframe="1D", time_unix=i,
                    time_str=f"2026-01-{(i % 28) + 1:02d}",
                    open=h, high=h, low=l, close=(h + l) / 2,
                    volume=1000,
                ))
            session.add(SRLevel(symbol="NVDA", price=999.0, level_type="resistance", source="user_created"))
            session.commit()

        monkeypatch.setattr(
            "workers.sr_auto_pivot.get_watched_symbols", lambda fallback=None: ["NVDA"]
        )

        compute_auto_pivots()
        with Session() as session:
            first_run_auto = session.execute(
                select(SRLevel).where(SRLevel.symbol == "NVDA", SRLevel.source == "auto_pivot")
            ).scalars().all()

        compute_auto_pivots()
        with Session() as session:
            second_run_auto = session.execute(
                select(SRLevel).where(SRLevel.symbol == "NVDA", SRLevel.source == "auto_pivot")
            ).scalars().all()
            user_created_row = session.execute(
                select(SRLevel).where(SRLevel.symbol == "NVDA", SRLevel.source == "user_created")
            ).scalars().all()

        assert len(first_run_auto) == len(second_run_auto)
        assert len(user_created_row) == 1
        assert user_created_row[0].price == 999.0  # untouched across both runs
