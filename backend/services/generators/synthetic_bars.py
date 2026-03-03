"""Synthetic intraday bar generator (L4 fallback).

Generates realistic intraday bars from daily OHLCV when external sources fail.
Uses deterministic Brownian bridge to ensure consistent results across repeated calls.
Useful for Thai stocks (.BK) with limited intraday availability.
"""
import math
import random
from datetime import datetime, timezone

from core.logger import get_logger
from models.schemas import OHLCVBar

logger = get_logger(__name__)


def generate_synthetic_intraday(
    daily_bars: list[OHLCVBar],
    timeframe: str,
    is_set: bool = False,
) -> list[OHLCVBar]:
    """Generate realistic synthetic intraday bars from daily OHLCV.

    Pure function. Uses a deterministic Brownian bridge: price starts at daily open,
    ends at daily close, stays within [low, high]. Volume follows a U-shaped
    distribution (higher at open and close) with small random noise.

    The RNG is seeded per-day with a deterministic value so results are
    consistent across repeated calls for the same symbol/timeframe.

    Args:
        daily_bars: Daily OHLCV bars (should be sorted ascending).
        timeframe:  One of "1m", "5m", "15m", "1h", "4h".
        is_set:     True for Thai SET stocks (uses SET trading hours UTC+7).

    Returns:
        list[OHLCVBar]: Synthetic intraday bars.
    """
    mpb_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
    mpb = mpb_map.get(timeframe, 5)

    # Trading sessions in minutes-from-local-midnight  (local = tz_offset from UTC)
    if is_set:
        # SET: 10:00–12:30  +  14:30–17:00  (Asia/Bangkok UTC+7)
        sessions = [(600, 750), (870, 1020)]
        tz_offset_sec = 7 * 3600
    else:
        # US equities: 09:30–16:00  (America/New_York approximated as UTC-5)
        sessions = [(570, 960)]
        tz_offset_sec = -5 * 3600

    rng = random.Random()
    result: list[OHLCVBar] = []

    # Limit to the most recent 100 daily bars for performance
    for day_bar in daily_bars[-100:]:
        # Determine UTC midnight for this trading day
        if isinstance(day_bar.time, str):
            try:
                dt = datetime.strptime(day_bar.time, "%Y-%m-%d")
                day_start_utc = int(datetime(dt.year, dt.month, dt.day,
                                             tzinfo=timezone.utc).timestamp())
            except Exception:
                continue
        else:
            ts_int = int(day_bar.time)
            dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
            day_start_utc = int(datetime(dt.year, dt.month, dt.day,
                                         tzinfo=timezone.utc).timestamp())

        # Deterministic seed: hash of day timestamp
        seed_val = day_start_utc ^ (hash(str(day_bar.open)) & 0xFFFF)
        rng.seed(seed_val)

        open_px  = float(day_bar.open)
        close_px = float(day_bar.close)
        high_px  = float(day_bar.high)
        low_px   = float(day_bar.low)
        total_vol = int(day_bar.volume or 0)
        px_range  = max(high_px - low_px, open_px * 0.005)

        # Collect bar start timestamps (UTC unix seconds)
        bar_times: list[int] = []
        for sess_start_min, sess_end_min in sessions:
            # Convert local-minute offsets to UTC unix seconds
            local_midnight_utc = day_start_utc - tz_offset_sec
            t = local_midnight_utc + sess_start_min * 60
            sess_end  = local_midnight_utc + sess_end_min * 60
            while t < sess_end:
                bar_times.append(t)
                t += mpb * 60

        n = len(bar_times)
        if n == 0:
            continue

        # ── Brownian bridge: open → close within [low, high] ────────────────
        volatility = px_range / max(n ** 0.5, 1) * 0.35
        prices = [open_px]
        for i in range(1, n + 1):
            remaining = n - i + 1
            drift = (close_px - prices[-1]) / remaining
            noise = rng.gauss(0, volatility)
            new_px = prices[-1] + drift + noise
            new_px = max(low_px * 0.9995, min(high_px * 1.0005, new_px))
            prices.append(new_px)

        # ── U-shaped volume distribution ─────────────────────────────────────
        vol_weights = []
        for i in range(n):
            t = i / max(n - 1, 1)
            w = 1.2 - math.cos(t * math.pi) + rng.uniform(0, 0.4)
            vol_weights.append(max(0.05, w))
        total_w = sum(vol_weights)

        # ── Build bars ───────────────────────────────────────────────────────
        for i, ts in enumerate(bar_times):
            b_open  = prices[i]
            b_close = prices[i + 1] if (i + 1) < len(prices) else prices[-1]
            spread  = abs(b_close - b_open) * 0.25 + volatility * 0.08
            b_high  = min(max(b_open, b_close) + abs(rng.gauss(0, spread)), high_px)
            b_low   = max(min(b_open, b_close) - abs(rng.gauss(0, spread)), low_px)
            b_vol   = int(total_vol * vol_weights[i] / total_w) if total_w > 0 else 0

            result.append(OHLCVBar(
                time=ts,
                open=round(b_open,  4),
                high=round(b_high,  4),
                low=round(b_low,    4),
                close=round(b_close,4),
                volume=b_vol,
            ))

    logger.info(
        "Generated synthetic intraday bars",
        timeframe=timeframe, bars=len(result), is_set=is_set,
    )
    return result
