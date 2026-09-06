"""Stock Screener API — filters stocks by technical indicators (pure-read from DB)."""
from __future__ import annotations

import asyncio
from typing import Literal
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core.logger import get_logger
from models.stock import Stock, MarketType
from models.ohlcv import OHLCVBar
from models.user import User
from api.middleware.auth import get_optional_user
from schemas.envelope import EnvelopingAPIRoute
# bd:shotockviz-06e — RSI/MACD/SMA math moved to services/indicators.py so
# workers/alert_checker.py can reuse the exact same computation instead of
# a second, independently-drifting copy. Re-imported under the original
# private names so this module's own call sites (and
# tests/test_screener_indicators.py, which imports these by name from
# here) do not need to change.
from services.indicators import (
    compute_rsi as _compute_rsi,
    compute_macd as _compute_macd,
    compute_sma as _compute_sma,
    compute_volume_ratio as _compute_volume_ratio,
)

# bd:deps-2026-09 S2 (ADR-001 r3) — prefix lifted /api/screener -> /screener,
# mounted under /api/v1 in main.py. route_class = envelope wrap (ADR-002).
router = APIRouter(prefix="/screener", tags=["screener"], route_class=EnvelopingAPIRoute)
logger = get_logger(__name__)


def _compute_signal(rsi: float, macd_val: float, sig_val: float) -> str:
    """Compute trading signal based on indicators.

    Args:
        rsi: RSI value (0-100)
        macd_val: MACD line value
        sig_val: MACD signal line value

    Returns:
        Signal: "Strong Buy", "Buy", "Sell", or "Neutral"
    """
    macd_bullish = macd_val > sig_val
    if rsi < 30 and macd_bullish:
        return "Strong Buy"
    if rsi < 45 or macd_bullish:
        return "Buy"
    if rsi > 70 and not macd_bullish:
        return "Sell"
    return "Neutral"


# ─── Filter param mappers ───────────────────────────────────────────────────

def _matches_rsi(rsi: float | None, flt: str) -> bool:
    """rsi is None when insufficient history to compute it
    (bd:shotockviz-kmi) — must never satisfy a specific filter; "any"
    doesn't test RSI at all so it still passes, mirroring how
    `_matches_price` already treats a None ma200/ma50."""
    if flt == "oversold":
        return rsi is not None and rsi < 30
    if flt == "neutral":
        return rsi is not None and 30 <= rsi <= 70
    if flt == "overbought":
        return rsi is not None and rsi > 70
    return True  # "any"


def _matches_volume(vol_ratio: float, flt: str) -> bool:
    if flt == "2x":
        return vol_ratio >= 2.0
    if flt == "1.5x":
        return vol_ratio >= 1.5
    return True  # "any"


def _matches_macd(macd_val: float, sig_val: float, flt: str) -> bool:
    if flt == "buy":
        return macd_val > sig_val
    if flt == "sell":
        return macd_val < sig_val
    return True  # "any"


def _matches_price(close: float, ma50: float | None, ma200: float | None, flt: str) -> bool:
    """A symbol whose MA cannot be computed (None — insufficient history)
    must never satisfy an MA filter (bd:shotockviz-0x0). It is excluded,
    not silently passed, when that specific filter is requested; a
    caller asking for "any" never needed the MA in the first place."""
    if flt == "above_ma200":
        return ma200 is not None and close > ma200
    if flt == "above_ma50":
        return ma50 is not None and close > ma50
    if flt == "below_ma200":
        return ma200 is not None and close < ma200
    return True  # "any"


async def _fetch_symbol_bars(db: AsyncSession, symbol: str) -> list[OHLCVBar] | None:
    """Fetch daily OHLCV bars for a symbol from PostgreSQL.

    Args:
        db: Database session
        symbol: Stock symbol

    Returns:
        List of OHLCVBar objects or None if insufficient data
    """
    try:
        # bd:shotockviz-p0y — order DESC + limit to take the newest 300 rows,
        # then reverse back to ascending (oldest→newest) so downstream code
        # (closes[-1] = "now") still sees chronological order. asc+limit
        # used to take the OLDEST 300 rows once a symbol passed 300 total,
        # freezing the screener window forever.
        result = await db.execute(
            select(OHLCVBar)
            .where(
                OHLCVBar.symbol == symbol,
                OHLCVBar.timeframe == "1D"
            )
            .order_by(OHLCVBar.time_unix.desc())
            .limit(300)
        )
        bars = list(reversed(result.scalars().all()))
        if len(bars) < 30:
            return None
        return bars
    except Exception as e:
        logger.debug("Failed to fetch bars for symbol", symbol=symbol, error=str(e))
        return None


