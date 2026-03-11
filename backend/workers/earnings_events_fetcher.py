"""Celery worker: fetch earnings events (EPS actual vs estimate) from Yahoo Finance.

Schedule: Daily at 06:00 ICT (23:00 UTC previous day)
Fetches earnings history for all active symbols and computes surprise % + price impact.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta

from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def fetch_earnings_events(self):
    """Fetch earnings history for all watched symbols."""
    start = time.time()
    try:
        import redis
        from sqlalchemy import create_engine
        from core.config import settings

        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        symbols = _get_watched_symbols(engine)
        if not symbols:
            logger.info("No symbols for earnings events")
            return

        total_events = 0
        errors = 0

        for symbol in symbols:
            try:
                count = _fetch_earnings_for_symbol(symbol, engine, redis_client)
                total_events += count
            except Exception as e:
                errors += 1
                logger.debug("Earnings fetch failed", symbol=symbol, error=str(e))

        elapsed = time.time() - start
        logger.info(
            "Earnings events fetch completed",
            symbols=len(symbols),
            total_events=total_events,
            errors=errors,
            elapsed_sec=f"{elapsed:.2f}",
        )

        redis_client.set("worker:earnings_events:last_success_at", datetime.now(timezone.utc).isoformat())

    except Exception as exc:
        logger.error("fetch_earnings_events failed", error=str(exc))
        raise self.retry(exc=exc)


def _get_watched_symbols(engine) -> list[str]:
    """Get unique symbols from watchlists + portfolio."""
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT DISTINCT symbol FROM watchlist_items "
            "UNION "
            "SELECT DISTINCT symbol FROM transactions"
        ))
        return [row[0] for row in result.fetchall()]


def _fetch_earnings_for_symbol(symbol: str, engine, redis_client) -> int:
    """Fetch earnings data for a symbol via yfinance."""
    import yfinance as yf
    from sqlalchemy import text
    from services.symbol_mapper import symbol_mapper

    yahoo_sym = symbol_mapper.get_yahoo_sync(symbol, redis_client)
    ticker = yf.Ticker(yahoo_sym)

    events_saved = 0

    try:
        # Get earnings dates with EPS data
        earnings_dates = ticker.earnings_dates
        if earnings_dates is None or earnings_dates.empty:
            return 0

        # Get historical prices for price impact calculation
        hist = ticker.history(period="2y", interval="1d")
        price_map = {}
        if hist is not None and not hist.empty:
            for idx, row in hist.iterrows():
                price_map[idx.strftime("%Y-%m-%d")] = float(row["Close"])

        with engine.connect() as conn:
            for idx, row in earnings_dates.iterrows():
                try:
                    report_date = idx.strftime("%Y-%m-%d")

                    # Extract EPS data
                    estimated_eps = _safe_float(row.get("EPS Estimate"))
                    actual_eps = _safe_float(row.get("Reported EPS"))

                    # Skip future dates without actual EPS
                    if actual_eps is None:
                        continue

                    # Compute surprise %
                    surprise_pct = None
                    if estimated_eps is not None and abs(estimated_eps) > 0.001:
                        surprise_pct = round(
                            (actual_eps - estimated_eps) / abs(estimated_eps) * 100, 4
                        )

                    # Price impact: 1 day before vs 1 day after
                    price_before = None
                    price_after = None
                    price_impact = None

                    report_dt = datetime.strptime(report_date, "%Y-%m-%d")
                    for delta in range(1, 5):
                        before_date = (report_dt - timedelta(days=delta)).strftime("%Y-%m-%d")
                        if before_date in price_map:
                            price_before = price_map[before_date]
                            break
                    for delta in range(0, 5):
                        after_date = (report_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
                        if after_date in price_map:
                            price_after = price_map[after_date]
                            break

                    if price_before and price_after and price_before > 0:
                        price_impact = round(
                            (price_after - price_before) / price_before * 100, 4
                        )

                    # Fiscal period label
                    fiscal_period = row.get("Fiscal Quarter End")
                    if fiscal_period is not None:
                        try:
                            fiscal_period = str(fiscal_period)[:10]
                        except Exception:
                            fiscal_period = None

                    conn.execute(text(
                        "INSERT INTO earnings_events "
                        "(symbol, report_date, fiscal_period, estimated_eps, actual_eps, "
                        "surprise_pct, price_1d_before, price_1d_after, price_impact_pct, source) "
                        "VALUES (:symbol, :report_date, :fiscal_period, :estimated_eps, "
                        ":actual_eps, :surprise_pct, :price_before, :price_after, "
                        ":price_impact, 'yfinance') "
                        "ON CONFLICT ON CONSTRAINT uq_earnings_event_symbol_date "
                        "DO UPDATE SET estimated_eps = :estimated_eps, actual_eps = :actual_eps, "
                        "surprise_pct = :surprise_pct, price_1d_before = :price_before, "
                        "price_1d_after = :price_after, price_impact_pct = :price_impact, "
                        "source = 'yfinance'"
                    ), {
                        "symbol": symbol.upper(),
                        "report_date": report_date,
                        "fiscal_period": fiscal_period,
                        "estimated_eps": estimated_eps,
                        "actual_eps": actual_eps,
                        "surprise_pct": surprise_pct,
                        "price_before": price_before,
                        "price_after": price_after,
                        "price_impact": price_impact,
                    })
                    events_saved += 1

                except Exception as e:
                    logger.debug("Earnings row error", symbol=symbol, error=str(e))
                    continue

            conn.commit()

    except Exception as e:
        logger.debug("Earnings fetch error", symbol=symbol, error=str(e))

    # Invalidate cache
    if events_saved > 0:
        try:
            redis_client.delete(f"earnings:{symbol.upper()}")
        except Exception:
            pass

    return events_saved


def _safe_float(val) -> float | None:
    """Safely convert a value to float."""
    if val is None:
        return None
    try:
        f = float(val)
        if str(f) in ("nan", "inf", "-inf"):
            return None
        return round(f, 4)
    except (ValueError, TypeError):
        return None
