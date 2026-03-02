"""Seed historical OHLCV data into PostgreSQL.

Run once to backfill years of daily data for all tracked stocks.
Subsequent new bars are added automatically by the daily Celery task.

Data source priority per symbol:
  • Yahoo Finance (query2 + cookie/crumb auth) — SET + US
  • Stooq fallback (stooq.com) — US stocks only, when Yahoo is rate-limited

Usage (inside backend container):
    python -m scripts.seed_history
    python -m scripts.seed_history --symbols PTT.BK ADVANC.BK AAPL --timeframes 1D 1W
    python -m scripts.seed_history --symbols ALL --timeframes 1D
"""
import asyncio
import argparse
import sys
import os

# Add backend root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import AsyncSessionLocal, engine, Base
from models.ohlcv import OHLCVBar as OHLCVBarModel
from services.stock_service import fetch_yahoo_bars, TF_CONFIG

# ── Default stock universe ────────────────────────────────────────────────────

SET_STOCKS = [
    "PTT.BK", "ADVANC.BK", "CPALL.BK", "KBANK.BK", "SCB.BK",
    "BBL.BK", "KTB.BK", "TRUE.BK", "DTAC.BK", "GULF.BK",
    "PTTEP.BK", "IRPC.BK", "TOP.BK", "BCP.BK", "BANPU.BK",
    "AOT.BK", "BEM.BK", "CPN.BK", "MINT.BK", "HMPRO.BK",
    "BDMS.BK", "BH.BK", "BCH.BK", "COM7.BK", "DOHOME.BK",
]

US_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "NVDA", "TSLA", "AMD", "INTC", "NFLX",
    "JPM", "BAC", "WMT", "V", "MA",
]

DEFAULT_SYMBOLS = SET_STOCKS + US_STOCKS

# Timeframes to seed (daily+ only — intraday refreshes too often to pre-seed)
DEFAULT_TIMEFRAMES = ["1D", "1W", "1M"]

# Longer periods for initial seed (more history than the default TF_CONFIG periods)
SEED_PERIOD = {
    "1D": "2y",   # 2 years daily — ~500 bars
    "1W": "5y",   # 5 years weekly — ~260 bars
    "1M": "10y",  # 10 years monthly — ~120 bars
}


async def upsert_bars(rows: list[dict]) -> int:
    """Bulk upsert rows into ohlcv_bars. Returns count inserted/updated."""
    if not rows:
        return 0
    async with AsyncSessionLocal() as session:
        stmt = pg_insert(OHLCVBarModel).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "time_unix"],
            set_={
                "time_str": stmt.excluded.time_str,
                "open":   stmt.excluded.open,
                "high":   stmt.excluded.high,
                "low":    stmt.excluded.low,
                "close":  stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return len(rows)


async def seed(symbols: list[str], timeframes: list[str], delay: float = 0.5) -> None:
    """Main seeder coroutine."""
    # Ensure table exists
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    total_symbols = len(symbols)
    total_bars = 0

    for idx, symbol in enumerate(symbols, 1):
        print(f"[{idx}/{total_symbols}] {symbol}")
        for tf in timeframes:
            period = SEED_PERIOD.get(tf)
            # fetch_yahoo_bars tries Yahoo Finance first, then Stooq fallback for US stocks
            rows = await fetch_yahoo_bars(symbol, tf, period=period)
            if rows:
                count = await upsert_bars(rows)
                total_bars += count
                source = "Yahoo" if symbol.endswith(".BK") else "Yahoo/Stooq"
                print(f"  ✓ {tf}: {count} bars saved ({source})")
            else:
                print(f"  - {tf}: no data (Yahoo rate-limited + no Stooq for .BK symbols)")
            # Small delay to avoid rate limiting
            await asyncio.sleep(delay)

    print(f"\n✅ Done — {total_bars} bars saved for {total_symbols} symbols")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed OHLCV history into TimescaleDB")
    parser.add_argument(
        "--symbols", nargs="+", default=["ALL"],
        help="Stock symbols (e.g. PTT.BK AAPL) or ALL for default universe"
    )
    parser.add_argument(
        "--timeframes", nargs="+", default=DEFAULT_TIMEFRAMES,
        choices=list(TF_CONFIG.keys()),
        help="Timeframes to seed"
    )
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="Delay between requests in seconds (default 0.5)"
    )
    args = parser.parse_args()

    symbols = DEFAULT_SYMBOLS if args.symbols == ["ALL"] else args.symbols

    print(f"🌱 Seeding {len(symbols)} symbols × {args.timeframes}")
    print(f"   Sources: Yahoo Finance (primary) + Stooq fallback (US stocks)")
    print(f"   Delay: {args.delay}s between requests\n")

    asyncio.run(seed(symbols, args.timeframes, args.delay))


if __name__ == "__main__":
    main()
