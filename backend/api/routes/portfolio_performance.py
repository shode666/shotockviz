"""Portfolio equity-curve endpoint — appended to portfolio router.

bd:shotockviz-la4 — this is the THIRD `/portfolio` surface, and it was the last
one still adding currencies raw: `total_value += price * qty` over every held
symbol with no conversion at all, feeding the Dashboard equity sparkline. The
same book's header total right next to it was correctly normalised to THB
(bd:shotockviz-sbe), so the two disagreed on the same screen.

It now converts through `services/portfolio_service.py` like the other two, at
the same rates from the same `build_fx_rates`. What it CANNOT do is convert each
day at that day's rate: that needs historical FX, the user's standing decision is
that historical rates are not backfilled (rule 4 / FX-1), and this codebase does
not invent them. So the curve is stated on the only honest basis left and says
which one, in the payload:

    fx_basis = "constant_current_rate"
        A mixed book. Every day is converted at ONE rate — today's. The line
        shows how the MARKET moved; it deliberately does not contain currency
        return, and its historical levels are NOT what the book was worth in THB
        on those dates. `fx_rates` / `fx_estimated` say which rate and how good
        it is. (Constant-currency reporting — declared, not implied.)

    fx_basis = "single_currency"
        The whole book is in the base currency. No conversion, nothing to
        qualify. The common Thai case.

A day on which any held symbol cannot be priced, cannot be converted, or has
conflicting currencies (rule 5) is omitted from the curve entirely rather than
valued partially — dropping a position out of a time series makes the line fall,
which reads as a loss that never happened.
"""
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
from api.routes.portfolio import fx_quote_cached
from services import portfolio_service, stock_service
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


def _empty(period: str) -> dict:
    """No curve, but the same shape — the client never has to guess a key."""
    return {
        "points": [],
        "period": period,
        "base_currency": portfolio_service.BASE_CURRENCY,
        "fx_basis": portfolio_service.CURVE_BASIS_SINGLE_CURRENCY,
        "fx_rates": [],
        "fx_estimated": False,
        "fx_unavailable_symbols": [],
        "currency_conflict_symbols": [],
        "excluded_symbols": [],
        "symbols": [],
    }


@router.get("/performance")
async def get_portfolio_performance(
    period: Literal["1M", "3M", "6M", "1Y", "ALL"] = Query("6M"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Calculate portfolio equity curve, stated in `base_currency`.

    Returns daily portfolio value from the first transaction date up to today,
    from stored OHLCV history. Every point is converted through
    `portfolio_service` on the basis reported by `fx_basis` — see the module
    docstring (bd:shotockviz-la4) for what a `constant_current_rate` curve does
    and does not claim.

    CQRS: reads from Redis/PostgreSQL cache only. No external API calls.
    """
    try:
        result = await db.execute(
            select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
        )
        txns = result.scalars().all()
    except Exception as e:
        logger.error("portfolio performance DB error", error=str(e))
        return _empty(period)

    if not txns:
        return _empty(period)

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

    # bd:shotockviz-la4 — one rate per symbol, fixed for the whole curve, from
    # the same `build_fx_rates` the other two `/portfolio` surfaces use, read
    # through the same cache-only path (`fx_quote_cached`). A symbol that cannot
    # be converted, or whose rows mix currencies (rule 5), is excluded by name
    # and excludes every day it is held on.
    plan = portfolio_service.curve_fx_plan(
        portfolio_service.build_holdings(txns),
        portfolio_service.build_fx_rates(txns, await fx_quote_cached()),
    )
    excluded = set(plan.fx_unavailable_symbols) | set(plan.currency_conflict_symbols)
    if excluded:
        logger.warning(
            "equity curve excluding symbols",
            fx_unavailable=plan.fx_unavailable_symbols,
            currency_conflict=plan.currency_conflict_symbols,
        )

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
        statable = True
        for sym, qty in holdings.items():
            # bd:shotockviz-la4 — an unconvertible symbol invalidates the whole
            # DAY, not just its own term. Silently dropping it would make the
            # line fall on the day it appears, which reads as a realised loss.
            rate = plan.rate_by_symbol.get(sym)
            if rate is None:
                statable = False
                break
            # Find closest available price (look back up to 5 days for weekends/holidays)
            price = None
            for lookback in range(5):
                check_date = (current - timedelta(days=lookback)).isoformat()
                if sym in history_map and check_date in history_map[sym]:
                    price = history_map[sym][check_date]
                    break
            if price is None:
                statable = False
                break
            # `price` is in the symbol's own currency; `rate` is base per unit of
            # it. This multiplication is the whole bead: the line above used to
            # be `total_value += price * qty` for THB and USD alike.
            total_value += price * qty * rate

        if statable and holdings:
            points.append({"date": date_str, "value": round(total_value, 2)})

        current += timedelta(days=1)

    return {
        "points": points,
        "period": period,
        "symbols": symbols,
        # ── what the numbers above mean (bd:shotockviz-la4) ──────────────────
        "base_currency": plan.base_currency,
        "fx_basis": plan.basis,
        "fx_rates": [
            {
                "currency": r.currency, "base": r.base, "rate": round(r.rate, 6),
                "source": r.source, "as_of": r.as_of, "estimated": r.estimated,
                "quote_orientation": r.quote_orientation,
            }
            for r in plan.fx_rates.values()
        ],
        "fx_estimated": plan.fx_estimated,
        "fx_unavailable_symbols": plan.fx_unavailable_symbols,
        "currency_conflict_symbols": plan.currency_conflict_symbols,
        "excluded_symbols": sorted(excluded),
    }
