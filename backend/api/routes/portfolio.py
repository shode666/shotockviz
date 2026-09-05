import asyncio
import json as _json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core import cache_keys
from models.user import User
from models.portfolio import Transaction
from models.schemas import (
    TransactionCreate, TransactionUpdate, TransactionResponse, PortfolioAnalytics,
    HoldingResponse, FxRateInfo,
)
from api.middleware.auth import get_current_user
from services import portfolio_service, stock_service
from schemas.envelope import EnvelopingAPIRoute

# bd:deps-2026-09 S2 (ADR-001 r3) — prefix lifted /api/portfolio -> /portfolio,
# mounted under /api/v1 in main.py. route_class = envelope wrap (ADR-002).
#
# bd:deps-2026-09 iter1 (CHRIS-10, AC-A2) — `portfolio_performance.py`
# ALSO declares `APIRouter(prefix="/portfolio", ...)` and is mounted
# separately in main.py (both under the same /api/v1 aggregate). This is
# intentional, not a collision: FastAPI merges same-prefix routers fine
# (no startup warning, no route shadowing — confirmed, this file's routes
# and portfolio_performance.py's `/equity-curve` route coexist under one
# effective `/api/v1/portfolio/*` surface); kept as two files instead of
# one merge because portfolio_performance.py is a later, separable
# addition (equity-curve analytics) with its own imports/logger, not CRUD
# — see that file's matching cross-reference comment.
router = APIRouter(prefix="/portfolio", tags=["portfolio"], route_class=EnvelopingAPIRoute)

# Yahoo Finance only accepts simple ticker symbols (letters, digits, dots, hyphens, carets).
# Thai mutual fund names like "SCBS&P500", "PRINCIPAL IPROP-D", "MPDIVMF" that contain
# spaces, &, or are known local-only funds will never resolve — skip them immediately
# rather than waiting for a 20 s Yahoo timeout.
_YAHOO_SYMBOL_RE = re.compile(r'^[\^]?[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,4})?$')

def _is_yahoo_fetchable(symbol: str) -> bool:
    """Return True if the symbol looks like a real Yahoo Finance ticker."""
    return bool(_YAHOO_SYMBOL_RE.match(symbol.upper()))


async def _fx_quote_cached() -> dict | None:
    """Cache-only read of the FX quote (`THBUSD=X`). None on miss — never fetch.

    Its own pipeline round-trip so a cold/absent FX rate can never disturb the
    holdings pipelines above it.
    """
    try:
        r = await stock_service.get_redis()
        pipe = r.pipeline()
        pipe.get(cache_keys.quote(portfolio_service.FX_QUOTE_SYMBOL))
        raw = (await pipe.execute())[0]
        return _json.loads(raw) if raw else None
    except Exception:
        return None


async def _record_fx_rate(currency: str, txn_date, explicit: float | None) -> float | None:
    """The rate to stamp on a new transaction (bd:shotockviz-fnn, rule FX-1).

    Order:
      1. THB -> 1.0 by definition; the base currency has no exchange rate and a
         client cannot override that;
      2. an explicit client-supplied rate (the user knows their fill rate) — kept
         even for a back-dated trade, because it is an observation, not a guess;
      3. the live cached rate, but ONLY for a contemporaneous trade;
      4. otherwise None.

    (3)'s date guard is the point. Stamping today's rate onto a trade dated six
    months ago would look like a recorded historical rate and would silently
    poison the FX return — the same class of bug as the 33.0 constant. The
    tolerance is one day because a US fill at 02:00 ICT belongs to the previous
    US session date. ICT is `utc + 7h`, the convention already used in
    `workers/fund_fetcher.py:146`.
    """
    if currency.upper() == portfolio_service.BASE_CURRENCY:
        return 1.0
    if explicit is not None:
        return float(explicit)

    today_ict = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    if txn_date is None or abs((today_ict - txn_date).days) > 1:
        return None  # back-dated: no observed rate exists, and none is invented

    return portfolio_service.live_rate_from_thbusd(await _fx_quote_cached())


