"""Unit tests for scripts.import_sr_levels — bd:features-2026-09 slice 1.

Focus: the JSON-defect-stripping (per Oliver's confirmed tail-of-file evidence)
and the wipe-scoped-to-source='manual_import' re-import behavior.
"""
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.database import Base
from models.sr_level import SRLevel
from scripts.import_sr_levels import (
    ImportStats,
    import_rows,
    parse_sr_json,
    strip_json_defect,
    validate_and_flatten,
)

# ── strip_json_defect / parse_sr_json ────────────────────────────────────────

class TestStripJsonDefect:
    def test_strips_stray_quote_before_final_brace(self):
        # Mirrors the exact tail Oliver pasted from the real file:
        # ...,"color":"#a78bfa"}],"supportTags":["S1","S2","S3"],
        # "resistanceTags":["R1","R2","R3"]}"\n}
        raw = (
            '{"AAPL": {"lines": [{"tag": "S1", "price": 100.0, "type": "support", '
            '"color": "#a78bfa"}], "supportTags": ["S1"], "resistanceTags": []}"\n}'
        )
        fixed = strip_json_defect(raw)
        assert fixed == (
            '{"AAPL": {"lines": [{"tag": "S1", "price": 100.0, "type": "support", '
            '"color": "#a78bfa"}], "supportTags": ["S1"], "resistanceTags": []}\n}'
        )
        # and it must actually be valid JSON now
        json.loads(fixed)

    def test_noop_on_clean_input(self):
        raw = '{"AAPL": {"lines": [], "supportTags": [], "resistanceTags": []}}'
        assert strip_json_defect(raw) == raw

    def test_does_not_touch_interior_quotes(self):
        """A quote that's followed by real content (not just EOF) must survive."""
        raw = '{"AAPL": {"lines": [], "supportTags": [], "resistanceTags": []}, "MSFT": {}}'
        assert strip_json_defect(raw) == raw


class TestParseSrJson:
    def test_parses_clean_json_directly(self):
        raw = '{"AAPL": {"lines": [], "supportTags": [], "resistanceTags": []}}'
        assert parse_sr_json(raw) == {"AAPL": {"lines": [], "supportTags": [], "resistanceTags": []}}

    def test_recovers_from_known_trailing_defect(self):
        raw = (
            '{"AAPL": {"lines": [{"tag": "S1", "price": 100.0, "type": "support", '
            '"color": "#a78bfa"}], "supportTags": ["S1"], "resistanceTags": []}"\n}'
        )
        data = parse_sr_json(raw)
        assert data["AAPL"]["lines"][0]["price"] == 100.0

    def test_raises_clear_error_on_unrecoverable_garbage(self):
        with pytest.raises(ValueError, match="no known defect pattern matched"):
            parse_sr_json("{not json at all")

    def test_raises_clear_error_when_defect_fix_still_fails(self):
        # Ends the same way as the real defect but the rest of the document is
        # broken elsewhere — the targeted fix must not silently paper over it.
        with pytest.raises(ValueError, match="still failed to parse"):
            parse_sr_json('{"AAPL": {"lines": [,]}"\n}')


# ── validate_and_flatten ──────────────────────────────────────────────────────

