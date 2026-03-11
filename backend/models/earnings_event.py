"""Earnings event model — tracks EPS actual vs estimate (surprise tracker).

Used by the Earnings Surprise Tracker UI to show chart markers and
EPS beat/miss overlays on the price chart.
"""
from datetime import datetime, date

from sqlalchemy import String, DateTime, Date, Numeric, func, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class EarningsEvent(Base):
    """Individual earnings report with actual vs estimated EPS.

    Example row:
        symbol="AAPL" report_date=2025-01-30 fiscal_period="Q1 2025"
        estimated_eps=2.35 actual_eps=2.40 surprise_pct=2.13
        price_1d_before=230.50 price_1d_after=235.20 price_impact_pct=2.04
    """
    __tablename__ = "earnings_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="Stock symbol",
    )
    report_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="Earnings report date",
    )
    fiscal_period: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="Fiscal period (e.g. Q3 2025, FY2025)",
    )
    estimated_eps: Mapped[float | None] = mapped_column(
        Numeric(10, 4), nullable=True,
        comment="Consensus EPS estimate",
    )
    actual_eps: Mapped[float | None] = mapped_column(
        Numeric(10, 4), nullable=True,
        comment="Actual reported EPS",
    )
    surprise_pct: Mapped[float | None] = mapped_column(
        Numeric(8, 4), nullable=True,
        comment="EPS surprise: (actual - estimate) / |estimate| * 100",
    )
    price_1d_before: Mapped[float | None] = mapped_column(
        Numeric(15, 4), nullable=True,
        comment="Closing price 1 day before report",
    )
    price_1d_after: Mapped[float | None] = mapped_column(
        Numeric(15, 4), nullable=True,
        comment="Closing price 1 day after report",
    )
    price_impact_pct: Mapped[float | None] = mapped_column(
        Numeric(8, 4), nullable=True,
        comment="Price change: (after - before) / before * 100",
    )
    source: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="Data source: yfinance, manual",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("symbol", "report_date", name="uq_earnings_event_symbol_date"),
        Index("ix_earnings_events_symbol_date", "symbol", "report_date"),
    )

    def __repr__(self) -> str:
        return f"<EarningsEvent {self.symbol} {self.report_date} EPS={self.actual_eps}>"
