"""Corporate action model — dividends, splits, and rights offerings.

Used by the price_adjuster service to compute adjusted OHLCV prices
for accurate technical analysis and total return calculations.
"""
from datetime import datetime, date

from sqlalchemy import String, DateTime, Date, Float, Numeric, func, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class CorporateAction(Base):
    """Records corporate actions (dividends, splits, rights) for a stock.

    Example rows:
        symbol="PTT.BK"  action_type="DIV"    ex_date=2025-08-15  value=1.50   ratio=None
        symbol="AAPL"     action_type="SPLIT"  ex_date=2020-08-31  value=None   ratio=0.25 (4:1)
        symbol="AOT.BK"   action_type="RIGHTS" ex_date=2025-03-01  value=10.00  ratio=0.1  (10:1)
    """
    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="Stock symbol (e.g. PTT.BK, AAPL)",
    )
    action_type: Mapped[str] = mapped_column(
        String(10), nullable=False,
        comment="DIV (dividend), SPLIT (stock split), RIGHTS (rights offering)",
    )
    ex_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="Ex-date: the first date the stock trades without this action",
    )
    value: Mapped[float | None] = mapped_column(
        Numeric(15, 6), nullable=True,
        comment="Dividend amount per share, or rights price",
    )
    ratio: Mapped[float | None] = mapped_column(
        Numeric(10, 6), nullable=True,
        comment="Split ratio (e.g. 0.5 for 2:1 split, 0.25 for 4:1 split)",
    )
    source: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="Data source: yfinance, manual, sec_thailand",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("symbol", "action_type", "ex_date", name="uq_corp_action_symbol_type_date"),
        Index("ix_corporate_actions_symbol_date", "symbol", "ex_date"),
    )

    def __repr__(self) -> str:
        return f"<CorporateAction {self.symbol} {self.action_type} {self.ex_date}>"
