import asyncio
import json as _json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core import cache_keys
from core.symbol_utils import ambiguous_bare_symbol_detail, is_ambiguous_bare_thai_symbol
from models.user import User
from models.portfolio import Transaction
from models.schemas import (
    TransactionCreate, TransactionUpdate, TransactionResponse, PortfolioAnalytics,
    HoldingResponse, FxRateInfo, ClosedPositionResponse, RealizedBookResponse,
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


async def fx_quote_cached() -> dict | None:
    """Cache-only read of the FX quote (`THBUSD=X`). None on miss — never fetch.

    Its own pipeline round-trip so a cold/absent FX rate can never disturb the
    holdings pipelines above it.

    Public (was `_fx_quote_cached`) because `portfolio_performance.py` — the
    third `/portfolio` surface, bd:shotockviz-la4 — must read the rate through
    exactly this path. A second copy of "how the FX quote is read" is how the
    three screens disagreed in the first place.
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

    return portfolio_service.live_rate_from_thbusd(await fx_quote_cached())


async def _assert_currency_consistent(
    db: AsyncSession,
    user_id: int,
    symbol: str,
    currency: str,
    exclude_txn_id: int | None = None,
) -> None:
    """Reject a transaction that would put one symbol in two currencies.

    bd:shotockviz-7ju / portfolio_service rule 5. `build_holdings` sums a
    symbol's rows into ONE `cost_basis`; if the rows are in different currencies
    that sum is not a number, and the FX conversion downstream inherits the
    error rather than causing it. The read path can only refuse to state such a
    position after the fact — this is where it is prevented.

    Judged over ALL of the symbol's rows (including fully-closed lots), matching
    what the read path flags, so the two paths cannot disagree about whether a
    book is broken. A genuine re-denomination means correcting the old rows.
    """
    stmt = select(Transaction.currency).where(
        Transaction.user_id == user_id,
        Transaction.symbol == symbol,
    )
    if exclude_txn_id is not None:
        stmt = stmt.where(Transaction.id != exclude_txn_id)

    existing = {
        getattr(c, "value", c) for c in (await db.execute(stmt.distinct())).scalars().all()
    }
    conflicting = sorted(existing - {currency})
    if conflicting:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{symbol} ถูกบันทึกไว้เป็นสกุล {'/'.join(conflicting)} อยู่แล้ว "
                f"— เพิ่มรายการสกุล {currency} จะทำให้ต้นทุนของสัญลักษณ์เดียวกันปนหน่วยเงิน "
                "และยอดรวมจะไม่มีความหมาย กรุณาแก้สกุลเงินให้ตรงกัน "
                "หรือแก้/ลบรายการเดิมก่อน"
            ),
        )


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
    fx_quote = await fx_quote_cached()
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

    # bd:shotockviz-tmz — the closed side. Built from `holdings` (ALL symbols,
    # including the fully-closed ones `active_holdings` drops) by the same fold
    # that produced the open positions above, so cost released and cost still
    # held cannot drift apart. Summary only here; the per-trade log is
    # GET /portfolio/realized so this hot path does not grow with trade history.
    realized = portfolio_service.build_realized(holdings)

    holding_responses = [
        HoldingResponse(
            symbol=v.symbol,
            qty=v.qty,
            # None on a currency conflict (bd:shotockviz-7ju): a cost basis that
            # mixes THB and USD is not a number, so no number is printed.
            avg_cost=round(v.avg_cost, 4) if v.avg_cost is not None else None,
            currency=v.currency,
            currency_conflict=v.currency_conflict,
            currencies=v.currencies,
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
                # bd:shotockviz-ss3 — which way up THBUSD=X actually arrived,
                # readable off a live response instead of trusted from a comment.
                quote_orientation=r.quote_orientation,
            )
            for r in totals.fx_rates.values()
        ],
        fx_unavailable_symbols=totals.fx_unavailable_symbols,
        currency_conflict_symbols=totals.currency_conflict_symbols,
        holdings=holding_responses,
        # Derived from the positions actually left unpriced (a cache "miss" that
        # the fund stage then resolved is not pending; a cached but unusable
        # price is).
        has_pending_prices=bool(totals.unpriced_symbols),
        # bd:shotockviz-tmz. `counted_sales` (not `realized_pl != 0`) guards the
        # money fields: a genuine break-even sale must print 0.00, while a book
        # with nothing sold must print nothing — "there are no closed trades" is
        # a different statement from "the closed trades made nothing". Same
        # None-not-zero doctrine as fx_pl.
        realized_pl=round(realized.realized_pl, 2) if realized.counted_sales else None,
        realized_fees=round(realized.realized_fees, 2) if realized.counted_sales else None,
        closed_positions_pl=(
            round(realized.closed_positions_pl, 2) if realized.total_trades else None
        ),
        total_trades=realized.total_trades,
        win_rate=round(realized.win_rate, 2) if realized.win_rate is not None else None,
        profit_factor=(
            round(realized.profit_factor, 4) if realized.profit_factor is not None else None
        ),
        realized_unavailable_symbols=realized.realized_unavailable_symbols,
    )


@router.get("/realized", response_model=RealizedBookResponse)
async def get_realized(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The closed-trade record — bd:shotockviz-tmz.

    COST FLOW: moving weighted average, stated in the payload (`cost_flow`) and
    argued in services/portfolio_service.py rule 6. Not FIFO: the open side has
    folded on average cost since bd:shotockviz-msg (so FIFO here would stop
    realized + unrealized reconciling to the cost actually put in), and
    `transactions.date` is a DATE with no lot id, so a FIFO answer would depend
    on the row order Postgres happened to return for same-day trades.

    Two grains, both reported because they are different numbers:
      `realized_pl`          — EVERY sale, scale-outs on still-open positions
                               included. Money already off the table.
      `closed_positions_pl`  — completed round trips only, i.e. the sum of the
                               rows in `closed_positions`.

    Everything is in `base_currency`, converted at the rate AT DISPOSAL (the
    SELL row's own `fx_rate`) against cost released at the lots' own rates. A
    disposal that cannot be converted is named in
    `realized_unavailable_symbols` and left out — never counted as zero.

    NOT tax output: see the AI-persona note on rule 6. Lot-relief rules differ
    by jurisdiction and this is one book's own convention.

    CQRS: pure read, DB only — no cache, no external call.
    """
    result = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
    )
    txns = result.scalars().all()

    book = portfolio_service.build_realized(portfolio_service.build_holdings(txns))

    return RealizedBookResponse(
        base_currency=book.base_currency,
        realized_pl=round(book.realized_pl, 2) if book.counted_sales else None,
        realized_fees=round(book.realized_fees, 2) if book.counted_sales else None,
        closed_positions_pl=(
            round(book.closed_positions_pl, 2) if book.total_trades else None
        ),
        total_trades=book.total_trades,
        wins=book.wins,
        losses=book.losses,
        scratches=book.scratches,
        win_rate=round(book.win_rate, 2) if book.win_rate is not None else None,
        profit_factor=(
            round(book.profit_factor, 4) if book.profit_factor is not None else None
        ),
        closed_positions=[
            ClosedPositionResponse(
                symbol=t.symbol,
                currency=t.currency,
                base_currency=book.base_currency,
                qty=t.qty,
                opened_on=t.opened_on,
                closed_on=t.closed_on,
                holding_days=t.holding_days,
                entry_price=round(t.entry_price, 4),
                exit_price=round(t.exit_price, 4),
                fees=round(t.fees, 2),
                realized_pl=round(t.realized_pl, 2),
                realized_pl_pct=(
                    round(t.realized_pl_pct, 2) if t.realized_pl_pct is not None else None
                ),
                # None stays None: "this trip cannot be stated in THB", which is
                # not the same claim as "it made nothing".
                realized_pl_base=(
                    round(t.realized_pl_base, 2) if t.realized_pl_base is not None else None
                ),
                sales=t.sales,
            )
            for t in book.closed_positions
        ],
        realized_unavailable_symbols=book.realized_unavailable_symbols,
        currency_conflict_symbols=book.currency_conflict_symbols,
        oversold_symbols=book.oversold_symbols,
    )


