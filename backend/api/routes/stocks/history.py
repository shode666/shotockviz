"""bd:deps-2026-09 WP-B5 — split from backend/api/routes/stocks.py (§2.1).
Pure file move: `GET /{symbol}/history`, `GET /{symbol}/rs`.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.middleware.auth import get_optional_user
from models.schemas import StockHistory
from models.user import User
from services import stock_service

from ._shared import VALID_TIMEFRAMES, _is_yahoo_fetchable
from schemas.envelope import EnvelopingAPIRoute

# bd:deps-2026-09 S2 — route_class = envelope wrap (ADR-002); prefix comes
# from the parent (stocks/__init__.py, lifted /api/stocks -> /stocks).
router = APIRouter(route_class=EnvelopingAPIRoute)


@router.get("/{symbol}/history", response_model=StockHistory)
async def get_history(
    symbol: str,
    timeframe: str = Query("1D", description="Timeframe: 1m,5m,15m,1h,4h,1D,1W,1M"),
    adjusted: bool = Query(False, description="Apply dividend/split adjustments"),
    _user: User | None = Depends(get_optional_user),
):
    """Get OHLCV history for a symbol and timeframe — pure-read.

    Pure-read: reads from Redis/PostgreSQL ONLY. Never calls external APIs.
    Fast-response: reads cache first (< 100ms).
    If data missing, requests background fetch and returns empty bars.
    Client gets WS 'data_ready' notification when bars are available.

    V2: Pass `adjusted=true` to apply dividend/split price adjustments.
    """
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timeframe. Choose from: {', '.join(VALID_TIMEFRAMES)}",
        )
    sym = symbol.upper()

    # Pure-read: Redis → PostgreSQL only
    bars = await stock_service.read_history(sym, timeframe)

    # Detect Thai mutual funds that have no chart data on Yahoo Finance
    is_fund = not _is_yahoo_fetchable(sym)

    if not bars and not is_fund:
        # No data — request background fetch with timeframe
        await stock_service.request_data_fetch(sym, "history", timeframe=timeframe)

    # V2: Apply corporate action adjustments if requested
    if adjusted and bars:
        from services.price_adjuster import adjust_prices
        bars = await adjust_prices(sym, bars)

    return StockHistory(symbol=sym, timeframe=timeframe, bars=bars, is_fund=is_fund)


@router.get("/{symbol}/rs")
async def get_relative_strength(
    symbol: str,
    benchmark: str = Query("^SET.BK", description="Benchmark index symbol"),
    timeframe: str = Query("1D", description="Timeframe for RS calculation"),
    period: int = Query(252, description="Lookback period in bars (252 = ~1 year daily)"),
    _user: User | None = Depends(get_optional_user),
):
    """Get Relative Strength (RS) line data for a symbol vs benchmark.

    RS measures whether a stock is outperforming or underperforming its benchmark.
    RS > 1.0 = outperforming, RS < 1.0 = underperforming.

    Calculation:
      RS = (symbol_close / symbol_close_N_ago) / (benchmark_close / benchmark_close_N_ago)

    Returns list of {time, value} points for charting as a separate panel.
    """
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timeframe. Choose from: {', '.join(VALID_TIMEFRAMES)}",
        )

    sym = symbol.upper()
    bench = benchmark.upper()

    # Read both symbol and benchmark history from cache
    symbol_bars = await stock_service.read_history(sym, timeframe)
    bench_bars = await stock_service.read_history(bench, timeframe)

    # Request background fetch if missing
    if not symbol_bars:
        await stock_service.request_data_fetch(sym, "history", timeframe=timeframe)
    if not bench_bars:
        await stock_service.request_data_fetch(bench, "history", timeframe=timeframe)

    if not symbol_bars or not bench_bars:
        return {"symbol": sym, "benchmark": bench, "timeframe": timeframe, "rs": []}

    # Build close price lookup for benchmark (time → close)
    bench_map = {}
    for b in bench_bars:
        bench_map[b.get("time") if isinstance(b, dict) else b.time] = (
            float(b.get("close") if isinstance(b, dict) else b.close)
        )

    # Calculate RS line
    rs_data = []
    lookback = min(period, len(symbol_bars))

    for i in range(lookback, len(symbol_bars)):
        bar = symbol_bars[i]
        bar_time = bar.get("time") if isinstance(bar, dict) else bar.time
        bar_close = float(bar.get("close") if isinstance(bar, dict) else bar.close)

        ref_bar = symbol_bars[i - lookback]
        ref_close = float(ref_bar.get("close") if isinstance(ref_bar, dict) else ref_bar.close)

        # Find matching benchmark bars
        bench_close = bench_map.get(bar_time)
        ref_time = ref_bar.get("time") if isinstance(ref_bar, dict) else ref_bar.time
        bench_ref_close = bench_map.get(ref_time)

        if bench_close and bench_ref_close and ref_close > 0 and bench_ref_close > 0:
            symbol_return = bar_close / ref_close
            bench_return = bench_close / bench_ref_close
            rs_value = symbol_return / bench_return if bench_return > 0 else 1.0

            rs_data.append({"time": bar_time, "value": round(rs_value, 4)})

    return {
        "symbol": sym,
        "benchmark": bench,
        "timeframe": timeframe,
        "period": lookback,
        "rs": rs_data,
    }
