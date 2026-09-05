"""Celery task: auto-register new symbols into the stocks table.

When a user adds a symbol to a watchlist or portfolio, it only gets stored in
watchlist_items / transactions tables. This worker detects unregistered symbols
and populates the `stocks` table with metadata from Yahoo Finance, so that
name_fetcher, fund_fetcher, and fundamentals_fetcher can process them.

Two modes:
  1. register_symbol(symbol) — on-demand, triggered by API endpoints
  2. scan_unregistered()     — periodic, scans watchlist_items + transactions
"""
from __future__ import annotations
import re
import time
from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger
from core.symbol_utils import is_crypto

logger = get_logger(__name__)

# Thai mutual fund patterns — these never exist on Yahoo Finance
# Examples: SCBS&P500, PRINCIPAL IPROP-D, MPDIVMF, K-CHINA, B-INCOME
_THAI_FUND_PATTERNS = [
    re.compile(r'[&\s]'),            # contains & or spaces → definitely a fund
    re.compile(r'^[A-Z]+-[A-Z]+'),   # K-CHINA, B-INCOME pattern (but NOT BRK-B)
]

# Known Thai fund prefixes (บลจ. / asset management companies)
_THAI_FUND_PREFIXES = (
    "SCB", "SCBS", "PRINCIPAL", "KFIN", "KF", "KTAM", "KT-", "K-",
    "B-", "BBLAM", "TISCO", "TMB", "UOBAM", "ONE-", "ASP", "PHATRA",
    "MFC", "LHFUND", "KRUNGSRI", "WE-", "MEGA", "DAOL",
)

# Yahoo Finance only accepts simple tickers
_YAHOO_SYMBOL_RE = re.compile(r'^[\^]?[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,4})?$')


def _classify_market(symbol: str, yf_info: dict | None = None) -> str:
    """Determine market type for a symbol.

    Returns: 'SET', 'US', 'FUND', or 'CRYPTO'
    """
    sym_upper = symbol.upper()

    # bd:features-2026-09 slice B bug fix — MUST be the first check, before
    # _THAI_FUND_PATTERNS: the regex `^[A-Z]+-[A-Z]+` (K-CHINA/B-INCOME
    # pattern) also matches "BTC-USD"/"ETH-USD", which would otherwise
    # misclassify crypto as a Thai fund. Precedence, not the regex, was
    # wrong — do not touch the regex itself.
    if is_crypto(sym_upper):
        return "CRYPTO"

    # Thai fund detection: special characters, known prefixes
    if any(p.search(sym_upper) for p in _THAI_FUND_PATTERNS):
        return "FUND"
    if any(sym_upper.startswith(prefix) for prefix in _THAI_FUND_PREFIXES):
        # Check if it's a known non-fund (e.g., SCBS could be confused)
        # If yfinance returned valid stock data, trust that
        if yf_info and yf_info.get("regularMarketPrice"):
            pass  # let it fall through to SET/US detection
        else:
            return "FUND"

    # SET stocks end with .BK
    if sym_upper.endswith(".BK"):
        return "SET"

    # If yfinance info is available, check exchange
    if yf_info:
        exchange = yf_info.get("exchange", "").upper()
        if exchange in ("SET", "MAI", "BKK"):
            return "SET"
        if exchange in ("NMS", "NYQ", "NGM", "NCM", "PCX", "ASE", "NYE"):
            return "US"
        # Check quoteType for funds
        quote_type = yf_info.get("quoteType", "").upper()
        if quote_type in ("MUTUALFUND",):
            return "FUND"

    # Default: if simple ticker without .BK → US
    return "US"


