"""Celery task: pre-fetch OHLCV history for symbols with expired cache."""
from __future__ import annotations

from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger
from core import cache_keys
from core.symbol_utils import normalize_for_yahoo
from workers.helpers.symbol_loader import get_watched_symbols
from workers.helpers.cache_publisher import cache_and_publish_history
from workers.helpers.task_timing import timed_task

logger = get_logger(__name__)


# ── Pure helper: parse yfinance DataFrame row → bar dict ──────────────────────

def _parse_bar(idx, row) -> dict | None:
    """Convert a single pandas DataFrame row to OHLCV bar dict.

    Args:
        idx: pandas Timestamp index.
        row: DataFrame row with Open, High, Low, Close, Volume.

    Returns:
        Bar dict or None if parsing fails.
    """
    try:
        return {
            "time": idx.strftime("%Y-%m-%d"),
            "time_unix": int(idx.timestamp()),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]),
        }
    except Exception:
        return None


# ── Pure helper: upsert bars to PostgreSQL ────────────────────────────────────

def _upsert_bars_to_db(engine, symbol: str, timeframe: str, bars: list[dict]) -> int:
    """Save OHLCV bars to PostgreSQL, skipping existing rows.

    Args:
        engine: SQLAlchemy sync engine.
        symbol: Stock symbol.
        timeframe: e.g. "1D".
        bars: List of bar dicts with time_unix, time (str), OHLCV.

    Returns:
        Number of new rows inserted.
    """
    from sqlalchemy import text

    inserted = 0
    with engine.connect() as conn:
        for bar in bars:
            exists = conn.execute(text(
                "SELECT 1 FROM ohlcv_bars WHERE symbol = :symbol "
                "AND timeframe = :timeframe AND time_unix = :time_unix"
            ), {"symbol": symbol, "timeframe": timeframe, "time_unix": bar["time_unix"]}).first()

            if not exists:
                conn.execute(text(
                    "INSERT INTO ohlcv_bars "
                    "(symbol, timeframe, time_unix, time_str, open, high, low, close, volume) "
                    "VALUES (:symbol, :timeframe, :time_unix, :time_str, "
                    ":open, :high, :low, :close, :volume)"
                ), {
                    "symbol": symbol, "timeframe": timeframe,
                    "time_unix": bar["time_unix"], "time_str": bar["time"],
                    "open": bar["open"], "high": bar["high"],
                    "low": bar["low"], "close": bar["close"],
                    "volume": bar["volume"],
                })
                inserted += 1
        conn.commit()
    return inserted


# ── Pure helper: fetch history for a single symbol ────────────────────────────

def _fetch_symbol_history(symbol: str) -> list[dict]:
    """Fetch 6-month daily history from Yahoo Finance.

    Args:
        symbol: Internal symbol (e.g., "PTT.BK", "AAPL").

    Returns:
        List of bar dicts, or empty list on failure.
    """
    import yfinance as yf

    yahoo_sym = normalize_for_yahoo(symbol)
    ticker = yf.Ticker(yahoo_sym)
    hist = ticker.history(period="6mo", interval="1d")

    if hist.empty:
        logger.debug("No history data", symbol=symbol)
        return []

    bars = []
    for idx, row in hist.iterrows():
        bar = _parse_bar(idx, row)
        if bar:
            bars.append(bar)
    return bars


# ── Main task ─────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
@timed_task("prefetch_history")
def prefetch_history(self):
    """Keep OHLCV history cache warm for all watched symbols.

    Flow:
      1. Get all symbols from watchlist + portfolio
      2. Skip symbols with fresh Redis cache
      3. Fetch from Yahoo Finance (1D bars, 6mo range)
      4. Save to PostgreSQL + Redis (6h TTL)
      5. Publish data_ready notification
    """
    import redis as redis_lib
    from sqlalchemy import create_engine
    from core.config import settings

    symbols = get_watched_symbols()
    if not symbols:
        logger.info("No symbols to prefetch history for")
        return

    redis_client = redis_lib.from_url(settings.redis_url)
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

    updated_count = 0
    cached_count = 0
    timeframe = "1D"

    for symbol in symbols:
        try:
            cache_key = cache_keys.ohlcv(symbol, timeframe)
            if redis_client.exists(cache_key):
                cached_count += 1
                continue

            bars = _fetch_symbol_history(symbol)
            if not bars:
                continue

            # Persist to PostgreSQL
            _upsert_bars_to_db(engine, symbol, timeframe, bars)

            # Cache in Redis (strip time_unix for lightweight JSON)
            cache_bars = [{k: v for k, v in b.items() if k != "time_unix"} for b in bars]
            cache_and_publish_history(
                redis_client, cache_key, cache_bars,
                ttl=21600, symbol=symbol, timeframe=timeframe,
            )
            updated_count += 1

        except Exception as e:
            logger.debug("Error fetching history", symbol=symbol, error=str(e))
            continue

    logger.info(
        "History prefetch complete",
        total=len(symbols), updated=updated_count, cached=cached_count,
        ts=datetime.now(timezone.utc).isoformat(),
    )
