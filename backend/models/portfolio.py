from datetime import datetime, date
from enum import Enum as PyEnum
from typing import TYPE_CHECKING
from sqlalchemy import String, DateTime, Float, Integer, Date, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base

# bd:deps-2026-09 WP-B5 (03-stan-refactor-strategy.md §1.2 F821 finding) —
# forward-ref string "User" in `Mapped["User"]` below needs a real import
# path for both ruff (F821) and mypy to resolve it; TYPE_CHECKING avoids a
# circular import at runtime (models.user doesn't import models.portfolio).
if TYPE_CHECKING:
    from models.user import User


class TransactionType(str, PyEnum):
    BUY = "BUY"
    SELL = "SELL"


class Currency(str, PyEnum):
    THB = "THB"
    USD = "USD"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False, server_default="THB")
    # bd:shotockviz-fnn — THB per 1 unit of `currency`, observed when the row was
    # recorded. NULLABLE on purpose and never backfilled: a row created before
    # this column existed has no observed rate, and inventing one would be the
    # same silent guess as the 33.0 constant this bead removes. NULL therefore
    # means "FX return unavailable for this lot", which the API reports as such
    # (services/portfolio_service.py rule 4 / FX-1). A THB row needs no rate —
    # it is 1.0 by definition — so the whole pre-existing book stays complete.
    fx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="transactions")
