"""bd:deps-2026-09 WP-B5 — split from backend/api/routes/stocks.py (§2.1).
Pure file move: `GET /{symbol}/news`, `GET /{symbol}/events`.
"""
import json as _json
import re

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_optional_user
from core.database import get_db
from core.logger import get_logger
from models.user import User
from services import stock_service

router = APIRouter()
logger = get_logger(__name__)


@router.get("/{symbol}/news")
async def get_stock_news(
    symbol: str,
    _user: User | None = Depends(get_optional_user),
):
    """Get recent news for a symbol — pure-read (CQRS).

    Reads from Redis cache only. If cache miss, triggers Celery
    news_fetcher on-demand task and returns empty list. News is NOT
    user-specific — all users share the same cached results.

    Cache is populated by:
      1. Celery beat: prefetch_news (every 30 min for watched symbols)
      2. On-demand: fetch_news_on_demand (for symbols not in watchlists)
    """
    # ── 1. Clean symbol for cache lookup ──────────────────────────────────
    raw = symbol.upper().strip()
    clean = raw
    clean = re.sub(r"\^", "", clean)
    clean = re.sub(r"=X$", "", clean)
    clean = re.sub(r"=F$", "", clean)
    clean = re.sub(r"\.(BK|MAI|T|HK|SS|SZ|L|DE|PA|AS|KS)$", "", clean)
    clean = re.sub(r"[^A-Z0-9/\- ]", "", clean)

    if not clean or len(clean) < 1:
        return []

    # ── 2. Pure-read: Redis cache only ────────────────────────────────────
    cache_key = f"news:{clean}"
    try:
        r = await stock_service.get_redis()
        cached = await r.get(cache_key)
        if cached:
            return _json.loads(cached)
    except Exception:
        pass

    # ── 3. Cache miss → trigger Celery on-demand fetch (non-blocking) ─────
    try:
        r = await stock_service.get_redis()
        dedup_key = f"fetch_request:news:{clean}"
        was_set = await r.set(dedup_key, "1", ex=30, nx=True)
        if was_set:
            from workers.news_fetcher import fetch_news_on_demand
            fetch_news_on_demand.delay(symbol)
            logger.debug("News on-demand fetch triggered", symbol=clean)
    except Exception:
        pass

    # Return empty — frontend will retry or show "loading"
    return []


@router.get("/{symbol}/events")
async def get_stock_events(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get corporate events (XD, XR, earnings) for a symbol.

    Returns a list of events within the optional date range.
    If no date range is specified, returns events from 1 year ago to 6 months in the future.

    Event types: XD (ex-dividend), XR (ex-rights), EARNINGS, etc.
    """
    from datetime import date, timedelta

    from sqlalchemy import text

    # Default range: 1 year back, 6 months forward
    today = date.today()
    start = start_date or (today - timedelta(days=365)).isoformat()
    end = end_date or (today + timedelta(days=180)).isoformat()

    try:
        # Query stock_events table (raw SQL for flexibility)
        result = await db.execute(
            text(
                "SELECT id, symbol, event_type, event_date, value, description "
                "FROM stock_events WHERE symbol = :symbol AND event_date::date BETWEEN :start AND :end "
                "ORDER BY event_date"
            ),
            {"symbol": symbol.upper(), "start": start, "end": end},
        )
        rows = result.all()
        events = [
            {
                "id": row[0],
                "symbol": row[1],
                "event_type": row[2],
                "event_date": row[3].isoformat() if hasattr(row[3], 'isoformat') else str(row[3]),
                "value": float(row[4]) if row[4] else None,
                "description": row[5],
            }
            for row in rows
        ]
        return {"symbol": symbol.upper(), "events": events}
    except Exception as e:
        logger.error("Failed to fetch stock events", symbol=symbol, error=str(e))
        return {"symbol": symbol.upper(), "events": []}