@shared_task(bind=True, max_retries=1, default_retry_delay=30)
def register_symbol(self, symbol: str):
    """
    Register a single symbol in the stocks table.

    Fetches metadata from Yahoo Finance (name, sector, exchange) to determine
    market type (SET/US/FUND). If Yahoo doesn't recognize it, falls back to
    pattern-based classification.

    Idempotent: skips if symbol already exists in stocks table.
    """
    start = time.time()
    sym = symbol.upper().strip()

    try:
        from sqlalchemy import create_engine, text
        from core.config import settings

        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        # Check if already registered
        with engine.connect() as conn:
            existing = conn.execute(
                text("SELECT id FROM stocks WHERE symbol = :symbol"),
                {"symbol": sym},
            ).first()
            if existing:
                logger.debug("Symbol already registered", symbol=sym)
                return {"symbol": sym, "status": "already_exists"}

        # Try Yahoo Finance for metadata
        yf_info = None
        short_name = sym
        sector = None

        if _YAHOO_SYMBOL_RE.match(sym):
            try:
                import yfinance as yf

                # Map special symbols
                yahoo_map = {"BRK.B": "BRK-B", "BRK.A": "BRK-A", "BF.B": "BF-B"}
                yahoo_sym = yahoo_map.get(sym, sym)

                ticker = yf.Ticker(yahoo_sym)
                yf_info = ticker.info or {}

                short_name = (
                    yf_info.get("shortName")
                    or yf_info.get("longName")
                    or sym
                )
                sector = yf_info.get("sector")
            except Exception as e:
                logger.debug("yfinance lookup failed", symbol=sym, error=str(e))

        # Classify market type
        market = _classify_market(sym, yf_info)

        # Insert into stocks table
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO stocks (symbol, name, market, sector, is_active) "
                "VALUES (:symbol, :name, :market, :sector, true) "
                "ON CONFLICT (symbol) DO NOTHING"
            ), {
                "symbol": sym,
                "name": short_name,
                "market": market,
                "sector": sector,
            })
            conn.commit()

        # Also cache the name in Redis
        try:
            import redis
            from core import cache_keys

            redis_client = redis.from_url(settings.redis_url)
            redis_client.setex(cache_keys.name(sym), 86400, short_name)
        except Exception:
            pass

        elapsed = time.time() - start
        logger.info(
            "Symbol registered",
            symbol=sym,
            name=short_name,
            market=market,
            sector=sector,
            elapsed_sec=f"{elapsed:.2f}",
        )
        return {"symbol": sym, "name": short_name, "market": market, "status": "registered"}

    except Exception as exc:
        elapsed = time.time() - start
        logger.error("register_symbol failed", symbol=sym, error=str(exc), elapsed_sec=f"{elapsed:.2f}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def scan_unregistered(self):
    """
    Periodic task: find symbols in watchlist_items and transactions
    that are NOT yet in the stocks table, and register them.

    This catches any symbols that were added before register_symbol
    was wired into the API endpoints, or when the endpoint fire-and-forget
    task failed.
    """
    start = time.time()
    try:
        from sqlalchemy import create_engine, text
        from core.config import settings

        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        with engine.connect() as conn:
            # Find symbols in watchlist_items not in stocks
            watchlist_syms = conn.execute(text(
                "SELECT DISTINCT wi.symbol FROM watchlist_items wi "
                "LEFT JOIN stocks s ON s.symbol = wi.symbol "
                "WHERE s.id IS NULL"
            )).fetchall()

            # Find symbols in transactions not in stocks
            txn_syms = conn.execute(text(
                "SELECT DISTINCT t.symbol FROM transactions t "
                "LEFT JOIN stocks s ON s.symbol = t.symbol "
                "WHERE s.id IS NULL"
            )).fetchall()

        # Combine unique symbols
        unregistered = list({r[0] for r in watchlist_syms} | {r[0] for r in txn_syms})

        if not unregistered:
            logger.info("No unregistered symbols found")
            return {"count": 0}

        logger.info("Found unregistered symbols", count=len(unregistered), symbols=unregistered[:10])

        # Dispatch individual register_symbol tasks
        for sym in unregistered:
            register_symbol.delay(sym)

        elapsed = time.time() - start
        logger.info(
            "scan_unregistered complete",
            total=len(unregistered),
            elapsed_sec=f"{elapsed:.2f}",
            ts=datetime.now(timezone.utc).isoformat(),
        )
        return {"count": len(unregistered), "symbols": unregistered}

    except Exception as exc:
        elapsed = time.time() - start
        logger.error("scan_unregistered failed", error=str(exc), elapsed_sec=f"{elapsed:.2f}")
        raise self.retry(exc=exc)
