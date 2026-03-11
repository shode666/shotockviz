"""Celery worker: fetch corporate actions (dividends, splits) from Yahoo Finance.

Schedule: Daily at 02:00 ICT (19:00 UTC previous day)
Fetches dividend history and split events for all active symbols in the watchlist.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger
from core import cache_keys

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def fetch_corporate_actions(self):
    """Fetch dividend and split data for all watched symbols.

    Iterates through all unique symbols from user watchlists and fetches
    dividend + split history from Yahoo Finance. Results are upserted into
    the corporate_actions table.
    """
    start = time.time()
    try:
        import redis
        from sqlalchemy import create_engine, text
        from core.config import settings

        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        # Get all unique symbols from watchlists
        symbols = _get_watched_symbols(engine)
        if not symbols:
            logger.info("No symbols to fetch corporate actions for")
            return

        total_actions = 0
        errors = 0

        for symbol in symbols:
            try:
                count = _fetch_actions_for_symbol(symbol, engine, redis_client)
                total_actions += count
            except Exception as e:
                errors += 1
                logger.debug("Corporate action fetch failed", symbol=symbol, error=str(e))

        elapsed = time.time() - start
        logger.info(
            "Corporate actions fetch completed",
            symbols=len(symbols),
            total_actions=total_actions,
            errors=errors,
            elapsed_sec=f"{elapsed:.2f}",
        )

        # Update worker stats
        redis_client.set("worker:corporate_actions:last_success_at", datetime.now(timezone.utc).isoformat())
        redis_client.set("worker:corporate_actions:last_success_elapsed", f"{elapsed:.2f}")

    except Exception as exc:
        logger.error("fetch_corporate_actions failed", error=str(exc))
        try:
            redis_client.set("worker:corporate_actions:last_failure_at", datetime.now(timezone.utc).isoformat())
            redis_client.set("worker:corporate_actions:last_error", str(exc))
        except Exception:
            pass
        raise self.retry(exc=exc)


def _get_watched_symbols(engine) -> list[str]:
    """Get all unique symbols from watchlists + portfolio."""
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT DISTINCT symbol FROM watchlist_items "
            "UNION "
            "SELECT DISTINCT symbol FROM transactions"
        ))
        return [row[0] for row in result.fetchall()]


def _fetch_actions_for_symbol(symbol: str, engine, redis_client) -> int:
    """Fetch dividends and splits for a single symbol via yfinance."""
    import yfinance as yf
    from sqlalchemy import text
    from services.symbol_mapper import symbol_mapper

    yahoo_sym = symbol_mapper.get_yahoo_sync(symbol, redis_client)
    ticker = yf.Ticker(yahoo_sym)

    actions_count = 0

    # ── Dividends ────────────────────────────────────────────────────────────
    try:
        dividends = ticker.dividends
        if dividends is not None and not dividends.empty:
            with engine.connect() as conn:
                for idx, amount in dividends.items():
                    if amount and float(amount) > 0:
                        ex_date = idx.strftime("%Y-%m-%d")
                        conn.execute(text(
                            "INSERT INTO corporate_actions "
                            "(symbol, action_type, ex_date, value, source) "
                            "VALUES (:symbol, 'DIV', :ex_date, :value, 'yfinance') "
                            "ON CONFLICT ON CONSTRAINT uq_corp_action_symbol_type_date "
                            "DO UPDATE SET value = :value, source = 'yfinance'"
                        ), {
                            "symbol": symbol.upper(),
                            "ex_date": ex_date,
                            "value": round(float(amount), 6),
                        })
                        actions_count += 1
                conn.commit()
    except Exception as e:
        logger.debug("Dividend fetch failed", symbol=symbol, error=str(e))

    # ── Splits ───────────────────────────────────────────────────────────────
    try:
        splits = ticker.splits
        if splits is not None and not splits.empty:
            with engine.connect() as conn:
                for idx, ratio in splits.items():
                    if ratio and float(ratio) != 1.0:
                        ex_date = idx.strftime("%Y-%m-%d")
                        # yfinance split ratio: "4.0" means 4:1 → our ratio = 1/4 = 0.25
                        split_ratio = 1.0 / float(ratio) if float(ratio) > 0 else 1.0
                        conn.execute(text(
                            "INSERT INTO corporate_actions "
                            "(symbol, action_type, ex_date, ratio, source) "
                            "VALUES (:symbol, 'SPLIT', :ex_date, :ratio, 'yfinance') "
                            "ON CONFLICT ON CONSTRAINT uq_corp_action_symbol_type_date "
                            "DO UPDATE SET ratio = :ratio, source = 'yfinance'"
                        ), {
                            "symbol": symbol.upper(),
                            "ex_date": ex_date,
                            "ratio": round(split_ratio, 6),
                        })
                        actions_count += 1
                conn.commit()
    except Exception as e:
        logger.debug("Split fetch failed", symbol=symbol, error=str(e))

    # Invalidate adjusted price cache
    if actions_count > 0:
        try:
            redis_client.delete(f"corp_actions:{symbol.upper()}")
        except Exception:
            pass

    return actions_count
