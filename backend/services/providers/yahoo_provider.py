"""Yahoo Finance data provider — main facade.

Handles quote fetching and OHLCV history. Auth, search, and fundamentals
are split into separate modules (yahoo_auth, yahoo_search, yahoo_fundamentals).

Uses v8 chart API for quotes and history.
"""
import asyncio
from typing import Optional

import httpx

from core.logger import get_logger
from .yahoo_auth import _get_yf_auth, _get_http_sem, _YF_HEADERS
from .yahoo_search import search_yahoo_direct
from .yahoo_fundamentals import fetch_fundamentals_direct

# Re-export for backward compatibility
__all__ = [
    "fetch_quote_direct",
    "fetch_yahoo_direct",
    "search_yahoo_direct",
    "fetch_fundamentals_direct",
]

logger = get_logger(__name__)

# Map internal period string → Yahoo Finance range parameter
_YF_PERIOD_MAP: dict[str, str] = {
    "1d": "1d",   "2d": "5d",    "5d": "5d",    "7d": "5d",
    "15d": "1mo", "30d": "1mo",  "60d": "3mo",  "90d": "3mo",
    "120d": "6mo","180d": "6mo", "1y": "1y",    "2y": "2y",
    "3y": "5y",   "5y": "5y",    "10y": "10y",
}


async def fetch_quote_direct(symbol: str):
    """Fetch current quote from Yahoo Finance chart API (5-day daily range).

    Pure async function that calls Yahoo Finance v8 chart API.
    Returns StockQuote or None on failure.
    """
    from models.schemas import StockQuote
    from core import cache_keys
    from core.config import settings
    import redis.asyncio as aioredis

    cookies, crumb = await _get_yf_auth()

    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    params: dict = {
        "interval": "1d", "range": "5d",
        "includePrePost": "false",
        "corsDomain": "finance.yahoo.com",
    }
    if crumb:
        params["crumb"] = crumb

    try:
        async with _get_http_sem():   # cap concurrent YF calls → avoid 429
            async with httpx.AsyncClient(
                headers=_YF_HEADERS, cookies=cookies or None,
                timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=True,
            ) as client:
                res = await client.get(url, params=params)
                if res.status_code == 429:
                    logger.warning("Yahoo Finance rate-limited on quote", symbol=symbol)
                    return None
                if res.status_code != 200:
                    return None
                data = res.json()
    except httpx.TimeoutException as e:
        logger.warning("Quote fetch timed out", symbol=symbol, error=str(e))
        return None
    except Exception as e:
        logger.error("Quote fetch error", symbol=symbol, error=str(e))
        return None

    try:
        result = data.get("chart", {}).get("result")
        if not result:
            return None

        chart = result[0]
        meta = chart.get("meta", {})
        qd = chart["indicators"]["quote"][0]
        closes  = qd.get("close",  [])
        opens   = qd.get("open",   [])
        highs   = qd.get("high",   [])
        lows    = qd.get("low",    [])
        volumes = qd.get("volume", [])

        last_idx = next(
            (i for i in range(len(closes) - 1, -1, -1) if closes[i] is not None), -1
        )
        if last_idx == -1:
            return None

        def _safe(lst, idx, fb=None):
            try:
                v = lst[idx]
                return float(v) if v is not None else fb
            except (IndexError, TypeError):
                return fb

        price = round(float(meta.get("regularMarketPrice") or closes[last_idx]), 4)
        prev_close = round(
            float(meta.get("chartPreviousClose") or meta.get("previousClose") or price), 4
        )
        change = round(price - prev_close, 4)
        change_pct = round((change / prev_close * 100) if prev_close else 0, 2)

        quote = StockQuote(
            symbol=symbol,
            price=price,
            open=round(float(meta.get("regularMarketOpen") or _safe(opens, last_idx, price)), 4),
            high=round(float(meta.get("regularMarketDayHigh") or _safe(highs, last_idx, price)), 4),
            low=round(float(meta.get("regularMarketDayLow") or _safe(lows, last_idx, price)), 4),
            prev_close=prev_close,
            change=change,
            change_pct=change_pct,
            volume=int(meta.get("regularMarketVolume") or _safe(volumes, last_idx, 0) or 0),
        )

        # Cache the company short name so /api/stocks/names can resolve US tickers
        short_name = meta.get("shortName") or meta.get("longName") or ""
        if short_name:
            try:
                r = aioredis.from_url(settings.redis_url, decode_responses=True)
                await r.setex(cache_keys.name(symbol), 86400, short_name)  # 24 h TTL
            except Exception:
                pass

        return quote
    except Exception as e:
        logger.error("Quote parse error", symbol=symbol, error=str(e))
        return None




