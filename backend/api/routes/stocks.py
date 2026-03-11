import asyncio
import json as _json
import re

from fastapi import APIRouter, Query, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from core.database import get_db
from core import cache_keys
from models.user import User
from models.stock import Stock
from models.schemas import StockQuote, StockHistory, StockFundamentals, OHLCVBar
from api.middleware.auth import get_optional_user
from services import stock_service
from core.logger import get_logger

router = APIRouter(prefix="/api/stocks", tags=["stocks"])
logger = get_logger(__name__)

VALID_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"}

# Yahoo Finance only accepts simple ticker symbols (letters, digits, dots, hyphens, carets).
# Thai mutual fund names like "SCBS&P500", "PRINCIPAL IPROP-D", "MPDIVMF" that contain
# spaces or & will never resolve — skip them to avoid 20s timeout per symbol.
_YAHOO_SYMBOL_RE = re.compile(r'^[\^]?[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,4})?$')

def _is_yahoo_fetchable(symbol: str) -> bool:
    """Return True if the symbol looks like a real Yahoo Finance ticker."""
    return bool(_YAHOO_SYMBOL_RE.match(symbol.upper()))


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
    """Batch name + market type lookup from the local DB.

    Returns ``{symbol: {name, market}}`` for every requested symbol.
    Symbols not found in the DB fall back to the raw symbol string with market=null.
    Used by the Sidebar to display company names instead of tickers,
    and to distinguish FUND symbols (show NAV) from stocks (show price).
    """
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:50]
    if not sym_list:
        return {}

    result = await db.execute(
        select(Stock.symbol, Stock.name, Stock.name_th, Stock.market)
        .where(Stock.symbol.in_(sym_list))
    )
    rows = result.all()

    # Build response: {symbol: {name, market}}
    name_map: dict[str, dict] = {sym: {"name": sym, "market": None} for sym in sym_list}
    for row in rows:
        # Prefer Thai name for .BK/.MAI symbols, English otherwise
        if row.symbol.endswith(".BK") or row.symbol.endswith(".MAI"):
            display_name = row.name_th or row.name or row.symbol
        else:
            display_name = row.name or row.symbol
        name_map[row.symbol] = {
            "name": display_name,
            "market": row.market.value if row.market else None,
        }

    # For symbols still showing raw ticker (not in local DB — e.g. US ETFs VOO, SCHD),
    # check Redis name cache populated by name_fetcher worker.
    db_misses = [sym for sym in sym_list if name_map[sym]["name"] == sym]
    if db_misses:
        try:
            r = await stock_service.get_redis()
            pipe = r.pipeline()
            for sym in db_misses:
                pipe.get(cache_keys.name(sym))
            name_values = await pipe.execute()
            for sym, cached_name in zip(db_misses, name_values):
                if cached_name:
                    name_map[sym]["name"] = cached_name
        except Exception:
            pass  # Redis unavailable — keep raw symbol as fallback

    return name_map


