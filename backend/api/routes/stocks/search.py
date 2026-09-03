"""bd:deps-2026-09 WP-B5 — split from backend/api/routes/stocks.py (§2.1).
Pure file move: `GET /search`, `GET /names` handler bodies unchanged.
Static paths — must be included BEFORE any `/{symbol}/*` sub-router in
`api/routes/stocks/__init__.py` (routing-order constraint, see that file).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_optional_user
from core import cache_keys
from core.database import get_db
from models.stock import Stock
from models.user import User
from services import stock_service
from schemas.envelope import EnvelopingAPIRoute

# bd:deps-2026-09 S2 — route_class = envelope wrap (ADR-002); prefix comes
# from the parent (stocks/__init__.py, lifted /api/stocks -> /stocks).
router = APIRouter(route_class=EnvelopingAPIRoute)


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
