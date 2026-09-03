"""bd:deps-2026-09 WP-B5 — split from backend/api/routes/stocks.py (§2.1).
Pure file move: `GET /quotes` (static), `GET /{symbol}/quote` (dynamic).
🔴 Ordering constraint (same as original single-file router): `/quotes`
MUST be registered (defined via @router.get) BEFORE `/{symbol}/quote` in
THIS file — FastAPI matches routes in registration order, and
`/{symbol}/quote` would otherwise shadow-match a literal path segment
"quotes". Preserved below: `/quotes` handler comes first.
"""
import json as _json

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select

from core import cache_keys
from models.stock import Stock
from services import stock_service

from ._shared import _is_yahoo_fetchable

router = APIRouter()


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
