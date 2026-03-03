"""Celery task: listen for on-demand fetch requests from API layer and execute them."""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from typing import Literal

from celery import shared_task
from core.logger import get_logger
from core import cache_keys

logger = get_logger(__name__)

# ─── Yahoo Finance symbol normalization ──────────────────────────────────────
YAHOO_SYMBOL_MAP = {
    "BRK.B": "BRK-B",
    "BRK.A": "BRK-A",
    "BF.B": "BF-B",
    "BF.A": "BF-A",
}

# ─── Timeframe → yfinance interval/period mapping ───────────────────────────
TF_CONFIG = {
    "1m":  {"interval": "1m",  "period": "1d"},
    "5m":  {"interval": "5m",  "period": "5d"},
    "15m": {"interval": "15m", "period": "15d"},
    "1h":  {"interval": "1h",  "period": "60d"},
    "4h":  {"interval": "1h",  "period": "60d"},    # 1h bars → aggregate to 4h (60d = yfinance safe limit)
    "1D":  {"interval": "1d",  "period": "6mo"},
    "1W":  {"interval": "1wk", "period": "3y"},
    "1M":  {"interval": "1mo", "period": "10y"},
}

DAILY_TIMEFRAMES = {"1D", "1W", "1M"}


def _to_yahoo_symbol(symbol: str) -> str:
    """Convert internal symbol to Yahoo Finance ticker format."""
    return YAHOO_SYMBOL_MAP.get(symbol, symbol)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def process_fetch_request(
    self,
    symbol: str,
    data_type: Literal["quote", "history", "fundamentals", "all"] = "all",
    timeframe: str | None = None,
):
    """
    Process on-demand fetch request from API layer.

    Called when an API endpoint detects a cache miss and publishes a fetch request
    to Celery instead of blocking the HTTP request.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL", "PTT.BK")
        data_type: Type of data to fetch — "quote", "history", "fundamentals", or "all"
        timeframe: For history requests, specifies timeframe (e.g., "1h", "4h", "1D")
    """
    start = time.time()
    try:
        import redis
        from core.config import settings

        redis_client = redis.from_url(settings.redis_url)

        # Map of data_type handlers
        handlers = {
            "quote": lambda s: _fetch_quote(s, redis_client),
            "history": lambda s: _fetch_history(s, redis_client, timeframe or "1D"),
            "fundamentals": lambda s: _fetch_fundamentals(s, redis_client),
        }

        if data_type == "all":
            types_to_fetch = ["quote", "history", "fundamentals"]
        else:
            types_to_fetch = [data_type]

        results = {}
        for dtype in types_to_fetch:
            try:
                handler = handlers[dtype]
                success = handler(symbol)
                results[dtype] = success
            except Exception as e:
                logger.debug("Handler failed", data_type=dtype, symbol=symbol, error=str(e))
                results[dtype] = False

        elapsed = time.time() - start
        logger.info(
            "On-demand fetch completed",
            symbol=symbol,
            data_type=data_type,
            timeframe=timeframe,
            results=results,
            elapsed_sec=f"{elapsed:.2f}",
            ts=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as exc:
        elapsed = time.time() - start
        logger.error(
            "process_fetch_request failed",
            symbol=symbol,
            data_type=data_type,
            error=str(exc),
            elapsed_sec=f"{elapsed:.2f}",
        )
        raise self.retry(exc=exc)


def _fetch_quote(symbol: str, redis_client) -> bool:
    """Fetch current quote via yfinance and cache in Redis."""
    try:
        import yfinance as yf

        yahoo_sym = _to_yahoo_symbol(symbol)
        ticker = yf.Ticker(yahoo_sym)
        info = ticker.fast_info

        price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
        prev = getattr(info, "previous_close", None)
        vol = getattr(info, "three_month_average_volume", None) or getattr(info, "regular_market_volume", None)

        if not price or price <= 0:
            logger.debug("Quote price invalid or missing", symbol=symbol)
            return False

        change = (price - prev) if prev else 0.0
        change_pct = (change / prev * 100) if prev else 0.0

        payload = {
            "symbol": symbol,
            "price": round(float(price), 4),
            "change": round(float(change), 4),
            "change_pct": round(float(change_pct), 4),
            "volume": int(vol) if vol else 0,
            "type": "price_update",
            "ts": int(time.time()),
        }

        # Cache and publish
        cache_key = cache_keys.quote(symbol)
        redis_client.setex(cache_key, 120, json.dumps(payload))  # 120 s TTL
        redis_client.publish("price_updates", json.dumps(payload))

        logger.debug("Quote fetch success", symbol=symbol, price=payload["price"])
        return True

    except Exception as e:
        logger.debug("Quote fetch error", symbol=symbol, error=str(e))
        return False


def _fetch_history(symbol: str, redis_client, timeframe: str = "1D") -> bool:
    """Fetch OHLCV history via yfinance for any timeframe, cache in Redis and DB.

    Supports all timeframes: 1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M.
    For 4h: fetches 1h bars and aggregates to 4-hour boundaries.
    """
    try:
        import yfinance as yf
        from sqlalchemy import create_engine, text
        from core.config import settings

        tf_cfg = TF_CONFIG.get(timeframe, TF_CONFIG["1D"])
        interval = tf_cfg["interval"]
        period = tf_cfg["period"]
        is_daily = timeframe in DAILY_TIMEFRAMES

        # Cache TTLs by timeframe
        cache_ttl = {
            "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 3600,
            "1D": 21600, "1W": 86400, "1M": 86400,
        }.get(timeframe, 21600)

        yahoo_sym = _to_yahoo_symbol(symbol)
        ticker = yf.Ticker(yahoo_sym)
        hist = ticker.history(period=period, interval=interval)

        if hist.empty:
            logger.debug("No history data", symbol=symbol, timeframe=timeframe, interval=interval)
            return False

        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
        bars = []
        db_rows = []

        for idx, row in hist.iterrows():
            try:
                ts_unix = int(idx.timestamp())

                if is_daily:
                    time_str = idx.strftime("%Y-%m-%d")
                    time_val = time_str
                else:
                    time_str = str(ts_unix)
                    time_val = ts_unix

                bar = {
                    "time": time_val,
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row["Volume"]),
                }
                bars.append(bar)

                db_rows.append({
                    "symbol": symbol,
                    "timeframe": timeframe if timeframe != "4h" else "4h",
                    "time_unix": ts_unix,
                    "time_str": idx.strftime("%Y-%m-%d") if is_daily else str(ts_unix),
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar["volume"],
                })
            except (IndexError, TypeError, ValueError):
                continue

        # Aggregate 1h → 4h if needed
        if timeframe == "4h" and bars:
            bars = _aggregate_4h_sync(bars)
            # Rebuild db_rows from aggregated bars
            db_rows = []
            for b in bars:
                ts = int(b["time"]) if isinstance(b["time"], (int, float)) else 0
                db_rows.append({
                    "symbol": symbol,
                    "timeframe": "4h",
                    "time_unix": ts,
                    "time_str": str(ts),
                    "open": b["open"],
                    "high": b["high"],
                    "low": b["low"],
                    "close": b["close"],
                    "volume": b["volume"],
                })

        # Bulk upsert to PostgreSQL
        if db_rows:
            try:
                with engine.connect() as conn:
                    for row in db_rows:
                        conn.execute(text(
                            "INSERT INTO ohlcv_bars "
                            "(symbol, timeframe, time_unix, time_str, open, high, low, close, volume) "
                            "VALUES (:symbol, :timeframe, :time_unix, :time_str, "
                            ":open, :high, :low, :close, :volume) "
                            "ON CONFLICT (symbol, timeframe, time_unix) "
                            "DO UPDATE SET open = :open, high = :high, low = :low, "
                            "close = :close, volume = :volume, time_str = :time_str"
                        ), row)
                    conn.commit()
            except Exception as e:
                logger.warning("DB upsert failed", symbol=symbol, timeframe=timeframe, error=str(e))

        # Cache in Redis
        if bars:
            cache_key = cache_keys.ohlcv(symbol, timeframe)
            redis_client.setex(cache_key, cache_ttl, json.dumps(bars))

            # Publish data-ready notification with correct timeframe
            msg = {
                "type": "data_ready",
                "data_type": "history",
                "symbol": symbol,
                "timeframe": timeframe,
            }
            redis_client.publish("price_updates", json.dumps(msg))

            logger.debug("History fetch success", symbol=symbol, timeframe=timeframe, bars=len(bars))
            return True

        return False

    except Exception as e:
        logger.debug("History fetch error", symbol=symbol, timeframe=timeframe, error=str(e))
        return False


