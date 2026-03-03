"""Stooq data provider for US stocks (fallback when Yahoo Finance is rate-limited).

Limitations:
- US stocks ONLY (symbol must not contain a dot, e.g. "AAPL", "NVDA")
- Daily / weekly / monthly only (no intraday)
- No API key required, no rate limits
"""
import csv
import io
from datetime import date, timedelta

import httpx

from core.logger import get_logger
from models.schemas import OHLCVBar

logger = get_logger(__name__)

# Stooq interval mapping (daily/weekly/monthly only)
_STOOQ_INTERVAL: dict[str, str] = {"1D": "d", "1W": "w", "1M": "m"}

# Approximate days for each period string (used to build stooq date range)
_PERIOD_TO_DAYS: dict[str, int] = {
    "1d": 2,    "2d": 3,    "5d": 7,    "7d": 9,
    "15d": 20,  "30d": 35,  "60d": 65,  "90d": 95,
    "120d": 125,"180d": 185,"1y": 370,  "2y": 740,
    "3y": 1100, "5y": 1830, "10y": 3660,
}


async def fetch_stooq_direct(
    symbol: str, period: str, timeframe: str
) -> list[OHLCVBar]:
    """Fetch historical OHLCV from stooq.com (free, no API key, no rate limits).

    Pure async function. Returns list of OHLCVBar objects.

    Limitations:
    - US stocks ONLY (symbol must not contain a dot, e.g. "AAPL", "NVDA")
    - Daily / weekly / monthly only (no intraday)

    Returns:
        list[OHLCVBar] on success, empty list on failure.
    """
    if "." in symbol:  # Thai (.BK) or other international — not supported
        return []
    if timeframe not in _STOOQ_INTERVAL:
        return []

    days = _PERIOD_TO_DAYS.get(period, 370)
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=days)

    url = "https://stooq.com/q/d/l/"
    params = {
        "s": f"{symbol.lower()}.us",
        "d1": start_dt.strftime("%Y%m%d"),
        "d2": end_dt.strftime("%Y%m%d"),
        "i": _STOOQ_INTERVAL[timeframe],
    }

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"}, timeout=httpx.Timeout(15.0, connect=5.0)
        ) as client:
            res = await client.get(url, params=params)
            if res.status_code != 200:
                return []

            text = res.text.strip()
            # Stooq returns "No data" or empty on failure
            if not text or len(text) < 30 or not text.startswith("Date"):
                return []

        reader = csv.DictReader(io.StringIO(text))
        bars: list[OHLCVBar] = []

        for row in reader:
            try:
                date_str = row.get("Date", "")
                o   = float(row.get("Open", 0) or 0)
                h   = float(row.get("High", 0) or 0)
                lo  = float(row.get("Low", 0) or 0)
                c   = float(row.get("Close", 0) or 0)
                v   = int(float(row.get("Volume", 0) or 0))
                if not date_str or not c:
                    continue
                bars.append(OHLCVBar(
                    time=date_str,  # stooq already returns "YYYY-MM-DD"
                    open=round(o, 4), high=round(h, 4),
                    low=round(lo, 4), close=round(c, 4),
                    volume=v,
                ))
            except (KeyError, TypeError, ValueError):
                continue

        # Sort ascending by time (stooq may return newest-first or already ascending)
        bars.sort(key=lambda b: b.time if isinstance(b.time, int) else str(b.time))
        logger.info("Stooq fetch OK", symbol=symbol, timeframe=timeframe, bars=len(bars))
        return bars

    except httpx.TimeoutException as e:
        logger.warning("Stooq fetch timed out", symbol=symbol, error=str(e))
        return []
    except Exception as e:
        logger.error("Stooq fetch error", symbol=symbol, error=str(e))
        return []
