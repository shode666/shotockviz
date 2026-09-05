from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from models.user import User
from models.alert import Alert, AlertType, AlertChannel
from models.schemas import AlertCreate, AlertUpdate, AlertResponse
from api.middleware.auth import get_current_user
from schemas.envelope import EnvelopingAPIRoute


# bd:shotockviz-06e — "RSI Below"/"RSI Above" (AlertsPage.tsx:10's own
# labels) do NOT naively normalize to a valid AlertType: uppercase +
# space->underscore gives "RSI_BELOW"/"RSI_ABOVE", neither of which is
# RSI_OVERSOLD/RSI_OVERBOUGHT. Every RSI alert created through the app's
# own dropdown 422'd before this map existed — found while wiring up RSI
# evaluation, since a type that can never be created can never be proven
# to fire end-to-end. Explicit label exceptions only; every other label
# ("Price Above", "Golden Cross", ...) already normalizes correctly and
# is left to the generic path below.
_ALERT_TYPE_LABEL_OVERRIDES = {
    "RSI BELOW": AlertType.RSI_OVERSOLD,
    "RSI ABOVE": AlertType.RSI_OVERBOUGHT,
}


def _resolve_alert_type(raw: str) -> AlertType:
    """Normalize frontend alert_type to DB enum.

    Accepts: "Price Above", "PRICE_ABOVE", "price_above", "RSI Below",
    "RSI Above" (see _ALERT_TYPE_LABEL_OVERRIDES), etc.
    """
    key = raw.strip().upper()
    if key in _ALERT_TYPE_LABEL_OVERRIDES:
        return _ALERT_TYPE_LABEL_OVERRIDES[key]
    key = key.replace(" ", "_")
    try:
        return AlertType(key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid alert_type '{raw}'. Valid: {[e.value for e in AlertType]}",
        )


def _resolve_channel(raw: str) -> AlertChannel:
    """Normalize frontend channel to DB enum.

    Accepts: "telegram", "TELEGRAM", etc.

    bd:shotockviz-675 — 'in_app' is explicitly rejected here, not just
    dropped from the frontend dropdown: it delivered nothing durable (no
    notification store; the only delivery was a 5s WS toast, dead in prod)
    and the default choice was the one that silently lost the
    notification. `AlertChannel.IN_APP` still exists as a Python/DB enum
    member (models/alert.py) purely so a pre-existing row can still be
    *read* without crashing — new/updated alerts can no longer choose it.
    Existing IN_APP rows are coerced to TELEGRAM by migration
    db/migrations/versions/20260905_0006_coerce_in_app_alert_channel.py.
    """
    key = raw.strip().upper()
    if key == "IN_APP":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="channel 'in_app' is no longer accepted (bd:shotockviz-675) — "
            "no in-app notification store exists. Use 'telegram'.",
        )
    try:
        return AlertChannel(key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid channel '{raw}'. Valid: {[e.value for e in AlertChannel if e != AlertChannel.IN_APP]}",
        )

# bd:deps-2026-09 S2 (ADR-001 r3) — prefix lifted /api/alerts -> /alerts,
# mounted under /api/v1 in main.py. route_class = envelope wrap (ADR-002).
router = APIRouter(prefix="/alerts", tags=["alerts"], route_class=EnvelopingAPIRoute)


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
        # bd:shotockviz-675 — route `channel` through the same resolver as
        # create_alert so PUT cannot set 'in_app' either (previously this
        # loop did a raw setattr, bypassing validation entirely).
        if field == "channel":
            val = _resolve_channel(val)
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
