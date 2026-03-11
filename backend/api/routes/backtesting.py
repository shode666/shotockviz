"""Backtesting API routes — run strategy simulations on historical data."""
from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Any

from core.logger import get_logger
from core.redis import get_redis
from core import cache_keys
from models.user import User
from api.middleware.auth import get_current_user_optional

router = APIRouter(prefix="/api/backtest", tags=["backtesting"])
logger = get_logger(__name__)

AVAILABLE_STRATEGIES = {
    "golden_cross": {
        "name": "Golden Cross / Death Cross",
        "description": "Buy when SMA(20) crosses above SMA(50), sell on death cross",
        "params": {"fast_period": 20, "slow_period": 50},
    },
    "rsi_reversal": {
        "name": "RSI Reversal",
        "description": "Buy at oversold RSI(14) < 30, sell at overbought > 70",
        "params": {"period": 14, "oversold": 30, "overbought": 70},
    },
    "macd_crossover": {
        "name": "MACD Crossover",
        "description": "Buy on MACD bullish crossover, sell on bearish crossover",
        "params": {"fast": 12, "slow": 26, "signal": 9},
    },
    "bb_bounce": {
        "name": "Bollinger Band Bounce",
        "description": "Buy at lower Bollinger Band, sell at upper band",
        "params": {"period": 20, "std_dev": 2.0},
    },
}


class BacktestRequest(BaseModel):
    symbol: str
    strategy_type: str
    params: dict[str, Any] | None = None
    period: str = "1y"  # 6m, 1y, 2y, 5y
    capital: float = 1_000_000


# ── GET /api/backtest/strategies ────────────────────────────────────────────

@router.get("/strategies")
async def list_strategies():
    """List available backtesting strategies with default parameters."""
    return {"strategies": AVAILABLE_STRATEGIES}


# ── POST /api/backtest/run ──────────────────────────────────────────────────

@router.post("/run")
async def run_backtest(
    body: BacktestRequest,
    user: User | None = Depends(get_current_user_optional),
):
    """Run a strategy backtest on historical data.

    Fetches OHLCV bars from cache/DB, runs the strategy engine,
    and returns performance metrics + trade list.
    """
    symbol = body.symbol.upper()
    strategy_type = body.strategy_type.lower()

    if strategy_type not in AVAILABLE_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy: {strategy_type}. Available: {list(AVAILABLE_STRATEGIES.keys())}",
        )

    # Map period string to yfinance period
    period_map = {"6m": "6mo", "1y": "1y", "2y": "2y", "5y": "5y"}
    yf_period = period_map.get(body.period, "1y")

    # Fetch historical bars
    bars = await _fetch_bars_for_backtest(symbol, yf_period)
    if not bars or len(bars) < 50:
        raise HTTPException(
            status_code=404,
            detail=f"Insufficient data for {symbol}. Need at least 50 bars, got {len(bars) if bars else 0}.",
        )

    # Merge user params with strategy defaults
    strategy_info = AVAILABLE_STRATEGIES[strategy_type]
    merged_params = {**strategy_info["params"]}
    if body.params:
        merged_params.update(body.params)

    # Run backtest
    from services.backtesting_engine import run_backtest as engine_run

    result = engine_run(
        symbol=symbol,
        bars=bars,
        strategy_type=strategy_type,
        params=merged_params,
        initial_capital=body.capital,
    )

    return {
        "symbol": result.symbol,
        "strategy": result.strategy,
        "strategy_name": strategy_info["name"],
        "params": merged_params,
        "period": body.period,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "initial_capital": result.initial_capital,
        "final_capital": result.final_capital,
        "total_return_pct": result.total_return_pct,
        "win_rate": result.win_rate,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "max_drawdown_pct": result.max_drawdown_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "avg_win_pct": result.avg_win_pct,
        "avg_loss_pct": result.avg_loss_pct,
        "profit_factor": result.profit_factor,
        "trades": result.trades[:100],  # cap at 100 trades in response
    }


async def _fetch_bars_for_backtest(symbol: str, period: str) -> list[dict]:
    """Fetch daily OHLCV bars for backtesting.

    Tries Redis cache first, then falls back to yfinance direct fetch.
    """
    r = await get_redis()

    # Try cache first (daily bars)
    cache_key = f"ohlcv:{symbol}:1D"
    cached = await r.get(cache_key)
    if cached:
        try:
            bars = json.loads(cached)
            if isinstance(bars, list) and len(bars) >= 50:
                return bars
        except json.JSONDecodeError:
            pass

    # Fallback: fetch from yfinance directly (async-safe via thread pool)
    import asyncio
    import concurrent.futures

    def _fetch_sync():
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval="1d")
        if hist is None or hist.empty:
            return []
        bars = []
        for idx, row in hist.iterrows():
            bars.append({
                "time": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row.get("Volume", 0)),
            })
        return bars

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        bars = await loop.run_in_executor(pool, _fetch_sync)

    return bars
