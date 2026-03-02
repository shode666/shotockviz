"""Stock data fetching service.

Data flow for OHLCV history (4-layer cache):
  1. Redis  (L1, hot)  — short TTL, shared per symbol+timeframe
  2. PostgreSQL / TimescaleDB (L2, warm) — persistent, shared across users
  3. External source (L3) — called only when DB is empty:
       • Yahoo Finance v8 API (query2 + cookie/crumb auth)
       • Stooq fallback for US stocks (no rate limits, no API key)
  4. Synthetic intraday (L4) — generated from daily data when L3 fails
       • Deterministic Brownian bridge ensures consistent results
       • Useful for Thai stocks (.BK) with limited intraday availability

Yahoo Finance notes:
  • query1 is more aggressively rate-limited than query2
  • Cookie + crumb auth is required for v8 API to avoid 401/429
  • Thai stocks (.BK) require Yahoo Finance; no free alternative
  • US stocks fall back to Stooq (stooq.com) when Yahoo is rate-limited
"""
import asyncio
import csv
import io
import json
import math
import random
import time as _time
from datetime import datetime, timedelta, timezone, date
from typing import Optional

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.config import settings
from core.logger import get_logger
from core.database import AsyncSessionLocal
from models.schemas import StockQuote, OHLCVBar, StockFundamentals
from models.ohlcv import OHLCVBar as OHLCVBarModel

logger = get_logger(__name__)

_redis_client = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


# ── Yahoo Finance HTTP headers ────────────────────────────────────────────────
_YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://finance.yahoo.com/",
    "Origin": "https://finance.yahoo.com",
}

# Map internal period string → Yahoo Finance range parameter
_YF_PERIOD_MAP: dict[str, str] = {
    "1d": "1d",   "2d": "5d",    "5d": "5d",    "7d": "5d",
    "15d": "1mo", "30d": "1mo",  "60d": "3mo",  "90d": "3mo",
    "120d": "6mo","180d": "6mo", "1y": "1y",    "2y": "2y",
    "3y": "5y",   "5y": "5y",    "10y": "10y",
}

# Stooq interval mapping (daily/weekly/monthly only)
_STOOQ_INTERVAL: dict[str, str] = {"1D": "d", "1W": "w", "1M": "m"}

# Approximate days for each period string (used to build stooq date range)
_PERIOD_TO_DAYS: dict[str, int] = {
    "1d": 2,    "2d": 3,    "5d": 7,    "7d": 9,
    "15d": 20,  "30d": 35,  "60d": 65,  "90d": 95,
    "120d": 125,"180d": 185,"1y": 370,  "2y": 740,
    "3y": 1100, "5y": 1830, "10y": 3660,
}

# ── Timeframe config ──────────────────────────────────────────────────────────
TF_CONFIG = {
    "1m":  {"interval": "1m",  "period": "1d"},
    "5m":  {"interval": "5m",  "period": "5d"},
    "15m": {"interval": "15m", "period": "15d"},
    "1h":  {"interval": "1h",  "period": "60d"},
    "4h":  {"interval": "1h",  "period": "120d"},   # 1h bars aggregated to 4h
    "1D":  {"interval": "1d",  "period": "1y"},
    "1W":  {"interval": "1wk", "period": "3y"},
    "1M":  {"interval": "1mo", "period": "10y"},
}

# Timeframes that use "YYYY-MM-DD" strings (required by lightweight-charts)
DAILY_TIMEFRAMES = {"1D", "1W", "1M"}


# ── Yahoo Finance session management (cookie + crumb) ─────────────────────────
# The v8 chart API requires: (1) session cookies from finance.yahoo.com homepage
# and (2) a crumb token from the /v1/test/getcrumb endpoint.

_yf_crumb: str = ""
_yf_crumb_cookies: dict = {}
_yf_crumb_ts: float = 0.0
_YF_CRUMB_TTL = 1800.0   # Refresh crumb every 30 min (was 1 hr — more robust)
# NOTE: asyncio primitives MUST be created inside a running event loop.
# In Python 3.12+, creating Lock/Semaphore at module level raises
# "RuntimeError: no running event loop" or silently binds to a stale loop.
# We use lazy getters that create them on first async access.
_yf_crumb_lock: asyncio.Lock | None = None
_yf_http_sem: asyncio.Semaphore | None = None


