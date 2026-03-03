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
# Yahoo uses '-' for share classes (BRK-B), not '.' (BRK.B)
# Also handles symbols that need special mapping
YAHOO_SYMBOL_MAP = {
    "BRK.B": "BRK-B",
    "BRK.A": "BRK-A",
    "BF.B": "BF-B",
    "BF.A": "BF-A",
}


def _to_yahoo_symbol(symbol: str) -> str:
    """Convert internal symbol to Yahoo Finance ticker format."""
    return YAHOO_SYMBOL_MAP.get(symbol, symbol)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def process_fetch_request(self, symbol: str, data_type: Literal["quote", "history", "fundamentals", "all"] = "all"):
    """
    Process on-demand fetch request from API layer.

    Called when an API endpoint detects a cache miss and publishes a fetch request
    to Celery instead of blocking the HTTP request.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL", "PTT.BK")
        data_type: Type of data to fetch — "quote", "history", "fundamentals", or "all"

    Deduplication is handled by Redis NX flag in request_data_fetch (stock_service.py),
    which sets a 30-second lock to prevent duplicate fetches within that window.
    """
    start = time.time()
    try:
        import redis
        import yfinance as yf
        from core.config import settings

        redis_client = redis.from_url(settings.redis_url)

        # Map of data_type handlers
        handlers = {
            "quote": lambda s: _fetch_quote(s, redis_client),
            "history": lambda s: _fetch_history(s, redis_client),
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


def _fetch_history(symbol: str, redis_client) -> bool:
    """Fetch 1D history via yfinance, cache in Redis and DB."""
    try:
        import yfinance as yf
        from sqlalchemy import create_engine, text
        from core.config import settings

        timeframe = "1D"
        ticker = yf.Ticker(_to_yahoo_symbol(symbol))
        hist = ticker.history(period="6mo", interval="1d")

        if hist.empty:
            logger.debug("No history data available", symbol=symbol)
            return False

        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
        bars = []

        for idx, row in hist.iterrows():
            try:
                time_str = idx.strftime("%Y-%m-%d")
                time_unix = int(idx.timestamp())

                bar = {
                    "time": time_str,
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row["Volume"]),
                }
                bars.append(bar)

                # Upsert to PostgreSQL
                with engine.connect() as conn:
                    exists = conn.execute(text(
                        "SELECT 1 FROM ohlcv_bars WHERE symbol = :symbol "
                        "AND timeframe = :timeframe AND time_unix = :time_unix"
                    ), {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "time_unix": time_unix,
                    }).first()

                    if not exists:
                        conn.execute(text(
                            "INSERT INTO ohlcv_bars "
                            "(symbol, timeframe, time_unix, time_str, open, high, low, close, volume) "
                            "VALUES (:symbol, :timeframe, :time_unix, :time_str, "
                            ":open, :high, :low, :close, :volume)"
                        ), {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "time_unix": time_unix,
                            "time_str": time_str,
                            "open": bar["open"],
                            "high": bar["high"],
                            "low": bar["low"],
                            "close": bar["close"],
                            "volume": bar["volume"],
                        })
                        conn.commit()

            except Exception as e:
                logger.debug("Error processing bar", symbol=symbol, error=str(e))
                continue

        # Cache in Redis
        if bars:
            cache_key = cache_keys.ohlcv(symbol, timeframe)
            redis_client.setex(cache_key, 21600, json.dumps(bars))  # 6 hours

            # Publish data-ready notification
            msg = {
                "type": "data_ready",
                "data_type": "history",
                "symbol": symbol,
                "timeframe": timeframe,
            }
            redis_client.publish("price_updates", json.dumps(msg))

            logger.debug("History fetch success", symbol=symbol, bars=len(bars))
            return True

        return False

    except Exception as e:
        logger.debug("History fetch error", symbol=symbol, error=str(e))
        return False


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