@router.get("", response_model=list[TransactionResponse])
async def get_transactions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all transactions for the current user."""
    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.date.desc())
    )
    return result.scalars().all()


@router.get("/analytics", response_model=PortfolioAnalytics)
async def get_analytics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Calculate portfolio analytics with current market prices."""
    try:
        result = await db.execute(
            select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
        )
        txns = result.scalars().all()
    except Exception as e:
        # Likely DB schema mismatch (e.g. migration not yet run) — return empty analytics
        import logging
        logging.getLogger(__name__).error(f"portfolio analytics DB error: {e}")
        return PortfolioAnalytics(
            total_value=0.0, total_cost=0.0,
            unrealized_pl=0.0, unrealized_pl_pct=0.0,
            holdings=[],
        )

    # Calculate holdings: net qty and avg cost per symbol.
    # bd:shotockviz-msg — one shared computation with dashboard.py (commission
    # in cost basis on BUY, realized on SELL: bd:shotockviz-fww). See
    # services/portfolio_service.py for the accounting rules.
    holdings = portfolio_service.build_holdings(txns)

    # Filter out sold positions
    active = portfolio_service.active_holdings(holdings)

    # Enrich with current prices.
    # Three-stage strategy:
    #   0. Pre-filter: skip symbols that Yahoo Finance can never resolve (Thai mutual funds
    #      with spaces / special chars like "SCBS&P500", "PRINCIPAL IPROP-D", "MPDIVMF").
    #      These would wait the full 20 s httpx timeout on every cold start — skip them now.
    #   1. Redis pipeline: check remaining symbols in one round-trip (sub-ms).
    #   2. Fetch only true cache misses from Yahoo Finance in parallel.
    symbols_list = list(active.keys())
    # Use simple dict {price, change_pct, ...} instead of StockQuote to handle
    # the simplified JSON format cached by on_demand_listener and price_fetcher.
    quote_map: dict[str, dict | None] = {sym: None for sym in symbols_list}

    # Stage 1: Redis pipeline — check quote:{symbol} for ALL symbols in one round-trip
    misses = list(symbols_list)
    try:
        r = await stock_service.get_redis()
        pipe = r.pipeline()
        for sym in symbols_list:
            pipe.get(cache_keys.quote(sym))
        cached_values = await pipe.execute()

        misses = []
        for sym, raw in zip(symbols_list, cached_values):
            if raw:
                try:
                    data = _json.loads(raw)
                    if data.get("price") is not None:
                        quote_map[sym] = data
                    else:
                        misses.append(sym)
                except Exception:
                    misses.append(sym)
            else:
                misses.append(sym)
    except Exception:
        misses = list(symbols_list)

    # Stage 2: For remaining misses, check fund:{symbol} cache (Thai mutual funds)
    fund_misses = list(misses)
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
                        nav = fund_data.get("nav")
                        if nav is not None:
                            quote_map[sym] = {
                                "symbol": sym, "price": float(nav),
                                "change": 0.0, "change_pct": 0.0, "volume": 0,
                                "type": "fund_nav",
                            }
                            misses = [m for m in misses if m != sym]
                    except Exception:
                        pass
        except Exception:
            pass

    # Stage 3: Request background fetch for fetchable misses (skip unfetchable fund symbols)
    if misses:
        fetchable_misses = [sym for sym in misses if _is_yahoo_fetchable(sym)]
        for sym in fetchable_misses:
            await stock_service.request_data_fetch(sym, "quote")

    # Stage 4: the FX rate itself (bd:shotockviz-fnn). Cache-only, like every
    # other read on this route; a cold THBUSD=X is normal off-hours and is what
    # used to silently become the hardcoded 33.0 on the dashboard.
    fx_quote = await _fx_quote_cached()
    fx_rates = portfolio_service.build_fx_rates(txns, fx_quote)
    if any(r.source != "live" for r in fx_rates.values()):
        # Warm it for the next load. Bypasses _is_yahoo_fetchable on purpose:
        # "THBUSD=X" contains '=' and would never pass that ticker regex, but it
        # is the symbol dashboard.py already fetches through the same path.
        try:
            await stock_service.request_data_fetch(portfolio_service.FX_QUOTE_SYMBOL, "quote")
        except Exception:
            pass

    # bd:shotockviz-2w8 — an unpriced position is excluded from BOTH sides of the
    # total (never valued at zero against a full cost basis, which fabricated a
    # loss equal to the whole position). It still returns as a row with
    # current_price=None, and has_pending_prices flags it.
    #
    # bd:shotockviz-sbe — the totals below used to be a raw sum of THB and USD
    # amounts while the dashboard normalised to THB, so the two screens stated
    # different numbers for the same book and the header total of a mixed book
    # meant nothing. Both now go through the same `fx` resolver.
    valued = portfolio_service.value_holdings(
        active, quote_map, fx=portfolio_service.fx_resolver(fx_rates)
    )
    totals = portfolio_service.summarize(valued)

    holding_responses = [
        HoldingResponse(
            symbol=v.symbol,
            qty=v.qty,
            avg_cost=round(v.avg_cost, 4),
            currency=v.currency,
            current_price=v.current_price,
            # `is not None`, not truthiness: a legitimate 0.0 P&L is a real
            # answer, not a missing one.
            current_value=round(v.current_value, 2) if v.current_value is not None else None,
            unrealized_pl=round(v.unrealized_pl, 2) if v.unrealized_pl is not None else None,
            unrealized_pl_pct=round(v.unrealized_pl_pct, 2) if v.unrealized_pl_pct is not None else None,
            base_currency=v.base_currency,
            fx_rate=round(v.fx_rate, 6) if v.fx_rate is not None else None,
            fx_source=v.fx_source,
            fx_estimated=v.fx_estimated,
            cost_basis_base=round(v.cost_basis_base, 2) if v.cost_basis_base is not None else None,
            cost_basis_source=v.cost_basis_source,
            current_value_base=round(v.current_value_base, 2) if v.current_value_base is not None else None,
            unrealized_pl_base=round(v.unrealized_pl_base, 2) if v.unrealized_pl_base is not None else None,
            unrealized_pl_pct_base=round(v.unrealized_pl_pct_base, 2) if v.unrealized_pl_pct_base is not None else None,
            market_pl_base=round(v.market_pl_base, 2) if v.market_pl_base is not None else None,
            # None stays None: "we cannot separate the currency move for this
            # position", which is not the same statement as "it was zero".
            fx_pl_base=round(v.fx_pl_base, 2) if v.fx_pl_base is not None else None,
        )
        for v in valued
    ]

    return PortfolioAnalytics(
        base_currency=totals.base_currency,
        total_value=round(totals.total_value, 2),
        total_cost=round(totals.total_cost, 2),
        unrealized_pl=round(totals.unrealized_pl, 2),
        unrealized_pl_pct=round(totals.unrealized_pl_pct, 2),
        market_pl=round(totals.market_pl, 2),
        fx_pl=round(totals.fx_pl, 2) if totals.fx_pl is not None else None,
        fx_estimated=totals.fx_estimated,
        cost_basis_estimated=totals.cost_basis_estimated,
        fx_rates=[
            FxRateInfo(
                currency=r.currency, base=r.base, rate=round(r.rate, 6),
                source=r.source, as_of=r.as_of, estimated=r.estimated,
            )
            for r in totals.fx_rates.values()
        ],
        fx_unavailable_symbols=totals.fx_unavailable_symbols,
        holdings=holding_responses,
        # Derived from the positions actually left unpriced (a cache "miss" that
        # the fund stage then resolved is not pending; a cached but unusable
        # price is).
        has_pending_prices=bool(totals.unpriced_symbols),
    )