def _get_crumb_lock() -> asyncio.Lock:
    """Lazily create the crumb lock inside the running event loop."""
    global _yf_crumb_lock
    if _yf_crumb_lock is None:
        _yf_crumb_lock = asyncio.Lock()
    return _yf_crumb_lock


def _get_http_sem() -> asyncio.Semaphore:
    """Lazily create the HTTP semaphore inside the running event loop."""
    global _yf_http_sem
    if _yf_http_sem is None:
        # 8 permits — sidebar makes 12 concurrent quote requests; Semaphore(3)
        # queued 9 of them, starving the event loop and making even /auth/me
        # take 6-9s. 8 balances Yahoo rate-limit avoidance with concurrency.
        _yf_http_sem = asyncio.Semaphore(8)
    return _yf_http_sem

# Alternative crumb endpoints (tried in order if query2 fails)
_YF_CRUMB_URLS = [
    "https://query2.finance.yahoo.com/v1/test/getcrumb",
    "https://query1.finance.yahoo.com/v1/test/getcrumb",
]


async def _get_yf_auth() -> tuple[dict, str]:
    """Return (cookies, crumb) for Yahoo Finance API auth.

    Cached in memory for 30 minutes. Uses a lock to prevent thundering herd
    on cache miss. Tries two crumb endpoints for resilience.
    On failure returns whatever was last cached so callers fall back gracefully.
    """
    global _yf_crumb, _yf_crumb_cookies, _yf_crumb_ts

    now = _time.monotonic()
    if _yf_crumb and (now - _yf_crumb_ts) < _YF_CRUMB_TTL:
        return _yf_crumb_cookies, _yf_crumb

    async with _get_crumb_lock():
        # Re-check under lock (another coroutine may have refreshed while we waited)
        now = _time.monotonic()
        if _yf_crumb and (now - _yf_crumb_ts) < _YF_CRUMB_TTL:
            return _yf_crumb_cookies, _yf_crumb

        # 2 attempts max, 5 s timeout per request — fail fast when rate-limited.
        # The quote endpoint has an 8 s hard cap (asyncio.wait_for), so we must
        # not block here for more than ~4 s per attempt.
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    headers=_YF_HEADERS, timeout=httpx.Timeout(4.0, connect=3.0), follow_redirects=True
                ) as client:
                    if attempt > 0:
                        await asyncio.sleep(0.5)  # minimal back-off

                    # Step 1: get session cookies from Yahoo Finance homepage
                    r1 = await client.get("https://finance.yahoo.com/")
                    cookies = dict(r1.cookies)

                    # Step 2: try each crumb endpoint
                    crumb = ""
                    for crumb_url in _YF_CRUMB_URLS:
                        try:
                            r2 = await client.get(
                                crumb_url,
                                cookies=cookies,
                                headers={**_YF_HEADERS, "Accept": "*/*"},
                            )
                            candidate = r2.text.strip() if r2.status_code == 200 else ""
                            if candidate and "Too Many" not in candidate and 3 < len(candidate) < 20:
                                crumb = candidate
                                break
                        except Exception:
                            continue

                    if crumb:
                        _yf_crumb = crumb
                        _yf_crumb_cookies = cookies
                        _yf_crumb_ts = _time.monotonic()
                        logger.info("Yahoo Finance crumb refreshed", attempt=attempt + 1)
                        return _yf_crumb_cookies, _yf_crumb
            except Exception as e:
                logger.warning("Failed to get Yahoo Finance crumb", attempt=attempt + 1, error=str(e))

    # All attempts failed — return stale cache (better than nothing)
    return _yf_crumb_cookies, _yf_crumb


# ── Core Yahoo Finance fetcher ────────────────────────────────────────────────

