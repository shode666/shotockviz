"""Celery task: fetch fundamentals (PE, PB, EPS, etc.) for all tracked symbols."""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger
from core import cache_keys

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def prefetch_fundamentals(self):
    """
    Pre-fetch fundamentals for all tracked symbols (not FUND market type).

    Flow:
      1. Query DB for all active symbols (exclude FUND market type)
      2. For each symbol: call yfinance .info to get PE, PB, EPS, marketCap, etc.
      3. Cache in Redis `fundamentals:{symbol}` with 14400s (4h) TTL
      4. Publish `data_ready` type=fundamentals on `price_updates` channel
      5. Log results
    """
    start = time.time()
    try:
        import redis
        import yfinance as yf
        from sqlalchemy import create_engine, text
        from core.config import settings
        from models.schemas import StockFundamentals

        # Connect to sync DB
        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        # Query all active non-FUND symbols
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT symbol FROM stocks WHERE is_active = true AND market != 'FUND' ORDER BY symbol"
            )).fetchall()

        if not rows:
            logger.info("No symbols to fetch fundamentals for")
            return

        symbols = [r[0] for r in rows]
        redis_client = redis.from_url(settings.redis_url)

        # Yahoo Finance symbol normalization (BRK.B → BRK-B, etc.)
        YAHOO_MAP = {"BRK.B": "BRK-B", "BRK.A": "BRK-A", "BF.B": "BF-B", "BF.A": "BF-A"}
        yahoo_syms = [YAHOO_MAP.get(s, s) for s in symbols]
        reverse_map = {YAHOO_MAP.get(s, s): s for s in symbols}

        # Batch fetch fundamentals via yfinance
        tickers = yf.Tickers(" ".join(yahoo_syms))
        updated_count = 0

        for ysym in yahoo_syms:
            symbol = reverse_map.get(ysym, ysym)
            try:
                t = tickers.tickers.get(ysym)
                if t is None:
                    continue

                # Extract fundamentals from .info
                info = t.info

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
                redis_client.setex(
                    cache_key,
                    14400,  # 4 hours
                    fundamentals.model_dump_json(),
                )

                updated_count += 1

            except Exception as e:
                logger.debug("Error fetching fundamentals", symbol=symbol, error=str(e))
                continue

        # Publish data-ready notification
        try:
            msg = {
                "type": "data_ready",
                "data_type": "fundamentals",
                "symbol": "*",
                "count": updated_count,
            }
            redis_client.publish("price_updates", json.dumps(msg))
        except Exception as e:
            logger.debug("Failed to publish data_ready", error=str(e))

        elapsed = time.time() - start
        logger.info(
            "Fundamentals prefetch complete",
            total=len(symbols),
            updated=updated_count,
            elapsed_sec=f"{elapsed:.2f}",
            ts=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as exc:
        elapsed = time.time() - start
        logger.error("prefetch_fundamentals failed", error=str(exc), elapsed_sec=f"{elapsed:.2f}")
        raise self.retry(exc=exc)
