"""Stock Screener API — filters stocks by technical indicators."""
import asyncio
from typing import Literal
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from models.stock import Stock, MarketType
from models.user import User
from api.middleware.auth import get_optional_user

router = APIRouter(prefix="/api/screener", tags=["screener"])

# ─── Indicator helpers ──────────────────────────────────────────────────────

def _compute_rsi(closes, period: int = 14) -> float:
    """Wilder smoothed RSI."""
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain.iloc[-1] / (loss.iloc[-1] if loss.iloc[-1] != 0 else 1e-9)
    return round(100 - 100 / (1 + rs), 2)


def _compute_macd(closes):
    """Returns (macd_val, signal_val) for the latest bar."""
    if len(closes) < 26:
        return 0.0, 0.0
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line.iloc[-1], signal_line.iloc[-1]


def _compute_signal(rsi: float, macd_val: float, sig_val: float) -> str:
    macd_bullish = macd_val > sig_val
    if rsi < 30 and macd_bullish:
        return "Strong Buy"
    if rsi < 45 or macd_bullish:
        return "Buy"
    if rsi > 70 and not macd_bullish:
        return "Sell"
    return "Neutral"


# ─── Filter param mappers ───────────────────────────────────────────────────

def _matches_rsi(rsi: float, flt: str) -> bool:
    if flt == "oversold":
        return rsi < 30
    if flt == "neutral":
        return 30 <= rsi <= 70
    if flt == "overbought":
        return rsi > 70
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


def _matches_price(close: float, ma50: float, ma200: float, flt: str) -> bool:
    if flt == "above_ma200":
        return close > ma200 if ma200 > 0 else True
    if flt == "above_ma50":
        return close > ma50 if ma50 > 0 else True
    if flt == "below_ma200":
        return close < ma200 if ma200 > 0 else True
    return True  # "any"


# ─── Core screener logic (sync, runs in executor) ───────────────────────────

def _run_screener(
    symbols: list[str],
    name_map: dict[str, str],
    rsi_filter: str,
    volume_filter: str,
    macd_filter: str,
    price_filter: str,
) -> list[dict]:
    import httpx
    import pandas as pd

    if not symbols:
        return []

    results = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }

    with httpx.Client(headers=headers, timeout=15.0, follow_redirects=True) as client:
        for sym in symbols:
            try:
                # Fetch 6 months of daily data
                res = client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=6mo")
                if res.status_code != 200:
                    continue
                
                res_data = res.json()
                chart_data = res_data.get("chart", {}).get("result")
                if not chart_data:
                    continue
                    
                chart = chart_data[0]
                timestamps = chart.get("timestamp", [])
                if not timestamps:
                    continue
                    
                quote_data = chart["indicators"]["quote"][0]
                closes = quote_data.get("close", [])
                volumes = quote_data.get("volume", [])
                
                df = pd.DataFrame({
                    "Close": closes,
                    "Volume": volumes
                }).dropna()

                if len(df) < 30:
                    continue

                closes_series = df["Close"]
                volumes_series = df["Volume"]

                if len(closes_series) < 26:
                    continue

                close_now = float(closes_series.iloc[-1])
                prev_close = float(closes_series.iloc[-2]) if len(closes_series) >= 2 else close_now

                # Indicators
                rsi = _compute_rsi(closes_series)
                macd_val, sig_val = _compute_macd(closes_series)
                ma50 = float(closes_series.tail(50).mean()) if len(closes_series) >= 50 else 0.0
                ma200 = float(closes_series.tail(200).mean()) if len(closes_series) >= 200 else 0.0
                vol_now = float(volumes_series.iloc[-1]) if len(volumes_series) > 0 else 0
                vol_avg20 = float(volumes_series.tail(20).mean()) if len(volumes_series) >= 20 else 1
                vol_ratio = vol_now / vol_avg20 if vol_avg20 > 0 else 0.0

                # Apply filters
                if not _matches_rsi(rsi, rsi_filter):
                    continue
                if not _matches_volume(vol_ratio, volume_filter):
                    continue
                if not _matches_macd(macd_val, sig_val, macd_filter):
                    continue
                if not _matches_price(close_now, ma50, ma200, price_filter):
                    continue

                chg = close_now - prev_close
                chg_pct = (chg / prev_close * 100) if prev_close else 0
                up = chg >= 0
                signal = _compute_signal(rsi, macd_val, sig_val)
                macd_label = "Buy" if macd_val > sig_val else "Sell" if macd_val < sig_val else "Neutral"

                results.append({
                    "sym": sym,
                    "name": name_map.get(sym, sym),
                    "rsi": rsi,
                    "macd": macd_label,
                    "vol": f"{vol_ratio:.1f}x",
                    "price": f"{close_now:.2f}",
                    "chg": f"{'+' if up else ''}{chg_pct:.2f}%",
                    "up": up,
                    "signal": signal,
                })
            except Exception:
                continue

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
    """Screen stocks by technical indicators. Open to guests."""
    # Load active stocks from DB
    stmt = select(Stock).where(Stock.is_active == True)
    if market != "all":
        market_enum = MarketType.SET if market == "SET" else MarketType.US
        stmt = stmt.where(Stock.market == market_enum)

    result = await db.execute(stmt)
    stocks = result.scalars().all()

    if not stocks:
        return []

    symbols = [s.symbol for s in stocks]
    name_map = {s.symbol: (s.name_th or s.name) for s in stocks}

    # Run sync yfinance in thread pool
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None,
        _run_screener,
        symbols,
        name_map,
        rsi,
        volume,
        macd,
        price,
    )

    return data
