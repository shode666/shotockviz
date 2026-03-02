from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from models.user import User
from models.portfolio import Transaction
from models.schemas import (
    TransactionCreate, TransactionUpdate, TransactionResponse, PortfolioAnalytics, HoldingResponse,
)
from api.middleware.auth import get_current_user
from services import stock_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


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
    result = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
    )
    txns = result.scalars().all()

    # Calculate holdings: net qty and avg cost per symbol
    holdings: dict[str, dict] = {}
    for t in txns:
        if t.symbol not in holdings:
            holdings[t.symbol] = {"qty": 0.0, "total_cost": 0.0}
        if t.type.value == "BUY":
            holdings[t.symbol]["qty"] += t.qty
            holdings[t.symbol]["total_cost"] += t.qty * t.price + t.fee
        else:  # SELL
            # Compute avg cost BEFORE reducing qty, then reduce cost basis proportionally
            avg = holdings[t.symbol]["total_cost"] / holdings[t.symbol]["qty"] if holdings[t.symbol]["qty"] else 0
            holdings[t.symbol]["qty"] -= t.qty
            holdings[t.symbol]["total_cost"] -= t.qty * avg

    # Filter out sold positions
    active = {s: h for s, h in holdings.items() if h["qty"] > 0}

    # Enrich with current prices
    holding_responses = []
    total_value = 0.0
    total_cost = 0.0

    for symbol, h in active.items():
        avg_cost = h["total_cost"] / h["qty"] if h["qty"] else 0
        quote = await stock_service.fetch_stock_quote(symbol)
        current_price = quote.price if quote else None
        current_value = current_price * h["qty"] if current_price else None
        cost_basis = h["total_cost"]

        unrealized_pl = (current_value - cost_basis) if current_value is not None else None
        unrealized_pl_pct = (unrealized_pl / cost_basis * 100) if (unrealized_pl is not None and cost_basis) else None

        holding_responses.append(HoldingResponse(
            symbol=symbol,
            qty=h["qty"],
            avg_cost=round(avg_cost, 4),
            current_price=current_price,
            current_value=round(current_value, 2) if current_value else None,
            unrealized_pl=round(unrealized_pl, 2) if unrealized_pl else None,
            unrealized_pl_pct=round(unrealized_pl_pct, 2) if unrealized_pl_pct else None,
        ))

        if current_value:
            total_value += current_value
        total_cost += cost_basis

    unrealized_pl = total_value - total_cost
    return PortfolioAnalytics(
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        unrealized_pl=round(unrealized_pl, 2),
        unrealized_pl_pct=round(unrealized_pl / total_cost * 100, 2) if total_cost else 0,
        holdings=holding_responses,
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
        date=body.date,
        note=body.note,
    )
    db.add(txn)
    await db.flush()
    await db.refresh(txn)
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

    for field, val in body.model_dump(exclude_unset=True).items():
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
