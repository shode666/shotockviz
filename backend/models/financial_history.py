"""Financial history model — 10-year annual financial data per stock.

Stores key financial metrics extracted from Yahoo Finance financial statements.
Used by the Financial Scorecard UI to show revenue/profit/ROE/D-E trends.
"""
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Numeric, func, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class FinancialHistory(Base):
    """Annual financial metrics for a stock (up to 10 years).

    Example row:
        symbol="PTT.BK" fiscal_year=2024 revenue=2.8T net_profit=120B roe=18.5% d_e=0.65
    """
    __tablename__ = "financial_history"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="Stock symbol",
    )
    fiscal_year: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Fiscal year (e.g. 2024)",
    )
    revenue: Mapped[float | None] = mapped_column(
        Numeric(20, 2), nullable=True,
        comment="Total revenue",
    )
    net_profit: Mapped[float | None] = mapped_column(
        Numeric(20, 2), nullable=True,
        comment="Net income / net profit",
    )
    roe: Mapped[float | None] = mapped_column(
        Numeric(8, 4), nullable=True,
        comment="Return on Equity (%)",
    )
    debt_equity: Mapped[float | None] = mapped_column(
        Numeric(8, 4), nullable=True,
        comment="Debt-to-Equity ratio",
    )
    eps: Mapped[float | None] = mapped_column(
        Numeric(10, 4), nullable=True,
        comment="Earnings per share",
    )
    dividend: Mapped[float | None] = mapped_column(
        Numeric(10, 4), nullable=True,
        comment="Dividend per share",
    )
    gross_margin: Mapped[float | None] = mapped_column(
        Numeric(8, 4), nullable=True,
        comment="Gross margin (%)",
    )
    operating_margin: Mapped[float | None] = mapped_column(
        Numeric(8, 4), nullable=True,
        comment="Operating margin (%)",
    )
    currency: Mapped[str | None] = mapped_column(
        String(5), nullable=True,
        comment="Currency: THB, USD, etc.",
    )
    source: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="Data source: yfinance, manual",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("symbol", "fiscal_year", name="uq_financial_history_symbol_year"),
        Index("ix_financial_history_symbol_year", "symbol", "fiscal_year"),
    )

    def __repr__(self) -> str:
        return f"<FinancialHistory {self.symbol} FY{self.fiscal_year}>"
