"""Support/Resistance price levels — read-only endpoint.

bd:features-2026-09 slice 2 — exposes the sr_levels rows (populated in
slice 1, see models/sr_level.py + scripts/import_sr_levels.py) for the
chart to render as horizontal price lines.

Auth: NONE — matches the existing convention for public read-type stock
data (backend/api/routes/stocks/*.py has no `Depends(get_current_user)`
on any GET handler; only drawings.py, which is per-user CRUD, requires
auth). sr_levels rows are either global (user_id NULL, imported data) or
attributable via the nullable user_id column.

bd:features-2026-09 iter3 (Chris Finding 1, 02-chris-review.md) — this
route is UNAUTHENTICATED, so it must never return `source='user_created'`
rows: those are the one source tied to a real, per-user-owned level via
the nullable `user_id` FK (models/sr_level.py:29-31, "User-requested
nullable FK... NULL = global/no owner"). `manual_import` and `auto_pivot`
are both non-personal (imported/computed, no owner) and safe to expose to
any anonymous caller. If/when a POST endpoint ships that lets a user create
`user_created` rows, THIS route needs a real per-user auth + ownership
filter (mirroring drawings.py's `Drawing.user_id == user.id`) added in the
SAME change that ships those writes — do not just widen this filter back
without also adding auth.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.sr_level import SRLevel
from models.schemas import SRLevelResponse
from schemas.envelope import EnvelopingAPIRoute

router = APIRouter(prefix="/sr-levels", tags=["sr-levels"], route_class=EnvelopingAPIRoute)

# Sources safe to expose on this unauthenticated, no-ownership-filter route.
# 'user_created' is deliberately excluded — see module docstring.
_PUBLIC_SOURCES = ("manual_import", "auto_pivot")


@router.get("/{symbol}", response_model=list[SRLevelResponse])
async def get_sr_levels(
    symbol: str,
    db: AsyncSession = Depends(get_db),
):
    """Get support/resistance levels for a symbol (non-personal sources only)."""
    result = await db.execute(
        select(SRLevel)
        .where(
            SRLevel.symbol == symbol.upper(),
            SRLevel.source.in_(_PUBLIC_SOURCES),
        )
        .order_by(SRLevel.price)
    )
    return result.scalars().all()
