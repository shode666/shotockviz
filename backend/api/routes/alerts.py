from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from models.user import User
from models.alert import Alert, AlertType, AlertChannel
from models.schemas import AlertCreate, AlertUpdate, AlertResponse
from api.middleware.auth import get_current_user


def _resolve_alert_type(raw: str) -> AlertType:
    """Normalize frontend alert_type to DB enum.

    Accepts: "Price Above", "PRICE_ABOVE", "price_above", etc.
    """
    key = raw.strip().upper().replace(" ", "_")
    try:
        return AlertType(key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid alert_type '{raw}'. Valid: {[e.value for e in AlertType]}",
        )


def _resolve_channel(raw: str) -> AlertChannel:
    """Normalize frontend channel to DB enum.

    Accepts: "in_app", "IN_APP", "telegram", etc.
    """
    key = raw.strip().upper()
    try:
        return AlertChannel(key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid channel '{raw}'. Valid: {[e.value for e in AlertChannel]}",
        )

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertResponse])
async def get_alerts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all alerts for the current user."""
    result = await db.execute(
        select(Alert).where(Alert.user_id == user.id).order_by(Alert.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new price/indicator alert."""
    alert = Alert(
        user_id=user.id,
        symbol=body.symbol.upper(),
        alert_type=_resolve_alert_type(body.alert_type),
        condition=body.condition,
        value=body.value,
        channel=_resolve_channel(body.channel),
    )
    db.add(alert)
    await db.flush()
    await db.commit()
    await db.refresh(alert)
    return alert


@router.put("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: int,
    body: AlertUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an alert."""
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(alert, field, val)
    return alert


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an alert."""
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    await db.delete(alert)


@router.patch("/{alert_id}/toggle", response_model=AlertResponse)
async def toggle_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle alert active/inactive."""
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    alert.is_active = not alert.is_active
    return alert
