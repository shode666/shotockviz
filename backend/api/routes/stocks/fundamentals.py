"""bd:deps-2026-09 WP-B5 — split from backend/api/routes/stocks.py (§2.1).
Pure file move: `GET /{symbol}/fundamentals`, `GET /{symbol}/financials`,
`GET /{symbol}/earnings`.
"""
import json as _json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from api.middleware.auth import get_optional_user
from core.logger import get_logger
from models.schemas import StockFundamentals
from models.user import User
from services import stock_service

from ._shared import _is_yahoo_fetchable
from schemas.envelope import EnvelopingAPIRoute

# bd:deps-2026-09 S2 — route_class = envelope wrap (ADR-002); prefix comes
# from the parent (stocks/__init__.py, lifted /api/stocks -> /stocks).
router = APIRouter(route_class=EnvelopingAPIRoute)
logger = get_logger(__name__)


@router.get("/{symbol}/fundamentals", response_model=StockFundamentals)
async def get_fundamentals(
    symbol: str,
    _user: User | None = Depends(get_optional_user),
):
    """Get fundamental data for a stock — pure-read.

    Pure-read: reads from Redis cache ONLY. Never calls external APIs.
    Returns empty (all-null) fundamentals when data is unavailable in cache.
    For missing data, requests background fetch via Celery.
    """
    sym = symbol.upper()

    # Pure-read: Redis cache only
    data = await stock_service.read_fundamentals(sym)

    if not data:
        # No cache — request background fetch (only for Yahoo-resolvable symbols)
        if _is_yahoo_fetchable(sym):
            await stock_service.request_data_fetch(sym, "fundamentals")
        return StockFundamentals(symbol=sym)

    return StockFundamentals(**data)


@router.get("/{symbol}/financials")
async def get_financials_history(
    symbol: str,
    years: int = Query(10, ge=1, le=20, description="Number of years of history"),
    _user: User | None = Depends(get_optional_user),
):
    """Get 10-year financial history scorecard — pure-read.

    Returns annual revenue, net profit, ROE, D/E, EPS, dividends,
    gross margin, and operating margin for up to 10 fiscal years.
    """
    sym = symbol.upper()

    # Read from Redis cache
    cache_key = f"financials_history:{sym}"
    try:
        r = await stock_service.get_redis()
        cached = await r.get(cache_key)
        if cached:
            data = _json.loads(cached)
            return {"symbol": sym, "years": data[:years]}
    except Exception:
        pass

    # Read from PostgreSQL
    try:
        from core.database import AsyncSessionLocal
        from models.financial_history import FinancialHistory

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(FinancialHistory)
                .where(FinancialHistory.symbol == sym)
                .order_by(FinancialHistory.fiscal_year.desc())
                .limit(years)
            )
            rows = result.scalars().all()
            if rows:
                data = [
                    {
                        "fiscal_year": r.fiscal_year,
                        "revenue": float(r.revenue) if r.revenue else None,
                        "net_profit": float(r.net_profit) if r.net_profit else None,
                        "roe": float(r.roe) if r.roe else None,
                        "debt_equity": float(r.debt_equity) if r.debt_equity else None,
                        "eps": float(r.eps) if r.eps else None,
                        "dividend": float(r.dividend) if r.dividend else None,
                        "gross_margin": float(r.gross_margin) if r.gross_margin else None,
                        "operating_margin": float(r.operating_margin) if r.operating_margin else None,
                        "currency": r.currency,
                    }
                    for r in rows
                ]
                # Cache for 6 hours
                try:
                    redis_cache = await stock_service.get_redis()
                    await redis_cache.setex(cache_key, 21600, _json.dumps(data))
                except Exception:
                    pass
                return {"symbol": sym, "years": data}
    except Exception as e:
        logger.debug("Financials history DB error", symbol=sym, error=str(e))

    return {"symbol": sym, "years": []}


@router.get("/{symbol}/earnings")
async def get_earnings_events(
    symbol: str,
    limit: int = Query(8, ge=1, le=20, description="Number of recent earnings events"),
    _user: User | None = Depends(get_optional_user),
):
    """Get recent earnings events with EPS surprise and price impact — pure-read.

    Returns actual vs estimated EPS, surprise %, and 1-day price impact
    for chart marker overlays (green = beat, red = miss).
    """
    sym = symbol.upper()

    # Read from Redis cache
    cache_key = f"earnings:{sym}"
    try:
        r = await stock_service.get_redis()
        cached = await r.get(cache_key)
        if cached:
            data = _json.loads(cached)
            return {"symbol": sym, "earnings": data[:limit]}
    except Exception:
        pass

    # Read from PostgreSQL
    try:
        from core.database import AsyncSessionLocal
        from models.earnings_event import EarningsEvent

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EarningsEvent)
                .where(EarningsEvent.symbol == sym)
                .order_by(EarningsEvent.report_date.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            if rows:
                data = [
                    {
                        "report_date": r.report_date.isoformat(),
                        "fiscal_period": r.fiscal_period,
                        "estimated_eps": float(r.estimated_eps) if r.estimated_eps else None,
                        "actual_eps": float(r.actual_eps) if r.actual_eps else None,
                        "surprise_pct": float(r.surprise_pct) if r.surprise_pct else None,
                        "price_1d_before": float(r.price_1d_before) if r.price_1d_before else None,
                        "price_1d_after": float(r.price_1d_after) if r.price_1d_after else None,
                        "price_impact_pct": float(r.price_impact_pct) if r.price_impact_pct else None,
                    }
                    for r in rows
                ]
                # Cache for 6 hours
                try:
                    redis_cache = await stock_service.get_redis()
                    await redis_cache.setex(cache_key, 21600, _json.dumps(data))
                except Exception:
                    pass
                return {"symbol": sym, "earnings": data}
    except Exception as e:
        logger.debug("Earnings events DB error", symbol=sym, error=str(e))

    return {"symbol": sym, "earnings": []}
