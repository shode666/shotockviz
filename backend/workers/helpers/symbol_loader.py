"""Shared helper: load watched symbols from database.

Single source of truth for fetching all unique symbols from
watchlist_items + transactions tables. Used by price_fetcher,
history_prefetcher, and any future worker needing the symbol list.
"""
from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)


def get_watched_symbols(fallback: list[str] | None = None) -> list[str]:
    """Return deduplicated symbols from all user watchlists + portfolios.

    Args:
        fallback: Symbols to return if DB is unreachable. Defaults to [].

    Returns:
        Deduplicated list of symbols.
    """
    if fallback is None:
        fallback = []

    try:
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
            raise ValueError("No watched symbols found in DB")
        return syms

    except Exception as e:
        logger.warning("DB symbol query failed, using fallback", error=str(e))
        return fallback