class TestValidateAndFlatten:
    def test_valid_rows_flattened_without_pixel_coords(self):
        data = {
            "AAPL": {
                "lines": [
                    {
                        "tag": "S1", "price": 150.5, "type": "support", "color": "#a78bfa",
                        "startX": 1, "startY": 2, "endX": 3, "endY": 4,
                    },
                ],
                "supportTags": ["S1"],
                "resistanceTags": [],
            },
        }
        rows, stats = validate_and_flatten(data)
        assert stats.symbols_seen == 1
        assert stats.rows_valid == 1
        assert stats.rows_skipped == 0
        assert rows == [{
            "symbol": "AAPL",
            "price": 150.5,
            "level_type": "support",
            "tag": "S1",
            "color": "#a78bfa",
            "source": "manual_import",
        }]

    def test_skips_invalid_price_without_aborting_batch(self):
        data = {
            "AAPL": {"lines": [
                {"tag": "S1", "price": -5, "type": "support"},
                {"tag": "S2", "price": 100.0, "type": "support"},
            ]},
        }
        rows, stats = validate_and_flatten(data)
        assert stats.rows_valid == 1
        assert stats.rows_skipped == 1
        assert len(rows) == 1
        assert rows[0]["tag"] == "S2"

    def test_skips_invalid_type(self):
        data = {"AAPL": {"lines": [{"tag": "X", "price": 10.0, "type": "bogus"}]}}
        rows, stats = validate_and_flatten(data)
        assert rows == []
        assert stats.rows_skipped == 1
        assert "type invalid" in stats.skipped_examples[0]

    def test_skips_symbol_with_missing_lines(self):
        data = {"AAPL": {"supportTags": [], "resistanceTags": []}}
        rows, stats = validate_and_flatten(data)
        assert rows == []
        assert stats.symbols_seen == 1
        assert stats.rows_skipped == 1

    def test_non_dict_top_level_raises(self):
        with pytest.raises(ValueError, match="top-level JSON must be an object"):
            validate_and_flatten(["not", "a", "dict"])

    def test_empty_input(self):
        rows, stats = validate_and_flatten({})
        assert rows == []
        assert stats == ImportStats()


# ── import_rows — wipe scoped to source ──────────────────────────────────────

@pytest.fixture
async def sr_test_db(monkeypatch):
    """In-memory SQLite session, wired as the AsyncSessionLocal import_rows() uses."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("scripts.import_sr_levels.AsyncSessionLocal", session_local)

    yield session_local
    await engine.dispose()


class TestImportRowsWipeScopedToSource:
    async def test_wipe_only_touches_manual_import_source(self, sr_test_db):
        session_local = sr_test_db
        async with session_local() as session:
            session.add_all([
                SRLevel(symbol="AAPL", price=100.0, level_type="support", source="manual_import"),
                SRLevel(symbol="AAPL", price=200.0, level_type="resistance", source="auto_pivot"),
                SRLevel(symbol="AAPL", price=300.0, level_type="resistance", source="user_created"),
            ])
            await session.commit()

        await import_rows([
            {"symbol": "MSFT", "price": 400.0, "level_type": "support", "tag": None, "color": None,
             "source": "manual_import"},
        ])

        async with session_local() as session:
            rows = (await session.execute(select(SRLevel).order_by(SRLevel.source))).scalars().all()
            sources_present = sorted(r.source for r in rows)
            symbols_by_source = {r.source: r.symbol for r in rows}

        assert sources_present == ["auto_pivot", "manual_import", "user_created"]
        assert symbols_by_source["manual_import"] == "MSFT"  # old AAPL manual_import row is gone
        assert symbols_by_source["auto_pivot"] == "AAPL"      # untouched
        assert symbols_by_source["user_created"] == "AAPL"    # untouched

    async def test_rerun_is_idempotent(self, sr_test_db):
        session_local = sr_test_db
        row = {"symbol": "AAPL", "price": 100.0, "level_type": "support", "tag": "S1",
               "color": "#a78bfa", "source": "manual_import"}

        await import_rows([row])
        await import_rows([row])  # re-run with identical input

        async with session_local() as session:
            rows = (await session.execute(select(SRLevel))).scalars().all()

        assert len(rows) == 1
        assert rows[0].symbol == "AAPL"

    async def test_empty_rows_still_wipes(self, sr_test_db):
        session_local = sr_test_db
        async with session_local() as session:
            session.add(SRLevel(symbol="AAPL", price=100.0, level_type="support", source="manual_import"))
            await session.commit()

        await import_rows([])

        async with session_local() as session:
            rows = (await session.execute(select(SRLevel))).scalars().all()
        assert rows == []