async def _fetch_yahoo_direct(
    symbol: str, interval: str, period: str, timeframe: str
) -> dict | list[OHLCVBar]:
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
    is_bk_symbol = symbol.upper().endswith(".BK")

    # Thai stocks get longer timeout and retry logic
    base_timeout = 20.0
    max_retries = 3 if is_bk_symbol else 1
    retry_delays = [0, 2, 6] if is_bk_symbol else [0]  # exponential backoff

    # Fallback periods for .BK symbols when initial period returns 0 bars
    fallback_periods = ["3mo", "1mo", "5d"] if is_bk_symbol else []

    cookies, crumb = await _get_yf_auth()
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"

    # For .BK symbols, maintain a list of periods to try in order
    periods_to_try = [period] + (fallback_periods if is_bk_symbol else [])
    bars_result = None

    for period_attempt, current_period in enumerate(periods_to_try):
        yf_range = _YF_PERIOD_MAP.get(current_period, current_period)

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
                            global _yf_crumb, _yf_crumb_ts
                            _yf_crumb = ""
                            _yf_crumb_ts = 0.0
                            cookies, crumb = await _get_yf_auth()
                            if crumb:
                                params["crumb"] = crumb
                            res = await client.get(url, params=params)

                        # On 429 (rate limited) — log and return [] immediately.
                        # A 2-second sleep + retry used to compound the blocking time;
                        # now we give up fast so the caller falls back to Finnhub/404.
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

        # If we got bars from this period, parse and return them.
        # Otherwise continue to the next period (for .BK symbols).
        if 'data' in locals():
            try:
                chart_data = data.get("chart", {})
                if chart_data.get("error"):
                    logger.warning("Yahoo Finance API error", symbol=symbol, error=chart_data["error"])
                    continue  # Try next period if available

                result = chart_data.get("result")
                if not result:
                    continue  # Try next period if available

                chart = result[0]
                meta = chart.get("meta", {})
                timestamps = chart.get("timestamp", [])
                if not timestamps:
                    continue  # Try next period if available

                # Use exchange gmtoffset so Asian stocks (UTC+7) get correct local trading date.
                # Yahoo timestamps are at local midnight; without offset, Thai "2025-02-25" → UTC "2025-02-24".
                gmt_offset = timedelta(seconds=meta.get("gmtoffset", 0))

                quote_data = chart["indicators"]["quote"][0]
                opens   = quote_data.get("open",   [])
                highs   = quote_data.get("high",   [])
                lows    = quote_data.get("low",    [])
                closes  = quote_data.get("close",  [])
                volumes = quote_data.get("volume", [])

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
                    logger.debug("Yahoo Finance returned 0 bars, trying next period",
                                symbol=symbol, period=current_period)
                    continue

            except (KeyError, IndexError, TypeError) as e:
                logger.error("Yahoo Finance parse error", symbol=symbol, error=str(e))
                continue  # Try next period if available

    # All periods exhausted with no data — return empty
    logger.warning("Yahoo Finance fetch failed for all periods", symbol=symbol)
    return []


# ── Stooq fallback (US stocks only) ──────────────────────────────────────────

