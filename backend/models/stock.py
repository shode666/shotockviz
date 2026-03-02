from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, DateTime, Float, BigInteger, Enum, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class MarketType(str, PyEnum):
    SET = "SET"
    US = "US"
    FUND = "FUND"  # Thai mutual funds (กองทุนรวม)


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_th: Mapped[str | None] = mapped_column(String(200), nullable=True)
    market: Mapped[MarketType] = mapped_column(Enum(MarketType), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StockPrice1m(Base):
    """1-minute OHLCV bars — TimescaleDB hypertable."""
    __tablename__ = "stock_prices_1m"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_stock_prices_1m_symbol_time", "symbol", "time"),
    )


class StockEvent(Base):
    """Corporate events: XD, XR, earnings dates."""
    __tablename__ = "stock_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)  # XD, XR, EARNINGS
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
