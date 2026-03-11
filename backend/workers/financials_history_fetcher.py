"""Celery worker: fetch 10-year financial history from Yahoo Finance.

Schedule: Daily at 01:00 ICT (18:00 UTC previous day)
Fetches income statement, balance sheet metrics for all active symbols.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def fetch_financials_history(self):
    """Fetch annual financial data for all watched symbols."""
    start = time.time()
    try:
        import redis
        from sqlalchemy import create_engine, text
        from core.config import settings

        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        symbols = _get_watched_symbols(engine)
        if not symbols:
            logger.info("No symbols for financials history")
            return

        total_years = 0
        errors = 0

        for symbol in symbols:
            try:
                count = _fetch_financials_for_symbol(symbol, engine, redis_client)
                total_years += count
            except Exception as e:
                errors += 1
                logger.debug("Financials fetch failed", symbol=symbol, error=str(e))

        elapsed = time.time() - start
        logger.info(
            "Financials history fetch completed",
            symbols=len(symbols),
            total_years=total_years,
            errors=errors,
            elapsed_sec=f"{elapsed:.2f}",
        )

        redis_client.set("worker:financials_history:last_success_at", datetime.now(timezone.utc).isoformat())

    except Exception as exc:
        logger.error("fetch_financials_history failed", error=str(exc))
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


def _fetch_financials_for_symbol(symbol: str, engine, redis_client) -> int:
    """Fetch financial statements for a symbol via yfinance."""
    import yfinance as yf
    import pandas as pd
    from sqlalchemy import text
    from services.symbol_mapper import symbol_mapper

    yahoo_sym = symbol_mapper.get_yahoo_sync(symbol, redis_client)
    ticker = yf.Ticker(yahoo_sym)

    years_saved = 0

    try:
        # Get income statement (annual)
        income = ticker.financials  # columns = fiscal year dates, rows = line items
        balance = ticker.balance_sheet

        if income is None or income.empty:
            logger.debug("No financials data", symbol=symbol)
            return 0

        # Get currency from ticker info
        try:
            currency = ticker.info.get("currency", "USD")
        except Exception:
            currency = "USD"

        with engine.connect() as conn:
            for col in income.columns[:10]:  # Up to 10 years
                fiscal_year = col.year

                # Extract metrics safely
                revenue = _safe_get(income, col, "Total Revenue")
                net_profit = _safe_get(income, col, "Net Income")
                gross_profit = _safe_get(income, col, "Gross Profit")
                operating_income = _safe_get(income, col, "Operating Income")

                # Margins
                gross_margin = None
                operating_margin = None
                if revenue and revenue > 0:
                    if gross_profit:
                        gross_margin = round(float(gross_profit / revenue * 100), 4)
                    if operating_income:
                        operating_margin = round(float(operating_income / revenue * 100), 4)

                # Balance sheet metrics
                roe = None
                debt_equity = None
                if balance is not None and not balance.empty and col in balance.columns:
                    total_equity = _safe_get(balance, col, "Stockholders Equity")
                    total_debt = _safe_get(balance, col, "Total Debt")

                    if total_equity and total_equity > 0:
                        if net_profit:
                            roe = round(float(net_profit / total_equity * 100), 4)
                        if total_debt:
                            debt_equity = round(float(total_debt / total_equity), 4)

                # EPS from ticker.info (current only, historical via earnings)
                eps = None
                try:
                    earnings = ticker.earnings
                    if earnings is not None and fiscal_year in earnings.index:
                        eps_val = earnings.loc[fiscal_year, "Earnings"]
                        # Approximate EPS (earnings / shares outstanding)
                        shares = ticker.info.get("sharesOutstanding")
                        if shares and shares > 0 and eps_val:
                            eps = round(float(eps_val / shares), 4)
                except Exception:
                    pass

                # Dividend
                dividend = None
                try:
                    divs = ticker.dividends
                    if divs is not None and not divs.empty:
                        year_divs = divs[divs.index.year == fiscal_year]
                        if not year_divs.empty:
                            dividend = round(float(year_divs.sum()), 4)
                except Exception:
                    pass

                conn.execute(text(
                    "INSERT INTO financial_history "
                    "(symbol, fiscal_year, revenue, net_profit, roe, debt_equity, "
                    "eps, dividend, gross_margin, operating_margin, currency, source) "
                    "VALUES (:symbol, :fiscal_year, :revenue, :net_profit, :roe, :debt_equity, "
                    ":eps, :dividend, :gross_margin, :operating_margin, :currency, 'yfinance') "
                    "ON CONFLICT ON CONSTRAINT uq_financial_history_symbol_year "
                    "DO UPDATE SET revenue = :revenue, net_profit = :net_profit, "
                    "roe = :roe, debt_equity = :debt_equity, eps = :eps, "
                    "dividend = :dividend, gross_margin = :gross_margin, "
                    "operating_margin = :operating_margin, currency = :currency, "
                    "source = 'yfinance', updated_at = NOW()"
                ), {
                    "symbol": symbol.upper(),
                    "fiscal_year": fiscal_year,
                    "revenue": float(revenue) if revenue else None,
                    "net_profit": float(net_profit) if net_profit else None,
                    "roe": roe,
                    "debt_equity": debt_equity,
                    "eps": eps,
                    "dividend": dividend,
                    "gross_margin": gross_margin,
                    "operating_margin": operating_margin,
                    "currency": currency,
                })
                years_saved += 1

            conn.commit()

    except Exception as e:
        logger.debug("Financials fetch error", symbol=symbol, error=str(e))

    # Invalidate cache
    if years_saved > 0:
        try:
            redis_client.delete(f"financials_history:{symbol.upper()}")
        except Exception:
            pass

    return years_saved


def _safe_get(df, col, row_name) -> float | None:
    """Safely extract a value from a DataFrame."""
    try:
        if row_name in df.index and col in df.columns:
            val = df.loc[row_name, col]
            if val is not None and str(val) not in ("nan", "NaN", ""):
                return float(val)
    except Exception:
        pass
    return None