async def _fetch_stooq_direct(
    symbol: str, period: str, timeframe: str
) -> list[OHLCVBar]:
    """Fetch historical OHLCV from stooq.com (free, no API key, no rate limits).

    Limitations:
    - US stocks ONLY (symbol must not contain a dot, e.g. "AAPL", "NVDA")
    - Daily / weekly / monthly only (no intraday)
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


# ── Quote / Fundamentals / Search direct fetchers ────────────────────────────

async def _fetch_quote_direct(symbol: str) -> Optional[StockQuote]:
    """Fetch current quote from Yahoo Finance chart API (5-day daily range)."""
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

        return StockQuote(
            symbol=symbol,
            price=price,
            open=round(float(meta.get("regularMarketOpen") or _safe(opens, last_idx, price)), 4),
            high=round(float(meta.get("regularMarketDayHigh") or _safe(highs, last_idx, price)), 4),
            low=round(float(meta.get("regularMarketDayLow") or _safe(lows, last_idx, price)), 4),
            prev_close=prev_close,
            change=change,
            change_pct=change_pct,
            volume=int(meta.get("regularMarketVolume") or _safe(volumes, last_idx, 0) or 0),
            timestamp=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.error("Quote parse error", symbol=symbol, error=str(e))
        return None


async def _fetch_fundamentals_direct(symbol: str) -> Optional[StockFundamentals]:
    """Fetch fundamentals from Yahoo Finance quoteSummary API.

    Tries v11 first (newer endpoint), falls back to v10 (older).
    On failure falls back to extracting available fields from the v8 chart API meta.
    """
    cookies, crumb = await _get_yf_auth()

    def _val(d: dict, key: str):
        v = d.get(key, {})
        return v.get("raw") if isinstance(v, dict) else v

    # ── Attempt quoteSummary (v11 → v10 fallback) ─────────────────────────────
    for qs_version in ("v11", "v10"):
        url = f"https://query2.finance.yahoo.com/{qs_version}/finance/quoteSummary/{symbol}"
        params: dict = {"modules": "summaryDetail,defaultKeyStatistics,financialData"}
        if crumb:
            params["crumb"] = crumb

        try:
            async with httpx.AsyncClient(
                headers=_YF_HEADERS, cookies=cookies or None,
                timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=True,
            ) as client:
                res = await client.get(url, params=params)
                if res.status_code != 200:
                    logger.debug("quoteSummary non-200", version=qs_version,
                                 symbol=symbol, status=res.status_code)
                    continue
                data = res.json()
        except httpx.TimeoutException as e:
            logger.warning("quoteSummary timed out", version=qs_version,
                           symbol=symbol, error=str(e))
            continue
        except Exception as e:
            logger.debug("quoteSummary request error", version=qs_version,
                         symbol=symbol, error=str(e))
            continue

        try:
            result = data.get("quoteSummary", {}).get("result")
            if not result:
                continue

            summary    = result[0].get("summaryDetail", {})
            key_stats  = result[0].get("defaultKeyStatistics", {})
            fin_data   = result[0].get("financialData", {})

            # Prefer financialData EPS over defaultKeyStatistics
            eps = _val(key_stats, "trailingEps") or _val(fin_data, "revenuePerShare")

            return StockFundamentals(
                symbol=symbol,
                pe_ratio=_val(summary, "trailingPE") or _val(key_stats, "trailingPE"),
                pb_ratio=_val(summary, "priceToBook") or _val(key_stats, "priceToBook"),
                eps=eps,
                dividend_yield=_val(summary, "dividendYield"),
                market_cap=_val(summary, "marketCap") or _val(key_stats, "enterpriseValue"),
                beta=_val(summary, "beta") or _val(key_stats, "beta"),
                week_52_high=_val(summary, "fiftyTwoWeekHigh"),
                week_52_low=_val(summary, "fiftyTwoWeekLow"),
                avg_volume=_val(summary, "averageVolume") or _val(summary, "averageVolume10days"),
            )
        except Exception as e:
            logger.error("Fundamentals parse error", version=qs_version,
                         symbol=symbol, error=str(e))
            continue

    # ── Fallback: extract available fundamentals from v8 chart API meta ────────
    logger.info(
        "quoteSummary failed, falling back to v8 chart API for fundamentals",
        symbol=symbol,
    )
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {
            "interval": "1d", "range": "5d",
            "includePrePost": "false", "corsDomain": "finance.yahoo.com",
        }
        if crumb:
            params["crumb"] = crumb

        async with httpx.AsyncClient(
            headers=_YF_HEADERS, cookies=cookies or None,
            timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=True,
        ) as client:
            res = await client.get(url, params=params)
            if res.status_code != 200:
                return None
            data = res.json()

        meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
        if not meta:
            return None

        high_52 = meta.get("fiftyTwoWeekHigh") or meta.get("52WeekHigh")
        low_52  = meta.get("fiftyTwoWeekLow")  or meta.get("52WeekLow")
        avg_vol = meta.get("averageVolume") or meta.get("regularMarketVolume")

        return StockFundamentals(
            symbol=symbol,
            pe_ratio=meta.get("trailingPE"),
            pb_ratio=None,
            eps=meta.get("epsTrailingTwelveMonths"),
            dividend_yield=None,
            market_cap=meta.get("marketCap"),
            beta=None,
            week_52_high=high_52,
            week_52_low=low_52,
            avg_volume=avg_vol,
        )
    except httpx.TimeoutException as e:
        logger.warning("v8 chart fundamentals fallback timed out", symbol=symbol, error=str(e))
        return None
    except Exception as e:
        logger.error("v8 chart fundamentals fallback error", symbol=symbol, error=str(e))
        return None


async def _search_yahoo_direct(query: str) -> list[dict]:
    """Search stocks using Yahoo Finance v1 search API."""
    cookies, crumb = await _get_yf_auth()
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params: dict = {
        "q": query, "quotesCount": 10,
        "newsCount": 0, "listsCount": 0,
        "enableFuzzyQuery": "false", "enableCb": "false",
    }
    if crumb:
        params["crumb"] = crumb

    try:
        async with _get_http_sem():
            async with httpx.AsyncClient(
                headers=_YF_HEADERS, cookies=cookies or None,
                timeout=httpx.Timeout(8.0, connect=5.0)
            ) as client:
                res = await client.get(url, params=params)
                if res.status_code != 200:
                    return []
                data = res.json()

        quotes = data.get("quotes", [])
        out = []
        for q in quotes[:10]:
            sym = q.get("symbol", "")
            if not sym:
                continue
            out.append({
                "symbol": sym,
                "name": q.get("longname") or q.get("shortname", ""),
                "market": "SET" if sym.endswith(".BK") else "US",
                "type": q.get("quoteType", ""),
            })
        return out
    except httpx.TimeoutException as e:
        logger.warning("Yahoo Finance search timed out", query=query, error=str(e))
        return []
    except Exception as e:
        logger.error("Yahoo Finance search error", query=query, error=str(e))
        return []


# ── Aggregation helpers ───────────────────────────────────────────────────────

def _aggregate_4h(bars: list[OHLCVBar]) -> list[OHLCVBar]:
    """Aggregate 1-hour bars into 4-hour bars."""
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


def _to_ohlcv(df, timeframe: str) -> list[OHLCVBar]:
    """Convert a pandas DataFrame (with timezone-aware DatetimeIndex) to OHLCVBar list.

    Used by seed_history.py when processing Yahoo Finance JSON via pandas.
    The index must be timezone-aware so that strftime extracts the correct local date.
    """
    import pandas as pd
    bars = []
    use_date_str = timeframe in DAILY_TIMEFRAMES

    for ts, row in df.iterrows():
        try:
            open_v  = float(row["Open"])
            high_v  = float(row["High"])
            low_v   = float(row["Low"])
            close_v = float(row["Close"])
            vol_v   = int(row["Volume"])
        except (KeyError, TypeError, ValueError):
            continue

        if use_date_str:
            t: int | str = pd.Timestamp(ts).strftime("%Y-%m-%d")
        else:
            t = int(pd.Timestamp(ts).timestamp())

        bars.append(OHLCVBar(
            time=t,
            open=round(open_v, 4), high=round(high_v, 4),
            low=round(low_v, 4),   close=round(close_v, 4),
            volume=vol_v,
        ))

    if timeframe == "4h":
        bars = _aggregate_4h(bars)
    return bars


def _bars_to_db_rows(bars: list[OHLCVBar], symbol: str, timeframe: str) -> list[dict]:
    """Convert OHLCVBar schema objects → DB row dicts for bulk upsert."""
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


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _save_bars_to_db(bars: list[OHLCVBar], symbol: str, timeframe: str) -> None:
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


async def _load_bars_from_db(symbol: str, timeframe: str) -> list[OHLCVBar]:
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


# ── Synthetic intraday generator (L4 fallback) ───────────────────────────────

def _generate_synthetic_intraday(
    daily_bars: list[OHLCVBar],
    timeframe: str,
    is_set: bool = False,
) -> list[OHLCVBar]:
    """Generate realistic synthetic intraday bars from daily OHLCV.

    Uses a deterministic Brownian bridge: price starts at daily open, ends at
    daily close, stays within [low, high]. Volume follows a U-shaped distribution
    (higher at open and close) with small random noise.

    The RNG is seeded per-day with a deterministic value so results are
    consistent across repeated calls for the same symbol/timeframe.

    Args:
        daily_bars: Daily OHLCV bars (should be sorted ascending).
        timeframe:  One of "1m", "5m", "15m", "1h", "4h".
        is_set:     True for Thai SET stocks (uses SET trading hours UTC+7).
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


