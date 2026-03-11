"""Centralized symbol mapping service.

Translates between internal symbols and provider-specific formats.
Uses an in-memory cache refreshed from PostgreSQL, with a Redis L1 layer
for fast lookups.

Pattern follows cache_keys.py — a single module that ALL workers and services
import for consistent symbol translation.

Usage:
    from services.symbol_mapper import symbol_mapper

    yahoo = await symbol_mapper.get_yahoo("PTT.BK")       # → "PTT.BK"
    yahoo = await symbol_mapper.get_yahoo("BRK.B")         # → "BRK-B"
    thinav = await symbol_mapper.get_thinav("SCBFIXD")     # → "T-SCBFIXD"

    # Sync versions for Celery workers (uses Redis only):
    yahoo = symbol_mapper.get_yahoo_sync("PTT.BK", redis_client)
"""
import json
from typing import Optional

from core.logger import get_logger
from core import cache_keys, symbol_utils

logger = get_logger(__name__)

# ── Known Yahoo symbol overrides ─────────────────────────────────────────────
# These are symbols where the internal name doesn't match Yahoo Finance format.
# This static map is used as a fallback when the DB mapping table is empty.
_YAHOO_OVERRIDES = {
    "BRK.B": "BRK-B",
    "BRK.A": "BRK-A",
    "BF.B": "BF-B",
    "BF.A": "BF-A",
}

# Redis cache key prefix for symbol mappings
_CACHE_PREFIX = "symbolmap"
_CACHE_TTL = 86400  # 24 hours


class SymbolMapper:
    """Provides symbol translation for all data providers.

    The mapping priority is:
      1. PostgreSQL `symbol_mappings` table (authoritative)
      2. Static override map (_YAHOO_OVERRIDES)
      3. Identity mapping (symbol == yahoo_symbol in most cases)
    """

    # ── Async API (FastAPI context) ──────────────────────────────────────────

    async def get_yahoo(self, symbol: str) -> str:
        """Get Yahoo Finance symbol. Async version for FastAPI."""
        mapping = await self._get_mapping(symbol)
        if mapping and mapping.get("yahoo_symbol"):
            return mapping["yahoo_symbol"]

        # Static fallback
        if symbol in _YAHOO_OVERRIDES:
            return _YAHOO_OVERRIDES[symbol]

        return symbol  # Identity: most symbols are the same

    async def get_finnhub(self, symbol: str) -> str:
        """Get Finnhub symbol. Async version."""
        mapping = await self._get_mapping(symbol)
        if mapping and mapping.get("finnhub_symbol"):
            return mapping["finnhub_symbol"]

        # For Thai stocks, strip .BK suffix for Finnhub
        if symbol.endswith(".BK"):
            return symbol[:-3]
        return symbol

    async def get_thinav(self, symbol: str) -> Optional[str]:
        """Get pythainav symbol. Returns None if not a fund."""
        mapping = await self._get_mapping(symbol)
        if mapping and mapping.get("thinav_symbol"):
            return mapping["thinav_symbol"]
        return None

    async def get_display_name(self, symbol: str) -> Optional[str]:
        """Get human-readable name."""
        mapping = await self._get_mapping(symbol)
        if mapping:
            return mapping.get("display_name")
        return None

    async def _get_mapping(self, symbol: str) -> Optional[dict]:
        """Fetch mapping from Redis cache, falling back to DB."""
        try:
            from services.stock_service import get_redis
            r = await get_redis()
            cache_key = f"{_CACHE_PREFIX}:{symbol.upper()}"
            cached = await r.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

        # Try DB
        try:
            from core.database import AsyncSessionLocal
            from models.symbol_mapping import SymbolMapping
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SymbolMapping).where(
                        SymbolMapping.internal_symbol == symbol.upper(),
                        SymbolMapping.is_active.is_(True),
                    )
                )
                row = result.scalar_one_or_none()
                if row:
                    mapping = {
                        "internal_symbol": row.internal_symbol,
                        "yahoo_symbol": row.yahoo_symbol,
                        "finnhub_symbol": row.finnhub_symbol,
                        "thinav_symbol": row.thinav_symbol,
                        "display_name": row.display_name,
                        "market": row.market,
                        "currency": row.currency,
                    }
                    # Cache in Redis
                    try:
                        from services.stock_service import get_redis
                        r = await get_redis()
                        await r.setex(
                            f"{_CACHE_PREFIX}:{symbol.upper()}",
                            _CACHE_TTL,
                            json.dumps(mapping),
                        )
                    except Exception:
                        pass
                    return mapping
        except Exception as e:
            logger.debug("DB lookup failed for symbol mapping", symbol=symbol, error=str(e))

        return None

    # ── Sync API (Celery worker context) ─────────────────────────────────────

    def get_yahoo_sync(self, symbol: str, redis_client=None) -> str:
        """Get Yahoo Finance symbol. Sync version for Celery workers."""
        if redis_client:
            try:
                cached = redis_client.get(f"{_CACHE_PREFIX}:{symbol.upper()}")
                if cached:
                    mapping = json.loads(cached)
                    if mapping.get("yahoo_symbol"):
                        return mapping["yahoo_symbol"]
            except Exception:
                pass

        # Static fallback
        if symbol in _YAHOO_OVERRIDES:
            return _YAHOO_OVERRIDES[symbol]

        return symbol

    def get_thinav_sync(self, symbol: str, redis_client=None) -> Optional[str]:
        """Get pythainav symbol. Sync version for Celery workers."""
        if redis_client:
            try:
                cached = redis_client.get(f"{_CACHE_PREFIX}:{symbol.upper()}")
                if cached:
                    mapping = json.loads(cached)
                    if mapping.get("thinav_symbol"):
                        return mapping["thinav_symbol"]
            except Exception:
                pass
        return None

    # ── Bulk operations ──────────────────────────────────────────────────────

    async def upsert(
        self,
        internal_symbol: str,
        *,
        yahoo_symbol: str | None = None,
        finnhub_symbol: str | None = None,
        thinav_symbol: str | None = None,
        display_name: str | None = None,
        market: str | None = None,
        currency: str | None = None,
    ) -> None:
        """Create or update a symbol mapping."""
        from core.database import AsyncSessionLocal
        from models.symbol_mapping import SymbolMapping
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        async with AsyncSessionLocal() as session:
            stmt = pg_insert(SymbolMapping).values(
                internal_symbol=internal_symbol.upper(),
                yahoo_symbol=yahoo_symbol,
                finnhub_symbol=finnhub_symbol,
                thinav_symbol=thinav_symbol,
                display_name=display_name,
                market=market,
                currency=currency,
            ).on_conflict_do_update(
                index_elements=["internal_symbol"],
                set_={
                    k: v for k, v in {
                        "yahoo_symbol": yahoo_symbol,
                        "finnhub_symbol": finnhub_symbol,
                        "thinav_symbol": thinav_symbol,
                        "display_name": display_name,
                        "market": market,
                        "currency": currency,
                    }.items() if v is not None
                },
            )
            await session.execute(stmt)
            await session.commit()

        # Invalidate cache
        try:
            from services.stock_service import get_redis
            r = await get_redis()
            await r.delete(f"{_CACHE_PREFIX}:{internal_symbol.upper()}")
        except Exception:
            pass


# Singleton instance
symbol_mapper = SymbolMapper()
