"""GET/PATCH /settings/trader — trader-set numeric thresholds that must
follow the user across devices, not just a browser.

bd:shotockviz-649.1 ("concentration limit is client-remembered only") and
bd:shotockviz-06z.1 ("gap list has no per-user magnitude threshold") are one
piece of work: both are a number the trader sets that wasn't stored
server-side, and both need the same two new `users` columns
(models/user.py, migration 20260906_0011).

A NEW route module, deliberately not folded into GET/PATCH /auth/settings
(api/routes/auth.py):
  * `auth.py` is outside this change's declared file scope — three other
    agents are working this tree concurrently (CLAUDE.md / hand-off Rule
    7), and touching a file outside a declared scope is exactly the
    "expand scope without confirming" move Philosophy 4 forbids. This is
    reported explicitly in the hand-off, not silently worked around.
  * Even absent that constraint, `auth.py`'s PATCH /auth/settings has a
    real side effect the moment `telegram_chat_id` changes — it sends a
    live Telegram test message (D2, 04-sara-telegram-spec.md §11). Bolting
    two side-effect-free numeric fields onto that handler would make one
    endpoint do two unrelated jobs with two different failure/side-effect
    shapes, the "two hand-rolled X for one concern" class of drift this
    codebase has already paid for (5 Telegram senders, bd:4d9; 5 fund-NAV
    dicts, bd:ubw).

This module owns exactly two columns on `users`
(`concentration_limit_pct`, `gap_min_pct`). Its only job is:
  1. read/write those two nullable columns for the current user;
  2. apply the ONE bounds-check each value already has elsewhere
     (`services.portfolio_service.MIN_/MAX_CONCENTRATION_LIMIT_PCT`,
     `models.schemas.MIN_/MAX_GAP_MIN_PCT`) so a bad value 422s here
     instead of being silently clamped, or stored broken, or accepted and
     later misapplied by a consumer that trusts it unchecked.

PATCH is a real partial update, not "send the whole object every time":
`body.model_fields_set` distinguishes "this field was present in the
request JSON" from "this field was omitted" — `{"gap_min_pct": null}`
explicitly clears a previously-chosen threshold back to "unset" (the
no-invented-default state both parent bds require), while a request that
never mentions `gap_min_pct` at all must leave it untouched. Without this,
saving the concentration limit alone from ConcentrationLimitPanel.tsx would
silently wipe an already-set gap threshold from SettingsPage.tsx, and
vice versa — two independent settings sharing one row must not be able to
clobber each other through an update that only meant to touch one.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.user import User
from models.schemas import (
    TraderSettingsResponse,
    TraderSettingsUpdate,
    MIN_GAP_MIN_PCT,
    MAX_GAP_MIN_PCT,
)
from api.middleware.auth import get_current_user
from schemas.envelope import EnvelopingAPIRoute
from services import portfolio_service

router = APIRouter(prefix="/settings", tags=["settings"], route_class=EnvelopingAPIRoute)


@router.get("/trader", response_model=TraderSettingsResponse)
async def get_trader_settings(user: User = Depends(get_current_user)):
    """The trader's own persisted thresholds. `None` on either field means
    "not set yet" — the caller (GET /portfolio/analytics,
    workers/gap_list_digest.py) applies its own documented fallback; this
    endpoint never fills one in."""
    return user


@router.patch("/trader", response_model=TraderSettingsResponse)
async def update_trader_settings(
    body: TraderSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update whichever of the two thresholds were actually present in the
    request body. See module docstring for why `model_fields_set` (not a
    plain `is not None` check) is required here."""
    fields_set = body.model_fields_set

    if "concentration_limit_pct" in fields_set:
        value = body.concentration_limit_pct
        if value is not None and not (
            portfolio_service.MIN_CONCENTRATION_LIMIT_PCT
            <= value
            <= portfolio_service.MAX_CONCENTRATION_LIMIT_PCT
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"concentration_limit_pct must be between "
                    f"{portfolio_service.MIN_CONCENTRATION_LIMIT_PCT} and "
                    f"{portfolio_service.MAX_CONCENTRATION_LIMIT_PCT}"
                ),
            )
        user.concentration_limit_pct = value

    if "gap_min_pct" in fields_set:
        value = body.gap_min_pct
        if value is not None and not (MIN_GAP_MIN_PCT <= value <= MAX_GAP_MIN_PCT):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"gap_min_pct must be between {MIN_GAP_MIN_PCT} and {MAX_GAP_MIN_PCT}"
                ),
            )
        user.gap_min_pct = value

    await db.commit()
    await db.refresh(user)
    return user