# ── Public API ────────────────────────────────────────────────────────────────

_HISTORY_TTL = {
    "1m": 60, "5m": 300, "15m": 900,
    "1h": 3600, "4h": 3600,
    "1D": 21600, "1W": 86400, "1M": 86400,
}


async def fetch_yahoo_bars(
    symbol: str, timeframe: str, period: Optional[str] = None
) -> list[dict]:
    """Fetch OHLCV bars and return DB row dicts.

    Used by fetch_stock_history() L3 and seed_history.py backfill.
    Tries Yahoo Finance first; falls back to Stooq for US stocks if Yahoo fails.

    Args:
        symbol:    Ticker (e.g. "AAPL", "PTT.BK")
        timeframe: TF key (e.g. "1D")
        period:    Override period (e.g. "2y" for longer backfill).
                   Defaults to TF_CONFIG[timeframe]["period"].
    """
    cfg = TF_CONFIG.get(timeframe, {})
    _period   = period or cfg.get("period", "1y")
    _interval = cfg.get("interval", "1d")

    bars = await _fetch_yahoo_direct(symbol, _interval, _period, timeframe)

    # Fallback: Stooq for US daily/weekly/monthly when Yahoo is unavailable
    if not bars and "." not in symbol and timeframe in DAILY_TIMEFRAMES:
        logger.info("Yahoo unavailable, trying Stooq", symbol=symbol, timeframe=timeframe)
        bars = await _fetch_stooq_direct(symbol, _period, timeframe)

    return _bars_to_db_rows(bars, symbol, timeframe)


