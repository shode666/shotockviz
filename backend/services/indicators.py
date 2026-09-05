"""Shared technical-indicator math — single source of truth.

Extracted bd:shotockviz-06e: the stock screener (`api/routes/screener.py`)
already had a working RSI/MACD/SMA implementation used to compute its
filter columns; `workers/alert_checker.py` needed the same math for
RSI/Golden-Cross/Death-Cross/Volume-Spike alerts. A second, independently
written copy of an indicator is exactly the class of bug this codebase
keeps producing (two numbers for "the same" RSI that quietly drift) — so
both callers import from here instead.

Pure functions, no I/O: price/volume lists in, numbers out.
"""
from __future__ import annotations


def compute_rsi(closes: list[float], period: int = 14) -> float:
    """Wilder smoothed RSI (computed from list of close prices)."""
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    # Simple moving average for the first calculation
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Smoothed EMA for the rest
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    rs = avg_gain / (avg_loss if avg_loss != 0 else 1e-9)
    return round(100 - 100 / (1 + rs), 2)


def compute_macd(closes: list[float]) -> tuple[float, float]:
    """Returns (macd_val, signal_val) for the latest bar."""
    if len(closes) < 26:
        return 0.0, 0.0

    # EMA calculation helper
    def ema(data: list[float], span: int) -> list[float]:
        if len(data) < span:
            return [None] * len(data)
        result = []
        multiplier = 2 / (span + 1)
        result.append(sum(data[:span]) / span)  # SMA for first value
        for i in range(span, len(data)):
            result.append(data[i] * multiplier + result[-1] * (1 - multiplier))
        return result

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)

    # ema() returns len(data)-span+1 elements; align by using the shorter ema26
    # ema26 is shorter — offset into ema12 to align them
    offset = len(ema12) - len(ema26)
    macd_line = [ema12[offset + i] - ema26[i] for i in range(len(ema26))]

    # Signal line (EMA9 of MACD line)
    if len(macd_line) < 9:
        return 0.0, 0.0

    signal_line = ema(macd_line, 9)
    return float(macd_line[-1]), float(signal_line[-1] if signal_line else 0)


def compute_sma(closes: list[float], period: int) -> float:
    """Simple moving average (SMA).

    Args:
        closes: List of closing prices
        period: Number of periods for SMA

    Returns:
        SMA value, or 0.0 if insufficient data
    """
    if len(closes) < period:
        return 0.0
    return sum(closes[-period:]) / period


def compute_volume_ratio(volumes: list[float], lookback: int = 20) -> float:
    """Latest volume ÷ average volume over the preceding `lookback` bars.

    Same ratio the screener's Volume filter has always used (formerly
    inlined in `api/routes/screener.py::_evaluate_symbol`) and now also
    what `workers/alert_checker.py` compares a VOLUME_SPIKE alert's
    user-supplied multiplier against — one definition, one place it can
    drift from itself.
    """
    if not volumes:
        return 0.0
    vol_now = volumes[-1]
    vol_avg = sum(volumes[-lookback:]) / len(volumes[-lookback:]) if len(volumes) >= lookback else 1
    return vol_now / vol_avg if vol_avg > 0 else 0.0
