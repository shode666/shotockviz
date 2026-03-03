"""Yahoo Finance fundamentals fetching — v11/v10/v8 fallback chain.

Isolated from quote and OHLCV data fetching.
"""
from typing import Optional

import httpx

from core.logger import get_logger
from models.schemas import StockFundamentals
from .yahoo_auth import _get_yf_auth, _YF_HEADERS

logger = get_logger(__name__)


async def fetch_fundamentals_direct(symbol: str) -> Optional[StockFundamentals]:
    """Fetch fundamentals from Yahoo Finance quoteSummary API.

    Tries v11 first (newer endpoint), falls back to v10 (older).
    On failure falls back to extracting available fields from the v8 chart API meta.

    Pure async function. Returns StockFundamentals or None.
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
