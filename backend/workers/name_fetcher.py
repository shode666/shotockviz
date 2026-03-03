"""Celery task: fetch company names from Yahoo Finance for all tracked symbols."""
from __future__ import annotations
import time
from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger
from core import cache_keys

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def prefetch_names(self):
    """
    Fetch company names for all active symbols in DB and cache them.

    Flow:
      1. Query DB for all active symbols in `stocks` table
      2. For each symbol missing a name in Redis `cache:name:{symbol}`:
         - Use Yahoo Finance Tickers batch API to get shortName
         - Cache in Redis with 86400s (24h) TTL
         - UPDATE `stocks.name` in DB if currently NULL
      3. Log results
    """
    start = time.time()
    try:
        import redis
        import yfinance as yf
        from sqlalchemy import create_engine, text, select
        from core.config import settings
        from models.stock import Stock

        # Connect to sync DB
        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        # Query all active symbols
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT symbol, name FROM stocks WHERE is_active = true ORDER BY symbol"
            )).fetchall()

        if not rows:
            logger.info("No active stocks to fetch names for")
            return

        symbols = [r[0] for r in rows]
        redis_client = redis.from_url(settings.redis_url)

        # Yahoo Finance symbol normalization (BRK.B → BRK-B, etc.)
        YAHOO_MAP = {"BRK.B": "BRK-B", "BRK.A": "BRK-A", "BF.B": "BF-B", "BF.A": "BF-A"}
        yahoo_syms = [YAHOO_MAP.get(s, s) for s in symbols]
        reverse_map = {YAHOO_MAP.get(s, s): s for s in symbols}

        # Batch fetch names via yfinance
        tickers = yf.Tickers(" ".join(yahoo_syms))
        updated_count = 0
        cached_count = 0

        for ysym in yahoo_syms:
            symbol = reverse_map.get(ysym, ysym)
            try:
                # Check if already cached
                cache_key = cache_keys.name(symbol)
                if redis_client.exists(cache_key):
                    cached_count += 1
                    continue

                # Fetch from yfinance
                t = tickers.tickers.get(ysym)
                if t is None:
                    continue

                short_name = None
                try:
                    # Try fast_info first (lightweight)
                    if hasattr(t, "fast_info"):
                        short_name = getattr(t.fast_info, "short_name", None)
                    # Fall back to full .info
                    if not short_name:
                        info = t.info
                        short_name = info.get("shortName") or info.get("longName")
                except Exception:
                    pass

                if short_name:
                    # Cache in Redis
                    redis_client.setex(cache_key, 86400, short_name)

                    # Update DB if name is NULL
                    with engine.connect() as conn:
                        conn.execute(text(
                            "UPDATE stocks SET name = :name WHERE symbol = :symbol AND name IS NULL"
                        ), {"name": short_name, "symbol": symbol})
                        conn.commit()

                    updated_count += 1
            except Exception as e:
                logger.debug("Error fetching name", symbol=symbol, error=str(e))
                continue

        elapsed = time.time() - start
        logger.info(
            "Names prefetch complete",
            total=len(symbols),
            updated=updated_count,
            cached=cached_count,
            elapsed_sec=f"{elapsed:.2f}",
            ts=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as exc:
        elapsed = time.time() - start
        logger.error("prefetch_names failed", error=str(exc), elapsed_sec=f"{elapsed:.2f}")
        raise self.retry(exc=exc)
