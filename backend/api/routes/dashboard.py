"""Dashboard API — aggregated market overview for the personal investment assistant."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
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


@router.get("")
async def get_dashboard(
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate market data for the dashboard:
    - Market index quotes (SET, S&P500, NASDAQ, USD/THB, Gold)
    - Portfolio summary (authenticated users)
    - Active alert count
    - Watchlist movers
    """
    # ── 1. Market indices ────────────────────────────────────────────────────
    async def fetch_index(symbol: str):
        try:
            q = await stock_service.fetch_stock_quote(symbol)
            if q:
                return {
                    "symbol": symbol,
                    "price": q.price,
                    "change": q.change,
                    "change_pct": q.change_pct,
                }
        except Exception:
            pass
        return {"symbol": symbol, "price": None, "change": None, "change_pct": None}

    indices_tasks = [fetch_index(sym) for sym in INDEX_SYMBOLS.values()]
    indices_raw = await asyncio.gather(*indices_tasks, return_exceptions=True)
    indices = []
    for name, data in zip(INDEX_SYMBOLS.keys(), indices_raw):
        if isinstance(data, Exception):
            indices.append({"name": name, "symbol": list(INDEX_SYMBOLS.values())[list(INDEX_SYMBOLS.keys()).index(name)], "price": None, "change": None, "change_pct": None})
        else:
            indices.append({"name": name, **data})

    # ── 2. Portfolio summary (auth only) ─────────────────────────────────────
    portfolio_summary = None
    if user:
        try:
            result = await db.execute(
                select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
            )
            txns = result.scalars().all()
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

            total_value = 0.0
            total_cost = 0.0
            top_holdings = []
            quote_tasks = [stock_service.fetch_stock_quote(sym) for sym in active]
            quotes = await asyncio.gather(*quote_tasks, return_exceptions=True)
            for (sym, h), q in zip(active.items(), quotes):
                if isinstance(q, Exception) or not q:
                    continue
                val = q.price * h["qty"]
                cost = h["total_cost"]
                total_value += val
                total_cost += cost
                top_holdings.append({
                    "symbol": sym,
                    "value": round(val, 2),
                    "change_pct": q.change_pct,
                    "unrealized_pct": round((val - cost) / cost * 100, 2) if cost else 0,
                })
            top_holdings.sort(key=lambda x: x["value"], reverse=True)
            unrealized_pl = total_value - total_cost
            portfolio_summary = {
                "total_value": round(total_value, 2),
                "total_cost": round(total_cost, 2),
                "unrealized_pl": round(unrealized_pl, 2),
                "unrealized_pl_pct": round(unrealized_pl / total_cost * 100, 2) if total_cost else 0,
                "position_count": len(active),
                "top_holdings": top_holdings[:5],
            }
        except Exception as e:
            logger.warning("portfolio summary error", error=str(e))

    # ── 3. Active alerts count ───────────────────────────────────────────────
    alert_count = 0
    triggered_alerts = []
    if user:
        try:
            res = await db.execute(
                select(Alert).where(Alert.user_id == user.id, Alert.is_active == True)
            )
            alerts_list = res.scalars().all()
            alert_count = len(alerts_list)
            # Check which ones are close to triggering
            for a in alerts_list[:10]:
                q = await stock_service.fetch_stock_quote(a.symbol)
                if q:
                    diff_pct = abs(q.price - a.target_price) / a.target_price * 100
                    if diff_pct < 3:  # within 3% of target
                        triggered_alerts.append({
                            "symbol": a.symbol,
                            "condition": a.condition.value if hasattr(a.condition, 'value') else str(a.condition),
                            "target": a.target_price,
                            "current": q.price,
                            "diff_pct": round(diff_pct, 2),
                        })
        except Exception:
            pass

    # ── 4. Watchlist movers ──────────────────────────────────────────────────
    watch_symbols = GUEST_WATCHLIST
    if user:
        try:
            from models.watchlist import WatchlistItem
            wres = await db.execute(
                select(WatchlistItem.symbol).where(WatchlistItem.user_id == user.id).limit(20)
            )
            user_syms = [r[0] for r in wres.all()]
            if user_syms:
                watch_symbols = user_syms
        except Exception:
            pass

    mover_tasks = [stock_service.fetch_stock_quote(s) for s in watch_symbols[:10]]
    mover_quotes = await asyncio.gather(*mover_tasks, return_exceptions=True)
    movers = []
    for sym, q in zip(watch_symbols[:10], mover_quotes):
        if isinstance(q, Exception) or not q:
            movers.append({"symbol": sym, "price": None, "change_pct": None})
        else:
            movers.append({"symbol": sym, "price": q.price, "change_pct": q.change_pct, "volume": q.volume})
    movers.sort(key=lambda x: abs(x.get("change_pct") or 0), reverse=True)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "indices": indices,
        "portfolio": portfolio_summary,
        "alert_count": alert_count,
        "alerts_near_target": triggered_alerts,
        "movers": movers,
    }
