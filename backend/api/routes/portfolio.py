import asyncio
import json as _json
import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core import cache_keys
from models.user import User
from models.portfolio import Transaction
from models.schemas import (
    TransactionCreate, TransactionUpdate, TransactionResponse, PortfolioAnalytics, HoldingResponse,
)
from api.middleware.auth import get_current_user
from services import stock_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

# Yahoo Finance only accepts simple ticker symbols (letters, digits, dots, hyphens, carets).
# Thai mutual fund names like "SCBS&P500", "PRINCIPAL IPROP-D", "MPDIVMF" that contain
# spaces, &, or are known local-only funds will never resolve — skip them immediately
# rather than waiting for a 20 s Yahoo timeout.
_YAHOO_SYMBOL_RE = re.compile(r'^[\^]?[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,4})?$')

def _is_yahoo_fetchable(symbol: str) -> bool:
    """Return True if the symbol looks like a real Yahoo Finance ticker."""
    return bool(_YAHOO_SYMBOL_RE.match(symbol.upper()))


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

    # Calculate holdings: net qty and avg cost per symbol
    holdings: dict[str, dict] = {}
    for t in txns:
        if t.symbol not in holdings:
            holdings[t.symbol] = {"qty": 0.0, "total_cost": 0.0, "currency": getattr(t, "currency", "THB") or "THB"}
        if t.type.value == "BUY":
            holdings[t.symbol]["qty"] += t.qty
            holdings[t.symbol]["total_cost"] += t.qty * t.price
        else:  # SELL
            # Compute avg cost BEFORE reducing qty, then reduce cost basis proportionally
            avg = holdings[t.symbol]["total_cost"] / holdings[t.symbol]["qty"] if holdings[t.symbol]["qty"] else 0
            holdings[t.symbol]["qty"] -= t.qty
            holdings[t.symbol]["total_cost"] -= t.qty * avg
            # Guard against float drift leaving tiny residual qty
            if abs(holdings[t.symbol]["qty"]) < 1e-6:
                holdings[t.symbol]["qty"] = 0.0
                holdings[t.symbol]["total_cost"] = 0.0

    # Filter out sold positions
    active = {s: h for s, h in holdings.items() if h["qty"] > 0}

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

    holding_responses = []
    total_value = 0.0
    total_cost = 0.0

    for symbol, h in active.items():
        avg_cost = h["total_cost"] / h["qty"] if h["qty"] else 0
        quote = quote_map.get(symbol)
        current_price = float(quote["price"]) if quote and quote.get("price") is not None else None
        current_value = current_price * h["qty"] if current_price else None
        cost_basis = h["total_cost"]

        unrealized_pl = (current_value - cost_basis) if current_value is not None else None
        unrealized_pl_pct = (unrealized_pl / cost_basis * 100) if (unrealized_pl is not None and cost_basis) else None

        holding_responses.append(HoldingResponse(
            symbol=symbol,
            qty=h["qty"],
            avg_cost=round(avg_cost, 4),
            currency=h.get("currency", "THB"),
            current_price=current_price,
            current_value=round(current_value, 2) if current_value else None,
            unrealized_pl=round(unrealized_pl, 2) if unrealized_pl else None,
            unrealized_pl_pct=round(unrealized_pl_pct, 2) if unrealized_pl_pct else None,
        ))

        if current_value:
            total_value += current_value
        total_cost += cost_basis

    unrealized_pl = total_value - total_cost
    unrealized_pl_pct = round(unrealized_pl / total_cost * 100, 2) if total_cost else 0.0

    return PortfolioAnalytics(
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        unrealized_pl=round(unrealized_pl, 2),
        unrealized_pl_pct=unrealized_pl_pct,
        holdings=holding_responses,
        has_pending_prices=len(misses) > 0,
    )


@router.post("/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def add_transaction(
    body: TransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a buy or sell transaction."""
    txn = Transaction(
        user_id=user.id,
        symbol=body.symbol.upper(),
        type=body.type,
        qty=body.qty,
        price=body.price,
        fee=body.fee,
        currency=body.currency.upper() if body.currency else "THB",
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

    _ALLOWED_UPDATE_FIELDS = {"qty", "price", "fee", "currency", "date", "note"}
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