@router.get("/quotes")
async def get_quotes_batch(symbols: str = Query(..., description="Comma-separated symbols, e.g. NVDA,VOO,PTT.BK")):
    """Batch quote fetch — returns a dict {symbol: quote} for all requested symbols.

    Pure-read: reads from Redis cache ONLY. For cache misses, triggers background
    Celery fetch via request_data_fetch() without blocking.

    Strategy:
      1. Redis pipeline: check all symbols in ONE round-trip (sub-millisecond).
         In steady state Celery keeps the cache warm, so nearly all hits land here.
      2. Cache misses: request background fetch via Celery (non-blocking).
         Client gets notified via WebSocket 'data_ready' when quotes arrive.
    """
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:30]
    result: dict = {sym: None for sym in sym_list}

    # ── Stage 1: Redis pipeline (all symbols, one round-trip) ─────────────────
    misses = list(sym_list)
    try:
        r = await stock_service.get_redis()
        pipe = r.pipeline()
        for sym in sym_list:
            pipe.get(cache_keys.quote(sym))
        cached_values = await pipe.execute()

        misses = []
        for sym, raw in zip(sym_list, cached_values):
            if raw:
                try:
                    result[sym] = _json.loads(raw)
                except Exception:
                    misses.append(sym)
            else:
                misses.append(sym)
    except Exception:
        misses = list(sym_list)   # Redis down — return empty, request fetches

    # ── Stage 2: Check fund NAV cache for symbols still missing ─────────────
    # Thai mutual funds don't exist on Yahoo Finance, so check fund:{symbol} cache
    fund_misses = [sym for sym in misses if result[sym] is None]
    if fund_misses:
        try:
            r = await stock_service.get_redis()
            pipe = r.pipeline()
            for sym in fund_misses:
                pipe.get(cache_keys.fund(sym))
            fund_values = await pipe.execute()
            for sym, raw in zip(fund_misses, fund_values):
                if raw:
                    try:
                        fund_data = _json.loads(raw)
                        # Convert fund NAV to quote-like format for sidebar compatibility
                        result[sym] = {
                            "symbol": sym,
                            "price": fund_data.get("nav"),
                            "change": 0,
                            "change_pct": 0,
                            "volume": 0,
                            "type": "fund_nav",
                            "nav_date": fund_data.get("date"),
                            "ts": fund_data.get("ts", 0),
                        }
                        # Remove from misses since we found fund data
                        misses = [m for m in misses if m != sym]
                    except Exception:
                        pass
        except Exception:
            pass

    # ── Stage 3: Request background fetch for remaining misses ────────────
    # Instead of blocking, return cached data NOW and request BG fetch for misses.
    # Client gets notified via WebSocket 'data_ready' when quotes arrive.
    # Skip: (a) symbols with bad chars for Yahoo, (b) DB market=FUND symbols.
    if misses:
        # Check DB for FUND market type to avoid sending Thai mutual funds to Yahoo
        fund_symbols: set[str] = set()
        try:
            from core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as db_check:
                res = await db_check.execute(
                    select(Stock.symbol).where(
                        Stock.symbol.in_(misses),
                        Stock.market == "FUND",
                    )
                )
                fund_symbols = {r[0] for r in res.all()}
        except Exception:
            pass

        fetchable = [sym for sym in misses if _is_yahoo_fetchable(sym) and sym not in fund_symbols]
        for sym in fetchable:
            await stock_service.request_data_fetch(sym, "quote")

    return result


@router.get("/{symbol}/quote")
async def get_quote(symbol: str):
    """Get current stock quote — pure-read fast response pattern.

    Pure-read: reads from Redis cache ONLY. Never calls external APIs.

    1. Check Redis cache (sub-ms) → return immediately if available
    2. Cache miss → request background fetch (non-blocking)
    3. Return 202 pending status + trigger Celery fetch + WS notify when ready
    """
    sym = symbol.upper()

    # L1: Cache check (instant)
    quote = await stock_service.read_quote(sym)
    if quote:
        return JSONResponse(content=quote)

    # L1.5: Check fund NAV cache (Thai mutual funds)
    try:
        r = await stock_service.get_redis()
        fund_raw = await r.get(cache_keys.fund(sym))
        if fund_raw:
            fund_data = _json.loads(fund_raw)
            nav = fund_data.get("nav")
            if nav is not None:
                return JSONResponse(content={
                    "symbol": sym, "price": nav,
                    "change": 0, "change_pct": 0, "volume": 0,
                    "type": "fund_nav", "nav_date": fund_data.get("date"),
                })
    except Exception:
        pass

    # L2: No cache — request background fetch (non-blocking)
    # Only for Yahoo-fetchable symbols — Thai mutual funds won't resolve
    if _is_yahoo_fetchable(sym):
        await stock_service.request_data_fetch(sym, "quote")

    return JSONResponse(
        status_code=202,
        content={
            "status": "pending",
            "symbol": sym,
            "message": "กำลังดึงข้อมูล — จะแจ้งผ่าน WebSocket เมื่อพร้อม",
        },
    )


