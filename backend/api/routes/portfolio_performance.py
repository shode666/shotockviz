"""Portfolio equity-curve endpoint — appended to portfolio router."""
from __future__ import annotations
import asyncio
from datetime import date, timedelta, datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core.logger import get_logger
from models.user import User
from models.portfolio import Transaction
from api.middleware.auth import get_current_user
from services import stock_service
from schemas.envelope import EnvelopingAPIRoute

# bd:deps-2026-09 S2 (ADR-001 r3) — prefix lifted /api/portfolio -> /portfolio,
# mounted under /api/v1 in main.py. route_class = envelope wrap (ADR-002).
#
# bd:deps-2026-09 iter1 (CHRIS-10, AC-A2) — `portfolio.py` ALSO declares
# `APIRouter(prefix="/portfolio", ...)` and is mounted separately in
# main.py. Intentional: this file is a separable, later addition
# (equity-curve analytics only — see the module docstring above) kept out
# of portfolio.py's CRUD router rather than merged in. FastAPI merges
# same-prefix routers without collision (confirmed: no startup warning,
# both files' routes coexist under one effective `/api/v1/portfolio/*`
# surface) — see portfolio.py's matching cross-reference comment.
router = APIRouter(prefix="/portfolio", tags=["portfolio"], route_class=EnvelopingAPIRoute)
logger = get_logger(__name__)


@router.get("/performance")
async def get_portfolio_performance(
    period: Literal["1M", "3M", "6M", "1Y", "ALL"] = Query("6M"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Calculate portfolio equity curve.
    Returns daily portfolio value from the first transaction date
    up to today, calculated from stored OHLCV history.
    CQRS: reads from Redis/PostgreSQL cache only. No external API calls.
    """
    try:
        result = await db.execute(
            select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
        )
        txns = result.scalars().all()
    except Exception as e:
        logger.error("portfolio performance DB error", error=str(e))
        return {"points": [], "period": period}

    if not txns:
        return {"points": [], "period": period}

    today = date.today()
    period_map = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "ALL": 3650}
    days = period_map[period]
    start_date = today - timedelta(days=days)

    # Effective start: max of period start and first transaction date
    first_txn_date = min(t.date for t in txns) if txns else today
    if hasattr(first_txn_date, 'date'):
        first_txn_date = first_txn_date.date()
    effective_start = max(start_date, first_txn_date)

    # Get all unique symbols
    symbols = list({t.symbol for t in txns})

    # CQRS: read history from Redis/PostgreSQL cache only (no external API calls)
    history_map: dict[str, dict[str, float]] = {}
    hist_tasks = [stock_service.read_history(sym, "1D") for sym in symbols]
    try:
        histories = await asyncio.wait_for(
            asyncio.gather(*hist_tasks, return_exceptions=True),
            timeout=4.5,
        )
    except asyncio.TimeoutError:
        logger.warning("Portfolio performance history read timeout", symbols=symbols[:5])
        histories = [Exception("timeout")] * len(symbols)

    # Trigger background fetch for symbols with no cached history
    for sym, bars in zip(symbols, histories):
        if isinstance(bars, Exception) or not bars:
            # Request background fetch for missing history
            try:
                await stock_service.request_data_fetch(sym, "history")
            except Exception:
                pass
            continue
        history_map[sym] = {}
        for bar in bars:
            # Handle both dict and OHLCVBar objects
            if isinstance(bar, dict):
                bar_date = bar.get("time", "")
                bar_close = bar.get("close", 0)
            else:
                bar_date = bar.time if isinstance(bar.time, str) else str(bar.time)[:10]
                bar_close = bar.close
            # Normalize date string (strip time component if present)
            bar_date = str(bar_date)[:10]
            history_map[sym][bar_date] = float(bar_close)

    # Walk day by day and compute portfolio value
    def compute_holdings_on(target_date: date) -> dict[str, float]:
        """Calculate net qty per symbol from all txns up to target_date."""
        h: dict[str, float] = {}
        for t in txns:
            t_date = t.date if isinstance(t.date, date) else t.date.date()
            if t_date > target_date:
                break
            sym = t.symbol
            if sym not in h:
                h[sym] = 0.0
            h[sym] += t.qty if t.type.value == "BUY" else -t.qty
        return {s: q for s, q in h.items() if q > 0.001}

    points = []
    current = effective_start
    prev_holdings = {}

    while current <= today:
        date_str = current.isoformat()
        holdings = compute_holdings_on(current)

        total_value = 0.0
        priced = True
        for sym, qty in holdings.items():
            # Find closest available price (look back up to 5 days for weekends/holidays)
            price = None
            for lookback in range(5):
                check_date = (current - timedelta(days=lookback)).isoformat()
                if sym in history_map and check_date in history_map[sym]:
                    price = history_map[sym][check_date]
                    break
            if price is None:
                priced = False
                break
            total_value += price * qty

        if priced and holdings:
            points.append({"date": date_str, "value": round(total_value, 2)})

        current += timedelta(days=1)

    return {"points": points, "period": period, "symbols": symbols}
