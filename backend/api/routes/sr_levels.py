"""Support/Resistance price levels — read + user-owned write.

bd:features-2026-09 slice 2 — exposes the sr_levels rows (populated in
slice 1, see models/sr_level.py + scripts/import_sr_levels.py) for the
chart to render as horizontal price lines.

bd:shotockviz-474 — adds the user-owned write path this module's own
docstring flagged as a future change ("If/when a POST endpoint ships that
lets a user create `user_created` rows, THIS route needs a real per-user
auth + ownership filter"). That filter lands in the SAME change as the
writes, per that note:

  - GET  stays unauthenticated (matches stocks/* public-read convention),
    but now ALSO returns the caller's own `user_created` rows when a valid
    token is present (`get_optional_user` — guest/no-token behavior is
    byte-for-byte unchanged, still `_PUBLIC_SOURCES` only). A `user_created`
    row belonging to someone else is never returned to anyone but its owner.
  - POST creates a `user_created` row owned by the caller. `source` and
    `user_id` are never accepted from the request body (SRLevelCreate has
    neither field) — the route sets both itself, so a caller cannot mint a
    `manual_import`/`auto_pivot` row or attribute a level to another user.
  - DELETE removes a `user_created` row, filtered on `user_id == caller`
    AND `source == 'user_created'` in the same WHERE — a `manual_import`/
    `auto_pivot` row (user_id NULL) can never match that filter, so this
    route can never delete imported/computed data, only what a user made.

Proximity digest (workers/sr_proximity_digest.py) is a deliberate NON-
consumer of `user_created` rows — see that module's own query
(`source.in_(["manual_import", "auto_pivot"])`, unchanged by this bead).
Product call, not an oversight: a digest is "a watchlist symbol is near a
level worth knowing about" (curated import or computed pivot); a
user-created H-line is a personal entry/stop/target scratch mark, and the
existing Alert/alert_checker feature is already the "notify me at this
price" path. Folding personal markers into the digest would (a) duplicate
that feature with a second, inconsistent notify mechanism, (b) push a
user's own private annotations into a shared 2x/day Telegram message
without them asking for that, and (c) risk drowning the curated signal
under `MAX_SYMBOLS_PER_MESSAGE=20` with scratch marks nobody but the owner
should see paged on. If a user wants a price notification, Alerts already
does that.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_current_user, get_optional_user
from core.database import get_db
from models.sr_level import SRLevel
from models.user import User
from models.schemas import SRLevelCreate, SRLevelResponse
from schemas.envelope import EnvelopingAPIRoute

router = APIRouter(prefix="/sr-levels", tags=["sr-levels"], route_class=EnvelopingAPIRoute)

# Sources safe to expose to ANY caller (including guests) on this route.
# 'user_created' is only ever added on top of this for the row's own owner
# — see get_sr_levels below.
_PUBLIC_SOURCES = ("manual_import", "auto_pivot")


@router.get("/{symbol}", response_model=list[SRLevelResponse])
async def get_sr_levels(
    symbol: str,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get support/resistance levels for a symbol.

    Guests (and any request without a valid token) get non-personal sources
    only, exactly as before this bead. An authenticated caller additionally
    gets their OWN `user_created` rows for this symbol — never another
    user's.
    """
    symbol_upper = symbol.upper()
    source_filter = SRLevel.source.in_(_PUBLIC_SOURCES)
    if user is not None:
        own_filter = (SRLevel.source == "user_created") & (SRLevel.user_id == user.id)
        source_filter = or_(source_filter, own_filter)

    result = await db.execute(
        select(SRLevel)
        .where(SRLevel.symbol == symbol_upper, source_filter)
        .order_by(SRLevel.price)
    )
    return result.scalars().all()


@router.post("/{symbol}", response_model=SRLevelResponse, status_code=status.HTTP_201_CREATED)
async def create_sr_level(
    symbol: str,
    body: SRLevelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a user-owned horizontal S/R level. Always source='user_created',
    always owned by the caller — never accepted from the request body."""
    level = SRLevel(
        symbol=symbol.upper(),
        price=body.price,
        level_type=body.level_type,
        tag=body.tag,
        color=None,
        source="user_created",
        user_id=user.id,
    )
    db.add(level)
    await db.flush()
    await db.refresh(level)
    return level


@router.delete("/{level_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sr_level(
    level_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a level the caller owns. `source == 'user_created'` is part of
    the WHERE (not just an implicit consequence of user_id matching) — a
    manual_import/auto_pivot row always has user_id NULL, so it could never
    match anyway, but pinning the source filter here keeps that guarantee
    explicit even if a future migration ever gives those rows an owner."""
    result = await db.execute(
        select(SRLevel).where(
            SRLevel.id == level_id,
            SRLevel.user_id == user.id,
            SRLevel.source == "user_created",
        )
    )
    level = result.scalar_one_or_none()
    if not level:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Level not found")
    await db.delete(level)
