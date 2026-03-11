"""Symbol mapping model — maps internal symbols to provider-specific formats.

Provides a centralized lookup for translating between internal symbol names
and the identifiers used by different data sources (Yahoo Finance, Finnhub,
Thai mutual fund databases, etc.).
"""
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, func, Index
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class SymbolMapping(Base):
    """Maps an internal symbol to provider-specific symbol formats.

    Example rows:
        internal_symbol="PTT.BK"   yahoo="PTT.BK"  finnhub="PTT"   thinav=None
        internal_symbol="AAPL"     yahoo="AAPL"     finnhub="AAPL"  thinav=None
        internal_symbol="SCBFIXD"  yahoo=None       finnhub=None    thinav="T-SCBFIXD"
    """
    __tablename__ = "symbol_mappings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    internal_symbol: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True,
        comment="Canonical symbol used across the app (e.g. PTT.BK, AAPL)",
    )
    yahoo_symbol: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="Yahoo Finance ticker (e.g. PTT.BK, BRK-B)",
    )
    finnhub_symbol: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="Finnhub symbol (e.g. PTT, AAPL)",
    )
    thinav_symbol: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="pythainav symbol for Thai mutual funds (e.g. T-SCBFIXD)",
    )
    display_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Human-readable name (e.g. PTT Public Company Limited)",
    )
    market: Mapped[str | None] = mapped_column(
        String(10), nullable=True,
        comment="Market code: SET, US, FUND, JP, etc.",
    )
    currency: Mapped[str | None] = mapped_column(
        String(5), nullable=True,
        comment="Trading currency: THB, USD, JPY, etc.",
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_symbol_mappings_market", "market"),
    )

    def __repr__(self) -> str:
        return f"<SymbolMapping {self.internal_symbol} → yahoo={self.yahoo_symbol}>"