def _evaluate_symbol(
    bars: list[OHLCVBar],
    name: str,
    rsi_filter: str,
    volume_filter: str,
    macd_filter: str,
    price_filter: str,
) -> dict | None:
    """Evaluate a single symbol against screener filters.

    Pure function: takes OHLCV bars + filters, returns result dict or None if filtered out.

    Args:
        bars: List of OHLCV bars (must have >= 26 bars)
        name: Company name
        rsi_filter: RSI filter ("oversold", "neutral", "overbought", "any")
        volume_filter: Volume filter ("2x", "1.5x", "any")
        macd_filter: MACD filter ("buy", "sell", "any")
        price_filter: Price filter ("above_ma200", "above_ma50", "below_ma200", "any")

    Returns:
        Result dict with indicators, or None if filtered out
    """
    if len(bars) < 26:
        return None

    # Extract price and volume data
    closes = [float(b.close) for b in bars]
    volumes = [float(b.volume) for b in bars]

    close_now = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else close_now

    # Compute all indicators
    rsi = _compute_rsi(closes)
    macd_val, sig_val = _compute_macd(closes)
    ma50 = _compute_sma(closes, 50)
    ma200 = _compute_sma(closes, 200)

    vol_ratio = _compute_volume_ratio(volumes)

    # bd:shotockviz-kmi — RSI (needs 15 closes) and volume ratio (needs 20
    # volumes) can also return None on insufficient data, same as
    # ma200/ma50 below (bd:shotockviz-0x0). The `len(bars) < 26` guard at
    # the top of this function makes this branch unreachable today, but
    # do not rely on a different, unrelated length check elsewhere to
    # keep it that way — that is exactly the arrangement that let the
    # MA200 bug live. Exclude explicitly, the same way ma200/ma50 already
    # are below, rather than letting a None reach `_matches_rsi`/
    # `_compute_signal`/the result payload as if it were a real number.
    if rsi is None or vol_ratio is None:
        logger.debug(
            "Screener: excluded — insufficient history for RSI/volume ratio",
            symbol=bars[0].symbol, bars=len(bars),
        )
        return None

    # Apply all filters with early exit (guard clauses)
    if not _matches_rsi(rsi, rsi_filter):
        return None
    if not _matches_volume(vol_ratio, volume_filter):
        return None
    if not _matches_macd(macd_val, sig_val, macd_filter):
        return None
    if price_filter in ("above_ma200", "below_ma200") and ma200 is None:
        logger.debug(
            "Screener: excluded — insufficient history for MA200",
            symbol=bars[0].symbol, bars=len(bars), filter=price_filter,
        )
        return None
    if price_filter == "above_ma50" and ma50 is None:
        logger.debug(
            "Screener: excluded — insufficient history for MA50",
            symbol=bars[0].symbol, bars=len(bars), filter=price_filter,
        )
        return None
    if not _matches_price(close_now, ma50, ma200, price_filter):
        return None

    # Build result
    chg = close_now - prev_close
    chg_pct = (chg / prev_close * 100) if prev_close else 0
    up = chg >= 0
    signal = _compute_signal(rsi, macd_val, sig_val)
    macd_label = "Buy" if macd_val > sig_val else "Sell" if macd_val < sig_val else "Neutral"

    return {
        "sym": bars[0].symbol,
        "name": name,
        "rsi": rsi,
        "macd": macd_label,
        "vol": f"{vol_ratio:.1f}x",
        "price": f"{close_now:.2f}",
        "chg": f"{'+' if up else ''}{chg_pct:.2f}%",
        "up": up,
        "signal": signal,
    }


async def _run_screener_db(
    db: AsyncSession,
    symbols: list[str],
    name_map: dict[str, str],
    rsi_filter: str,
    volume_filter: str,
    macd_filter: str,
    price_filter: str,
) -> list[dict]:
    """Screen stocks using OHLCV data from PostgreSQL (pure-read).

    For each symbol, fetch daily bars and evaluate against filters.
    """
    results = []

    for sym in symbols:
        # Guard clause: skip if we can't fetch bars
        bars = await _fetch_symbol_bars(db, sym)
        if not bars:
            continue

        # Evaluate symbol and skip if filtered out
        result = _evaluate_symbol(
            bars,
            name_map.get(sym, sym),
            rsi_filter,
            volume_filter,
            macd_filter,
            price_filter,
        )
        if result:
            results.append(result)

    # Sort: Strong Buy > Buy > Neutral > Sell
    order = {"Strong Buy": 0, "Buy": 1, "Neutral": 2, "Sell": 3}
    results.sort(key=lambda x: order.get(x["signal"], 9))
    return results


# ─── Endpoint ───────────────────────────────────────────────────────────────

@router.get("")
async def screen_stocks(
    market: Literal["SET", "US", "all"] = Query("all"),
    rsi: Literal["oversold", "neutral", "overbought", "any"] = Query("any"),
    volume: Literal["2x", "1.5x", "any"] = Query("any"),
    macd: Literal["buy", "sell", "any"] = Query("any"),
    price: Literal["above_ma200", "above_ma50", "below_ma200", "any"] = Query("any"),
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_optional_user),
):
    """Screen stocks by technical indicators — pure-read from PostgreSQL.

    Reads OHLCV data from the ohlcv_bars table and computes RSI, MACD, MAs.
    Open to guests. Cap at 4.5s total to respect <5s SLA.
    If screener can't finish in time, return whatever partial results we got.
    """
    # Load active stocks from DB — screener only supports SET and US markets.
    # Other markets (UK, HK, DE, FUND, etc.) are excluded to avoid enum cast errors.
    if market == "all":
        stmt = select(Stock).where(
            Stock.is_active == True,
            Stock.market.in_([MarketType.SET, MarketType.US]),
        )
    else:
        try:
            market_enum = MarketType(market)
        except ValueError:
            market_enum = MarketType.US
        stmt = select(Stock).where(
            Stock.is_active == True,
            Stock.market == market_enum,
        )

    result = await db.execute(stmt)
    stocks = result.scalars().all()

    if not stocks:
        return []

    symbols = [s.symbol for s in stocks]
    name_map = {s.symbol: (s.name_th or s.name) for s in stocks}

    # Run screener with DB reads — cap at 4.5s total to respect <5s SLA
    try:
        data = await asyncio.wait_for(
            _run_screener_db(
                db,
                symbols,
                name_map,
                rsi,
                volume,
                macd,
                price,
            ),
            timeout=4.5,
        )
    except asyncio.TimeoutError:
        logger.warning("Screener timeout, returning partial results")
        data = []  # Return empty rather than hang — user can retry

    return data
