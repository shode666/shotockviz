"""Support/Resistance price levels — bd:features-2026-09 slice 1 (DB + import only).

Rows come from 3 sources (`source` column): `manual_import` (user-exported JSON,
see backend/scripts/import_sr_levels.py), `auto_pivot` (future: computed pivots),
`user_created` (future: drawn in-app). Re-import of `manual_import` wipes-and-reloads
ONLY rows with source='manual_import' — auto_pivot/user_created rows are never touched
(user-confirmed decision, outputs/features-2026-09/00-sara-sr-schema.md §4.1).

bd:shotockviz-43y — `level_type` gains a third value, `stop`, and this table
becomes where a position's stop-loss lives. The alternative was a stop ON the
position, and there IS no position: a holding is a fold over `transactions`
(services/portfolio_service.py::build_holdings), so "on the position" means a
new positions table, i.e. a THIRD place a price-per-symbol can live beside
`alerts.value` and this column. A stop is already exactly the shape of a
`user_created` row — one user, one symbol, one price — so it is one, with the
role named in the column that already answers "what kind of line is this".

Why a new `level_type` value rather than a separate `role` column: a second
axis lets two columns disagree (role='stop' + level_type='resistance' is
incoherent on a long book and nothing would catch it), and `level_type` is
already the role axis. Support and resistance are observations about market
structure; a stop is a personal commitment; those are three kinds, not two
kinds and a flag.

A 'stop' row is ALWAYS user-owned — enforced in the DB
(`ck_sr_levels_stop_is_user_owned`), not just by the route — so a curated
`manual_import` level can never be read as somebody's stop.

ONE stop per (user, symbol) is enforced on the write path
(api/routes/sr_levels.py replaces in place), the same place bd:shotockviz-7ju
puts its one-symbol-one-currency refusal. The read path refuses to guess if a
second row ever appears anyway (`EXCLUDED_AMBIGUOUS_STOP`). It is deliberately
NOT a partial unique index: the WHERE clause needs per-dialect kwargs
(`sqlite_where`/`postgresql_where`) and the test suite runs on SQLite while
production runs Postgres, so an index that degrades to a NON-partial UNIQUE on
either dialect would forbid a user holding both a support and a resistance
level on one symbol. Prevention at the write path, loudness at the read path —
the pattern this codebase already uses.
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base

# bd:shotockviz-43y — the one spelling of the stop role. Imported by the route
# and the tests; `services/portfolio_service.py` deliberately does NOT import it
# (that module stays free of app imports — see its rule 7 note) and takes plain
# floats instead.
STOP_LEVEL_TYPE = "stop"

# Levels that are chart annotations, i.e. everything the S/R chart layer renders.
# A stop is not one of these: it is a portfolio input, and painting it as an "R"
# chip is what the sr_levels GET filter exists to prevent (see api/routes/sr_levels.py).
CHART_LEVEL_TYPES = ("support", "resistance")


class SRLevel(Base):
    __tablename__ = "sr_levels"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    # support | resistance | stop  (bd:shotockviz-43y added 'stop')
    level_type: Mapped[str] = mapped_column(String(10), nullable=False)
    tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    color: Mapped[str | None] = mapped_column(String(9), nullable=True)  # "#a78bfa" etc.
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="manual_import"
    )
    # User-requested nullable FK (Oliver relay §4.3 — user chose B over Sara's
    # "skip it" recommendation). NULL = global/no owner. No other per-user
    # logic (filtering, ownership check) is in scope for this slice.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "level_type IN ('support','resistance','stop')",
            name="ck_sr_levels_level_type",
        ),
        CheckConstraint(
            "source IN ('manual_import','auto_pivot','user_created')",
            name="ck_sr_levels_source",
        ),
        CheckConstraint("price > 0", name="ck_sr_levels_price_positive"),
        # bd:shotockviz-43y — a stop is somebody's money decision, so it must
        # have an owner and must have been made by them. Without this, a curated
        # `manual_import` row (user_id NULL, visible to every caller) could be
        # written with level_type='stop' and would then be read as a stop by
        # anyone who happened to hold that symbol. Enforced here rather than
        # only in the route, because the importer script writes this table too.
        CheckConstraint(
            "level_type <> 'stop' OR (source = 'user_created' AND user_id IS NOT NULL)",
            name="ck_sr_levels_stop_is_user_owned",
        ),
        Index("ix_sr_levels_symbol_source", "symbol", "source"),
    )
