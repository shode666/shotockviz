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

bd:shotockviz-43y — this table also became where a POSITION'S STOP lives
(`level_type='stop'`, always `user_created`, always owned). Three
consequences here:

  - GET /{symbol} no longer returns stop rows to ANYONE, owner included.
    It feeds the chart's S/R line layer, which labels anything that is not
    'support' as "R" — a stop drawn as a resistance level is a wrong label
    on a price the user manages money by.
  - GET /{symbol}/stop is the stop's own read. Authenticated (a stop is
    never public) and returns null, not 404, when there is none.
  - POST /{symbol} with level_type='stop' REPLACES the caller's existing
    stop rather than adding a second row. One position, one stop.

Because a stop is a `user_created` row, the proximity digest's existing
exclusion below already excludes it — no change needed there, and the
reasoning in that paragraph applies verbatim (a stop is the most personal
marker on the list).

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
from models.sr_level import CHART_LEVEL_TYPES, STOP_LEVEL_TYPE, SRLevel
from models.user import User
from models.schemas import SRLevelCreate, SRLevelResponse
from schemas.envelope import EnvelopingAPIRoute

router = APIRouter(prefix="/sr-levels", tags=["sr-levels"], route_class=EnvelopingAPIRoute)

# Sources safe to expose to ANY caller (including guests) on this route.
# 'user_created' is only ever added on top of this for the row's own owner
# — see get_sr_levels below.
_PUBLIC_SOURCES = ("manual_import", "auto_pivot")


async def _existing_stop(db: AsyncSession, user_id: int, symbol: str) -> SRLevel | None:
    """The caller's current stop for `symbol`, if any.

    bd:shotockviz-43y — ONE stop per (user, symbol). Enforced here, on the write
    path, exactly where bd:shotockviz-7ju puts its one-symbol-one-currency
    refusal, and for the same reason: the read path can only decline to state a
    number after the fact (`portfolio_service.EXCLUDED_AMBIGUOUS_STOP`), so the
    ambiguity is prevented rather than resolved. It is not a partial unique
    index because that needs a per-dialect WHERE clause and the suite runs
    SQLite against a Postgres production — see models/sr_level.py.
    """
    result = await db.execute(
        select(SRLevel).where(
            SRLevel.symbol == symbol,
            SRLevel.user_id == user_id,
            SRLevel.source == "user_created",
            SRLevel.level_type == STOP_LEVEL_TYPE,
        )
    )
    return result.scalars().first()


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

    bd:shotockviz-43y — `level_type='stop'` rows are EXCLUDED here, for every
    caller including their owner. This route feeds the chart's S/R price-line
    layer, whose renderer knows two kinds of line: the toolbar chip labels
    anything that is not 'support' as "R" and paints it magenta
    (frontend/src/components/chart/ChartToolbar.tsx:219-223). A stop returned
    through this endpoint would therefore be drawn on the chart as a
    RESISTANCE level — a wrong label on a price the user manages money by,
    which is worse than not drawing it yet. The stop's surface is the portfolio
    (`GET /portfolio/analytics` -> `open_risk.positions[].stop_price`), which
    is where it is read today. Painting stops on the chart is a UI change and
    needs a design artifact before any frontend work starts, so it is a
    separate bead, not a silent side effect of this one.
    """
    symbol_upper = symbol.upper()
    source_filter = SRLevel.source.in_(_PUBLIC_SOURCES)
    if user is not None:
        own_filter = (SRLevel.source == "user_created") & (SRLevel.user_id == user.id)
        source_filter = or_(source_filter, own_filter)

    result = await db.execute(
        select(SRLevel)
        .where(
            SRLevel.symbol == symbol_upper,
            SRLevel.level_type.in_(CHART_LEVEL_TYPES),
            source_filter,
        )
        .order_by(SRLevel.price)
    )
    return result.scalars().all()


@router.get("/{symbol}/stop", response_model=SRLevelResponse | None)
async def get_stop_level(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's stop for `symbol`, or null — bd:shotockviz-43y.

    Authenticated, unlike the S/R read above: a stop is one user's money
    decision, never public. Returns null rather than 404 because "this position
    has no stop" is a normal, expected state that the risk report already names
    (`no_stop`), not an error. The row's `id` is here so the existing DELETE can
    remove it — the S/R read no longer returns stops, so this is the only place
    a client can learn it.
    """
    return await _existing_stop(db, user.id, symbol.upper())


@router.post("/{symbol}", response_model=SRLevelResponse, status_code=status.HTTP_201_CREATED)
async def create_sr_level(
    symbol: str,
    body: SRLevelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a user-owned horizontal S/R level. Always source='user_created',
    always owned by the caller — never accepted from the request body.

    bd:shotockviz-43y — `level_type='stop'` REPLACES the caller's existing stop
    for this symbol in place instead of adding a second row. One position, one
    stop: "move my stop up" is the user's actual verb, and two stop rows on one
    symbol is a state nothing could resolve honestly (the read path would have
    to pick one, and picking the higher understates the risk — the dangerous
    direction). Prevented on write, the same way bd:shotockviz-7ju prevents a
    symbol holding two currencies. Support/resistance levels are unaffected: a
    user may hold as many of those on a symbol as they like.
    """
    symbol_upper = symbol.upper()

    if body.level_type == STOP_LEVEL_TYPE:
        existing = await _existing_stop(db, user.id, symbol_upper)
        if existing is not None:
            existing.price = body.price
            existing.tag = body.tag
            await db.flush()
            await db.refresh(existing)
            return existing

    level = SRLevel(
        symbol=symbol_upper,
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
