"""
Celery tasks for fetching stock prices.

KEY DESIGN — "Watchlist-driven prefetch loop"
──────────────────────────────────────────────────────────────────────────────
Rather than fetching a hardcoded list of symbols, every scheduled run:
  1. Queries the DB for ALL unique symbols across every user's watchlist
     AND every active portfolio holding.
  2. Splits into SET (.BK / .MAI) and US buckets.
  3. Batch-fetches via yfinance (supports multiple tickers per call, far
     fewer requests than per-symbol calls).
  4. Caches each quote in Redis (60 s TTL) and publishes a 'price_updates'
     channel message so the WebSocket layer can push to subscribers.

Benefits:
- Zero rate-limit waste on symbols nobody watches.
- New watchlist additions are auto-picked up within 60 s.
- Single batch yfinance call per run (not N individual calls).
- Guests who only view the page trigger on-demand fetches; the Celery loop
  keeps cache warm for authenticated users who have watchlists.
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)

# Fallback symbols used when DB is empty / unreachable
FALLBACK_SET = ["PTT.BK", "CPALL.BK", "ADVANC.BK", "AOT.BK", "KBANK.BK", "SCB.BK"]
FALLBACK_US  = ["AAPL", "NVDA", "TSLA", "MSFT", "SPY", "QQQ", "GOOGL", "AMZN"]
FALLBACK_IDX = ["^SET.BK", "^GSPC", "^IXIC", "THBUSD=X", "GC=F"]   # always fetch

# ── helpers ───────────────────────────────────────────────────────────────────

def _get_all_watched_symbols() -> list[str]:
    """
    Return deduplicated list of all symbols from:
      - Every watchlist_items row (all users)
      - Every active portfolio transaction (all users)
    Falls back to FALLBACK_SET + FALLBACK_US if DB unreachable.
    """
    try:
        import sqlalchemy
        from sqlalchemy import create_engine, text
        from core.config import settings

        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT symbol FROM watchlist_items "
                "UNION "
                "SELECT DISTINCT symbol FROM transactions"
            )).fetchall()
        syms = [r[0] for r in rows if r[0]]
        if not syms:
            raise ValueError("empty")
        return syms
    except Exception as e:
        logger.warning("DB symbol query failed, using fallback", error=str(e))
        return FALLBACK_SET + FALLBACK_US


def _yfinance_batch_quotes(symbols: list[str]) -> dict[str, dict]:
    """
    Fetch quotes for a list of symbols using yfinance batch download.
    Returns {symbol: {price, change, change_pct, volume}} dict.
    Uses yfinance's download() which issues ONE call per batch.
    """
    import yfinance as yf

    results: dict[str, dict] = {}
    if not symbols:
        return results

    # yfinance Tickers() supports batch info fetch
    tickers = yf.Tickers(" ".join(symbols))
    for sym in symbols:
        try:
            t = tickers.tickers.get(sym)
            if t is None:
                continue
            info = t.fast_info  # lightweight, no heavy .info call
            price = getattr(info, 'last_price', None) or getattr(info, 'regular_market_price', None)
            prev  = getattr(info, 'previous_close', None)
            vol   = getattr(info, 'three_month_average_volume', None) or getattr(info, 'regular_market_volume', None)
            if price and price > 0:
                change = (price - prev) if prev else 0.0
                change_pct = (change / prev * 100) if prev else 0.0
                results[sym] = {
                    "symbol": sym,
                    "price": round(float(price), 4),
                    "change": round(float(change), 4),
                    "change_pct": round(float(change_pct), 4),
                    "volume": int(vol) if vol else 0,
                }
        except Exception as e:
            logger.debug("yf quote error", symbol=sym, error=str(e))

    return results


def _cache_and_publish(quotes: dict[str, dict], r) -> int:
    """Write quotes to Redis cache and publish price_updates channel.

    Uses key pattern  cache:quote:{sym}  (same as stock_service.fetch_stock_quote)
    so the API endpoint reads background-fetched data without calling external APIs.
    """
    count = 0
    for sym, data in quotes.items():
        payload = {**data, "type": "price_update", "ts": int(time.time())}
        encoded = json.dumps(payload)
        r.setex(f"cache:quote:{sym}", 120, encoded)   # 120 s TTL — 2× task interval
        r.publish("price_updates", encoded)
        count += 1
    return count


# ── Task: SET market ──────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def fetch_set_prices(self):
    """
    Prefetch quotes for all SET/mai symbols in any user watchlist or portfolio.
    Runs every minute during SET market hours (09:25 – 17:00 ICT).
    """
    start = time.time()
    try:
        import redis
        from core.config import settings

        all_syms = _get_all_watched_symbols()
        set_syms = [s for s in all_syms if s.endswith(".BK") or s.endswith(".MAI")]
        # Always include index symbols
        set_syms += [s for s in FALLBACK_IDX if s.endswith(".BK")]
        set_syms = list(dict.fromkeys(set_syms))  # deduplicate, preserve order

        if not set_syms:
            logger.info("No SET symbols to fetch")
            return

        quotes = _yfinance_batch_quotes(set_syms)
        r = redis.from_url(settings.redis_url)
        count = _cache_and_publish(quotes, r)

        elapsed = time.time() - start
        logger.info("SET prices fetched", total=len(set_syms), priced=count,
                    elapsed_sec=f'{elapsed:.2f}',
                    ts=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        elapsed = time.time() - start
        logger.error("fetch_set_prices failed", error=str(exc), elapsed_sec=f'{elapsed:.2f}')
        raise self.retry(exc=exc)


# ── Task: US market ───────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def fetch_us_prices(self):
    """
    Prefetch quotes for all US symbols in any user watchlist or portfolio.
    Runs every minute during US market hours (21:30 – 04:00 ICT+1).
    Also fetches global indices (S&P500, NASDAQ, Gold, USD/THB) unconditionally.
    """
    start = time.time()
    try:
        import redis
        from core.config import settings

        all_syms = _get_all_watched_symbols()
        us_syms = [s for s in all_syms if not s.endswith(".BK") and not s.endswith(".MAI")]
        # Always include global index symbols
        us_syms += FALLBACK_IDX
        us_syms = list(dict.fromkeys(us_syms))

        if not us_syms:
            logger.info("No US symbols to fetch")
            return

        quotes = _yfinance_batch_quotes(us_syms)
        r = redis.from_url(settings.redis_url)
        count = _cache_and_publish(quotes, r)

        elapsed = time.time() - start
        logger.info("US prices fetched", total=len(us_syms), priced=count,
                    elapsed_sec=f'{elapsed:.2f}',
                    ts=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        elapsed = time.time() - start
        logger.error("fetch_us_prices failed", error=str(exc), elapsed_sec=f'{elapsed:.2f}')
        raise self.retry(exc=exc)


# ── Task: always-on market overview (every 2 min, no market-hours check) ─────

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def fetch_overview_prices(self):
    """
    Always-on task that keeps global indices + USD/THB + Gold cached
    regardless of market session — for the Dashboard overview page.
    Runs every 2 minutes unconditionally.
    """
    start = time.time()
    try:
        import redis
        from core.config import settings

        quotes = _yfinance_batch_quotes(FALLBACK_IDX)
        r = redis.from_url(settings.redis_url)
        count = _cache_and_publish(quotes, r)
        
        elapsed = time.time() - start
        logger.info("Overview prices refreshed", count=count, elapsed_sec=f'{elapsed:.2f}')
    except Exception as exc:
        elapsed = time.time() - start
        logger.error("fetch_overview_prices failed", error=str(exc), elapsed_sec=f'{elapsed:.2f}')
        raise self.retry(exc=exc)