async def fetch_yahoo_direct(
    symbol: str, interval: str, period: str, timeframe: str
):
    """Fetch OHLCV from Yahoo Finance v8 chart API (query2 + cookie/crumb auth).

    Uses gmtoffset from the API response to convert timestamps to correct
    local trading dates (critical for Thai/Asian stocks).

    For Thai stocks (.BK symbols): uses 20s timeout and exponential backoff retry
    (3 attempts with [0, 2, 6] second delays). If fetch succeeds but returns 0 bars,
    tries alternative periods (3mo → 1mo → 5d) before giving up. If all fail but
    stale data exists in Redis, returns {"data": [...], "is_stale": true}.
    For US stocks: uses 6s timeout with no retry.

    Returns:
        list[OHLCVBar] if fresh data found
        dict with {"data": [...], "is_stale": true} if using stale cache
        [] if no data available
    """
    from datetime import datetime, timedelta, timezone
    from models.schemas import OHLCVBar

    is_bk_symbol = symbol.upper().endswith(".BK")

    # Thai stocks get slightly longer timeout but capped at 8s (was 20s) so that
    # fetch_quote_now()'s 7s hard cap can fire cleanly before Yahoo gives up.
    # US stocks stay at 5s — fast enough for live markets.
    base_timeout = 8.0 if is_bk_symbol else 5.0
    max_retries = 2 if is_bk_symbol else 1
    retry_delays = [0, 2] if is_bk_symbol else [0]  # reduced from [0, 2, 6]

    # Fallback periods for .BK symbols when initial period returns 0 bars
    fallback_periods = ["3mo", "1mo", "5d"] if is_bk_symbol else []

    cookies, crumb = await _get_yf_auth()
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"

    # For .BK symbols, maintain a list of periods to try in order
    periods_to_try = [period] + (fallback_periods if is_bk_symbol else [])
    bars_result = None

    for period_attempt, current_period in enumerate(periods_to_try):
        yf_range = _YF_PERIOD_MAP.get(current_period, current_period)
        data_received = False  # Track whether fresh data was received for this period

        for attempt in range(max_retries):
            try:
                # Apply backoff delay before retry (but not on first attempt)
                if attempt > 0:
                    delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                    if delay > 0:
                        logger.debug("Yahoo Finance retry backoff", symbol=symbol,
                                    attempt=attempt, delay=delay)
                        await asyncio.sleep(delay)

                params: dict = {
                    "interval": interval,
                    "range": yf_range,
                    "includePrePost": "false",
                    "events": "div,splits",
                    "corsDomain": "finance.yahoo.com",
                }
                if crumb:
                    params["crumb"] = crumb

                async with _get_http_sem():   # cap concurrent YF calls → avoid 429
                    async with httpx.AsyncClient(
                        headers=_YF_HEADERS,
                        cookies=cookies or None,
                        timeout=httpx.Timeout(base_timeout, connect=5.0),
                        follow_redirects=True,
                    ) as client:
                        res = await client.get(url, params=params)

                        # On 401 (expired crumb) — invalidate and retry once
                        if res.status_code == 401:
                            from .yahoo_auth import _yf_crumb as _orig_crumb, _yf_crumb_ts as _orig_ts
                            import services.providers.yahoo_auth as _yf_auth_module
                            _yf_auth_module._yf_crumb = ""
                            _yf_auth_module._yf_crumb_ts = 0.0
                            cookies, crumb = await _get_yf_auth()
                            if crumb:
                                params["crumb"] = crumb
                            res = await client.get(url, params=params)

                        # On 429 (rate limited) — log and return [] immediately.
                        if res.status_code == 429:
                            logger.warning("Yahoo Finance rate limited — giving up fast",
                                           symbol=symbol, attempt=attempt)
                            return []

                        if res.status_code != 200:
                            logger.warning(
                                "Yahoo Finance non-200",
                                symbol=symbol, status=res.status_code, attempt=attempt,
                            )
                            # For .BK symbols, retry on non-200 (except rate limit)
                            if is_bk_symbol and attempt < max_retries - 1:
                                continue
                            return []
                        data = res.json()
                        data_received = True  # Mark that we successfully received fresh data

                # Success — break out of retry loop (semaphore released above)
                logger.debug("Yahoo Finance fetch success", symbol=symbol,
                             attempt=attempt + 1)
                break

            except (asyncio.TimeoutError, httpx.TimeoutException) as e:
                # Timeout on .BK symbols — retry with backoff
                logger.warning("Yahoo Finance timeout", symbol=symbol,
                             attempt=attempt + 1, timeout=base_timeout)
                if is_bk_symbol and attempt < max_retries - 1:
                    continue
                logger.error("Yahoo Finance fetch error (timeout exhausted)",
                           symbol=symbol, error=str(e))
                return []
            except Exception as e:
                logger.error("Yahoo Finance fetch error", symbol=symbol,
                           attempt=attempt + 1, error=str(e))
                if is_bk_symbol and attempt < max_retries - 1:
                    continue
                return []

        # If we got fresh data from this period, parse and return it.
        # Otherwise continue to the next period (for .BK symbols).
        if data_received:
            try:
                logger.debug("Parsing Yahoo Finance response", symbol=symbol, period=current_period)
                chart_data = data.get("chart", {})
                if chart_data.get("error"):
                    logger.warning("Yahoo Finance API error", symbol=symbol, period=current_period,
                                   error=chart_data["error"])
                    if is_bk_symbol and period_attempt < len(periods_to_try) - 1:
                        logger.debug("Trying next period", symbol=symbol, current=current_period)
                    continue  # Try next period if available

                result = chart_data.get("result")
                if not result:
                    logger.debug("Yahoo Finance returned no result", symbol=symbol, period=current_period)
                    if is_bk_symbol and period_attempt < len(periods_to_try) - 1:
                        logger.debug("Trying next period", symbol=symbol, current=current_period)
                    continue  # Try next period if available

                chart = result[0]
                meta = chart.get("meta", {})
                timestamps = chart.get("timestamp", [])
                if not timestamps:
                    logger.debug("Yahoo Finance returned no timestamps", symbol=symbol, period=current_period)
                    if is_bk_symbol and period_attempt < len(periods_to_try) - 1:
                        logger.debug("Trying next period", symbol=symbol, current=current_period)
                    continue  # Try next period if available

                # Use exchange gmtoffset so Asian stocks (UTC+7) get correct local trading date.
                gmt_offset = timedelta(seconds=meta.get("gmtoffset", 0))

                quote_data = chart["indicators"]["quote"][0]
                opens   = quote_data.get("open",   [])
                highs   = quote_data.get("high",   [])
                lows    = quote_data.get("low",    [])
                closes  = quote_data.get("close",  [])
                volumes = quote_data.get("volume", [])

                # Need to import here to avoid circular imports
                from services.stock_service import DAILY_TIMEFRAMES

                use_date_str = timeframe in DAILY_TIMEFRAMES
                bars: list[OHLCVBar] = []

                for i, ts in enumerate(timestamps):
                    try:
                        o = opens[i]; h = highs[i]; lo = lows[i]; c = closes[i]
                        v = volumes[i] if i < len(volumes) else 0

                        if None in (o, h, lo, c):
                            continue

                        if use_date_str:
                            local_dt = datetime.fromtimestamp(ts, tz=timezone.utc) + gmt_offset
                            time_val: int | str = local_dt.strftime("%Y-%m-%d")
                        else:
                            time_val = int(ts)

                        bars.append(OHLCVBar(
                            time=time_val,
                            open=round(float(o), 4),
                            high=round(float(h), 4),
                            low=round(float(lo), 4),
                            close=round(float(c), 4),
                            volume=int(v or 0),
                        ))
                    except (IndexError, TypeError, ValueError):
                        continue

                if timeframe == "4h":
                    from services.stock_service import _aggregate_4h
                    bars = _aggregate_4h(bars)

                # Ensure ascending time order
                bars.sort(key=lambda b: b.time if isinstance(b.time, int) else str(b.time))

                # Success — return bars
                if bars:
                    logger.info("Yahoo Finance fetch OK", symbol=symbol, timeframe=timeframe,
                               period=current_period, bars=len(bars))
                    return bars
                else:
                    # Empty bars — try next period for .BK symbols
                    logger.warning("Yahoo Finance returned 0 bars from period",
                                symbol=symbol, period=current_period)
                    if is_bk_symbol and period_attempt < len(periods_to_try) - 1:
                        next_period = periods_to_try[period_attempt + 1]
                        logger.debug("Trying fallback period", symbol=symbol,
                                    current_period=current_period, next_period=next_period)
                    continue

            except (KeyError, IndexError, TypeError) as e:
                logger.error("Yahoo Finance parse error", symbol=symbol, error=str(e))
                continue  # Try next period if available

    # All periods exhausted with no data — return empty
    tried_periods = ", ".join(periods_to_try) if is_bk_symbol else periods_to_try[0]
    logger.error("Yahoo Finance all periods exhausted with no data", symbol=symbol,
                 periods_tried=tried_periods)
    return []
