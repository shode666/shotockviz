"""Dashboard API — aggregated market overview for the personal investment assistant.

Performance strategy: Return cached data IMMEDIATELY (< 1s).
If cache is cold, return partial data with nulls and trigger background fetch.
When background fetch completes, WebSocket 'data_ready' notifies the client to re-fetch.
Target: dashboard API always responds < 3 seconds, even on cold cache.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core import cache_keys
from core.logger import get_logger
from models.user import User
from models.portfolio import Transaction
from models.alert import Alert
from api.middleware.auth import get_current_user_optional
from services import stock_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
logger = get_logger(__name__)

# Market index symbols
INDEX_SYMBOLS = {
    "SET": "^SET.BK",
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC",
    "USD/THB": "THBUSD=X",
    "Gold": "GC=F",
}

# Default watchlist for guest
GUEST_WATCHLIST = ["PTT.BK", "CPALL.BK", "AAPL", "NVDA", "MSFT"]


async def _fast_quote(symbol: str) -> dict | None:
    """Get quote from Redis cache ONLY (sub-ms). Returns None on miss.
    Does NOT call external APIs — that's done in background."""
    try:
        r = await stock_service.get_redis()
        cached = await r.get(cache_keys.quote(symbol))
        if cached:
            import json
            return json.loads(cached)
    except Exception:
        pass
    return None


async def _ensure_quotes_cached(symbols: list[str]) -> None:
    """Background task: fetch missing quotes and notify client via WS."""
    for sym in symbols:
        try:
            await stock_service._cache_quote_background(sym)
        except Exception:
            pass
    # Notify dashboard to refresh
    try:
        await stock_service._notify_data_ready("dashboard", "*")
    except Exception:
        pass


async def _fetch_indices_cached() -> tuple[list[dict], list[str]]:
    """Fetch market index cards from Redis cache.

    Returns:
        (indices_list, misses_list) where misses need background fetch
    """
    indices = []
    index_misses = []

    for name, sym in INDEX_SYMBOLS.items():
        cached = await _fast_quote(sym)
        if cached:
            indices.append({
                "name": name,
                "symbol": sym,
                "price": cached.get("price"),
                "change": cached.get("change"),
                "change_pct": cached.get("change_pct"),
            })
        else:
            index_misses.append(sym)
            indices.append({"name": name, "symbol": sym, "price": None, "change": None, "change_pct": None})

    return indices, index_misses


async def _build_portfolio_summary(user: User, db: AsyncSession) -> tuple[dict | None, list[str]]:
    """Build portfolio aggregation with holdings calculation.

    Args:
        user: Current user
        db: Database session

    Returns:
        (portfolio_summary_dict, misses_list) where misses need background fetch
    """
    if not user:
        return None, []

    try:
        result = await db.execute(
            select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
        )
        txns = result.scalars().all()
        if not txns:
            return None, []

        # Calculate holdings from transactions
        holdings: dict[str, dict] = {}
        for t in txns:
            if t.symbol not in holdings:
                holdings[t.symbol] = {"qty": 0.0, "total_cost": 0.0}

            if t.type.value == "BUY":
                holdings[t.symbol]["qty"] += t.qty
                holdings[t.symbol]["total_cost"] += t.qty * t.price + t.fee
            else:
                avg = holdings[t.symbol]["total_cost"] / max(holdings[t.symbol]["qty"], 1)
                holdings[t.symbol]["qty"] -= t.qty
                holdings[t.symbol]["total_cost"] -= t.qty * avg

        active = {s: h for s, h in holdings.items() if h["qty"] > 0.001}
        if not active:
            return None, []

        # Aggregate values using cache-only quotes
        total_value = 0.0
        total_cost = 0.0
        top_holdings = []
        portfolio_misses = []

        for sym, h in active.items():
            cached = await _fast_quote(sym)
            if not cached:
                portfolio_misses.append(sym)
                continue

            val = cached.get("price", 0) * h["qty"]
            cost = h["total_cost"]
            total_value += val
            total_cost += cost
            top_holdings.append({
                "symbol": sym,
                "value": round(val, 2),
                "change_pct": cached.get("change_pct"),
                "unrealized_pct": round((val - cost) / cost * 100, 2) if cost else 0,
            })

        if not top_holdings:
            return None, portfolio_misses

        top_holdings.sort(key=lambda x: x["value"], reverse=True)
        unrealized_pl = total_value - total_cost

        return {
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "unrealized_pl": round(unrealized_pl, 2),
            "unrealized_pl_pct": round(unrealized_pl / total_cost * 100, 2) if total_cost else 0,
            "position_count": len(active),
            "top_holdings": top_holdings[:5],
            "has_pending_prices": len(portfolio_misses) > 0,
        }, portfolio_misses
    except Exception as e:
        logger.warning("portfolio summary error", error=str(e))
        return None, []


