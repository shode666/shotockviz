"""Per-stock investment thesis / notes API."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict

from core.database import get_db
from models.user import User
from models.note import StockNote
from api.middleware.auth import get_current_user

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteUpsert(BaseModel):
    content: str


class NoteResponse(BaseModel):
    symbol: str
    content: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


@router.get("/{symbol}", response_model=NoteResponse)
async def get_note(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get investment note for a symbol."""
    res = await db.execute(
        select(StockNote).where(
            StockNote.user_id == user.id,
            StockNote.symbol == symbol.upper(),
        )
    )
    note = res.scalar_one_or_none()
    if not note:
        return NoteResponse(symbol=symbol.upper(), content="", updated_at="")
    return NoteResponse(
        symbol=note.symbol,
        content=note.content,
        updated_at=note.updated_at.isoformat() if note.updated_at else "",
    )


@router.put("/{symbol}", response_model=NoteResponse)
async def upsert_note(
    symbol: str,
    body: NoteUpsert,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update investment note for a symbol."""
    sym = symbol.upper()
    res = await db.execute(
        select(StockNote).where(StockNote.user_id == user.id, StockNote.symbol == sym)
    )
    note = res.scalar_one_or_none()
    if note:
        note.content = body.content
    else:
        note = StockNote(user_id=user.id, symbol=sym, content=body.content)
        db.add(note)
    await db.flush()
    await db.refresh(note)
    return NoteResponse(
        symbol=note.symbol,
        content=note.content,
        updated_at=note.updated_at.isoformat() if note.updated_at else "",
    )


@router.delete("/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete investment note for a symbol."""
    res = await db.execute(
        select(StockNote).where(
            StockNote.user_id == user.id,
            StockNote.symbol == symbol.upper(),
        )
    )
    note = res.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
