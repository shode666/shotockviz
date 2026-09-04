from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from models.user import User
from models.drawing import Drawing
from models.schemas import DrawingCreate, DrawingUpdate, DrawingResponse
from api.middleware.auth import get_current_user
from schemas.envelope import EnvelopingAPIRoute

# bd:deps-2026-09 S2 (ADR-001 r3) — prefix lifted /api/drawings -> /drawings,
# mounted under /api/v1 in main.py. route_class = envelope wrap (ADR-002).
router = APIRouter(prefix="/drawings", tags=["drawings"], route_class=EnvelopingAPIRoute)


@router.get("/{symbol}", response_model=list[DrawingResponse])
async def get_drawings(
    symbol: str,
    tf: str = Query("1D"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get saved drawings for a symbol + timeframe."""
    result = await db.execute(
        select(Drawing).where(
            Drawing.user_id == user.id,
            Drawing.symbol == symbol.upper(),
            Drawing.timeframe == tf,
        )
    )
    return result.scalars().all()


@router.post("/{symbol}", response_model=DrawingResponse, status_code=status.HTTP_201_CREATED)
async def save_drawing(
    symbol: str,
    body: DrawingCreate,
    tf: str = Query("1D"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a new drawing."""
    drawing = Drawing(
        user_id=user.id,
        symbol=symbol.upper(),
        timeframe=tf,
        tool_type=body.tool_type,
        data_json=body.data_json,
        style_json=body.style_json,
    )
    db.add(drawing)
    await db.flush()
    await db.refresh(drawing)
    return drawing


@router.put("/{drawing_id}", response_model=DrawingResponse)
async def update_drawing(
    drawing_id: int,
    body: DrawingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a drawing's data or style."""
    result = await db.execute(
        select(Drawing).where(Drawing.id == drawing_id, Drawing.user_id == user.id)
    )
    drawing = result.scalar_one_or_none()
    if not drawing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drawing not found")

    if body.data_json is not None:
        drawing.data_json = body.data_json
    if body.style_json is not None:
        drawing.style_json = body.style_json
    return drawing


@router.delete("/{drawing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_drawing(
    drawing_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a drawing."""
    result = await db.execute(
        select(Drawing).where(Drawing.id == drawing_id, Drawing.user_id == user.id)
    )
    drawing = result.scalar_one_or_none()
    if not drawing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drawing not found")
    await db.delete(drawing)
