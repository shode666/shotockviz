"""Database helpers — pure DB/transformation functions for OHLCV data.

Handles DB persistence and data format conversions.
No external API calls or cache logic — just storage operations.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.config import settings
from core.database import AsyncSessionLocal
from core.logger import get_logger
from models.schemas import OHLCVBar
from models.ohlcv import OHLCVBar as OHLCVBarModel

logger = get_logger(__name__)


async def _load_bars_from_db(symbol: str, timeframe: str) -> list[OHLCVBar]:
    """Async helper: load OHLCV bars from database."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OHLCVBarModel)
                .where(
                    OHLCVBarModel.symbol == symbol,
                    OHLCVBarModel.timeframe == timeframe,
                )
                .order_by(OHLCVBarModel.time_unix)
            )
            rows = result.scalars().all()
            if not rows:
                return []

            # Import here to avoid circular dependency
            from services.stock_service import DAILY_TIMEFRAMES
            return [
                OHLCVBar(
                    time=r.time_str if timeframe in DAILY_TIMEFRAMES else int(r.time_unix),
                    open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume,
                )
                for r in rows
            ]
    except Exception as e:
        logger.error("Failed to load from DB", symbol=symbol, timeframe=timeframe, error=str(e))
        return []


async def _save_bars_to_db(bars: list[OHLCVBar], symbol: str, timeframe: str) -> None:
    """Async helper: save OHLCV bars to database (upsert on conflict)."""
    if not bars:
        return
    rows = _bars_to_db_rows(bars, symbol, timeframe)
    try:
        async with AsyncSessionLocal() as session:
            stmt = pg_insert(OHLCVBarModel).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "timeframe", "time_unix"],
                set_={
                    "time_str": stmt.excluded.time_str,
                    "open":  stmt.excluded.open, "high": stmt.excluded.high,
                    "low":   stmt.excluded.low,  "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                },
            )
            await session.execute(stmt)
            await session.commit()
        logger.info("Saved OHLCV to DB", symbol=symbol, timeframe=timeframe, count=len(rows))
    except Exception as e:
        logger.error("Failed to save to DB", symbol=symbol, timeframe=timeframe, error=str(e))


def _bars_to_db_rows(bars: list[OHLCVBar], symbol: str, timeframe: str) -> list[dict]:
    """Convert OHLCVBar schema objects → DB row dicts for bulk upsert. Pure function."""
    rows = []
    for b in bars:
        t_str = str(b.time)
        t_unix = (
            int(b.time) if isinstance(b.time, (int, float))
            else int(datetime.strptime(t_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        )
        rows.append({
            "symbol":    symbol,
            "timeframe": timeframe,
            "time_unix": t_unix,
            "time_str":  t_str,
            "open":  b.open, "high": b.high,
            "low":   b.low,  "close": b.close,
            "volume": b.volume,
        })
    return rows


def _aggregate_4h(bars: list[OHLCVBar]) -> list[OHLCVBar]:
    """Aggregate 1-hour bars into 4-hour bars. Pure function."""
    result = []
    chunk: list[OHLCVBar] = []
    for bar in bars:
        chunk.append(bar)
        if len(chunk) == 4:
            result.append(OHLCVBar(
                time=chunk[0].time,
                open=chunk[0].open,
                high=max(b.high for b in chunk),
                low=min(b.low for b in chunk),
                close=chunk[-1].close,
                volume=sum(b.volume for b in chunk),
            ))
            chunk = []
    if chunk:
        result.append(OHLCVBar(
            time=chunk[0].time,
            open=chunk[0].open,
            high=max(b.high for b in chunk),
            low=min(b.low for b in chunk),
            close=chunk[-1].close,
            volume=sum(b.volume for b in chunk),
        ))
    return result