@router.post("/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def add_transaction(
    body: TransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a buy or sell transaction."""
    currency = body.currency.upper() if body.currency else "THB"
    txn = Transaction(
        user_id=user.id,
        symbol=body.symbol.upper(),
        type=body.type,
        qty=body.qty,
        price=body.price,
        fee=body.fee,
        currency=currency,
        # bd:shotockviz-fnn — record the rate now; NULL when none can honestly
        # be observed for this trade date. See _record_fx_rate.
        fx_rate=await _record_fx_rate(currency, body.date, body.fx_rate),
        date=body.date,
        note=body.note,
    )
    db.add(txn)
    await db.flush()
    await db.refresh(txn)

    # Fire-and-forget: ensure symbol is registered in stocks table
    try:
        from workers.symbol_registrar import register_symbol
        register_symbol.delay(body.symbol.upper())
    except Exception:
        pass  # Non-critical — scan_unregistered will catch it later

    return txn


@router.put("/transactions/{txn_id}", response_model=TransactionResponse)
async def update_transaction(
    txn_id: int,
    body: TransactionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing transaction."""
    result = await db.execute(
        select(Transaction).where(Transaction.id == txn_id, Transaction.user_id == user.id)
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    # `fx_rate` is settable here so a user can correct/supply the real fill rate
    # of an older trade — the only route by which a back-dated foreign position
    # ever regains its FX return. It is never *recomputed* as a side effect of
    # editing qty/price/date: a rate is an observation, not a derived field.
    _ALLOWED_UPDATE_FIELDS = {"qty", "price", "fee", "currency", "date", "note", "fx_rate"}
    for field, val in body.model_dump(exclude_unset=True).items():
        if field not in _ALLOWED_UPDATE_FIELDS:
            continue
        setattr(txn, field, val)
    return txn


@router.delete("/transactions/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    txn_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a transaction."""
    result = await db.execute(
        select(Transaction).where(Transaction.id == txn_id, Transaction.user_id == user.id)
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    await db.delete(txn)