async def fetch_stock_history(symbol: str, timeframe: str) -> list[OHLCVBar]:
    """Fetch historical OHLCV data (3-layer cache).

    L1: Redis (hot)   → L2: PostgreSQL (persistent)   → L3: Yahoo/Stooq (source)
    """
    if timeframe not in TF_CONFIG:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    cache_key = f"cache:history:{symbol}:{timeframe}"
    ttl = _HISTORY_TTL.get(timeframe, 900)

    # L1: Redis
    try:
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            return [OHLCVBar(**item) for item in json.loads(cached)]
    except Exception as e:
        logger.warning("Redis cache read failed", error=str(e))

    # L2: PostgreSQL
    db_bars = await _load_bars_from_db(symbol, timeframe)
    if db_bars:
        logger.info("Serving from DB", symbol=symbol, timeframe=timeframe, bars=len(db_bars))
        try:
            r = await get_redis()
            await r.setex(cache_key, ttl, json.dumps([b.model_dump() for b in db_bars]))
        except Exception:
            pass
        return db_bars

    # L3: External source
    logger.info("Fetching from source (first time)", symbol=symbol, timeframe=timeframe)
    cfg = TF_CONFIG[timeframe]

    bars = await _fetch_yahoo_direct(symbol, cfg["interval"], cfg["period"], timeframe)

    if not bars and "." not in symbol and timeframe in DAILY_TIMEFRAMES:
        logger.info("Yahoo unavailable, trying Stooq", symbol=symbol, timeframe=timeframe)
        bars = await _fetch_stooq_direct(symbol, cfg["period"], timeframe)

    # L4: Synthetic intraday fallback — generate from daily OHLCV when Yahoo fails
    if not bars and timeframe not in DAILY_TIMEFRAMES:
        logger.info(
            "No intraday data from Yahoo, generating synthetic from daily",
            symbol=symbol, timeframe=timeframe,
        )
        # Fetch daily bars (uses its own 3-layer cache so no redundant API calls)
        daily_bars = await fetch_stock_history(symbol, "1D")
        if daily_bars:
            is_set = symbol.upper().endswith(".BK")
            bars = _generate_synthetic_intraday(daily_bars, timeframe, is_set=is_set)

    if bars:
        asyncio.create_task(_save_bars_to_db(bars, symbol, timeframe))
        try:
            r = await get_redis()
            await r.setex(cache_key, ttl, json.dumps([b.model_dump() for b in bars]))
        except Exception:
            pass

    return bars


