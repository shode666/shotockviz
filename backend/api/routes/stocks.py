import asyncio

from fastapi import APIRouter, Query, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from core.database import get_db
from models.user import User
from models.stock import Stock
from models.schemas import StockQuote, StockHistory, StockFundamentals, OHLCVBar
from api.middleware.auth import get_optional_user
from services import stock_service

router = APIRouter(prefix="/api/stocks", tags=["stocks"])

VALID_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"}


@router.get("/search")
async def search_stocks(
    q: str = Query(..., min_length=1, max_length=50),
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_optional_user),
):
    """Search stocks by symbol, English name, or Thai name.

    Priority order:
      1. Exact symbol match  (highest relevance)
      2. Symbol prefix match
      3. Thai name (name_th) contains q
      4. English name contains q
      5. Yahoo Finance symbol search (fallback for unlisted symbols)
    """
    q_strip = q.strip()

    # ── L1: Local DB full-text search ────────────────────────────────────────
    result = await db.execute(
        select(Stock).where(
            Stock.is_active == True,
            or_(
                Stock.symbol.ilike(f"%{q_strip}%"),
                Stock.name.ilike(f"%{q_strip}%"),
                # Thai name search — critical for กองทุน / SET stocks
                Stock.name_th.ilike(f"%{q_strip}%"),
            )
        ).limit(20)  # Fetch more, we rank below
    )
    stocks = result.scalars().all()

    if stocks:
        # ── Rank results ──────────────────────────────────────────────────────
        # Score: exact symbol (100) > symbol prefix (80) > name_th match (60) > name match (40)
        def _score(s: Stock) -> int:
            sym_upper = s.symbol.upper()
            q_upper   = q_strip.upper()
            if sym_upper == q_upper:                          return 100
            if sym_upper.startswith(q_upper):                 return 80
            if s.name_th and q_strip in s.name_th:           return 70
            if s.name_th and q_strip.lower() in s.name_th.lower(): return 65
            if q_upper in sym_upper:                          return 60
            return 40

        ranked = sorted(stocks, key=_score, reverse=True)[:10]
        return [
            {
                "symbol":  s.symbol,
                "name":    s.name,
                "name_th": s.name_th,
                "market":  s.market.value,
            }
            for s in ranked
        ]

    # ── L2: Yahoo Finance symbol search (for US stocks not in local DB) ───────
    yf_results = await stock_service.search_stocks(q_strip)
    if yf_results:
        return yf_results

    # Return empty list instead of 404 — frontend handles gracefully
    return []


@router.get("/names")
async def get_stock_names(
    symbols: str = Query(..., description="Comma-separated list of symbols, e.g. PTT.BK,AAPL,NVDA"),
    db: AsyncSession = Depends(get_db),
):
    """Batch name lookup from the local DB.

    Returns ``{symbol: name}`` for every requested symbol.
    Symbols not found in the DB fall back to the raw symbol string.
    Used by the Sidebar to display company names instead of tickers.
    """
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:50]
    if not sym_list:
        return {}

    result = await db.execute(
        select(Stock.symbol, Stock.name, Stock.name_th)
        .where(Stock.symbol.in_(sym_list))
    )
    rows = result.all()

    name_map: dict[str, str] = {sym: sym for sym in sym_list}  # default: symbol itself
    for row in rows:
        # Prefer Thai name for .BK/.MAI symbols, English otherwise
        if row.symbol.endswith(".BK") or row.symbol.endswith(".MAI"):
            name_map[row.symbol] = row.name_th or row.name or row.symbol
        else:
            name_map[row.symbol] = row.name or row.symbol

    return name_map


@router.get("/{symbol}/quote")
async def get_quote(symbol: str):
    """Get current stock quote — served from Redis cache only.

    Returns the cached quote if available, or {"status": "pending"} with
    HTTP 202 if the background worker hasn't fetched the symbol yet.
    External APIs are never called inside this request.
    """
    quote = await stock_service.fetch_stock_quote(symbol.upper())
    if not quote:
        # Background fetch has been triggered — tell the client to retry
        return JSONResponse(
            status_code=202,
            content={"status": "pending", "symbol": symbol.upper(),
                     "message": "Data is being fetched. Retry in a few seconds."},
        )
    return quote


@router.get("/{symbol}/history", response_model=StockHistory)
async def get_history(
    symbol: str,
    tf: str = Query("1D", description="Timeframe: 1m,5m,15m,1h,4h,1D,1W,1M"),
    _user: User | None = Depends(get_optional_user),
):
    """Get OHLCV history for a symbol and timeframe."""
    if tf not in VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timeframe. Choose from: {', '.join(VALID_TIMEFRAMES)}",
        )
    bars = await stock_service.fetch_stock_history(symbol.upper(), tf)
    return StockHistory(symbol=symbol.upper(), timeframe=tf, bars=bars)


@router.get("/{symbol}/fundamentals", response_model=StockFundamentals)
async def get_fundamentals(
    symbol: str,
    _user: User | None = Depends(get_optional_user),
):
    """Get fundamental data for a stock.

    Returns empty (all-null) fundamentals when data is unavailable (e.g. Yahoo
    Finance rate-limiting) so the frontend shows '—' instead of an error state.
    """
    data = await stock_service.fetch_stock_fundamentals(symbol.upper())
    if not data:
        # Return shell object with null fields — 200 keeps the frontend quiet
        return StockFundamentals(symbol=symbol.upper())
    return data


@router.get("/{symbol}/news")
async def get_stock_news(
    symbol: str,
    _user: User | None = Depends(get_optional_user),
):
    """Get recent news for a symbol via RSS."""
    import feedparser
    query = symbol.replace(".BK", "") + " stock"
    url = f"https://news.google.com/rss/search?q={query}&hl=th&gl=TH&ceid=TH:th"
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:10]:
            items.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "source": entry.get("source", {}).get("title", "Google News"),
                "published_at": entry.get("published", ""),
                "summary": entry.get("summary", ""),
            })
        return items
    except Exception:
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
