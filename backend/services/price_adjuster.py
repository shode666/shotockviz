"""Price adjuster — computes adjusted OHLCV prices using corporate actions.

Adjusts historical prices backward from the most recent data point,
applying dividend and split corrections. Raw data is NEVER modified in the DB;
adjustments are computed on-the-fly and cached.

Usage:
    from services.price_adjuster import adjust_prices

    # bars: list of dicts with {time, open, high, low, close, volume}
    # Returns new list with adjusted values (original list is not modified)
    adjusted = await adjust_prices("PTT.BK", bars)
"""
import json
from datetime import date, datetime
from typing import Optional

from core.logger import get_logger
from core import cache_keys

logger = get_logger(__name__)

# Cache TTL for adjusted price data (6 hours — corporate actions rarely change)
_ADJUSTED_CACHE_TTL = 21600


async def adjust_prices(
    symbol: str,
    bars: list[dict],
    *,
    adjust_dividends: bool = True,
    adjust_splits: bool = True,
) -> list[dict]:
    """Compute adjusted OHLCV prices by applying corporate actions backward.

    Algorithm:
      1. Load all corporate actions for the symbol, sorted by ex_date DESC.
      2. Walk bars from newest to oldest.
      3. For each action before the current bar's date:
         - DIV:   adj_factor *= (close_before_xd - dividend) / close_before_xd
         - SPLIT: adj_factor *= ratio
      4. Multiply OHLC by cumulative adj_factor. Divide volume by adj_factor.

    Args:
        symbol: Stock symbol
        bars: List of OHLCV dicts (time can be string "YYYY-MM-DD" or unix int)
        adjust_dividends: Apply dividend adjustments (default True)
        adjust_splits: Apply split adjustments (default True)

    Returns:
        New list of adjusted OHLCV dicts. Original list is NOT modified.
    """
    if not bars:
        return []

    actions = await _load_corporate_actions(symbol)
    if not actions:
        return bars  # No actions → return raw data unchanged

    # Filter by requested adjustment types
    filtered = []
    for a in actions:
        if a["action_type"] == "DIV" and adjust_dividends:
            filtered.append(a)
        elif a["action_type"] == "SPLIT" and adjust_splits:
            filtered.append(a)
        elif a["action_type"] == "RIGHTS" and adjust_splits:
            filtered.append(a)
    if not filtered:
        return bars

    # Sort actions by ex_date ascending for backward traversal
    filtered.sort(key=lambda x: x["ex_date"])

    # Build adjusted bars (copy, don't mutate)
    adjusted = []
    for bar in bars:
        bar_date = _parse_bar_date(bar.get("time"))
        if bar_date is None:
            adjusted.append(dict(bar))  # Can't parse date, keep raw
            continue

        adj_factor = 1.0
        for action in filtered:
            # Only apply actions with ex_date AFTER this bar's date
            # (adjust bars BEFORE the ex-date backward)
            if action["ex_date"] > bar_date:
                if action["action_type"] == "DIV" and action.get("value"):
                    # Dividend adjustment: reduce price by dividend amount
                    # Use the previous close as reference (approximation)
                    div_amount = float(action["value"])
                    ref_price = float(bar.get("close", 0))
                    if ref_price > div_amount > 0:
                        adj_factor *= (ref_price - div_amount) / ref_price
                elif action["action_type"] == "SPLIT" and action.get("ratio"):
                    # Split adjustment: multiply by ratio
                    adj_factor *= float(action["ratio"])
                elif action["action_type"] == "RIGHTS" and action.get("ratio"):
                    adj_factor *= float(action["ratio"])

        adj_bar = dict(bar)
        if adj_factor != 1.0:
            adj_bar["open"] = round(float(bar["open"]) * adj_factor, 4)
            adj_bar["high"] = round(float(bar["high"]) * adj_factor, 4)
            adj_bar["low"] = round(float(bar["low"]) * adj_factor, 4)
            adj_bar["close"] = round(float(bar["close"]) * adj_factor, 4)
            # Volume is inversely adjusted
            if adj_factor > 0:
                adj_bar["volume"] = int(float(bar["volume"]) / adj_factor)

        adjusted.append(adj_bar)

    return adjusted


async def _load_corporate_actions(symbol: str) -> list[dict]:
    """Load corporate actions from Redis cache → PostgreSQL."""
    cache_key = f"corp_actions:{symbol.upper()}"

    # L1: Redis
    try:
        from services.stock_service import get_redis
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    # L2: PostgreSQL
    try:
        from core.database import AsyncSessionLocal
        from models.corporate_action import CorporateAction
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CorporateAction)
                .where(CorporateAction.symbol == symbol.upper())
                .order_by(CorporateAction.ex_date.desc())
            )
            rows = result.scalars().all()
            if rows:
                actions = [
                    {
                        "symbol": r.symbol,
                        "action_type": r.action_type,
                        "ex_date": r.ex_date.isoformat(),
                        "value": float(r.value) if r.value is not None else None,
                        "ratio": float(r.ratio) if r.ratio is not None else None,
                        "source": r.source,
                    }
                    for r in rows
                ]
                # Cache
                try:
                    from services.stock_service import get_redis
                    r = await get_redis()
                    await r.setex(cache_key, _ADJUSTED_CACHE_TTL, json.dumps(actions))
                except Exception:
                    pass
                return actions
    except Exception as e:
        logger.debug("Failed to load corporate actions", symbol=symbol, error=str(e))

    return []


def _parse_bar_date(time_val) -> Optional[date]:
    """Parse bar time value to a date object.

    Handles:
      - "2025-03-01" string → date(2025, 3, 1)
      - 1709251200 unix timestamp → date from timestamp
    """
    if time_val is None:
        return None
    if isinstance(time_val, str):
        try:
            return date.fromisoformat(time_val[:10])
        except ValueError:
            # Might be a unix timestamp as string
            try:
                return datetime.fromtimestamp(int(time_val)).date()
            except (ValueError, OSError):
                return None
    if isinstance(time_val, (int, float)):
        try:
            return datetime.fromtimestamp(int(time_val)).date()
        except (ValueError, OSError):
            return None
    return None
