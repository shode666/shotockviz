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

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])
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
    """
    result = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
    )
    txns = result.scalars().all()
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

    # Fetch daily history for each symbol (covers the full performance period)
    history_map: dict[str, dict[str, float]] = {}
    hist_tasks = [
        stock_service.fetch_stock_history(
            sym, "1D",
            from_ts=int(datetime.combine(effective_start, datetime.min.time()).timestamp()),
            to_ts=int(datetime.combine(today, datetime.max.time()).timestamp()),
        )
        for sym in symbols
    ]
    histories = await asyncio.gather(*hist_tasks, return_exceptions=True)
    for sym, bars in zip(symbols, histories):
        if isinstance(bars, Exception) or not bars:
            continue
        history_map[sym] = {}
        for bar in bars:
            bar_date = bar.time if isinstance(bar.time, str) else str(bar.time)[:10]
            history_map[sym][bar_date] = bar.close

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