@router.get("/{symbol}/history", response_model=StockHistory)
async def get_history(
    symbol: str,
    timeframe: str = Query("1D", description="Timeframe: 1m,5m,15m,1h,4h,1D,1W,1M"),
    adjusted: bool = Query(False, description="Apply dividend/split adjustments"),
    _user: User | None = Depends(get_optional_user),
):
    """Get OHLCV history for a symbol and timeframe — pure-read.

    Pure-read: reads from Redis/PostgreSQL ONLY. Never calls external APIs.
    Fast-response: reads cache first (< 100ms).
    If data missing, requests background fetch and returns empty bars.
    Client gets WS 'data_ready' notification when bars are available.

    V2: Pass `adjusted=true` to apply dividend/split price adjustments.
    """
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timeframe. Choose from: {', '.join(VALID_TIMEFRAMES)}",
        )
    sym = symbol.upper()

    # Pure-read: Redis → PostgreSQL only
    bars = await stock_service.read_history(sym, timeframe)

    # Detect Thai mutual funds that have no chart data on Yahoo Finance
    is_fund = not _is_yahoo_fetchable(sym)

    if not bars and not is_fund:
        # No data — request background fetch with timeframe
        await stock_service.request_data_fetch(sym, "history", timeframe=timeframe)

    # V2: Apply corporate action adjustments if requested
    if adjusted and bars:
        from services.price_adjuster import adjust_prices
        bars = await adjust_prices(sym, bars)

    return StockHistory(symbol=sym, timeframe=timeframe, bars=bars, is_fund=is_fund)


@router.get("/{symbol}/rs")
async def get_relative_strength(
    symbol: str,
    benchmark: str = Query("^SET.BK", description="Benchmark index symbol"),
    timeframe: str = Query("1D", description="Timeframe for RS calculation"),
    period: int = Query(252, description="Lookback period in bars (252 = ~1 year daily)"),
    _user: User | None = Depends(get_optional_user),
):
    """Get Relative Strength (RS) line data for a symbol vs benchmark.

    RS measures whether a stock is outperforming or underperforming its benchmark.
    RS > 1.0 = outperforming, RS < 1.0 = underperforming.

    Calculation:
      RS = (symbol_close / symbol_close_N_ago) / (benchmark_close / benchmark_close_N_ago)

    Returns list of {time, value} points for charting as a separate panel.
    """
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timeframe. Choose from: {', '.join(VALID_TIMEFRAMES)}",
        )

    sym = symbol.upper()
    bench = benchmark.upper()

    # Read both symbol and benchmark history from cache
    symbol_bars = await stock_service.read_history(sym, timeframe)
    bench_bars = await stock_service.read_history(bench, timeframe)

    # Request background fetch if missing
    if not symbol_bars:
        await stock_service.request_data_fetch(sym, "history", timeframe=timeframe)
    if not bench_bars:
        await stock_service.request_data_fetch(bench, "history", timeframe=timeframe)

    if not symbol_bars or not bench_bars:
        return {"symbol": sym, "benchmark": bench, "timeframe": timeframe, "rs": []}

    # Build close price lookup for benchmark (time → close)
    bench_map = {}
    for b in bench_bars:
        bench_map[b.get("time") if isinstance(b, dict) else b.time] = (
            float(b.get("close") if isinstance(b, dict) else b.close)
        )

    # Calculate RS line
    rs_data = []
    lookback = min(period, len(symbol_bars))

    for i in range(lookback, len(symbol_bars)):
        bar = symbol_bars[i]
        bar_time = bar.get("time") if isinstance(bar, dict) else bar.time
        bar_close = float(bar.get("close") if isinstance(bar, dict) else bar.close)

        ref_bar = symbol_bars[i - lookback]
        ref_close = float(ref_bar.get("close") if isinstance(ref_bar, dict) else ref_bar.close)

        # Find matching benchmark bars
        bench_close = bench_map.get(bar_time)
        ref_time = ref_bar.get("time") if isinstance(ref_bar, dict) else ref_bar.time
        bench_ref_close = bench_map.get(ref_time)

        if bench_close and bench_ref_close and ref_close > 0 and bench_ref_close > 0:
            symbol_return = bar_close / ref_close
            bench_return = bench_close / bench_ref_close
            rs_value = symbol_return / bench_return if bench_return > 0 else 1.0

            rs_data.append({"time": bar_time, "value": round(rs_value, 4)})

    return {
        "symbol": sym,
        "benchmark": bench,
        "timeframe": timeframe,
        "period": lookback,
        "rs": rs_data,
    }


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
