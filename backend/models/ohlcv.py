"""OHLCV bar storage model — shared across all users, partitioned by symbol+timeframe."""
from sqlalchemy import (
    Column, String, Float, BigInteger, Index,
    UniqueConstraint, text,
)
from core.database import Base


class OHLCVBar(Base):
    """Persistent OHLCV bar storage backed by TimescaleDB.

    Time representation:
    - Daily/Weekly/Monthly: time_str = "YYYY-MM-DD", time_unix = midnight UTC of that date
    - Intraday: time_str = ISO-8601 UTC string, time_unix = unix seconds

    This table is shared between ALL users (OHLCV data is public).
    Redis is used as L1 cache on top for hot reads.
    """

    __tablename__ = "ohlcv_bars"

    # Composite PK covers uniqueness; TimescaleDB partitions on time_unix
    symbol    = Column(String(20), primary_key=True, nullable=False)
    timeframe = Column(String(4),  primary_key=True, nullable=False)
    time_unix = Column(BigInteger,  primary_key=True, nullable=False)

    # Human-readable time kept for easy SQL queries and API responses
    time_str  = Column(String(20), nullable=False)  # "YYYY-MM-DD" or ISO datetime

    open   = Column(Float, nullable=False)
    high   = Column(Float, nullable=False)
    low    = Column(Float, nullable=False)
    close  = Column(Float, nullable=False)
    volume = Column(BigInteger, nullable=False)

    __table_args__ = (
        # Fast range queries: symbol + timeframe + time window
        Index("ix_ohlcv_sym_tf_ts", "symbol", "timeframe", "time_unix"),
        # Covered index for API response ordering
        Index("ix_ohlcv_sym_tf_str", "symbol", "timeframe", "time_str"),
    )

    def to_api_dict(self) -> dict:
        """Return dict matching OHLCVBar schema expected by frontend.

        Intraday timeframes (1m/5m/15m/1h/4h): returns time_unix (int) so
        TradingView Lightweight Charts v5 receives UTCTimestamp as required.

        Daily/Weekly/Monthly: returns time_str ("YYYY-MM-DD") as BusinessDay.
        """
        # time_str is a numeric string for intraday (e.g. "1759761000")
        # and "YYYY-MM-DD" for daily/weekly/monthly
        is_intraday = self.time_str and self.time_str.isdigit()
        return {
            "time":   self.time_unix if is_intraday else self.time_str,
            "open":   self.open,
            "high":   self.high,
            "low":    self.low,
            "close":  self.close,
            "volume": self.volume,
        }
