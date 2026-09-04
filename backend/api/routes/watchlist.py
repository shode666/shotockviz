from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from sqlalchemy.orm import selectinload

from core.database import get_db
from models.user import User
from models.watchlist import Watchlist, WatchlistItem
from models.schemas import WatchlistCreate, WatchlistUpdate, WatchlistItemAdd, WatchlistResponse, WatchlistReorderRequest
from api.middleware.auth import get_current_user
from schemas.envelope import EnvelopingAPIRoute

# bd:deps-2026-09 S2 (ADR-001 r3) — prefix lifted /api/watchlists -> /watchlists,
# mounted under /api/v1 in main.py. route_class = envelope wrap (ADR-002).
router = APIRouter(prefix="/watchlists", tags=["watchlist"], route_class=EnvelopingAPIRoute)


@router.get("", response_model=list[WatchlistResponse])
async def get_watchlists(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all watchlists for the current user."""
    result = await db.execute(
        select(Watchlist)
        .where(Watchlist.user_id == user.id)
        .options(selectinload(Watchlist.items))
        .order_by(Watchlist.sort_order)
    )
    return result.scalars().all()


@router.post("", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    body: WatchlistCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new watchlist."""
    wl = Watchlist(user_id=user.id, name=body.name)
    db.add(wl)
    await db.flush()
    await db.refresh(wl, ["items"])
    return wl


@router.put("/{watchlist_id}", response_model=WatchlistResponse)
async def update_watchlist(
    watchlist_id: int,
    body: WatchlistUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update watchlist name or sort order."""
    result = await db.execute(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user.id)
        .options(selectinload(Watchlist.items))
    )
    wl = result.scalar_one_or_none()
    if not wl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")

    if body.name is not None:
        wl.name = body.name
    if body.sort_order is not None:
        wl.sort_order = body.sort_order
    return wl


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    watchlist_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a watchlist."""
    result = await db.execute(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user.id)
    )
    wl = result.scalar_one_or_none()
    if not wl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    await db.delete(wl)


@router.post("/{watchlist_id}/stocks", status_code=status.HTTP_201_CREATED)
async def add_stock(
    watchlist_id: int,
    body: WatchlistItemAdd,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a stock to a watchlist."""
    result = await db.execute(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user.id)
    )
    wl = result.scalar_one_or_none()
    if not wl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")

    # Check duplicate
    existing = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist_id,
            WatchlistItem.symbol == body.symbol.upper(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stock already in watchlist")

    item = WatchlistItem(watchlist_id=watchlist_id, symbol=body.symbol.upper())
    db.add(item)

    # Fire-and-forget: ensure symbol is registered in stocks table
    # (needed for name_fetcher, fund_fetcher to pick it up)
    try:
        from workers.symbol_registrar import register_symbol
        register_symbol.delay(body.symbol.upper())
    except Exception:
        pass  # Non-critical — scan_unregistered will catch it later

    return {"message": "Stock added"}


@router.delete("/{watchlist_id}/stocks/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_stock(
    watchlist_id: int,
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a stock from a watchlist."""
    result = await db.execute(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")

    await db.execute(
        delete(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist_id,
            WatchlistItem.symbol == symbol.upper(),
        )
    )


@router.patch("/{watchlist_id}/stocks/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_stocks(
    watchlist_id: int,
    body: WatchlistReorderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-update sort_order for all items in a watchlist."""
    result = await db.execute(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")

    for entry in body.items:
        await db.execute(
            update(WatchlistItem)
            .where(
                WatchlistItem.watchlist_id == watchlist_id,
                WatchlistItem.symbol == entry.symbol.upper(),
            )
            .values(sort_order=entry.sort_order)
        )