def _aggregate_4h_sync(bars: list[dict]) -> list[dict]:
    """Aggregate 1h bar dicts into 4h bars aligned to 4-hour UTC boundaries.

    Sync version for use inside Celery worker (no OHLCVBar schema dependency).
    """
    if not bars:
        return []

    FOUR_HOURS = 4 * 3600

    # Deduplicate by timestamp
    seen: dict[int, dict] = {}
    for b in bars:
        ts = int(b["time"]) if isinstance(b["time"], (int, float)) else 0
        if ts > 0:
            seen[ts] = b

    if not seen:
        return []

    # Group by 4-hour boundary
    buckets: dict[int, list[dict]] = {}
    for ts in sorted(seen.keys()):
        boundary = (ts // FOUR_HOURS) * FOUR_HOURS
        buckets.setdefault(boundary, []).append(seen[ts])

    # Aggregate each bucket
    result = []
    for boundary in sorted(buckets.keys()):
        chunk = buckets[boundary]
        result.append({
            "time": boundary,
            "open": chunk[0]["open"],
            "high": max(b["high"] for b in chunk),
            "low": min(b["low"] for b in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(b["volume"] for b in chunk),
        })

    return result


def _fetch_fundamentals(symbol: str, redis_client) -> bool:
    """Fetch fundamentals via yfinance .info and cache in Redis."""
    try:
        import yfinance as yf
        from models.schemas import StockFundamentals

        ticker = yf.Ticker(_to_yahoo_symbol(symbol))
        info = ticker.info

        def _get_field(key: str, default=None):
            val = info.get(key)
            if isinstance(val, dict):
                return val.get("raw", default)
            return val if val is not None else default

        fundamentals = StockFundamentals(
            symbol=symbol,
            pe_ratio=_get_field("trailingPE"),
            pb_ratio=_get_field("priceToBook"),
            eps=_get_field("trailingEps"),
            dividend_yield=_get_field("dividendYield"),
            market_cap=_get_field("marketCap"),
            beta=_get_field("beta"),
            week_52_high=_get_field("fiftyTwoWeekHigh"),
            week_52_low=_get_field("fiftyTwoWeekLow"),
            avg_volume=_get_field("averageVolume"),
        )

        # Cache in Redis
        cache_key = cache_keys.fundamentals(symbol)
        redis_client.setex(cache_key, 14400, fundamentals.model_dump_json())  # 4 hours

        # Publish data-ready notification
        msg = {
            "type": "data_ready",
            "data_type": "fundamentals",
            "symbol": symbol,
        }
        redis_client.publish("price_updates", json.dumps(msg))

        logger.debug("Fundamentals fetch success", symbol=symbol)
        return True

    except Exception as e:
        logger.debug("Fundamentals fetch error", symbol=symbol, error=str(e))
        return False