async def _find_alerts_near_target(user: User, db: AsyncSession) -> tuple[int, list[dict], list[str]]:
    """Find active alerts within 3% of target price.

    Args:
        user: Current user
        db: Database session

    Returns:
        (alert_count, triggered_alerts, misses_list)
    """
    if not user:
        return 0, [], []

    try:
        res = await db.execute(
            select(Alert).where(Alert.user_id == user.id, Alert.is_active == True)
        )
        alerts_list = res.scalars().all()
        alert_count = len(alerts_list)
        triggered_alerts = []
        alert_misses = []

        for a in alerts_list[:10]:
            if a.value is None:
                continue

            cached = await _fast_quote(a.symbol)
            if not cached or not cached.get("price"):
                alert_misses.append(a.symbol)
                continue

            diff_pct = abs(cached["price"] - a.value) / a.value * 100
            if diff_pct < 3:
                triggered_alerts.append({
                    "symbol": a.symbol,
                    "condition": a.condition.value if hasattr(a.condition, 'value') else str(a.condition),
                    "target": a.value,
                    "current": cached["price"],
                    "diff_pct": round(diff_pct, 2),
                })

        return alert_count, triggered_alerts, alert_misses
    except Exception:
        return 0, [], []


async def _get_user_watchlist(user: User, db: AsyncSession) -> list[str]:
    """Fetch user's watchlist or return guest default.

    Args:
        user: Current user
        db: Database session

    Returns:
        List of symbols to display
    """
    if not user:
        return GUEST_WATCHLIST

    try:
        from models.watchlist import WatchlistItem
        wres = await db.execute(
            select(WatchlistItem.symbol).where(WatchlistItem.user_id == user.id).limit(20)
        )
        user_syms = [r[0] for r in wres.all()]
        return user_syms if user_syms else GUEST_WATCHLIST
    except Exception:
        return GUEST_WATCHLIST


async def _get_top_movers(symbols: list[str]) -> tuple[list[dict], list[str]]:
    """Build movers data from watchlist symbols.

    Args:
        symbols: List of stock symbols to check

    Returns:
        (movers_list sorted by change_pct, misses_list)
    """
    movers = []
    mover_misses = []

    for sym in symbols[:10]:
        cached = await _fast_quote(sym)
        if cached:
            movers.append({
                "symbol": sym,
                "price": cached.get("price"),
                "change_pct": cached.get("change_pct"),
                "volume": cached.get("volume")
            })
        else:
            mover_misses.append(sym)
            movers.append({"symbol": sym, "price": None, "change_pct": None})

    movers.sort(key=lambda x: abs(x.get("change_pct") or 0), reverse=True)
    return movers, mover_misses


@router.get("")
async def get_dashboard(
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate market data for the dashboard.

    **Fast-response pattern:**
    1. Read ALL quotes from Redis cache (sub-ms, no external calls)
    2. Return immediately with whatever data is available
    3. If any symbols had cache misses, trigger background fetch
    4. Background fetch → cache → WS 'data_ready' → client re-fetches
    """
    # ── 1. Market indices (CACHE ONLY — instant) ─────────────────────────────
    indices, index_misses = await _fetch_indices_cached()

    # ── 2. Portfolio summary (auth only, CACHE-ONLY quotes) ──────────────────
    portfolio_summary, portfolio_misses = await _build_portfolio_summary(user, db)

    # ── 3. Active alerts count (CACHE-ONLY for proximity check) ──────────────
    alert_count, triggered_alerts, alert_misses = await _find_alerts_near_target(user, db)

    # ── 4. Watchlist movers (CACHE-ONLY) ──────────────────────────────────────
    watch_symbols = await _get_user_watchlist(user, db)
    movers, mover_misses = await _get_top_movers(watch_symbols)

    # ── 5. Trigger background fetch for ALL cache misses ──────────────────────
    all_misses = list(set(index_misses + portfolio_misses + alert_misses + mover_misses))
    if all_misses:
        logger.info("Dashboard: triggering background fetch for cache misses",
                     count=len(all_misses), symbols=all_misses[:5])
        asyncio.create_task(_ensure_quotes_cached(all_misses))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "indices": indices,
        "portfolio": portfolio_summary,
        "alert_count": alert_count,
        "alerts_near_target": triggered_alerts,
        "movers": movers,
        "has_pending_data": len(all_misses) > 0,
    }
