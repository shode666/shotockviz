"""Stock investment thesis / notes model."""
from datetime import datetime
from sqlalchemy import String, Text, DateTime, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class StockNote(Base):
    """Per-user per-symbol investment thesis / notes."""
    __tablename__ = "stock_notes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_note_user_symbol"),
    )
