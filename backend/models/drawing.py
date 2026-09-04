from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base

# bd:deps-2026-09 WP-B5 (03-stan-refactor-strategy.md §1.2 F821 finding) —
# forward-ref string "User" in `Mapped["User"]` below needs a real import
# path for both ruff (F821) and mypy to resolve it; TYPE_CHECKING avoids a
# circular import at runtime (models.user doesn't import models.drawing).
if TYPE_CHECKING:
    from models.user import User


class Drawing(Base):
    __tablename__ = "drawings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)  # 1m, 5m, 1D etc.
    tool_type: Mapped[str] = mapped_column(String(50), nullable=False)  # TREND_LINE, FIBO, etc.
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False)   # coordinates, points
    style_json: Mapped[dict] = mapped_column(JSON, nullable=False)   # color, width, style
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="drawings")
