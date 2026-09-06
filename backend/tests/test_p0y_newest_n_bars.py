"""Tests for bd:shotockviz-p0y — `api/routes/screener.py::_fetch_symbol_bars`
(limit 300) and `services/stock_service.py::read_history`'s L2 query
(limit 500) used to `.order_by(time_unix.asc()).limit(N)`, which takes the
OLDEST N rows once a symbol has more than N total — freezing the screener/
chart window on a stale slice that ends ~(total-N) trading days in the
past and never advances as new bars are inserted. Fixed to
`.order_by(time_unix.desc()).limit(N)` + reverse, so the window is always
the most recent N bars in ascending (oldest->newest) order.
"""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.routes.screener import _fetch_symbol_bars
from core.database import Base
from models.ohlcv import OHLCVBar
from services import stock_service


def _seed_bars(n: int, symbol: str = "SEEDTEST"):
    """n daily bars, time_unix ascending, close == bar index (so the
    returned window's closes reveal exactly which bars survived)."""
    base = 1_700_000_000  # arbitrary epoch anchor, one day (86400s) apart
    return [
        OHLCVBar(
            symbol=symbol, timeframe="1D",
            time_unix=base + i * 86400,
            time_str=f"2026-01-{(i % 28) + 1:02d}",
            open=float(i), high=float(i), low=float(i), close=float(i),
            volume=1_000_000,
        )
        for i in range(n)
    ]


@pytest.fixture
async def sqlite_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
class TestScreenerFetchSymbolBarsTakesNewestWindow:
    async def test_over_limit_returns_newest_300_not_oldest_300(self, sqlite_engine):
        session_local = async_sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_local() as session:
            session.add_all(_seed_bars(350))  # 350 > 300 limit
            await session.commit()

        async with session_local() as session:
            bars = await _fetch_symbol_bars(session, "SEEDTEST")

        assert bars is not None
        assert len(bars) == 300
        closes = [b.close for b in bars]
        # Newest 300 of 0..349 is 50..349, in ascending (oldest->newest) order.
        assert closes == [float(i) for i in range(50, 350)]
        # The most-recent bar (349) — what closes[-1] feeds RSI/MACD/price
        # off of — must be present; the pre-fix bug would return 0..299
        # and never include it.
        assert closes[-1] == 349.0

    async def test_under_limit_returns_all_bars_unchanged(self, sqlite_engine):
        session_local = async_sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_local() as session:
            session.add_all(_seed_bars(100))
            await session.commit()

        async with session_local() as session:
            bars = await _fetch_symbol_bars(session, "SEEDTEST")

        assert bars is not None
        assert len(bars) == 100
        assert [b.close for b in bars] == [float(i) for i in range(100)]

    async def test_below_min_bars_returns_none(self, sqlite_engine):
        session_local = async_sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_local() as session:
            session.add_all(_seed_bars(10))  # < 30 minimum
            await session.commit()

        async with session_local() as session:
            bars = await _fetch_symbol_bars(session, "SEEDTEST")

        assert bars is None


@pytest.mark.asyncio
class TestReadHistoryL2TakesNewestWindow:
    async def test_over_limit_returns_newest_500_not_oldest_500(self, sqlite_engine, monkeypatch):
        session_local = async_sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_local() as session:
            session.add_all(_seed_bars(550, symbol="SEEDHIST"))  # 550 > 500 limit
            await session.commit()

        monkeypatch.setattr("services.stock_service.AsyncSessionLocal", session_local)
        # Force the Redis L1 lookup to miss so the L2 (PostgreSQL) path runs.
        monkeypatch.setattr(
            "services.stock_service.get_redis",
            AsyncMock(side_effect=Exception("no redis in this test")),
        )

        bars = await stock_service.read_history("SEEDHIST", "1D")

        assert len(bars) == 500
        closes = [b["close"] for b in bars]
        # Newest 500 of 0..549 is 50..549, ascending order.
        assert closes == [float(i) for i in range(50, 550)]
        assert closes[-1] == 549.0