@router.post("/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def add_transaction(
    body: TransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a buy or sell transaction."""
    currency = body.currency.upper() if body.currency else "THB"
    symbol = body.symbol.upper()

    # bd:shotockviz-3p6 — the same refusal `watchlist.py` already makes, for the
    # same reason. SCB / TISCO / ASP (and the other Thai fund-house prefixes) are
    # simultaneously real SET tickers and fund-code prefixes; the app's accepted
    # convention is that a SET ticker carries an explicit ".BK".
    #
    # Since bd:shotockviz-m6q the registrar REFUSES to write a guessed FUND row
    # for these, so the data stays clean — but this endpoint fired
    # `register_symbol.delay()` and returned 201 regardless, so a transaction on
    # a bare "SCB" was accepted, never resolved to an instrument, and never got
    # a name or a price, with nothing anywhere telling the user why. Silence
    # after a refusal is worse than the wrong guess it replaced: the user has no
    # reason to suspect anything and no idea what to type instead.
    if is_ambiguous_bare_thai_symbol(symbol):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ambiguous_bare_symbol_detail(symbol),
        )

    # bd:shotockviz-7ju — refuse before writing, loudly. See rule 5.
    await _assert_currency_consistent(db, user.id, symbol, currency)
    txn = Transaction(
        user_id=user.id,
        symbol=symbol,
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
        register_symbol.delay(symbol)
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

    # bd:shotockviz-7ju — editing the currency can break the symbol's consistency
    # just as easily as inserting a new row; same refusal, same rule 5. Checked
    # against the symbol's OTHER rows (this one is being replaced).
    patch = body.model_dump(exclude_unset=True)
    if patch.get("currency") is not None:
        new_currency = str(getattr(patch["currency"], "value", patch["currency"])).upper()
        patch["currency"] = new_currency
        await _assert_currency_consistent(
            db, user.id, txn.symbol, new_currency, exclude_txn_id=txn.id
        )

    for field, val in patch.items():
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
