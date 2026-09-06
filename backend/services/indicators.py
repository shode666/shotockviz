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


def compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder smoothed RSI (computed from list of close prices).

    Returns None if there are fewer than `period + 1` closes.

    bd:shotockviz-kmi — sibling of bd:shotockviz-0x0 (compute_sma). This
    used to return 50.0 (dead-centre "Neutral") on insufficient data,
    which is indistinguishable from a genuinely neutral RSI — the
    screener's rsi_filter=="neutral" (30 <= rsi <= 70) and MACD-driven
    "Buy"/"Neutral" signal path (services/indicators._compute_signal, via
    api/routes/screener.py) would both silently accept a symbol whose RSI
    was never actually computed. Callers must treat None as "cannot
    evaluate" and exclude, never compare it as if it were a real value.
    """
    if len(closes) < period + 1:
        return None

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


def compute_sma(closes: list[float], period: int) -> float | None:
    """Simple moving average (SMA).

    Args:
        closes: List of closing prices
        period: Number of periods for SMA

    Returns:
        SMA value, or None if there are fewer than `period` closes.

        bd:shotockviz-0x0 — this used to return 0.0 on insufficient data,
        which is indistinguishable from "the SMA genuinely computed to
        0.0". api/routes/screener.py's price filter treated 0.0 as
        "no MA configured, pass everything", so a symbol that could not
        even compute MA200 silently passed the "close > MA200" filter for
        every symbol, always. An unevaluable indicator must say so
        (None), never a value a caller can mistake for a real one.
    """
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def compute_volume_ratio(volumes: list[float], lookback: int = 20) -> float | None:
    """Latest volume ÷ average volume over the preceding `lookback` bars.

    Same ratio the screener's Volume filter has always used (formerly
    inlined in `api/routes/screener.py::_evaluate_symbol`) and now also
    what `workers/alert_checker.py` compares a VOLUME_SPIKE alert's
    user-supplied multiplier against — one definition, one place it can
    drift from itself.

    Returns None if there are fewer than `lookback` volumes to average.

    bd:shotockviz-kmi — sibling of bd:shotockviz-0x0 (compute_sma). This
    used to fall back to `vol_avg = 1` on insufficient data, which made
    the "ratio" just the raw current volume — millions for any real
    symbol — satisfying both the screener's "> 2x Average" and "> 1.5x
    Average" filters every single time. Worse than the MA200 case (which
    at least failed toward zero): a caller must treat None as "cannot
    evaluate" and exclude, never compare it as if it were a real ratio.
    """
    if len(volumes) < lookback:
        return None
    vol_now = volumes[-1]
    vol_avg = sum(volumes[-lookback:]) / lookback
    return vol_now / vol_avg if vol_avg > 0 else 0.0
