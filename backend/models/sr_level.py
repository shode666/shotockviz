"""Support/Resistance price levels — bd:features-2026-09 slice 1 (DB + import only).

Rows come from 3 sources (`source` column): `manual_import` (user-exported JSON,
see backend/scripts/import_sr_levels.py), `auto_pivot` (future: computed pivots),
`user_created` (future: drawn in-app). Re-import of `manual_import` wipes-and-reloads
ONLY rows with source='manual_import' — auto_pivot/user_created rows are never touched
(user-confirmed decision, outputs/features-2026-09/00-sara-sr-schema.md §4.1).
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class SRLevel(Base):
    __tablename__ = "sr_levels"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    level_type: Mapped[str] = mapped_column(String(10), nullable=False)  # support | resistance
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
        CheckConstraint("level_type IN ('support','resistance')", name="ck_sr_levels_level_type"),
        CheckConstraint(
            "source IN ('manual_import','auto_pivot','user_created')",
            name="ck_sr_levels_source",
        ),
        CheckConstraint("price > 0", name="ck_sr_levels_price_positive"),
        Index("ix_sr_levels_symbol_source", "symbol", "source"),
    )
