"""Strategy backtesting engine.

Runs historical simulations of trading strategies against OHLCV data.
Supports: Golden Cross, RSI Reversal, MACD Crossover, Bollinger Bounce.

All computations are stateless — no database writes, pure math.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Trade:
    """A single backtest trade."""
    entry_date: str
    entry_price: float
    exit_date: str | None = None
    exit_price: float | None = None
    direction: str = "LONG"  # LONG or SHORT
    pnl: float = 0.0
    pnl_pct: float = 0.0
    reason: str = ""


@dataclass
class BacktestResult:
    """Complete backtest results."""
    symbol: str
    strategy: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    max_drawdown_pct: float
    sharpe_ratio: float | None
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float | None
    trades: list[dict] = field(default_factory=list)


def run_backtest(
    symbol: str,
    bars: list[dict],
    strategy_type: str,
    params: dict[str, Any] | None = None,
    initial_capital: float = 1_000_000,
) -> BacktestResult:
    """Run a backtest simulation.

    Args:
        symbol: Stock symbol
        bars: OHLCV bars sorted by time ascending
            [{time, open, high, low, close, volume}, ...]
        strategy_type: Strategy name (golden_cross, rsi_reversal, macd_crossover, bb_bounce)
        params: Strategy-specific parameters
        initial_capital: Starting capital

    Returns:
        BacktestResult with trade list and performance metrics
    """
    if not bars or len(bars) < 50:
        return _empty_result(symbol, strategy_type, initial_capital)

    params = params or {}

    # Dispatch to strategy
    strategies = {
        "golden_cross": _strategy_golden_cross,
        "rsi_reversal": _strategy_rsi_reversal,
        "macd_crossover": _strategy_macd_crossover,
        "bb_bounce": _strategy_bb_bounce,
    }

    strategy_fn = strategies.get(strategy_type)
    if not strategy_fn:
        return _empty_result(symbol, strategy_type, initial_capital)

    trades = strategy_fn(bars, params)
    return _compute_metrics(symbol, strategy_type, bars, trades, initial_capital)


# ── Strategy Implementations ──────────────────────────────────────────────


def _strategy_golden_cross(bars: list[dict], params: dict) -> list[Trade]:
    """Golden Cross: Buy when SMA(fast) crosses above SMA(slow)."""
    fast = params.get("fast_period", 20)
    slow = params.get("slow_period", 50)

    closes = [b["close"] for b in bars]
    sma_fast = _sma(closes, fast)
    sma_slow = _sma(closes, slow)

    trades = []
    in_trade = False
    entry_trade = None

    for i in range(slow, len(bars)):
        if sma_fast[i] is None or sma_slow[i] is None:
            continue

        prev_fast = sma_fast[i - 1] if sma_fast[i - 1] is not None else 0
        prev_slow = sma_slow[i - 1] if sma_slow[i - 1] is not None else 0

        # Golden cross: fast crosses above slow
        if not in_trade and prev_fast <= prev_slow and sma_fast[i] > sma_slow[i]:
            entry_trade = Trade(
                entry_date=str(bars[i]["time"]),
                entry_price=bars[i]["close"],
                reason="Golden Cross",
            )
            in_trade = True

        # Death cross: fast crosses below slow → exit
        elif in_trade and prev_fast >= prev_slow and sma_fast[i] < sma_slow[i]:
            entry_trade.exit_date = str(bars[i]["time"])
            entry_trade.exit_price = bars[i]["close"]
            entry_trade.pnl = entry_trade.exit_price - entry_trade.entry_price
            entry_trade.pnl_pct = (entry_trade.pnl / entry_trade.entry_price) * 100
            entry_trade.reason = "Death Cross exit"
            trades.append(entry_trade)
            in_trade = False

    # Close open trade at last bar
    if in_trade and entry_trade:
        entry_trade.exit_date = str(bars[-1]["time"])
        entry_trade.exit_price = bars[-1]["close"]
        entry_trade.pnl = entry_trade.exit_price - entry_trade.entry_price
        entry_trade.pnl_pct = (entry_trade.pnl / entry_trade.entry_price) * 100
        entry_trade.reason = "End of data"
        trades.append(entry_trade)

    return trades


def _strategy_rsi_reversal(bars: list[dict], params: dict) -> list[Trade]:
    """RSI Reversal: Buy when RSI crosses above oversold, sell when overbought."""
    period = params.get("period", 14)
    oversold = params.get("oversold", 30)
    overbought = params.get("overbought", 70)

    closes = [b["close"] for b in bars]
    rsi = _rsi(closes, period)

    trades = []
    in_trade = False
    entry_trade = None

    for i in range(period + 1, len(bars)):
        if rsi[i] is None or rsi[i - 1] is None:
            continue

        # Buy: RSI crosses above oversold level
        if not in_trade and rsi[i - 1] <= oversold and rsi[i] > oversold:
            entry_trade = Trade(
                entry_date=str(bars[i]["time"]),
                entry_price=bars[i]["close"],
                reason=f"RSI crosses above {oversold}",
            )
            in_trade = True

        # Sell: RSI crosses above overbought level
        elif in_trade and rsi[i] >= overbought:
            entry_trade.exit_date = str(bars[i]["time"])
            entry_trade.exit_price = bars[i]["close"]
            entry_trade.pnl = entry_trade.exit_price - entry_trade.entry_price
            entry_trade.pnl_pct = (entry_trade.pnl / entry_trade.entry_price) * 100
            entry_trade.reason = f"RSI overbought ({rsi[i]:.0f})"
            trades.append(entry_trade)
            in_trade = False

    if in_trade and entry_trade:
        entry_trade.exit_date = str(bars[-1]["time"])
        entry_trade.exit_price = bars[-1]["close"]
        entry_trade.pnl = entry_trade.exit_price - entry_trade.entry_price
        entry_trade.pnl_pct = (entry_trade.pnl / entry_trade.entry_price) * 100
        entry_trade.reason = "End of data"
        trades.append(entry_trade)

    return trades


def _strategy_macd_crossover(bars: list[dict], params: dict) -> list[Trade]:
    """MACD Crossover: Buy when MACD crosses above signal, sell on cross below."""
    fast = params.get("fast", 12)
    slow = params.get("slow", 26)
    signal_period = params.get("signal", 9)

    closes = [b["close"] for b in bars]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    macd = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd[i] = ema_fast[i] - ema_slow[i]

    signal = _ema([m if m is not None else 0 for m in macd], signal_period)

    trades = []
    in_trade = False
    entry_trade = None

    for i in range(slow + signal_period, len(bars)):
        if macd[i] is None or signal[i] is None or macd[i - 1] is None or signal[i - 1] is None:
            continue

        # Buy: MACD crosses above signal
        if not in_trade and macd[i - 1] <= signal[i - 1] and macd[i] > signal[i]:
            entry_trade = Trade(
                entry_date=str(bars[i]["time"]),
                entry_price=bars[i]["close"],
                reason="MACD bullish crossover",
            )
            in_trade = True

        # Sell: MACD crosses below signal
        elif in_trade and macd[i - 1] >= signal[i - 1] and macd[i] < signal[i]:
            entry_trade.exit_date = str(bars[i]["time"])
            entry_trade.exit_price = bars[i]["close"]
            entry_trade.pnl = entry_trade.exit_price - entry_trade.entry_price
            entry_trade.pnl_pct = (entry_trade.pnl / entry_trade.entry_price) * 100
            entry_trade.reason = "MACD bearish crossover"
            trades.append(entry_trade)
            in_trade = False

    if in_trade and entry_trade:
        entry_trade.exit_date = str(bars[-1]["time"])
        entry_trade.exit_price = bars[-1]["close"]
        entry_trade.pnl = entry_trade.exit_price - entry_trade.entry_price
        entry_trade.pnl_pct = (entry_trade.pnl / entry_trade.entry_price) * 100
        entry_trade.reason = "End of data"
        trades.append(entry_trade)

    return trades


def _strategy_bb_bounce(bars: list[dict], params: dict) -> list[Trade]:
    """Bollinger Band Bounce: Buy at lower band, sell at upper band."""
    period = params.get("period", 20)
    std_dev = params.get("std_dev", 2.0)

    closes = [b["close"] for b in bars]
    sma = _sma(closes, period)

    trades = []
    in_trade = False
    entry_trade = None

    for i in range(period, len(bars)):
        if sma[i] is None:
            continue

        # Calculate Bollinger Bands
        window = closes[i - period + 1:i + 1]
        mean = sum(window) / len(window)
        variance = sum((x - mean) ** 2 for x in window) / len(window)
        sd = math.sqrt(variance) if variance > 0 else 0

        upper = mean + std_dev * sd
        lower = mean - std_dev * sd

        # Buy: price touches lower band
        if not in_trade and bars[i]["close"] <= lower:
            entry_trade = Trade(
                entry_date=str(bars[i]["time"]),
                entry_price=bars[i]["close"],
                reason="Price at lower BB",
            )
            in_trade = True

        # Sell: price touches upper band or SMA (take profit)
        elif in_trade and bars[i]["close"] >= upper:
            entry_trade.exit_date = str(bars[i]["time"])
            entry_trade.exit_price = bars[i]["close"]
            entry_trade.pnl = entry_trade.exit_price - entry_trade.entry_price
            entry_trade.pnl_pct = (entry_trade.pnl / entry_trade.entry_price) * 100
            entry_trade.reason = "Price at upper BB"
            trades.append(entry_trade)
            in_trade = False

    if in_trade and entry_trade:
        entry_trade.exit_date = str(bars[-1]["time"])
        entry_trade.exit_price = bars[-1]["close"]
        entry_trade.pnl = entry_trade.exit_price - entry_trade.entry_price
        entry_trade.pnl_pct = (entry_trade.pnl / entry_trade.entry_price) * 100
        entry_trade.reason = "End of data"
        trades.append(entry_trade)

    return trades


# ── Indicator Helpers ─────────────────────────────────────────────────────


def _sma(values: list[float], period: int) -> list[float | None]:
    result = [None] * len(values)
    for i in range(period - 1, len(values)):
        result[i] = sum(values[i - period + 1:i + 1]) / period
    return result


def _ema(values: list[float], period: int) -> list[float | None]:
    result = [None] * len(values)
    if len(values) < period:
        return result
    k = 2 / (period + 1)
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = values[i] * k + (result[i - 1] or 0) * (1 - k)
    return result


def _rsi(values: list[float], period: int) -> list[float | None]:
    result = [None] * len(values)
    if len(values) < period + 1:
        return result

    gains = []
    losses = []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        result[period] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            result[i + 1] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    return result


# ── Metrics Computation ───────────────────────────────────────────────────


def _compute_metrics(
    symbol: str,
    strategy: str,
    bars: list[dict],
    trades: list[Trade],
    initial_capital: float,
) -> BacktestResult:
    """Compute performance metrics from trade list."""
    if not trades:
        return _empty_result(symbol, strategy, initial_capital)

    # P&L
    total_pnl = sum(t.pnl for t in trades)
    winning = [t for t in trades if t.pnl > 0]
    losing = [t for t in trades if t.pnl <= 0]

    win_rate = len(winning) / len(trades) * 100 if trades else 0

    avg_win = sum(t.pnl_pct for t in winning) / len(winning) if winning else 0
    avg_loss = sum(t.pnl_pct for t in losing) / len(losing) if losing else 0

    gross_profit = sum(t.pnl for t in winning)
    gross_loss = abs(sum(t.pnl for t in losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    # Equity curve for drawdown + Sharpe
    equity = initial_capital
    equity_curve = [initial_capital]
    returns = []

    for t in trades:
        position_size = equity  # all-in for simplicity
        pnl = position_size * (t.pnl_pct / 100)
        equity += pnl
        equity_curve.append(equity)
        returns.append(t.pnl_pct / 100)

    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Sharpe ratio (annualized, assuming ~252 trading days)
    sharpe = None
    if len(returns) >= 2:
        mean_ret = sum(returns) / len(returns)
        var_ret = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
        std_ret = math.sqrt(var_ret) if var_ret > 0 else 0
        if std_ret > 0:
            sharpe = round((mean_ret / std_ret) * math.sqrt(min(len(returns), 252)), 2)

    return BacktestResult(
        symbol=symbol,
        strategy=strategy,
        start_date=str(bars[0]["time"]) if bars else "",
        end_date=str(bars[-1]["time"]) if bars else "",
        initial_capital=initial_capital,
        final_capital=round(equity, 2),
        total_return_pct=round((equity - initial_capital) / initial_capital * 100, 2),
        win_rate=round(win_rate, 1),
        total_trades=len(trades),
        winning_trades=len(winning),
        losing_trades=len(losing),
        max_drawdown_pct=round(max_dd, 2),
        sharpe_ratio=sharpe,
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
        trades=[
            {
                "entry_date": t.entry_date,
                "entry_price": round(t.entry_price, 2),
                "exit_date": t.exit_date,
                "exit_price": round(t.exit_price, 2) if t.exit_price else None,
                "pnl": round(t.pnl, 2),
                "pnl_pct": round(t.pnl_pct, 2),
                "reason": t.reason,
            }
            for t in trades
        ],
    )


def _empty_result(symbol: str, strategy: str, capital: float) -> BacktestResult:
    return BacktestResult(
        symbol=symbol,
        strategy=strategy,
        start_date="",
        end_date="",
        initial_capital=capital,
        final_capital=capital,
        total_return_pct=0,
        win_rate=0,
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        max_drawdown_pct=0,
        sharpe_ratio=None,
        avg_win_pct=0,
        avg_loss_pct=0,
        profit_factor=None,
        trades=[],
    )