async def _cache_quote_background(symbol: str) -> None:
    """Background coroutine: fetch quote from Yahoo Finance and cache in Redis.

    Called via asyncio.create_task() so it does not block the request path.
    Silently skips if a quote is already cached (race-condition guard).
    """
    try:
        cache_key = f"cache:quote:{symbol}"
        r = await get_redis()
        # Skip if another task already populated the cache
        if await r.get(cache_key):
            return
        quote = await _fetch_quote_direct(symbol)
        if quote:
            await r.setex(cache_key, 60, quote.model_dump_json())
            logger.info("Background quote cached", symbol=symbol)
    except Exception as e:
        logger.debug("Background quote fetch failed", symbol=symbol, error=str(e))


async def fetch_stock_quote(symbol: str) -> Optional[StockQuote]:
    """Fetch current quote for a symbol.

    Architecture:
      1. Read from Redis  cache:quote:{symbol}  (written by background Celery tasks
         or the asyncio fallback below).
      2. If cache miss → trigger Celery background fetch AND an asyncio fallback
         task that fetches from Yahoo Finance directly; return None so the caller
         can return 202.  The asyncio task completes in ~5 s, so the next frontend
         retry will hit the cache.
    """
    cache_key = f"cache:quote:{symbol}"
    try:
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            return StockQuote(**json.loads(cached))
    except Exception as e:
        logger.error("Redis quote cache read failed", error=str(e))
        return None

    # Cache miss — try Celery (fast, fire-and-forget) then asyncio fallback.
    logger.info("Quote cache miss — triggering background fetch", symbol=symbol)
    try:
        from workers.price_fetcher import fetch_set_prices, fetch_us_prices
        if symbol.endswith(".BK") or symbol.endswith(".MAI"):
            fetch_set_prices.apply_async(countdown=0, priority=9)
        else:
            fetch_us_prices.apply_async(countdown=0, priority=9)
    except Exception as ce:
        logger.debug("Could not trigger Celery fetch (fallback to asyncio)", error=str(ce))
        # Celery not available — spin up a local asyncio task instead
        asyncio.create_task(_cache_quote_background(symbol))

    return None


_FUNDAMENTALS_NULL_SENTINEL = "__null__"


async def fetch_stock_fundamentals(symbol: str) -> Optional[StockFundamentals]:
    """Fetch fundamental data for a symbol.

    Negative caching: if Yahoo Finance rate-limits all attempts, stores a
    sentinel in Redis for 5 min so we don't hammer Yahoo on every retry.
    Overall timeout of 12 s prevents the endpoint from hanging when all
    Yahoo Finance requests are slow or rate-limited.
    """
    cache_key = f"cache:fundamentals:{symbol}"
    try:
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            if cached == _FUNDAMENTALS_NULL_SENTINEL:
                return None  # negative cache hit — data not available right now
            return StockFundamentals(**json.loads(cached))
    except Exception:
        pass

    try:
        fundamentals = await asyncio.wait_for(
            _fetch_fundamentals_direct(symbol), timeout=12.0
        )
    except asyncio.TimeoutError:
        logger.warning("fetch_stock_fundamentals timed out", symbol=symbol)
        fundamentals = None

    try:
        r = await get_redis()
        if fundamentals:
            await r.setex(cache_key, 300, fundamentals.model_dump_json())
        else:
            # Negative cache — avoid hammering Yahoo when rate-limited
            await r.setex(cache_key, 300, _FUNDAMENTALS_NULL_SENTINEL)
    except Exception:
        pass

    return fundamentals


async def search_stocks(query: str) -> list[dict]:
    """Search stocks by symbol or name."""
    cache_key = f"cache:search:{query}"
    try:
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    results = await _search_yahoo_direct(query)
    if results:
        try:
            r = await get_redis()
            await r.setex(cache_key, 86400, json.dumps(results))
        except Exception:
            pass

    return results
