"""Celery tasks for fetching stock prices.

KEY DESIGN — "Round-robin market rotation"
──────────────────────────────────────────────────────────────────────────────
Single `fetch_prices` task runs every 1 minute.  Each run it picks the NEXT
market slot from a rotating list (stored as Redis counter).

With 5 market slots (SET, US, JP+HK+CN, EU, overview) each market updates
every 5 minutes.  During off-hours a market is skipped → faster rotation
for markets that are open.

Slot assignment:
  0 = SET (.BK)                — skip if outside SET hours
  1 = US  (no suffix)          — skip if outside US hours
  2 = Asia (JP .T, HK .HK, CN .SS/.SZ) — skip if outside Asia hours
  3 = Europe (UK .L, DE .DE, FR .PA, NL .AS) — skip if outside EU hours
  4 = Overview (indices, FX, gold) — always runs

If the current slot's market is closed, the task immediately advances to
the next slot, so open markets get more frequent updates.
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from celery import shared_task
from core.logger import get_logger
from core.symbol_utils import (
    normalize_for_yahoo,
    detect_market,
    is_thai_stock,
    deduplicate,
)
from workers.helpers.symbol_loader import get_watched_symbols
from workers.helpers.cache_publisher import cache_and_publish_quotes
from workers.helpers.task_timing import timed_task

logger = get_logger(__name__)

# ── Fallback symbols ──────────────────────────────────────────────────────────
FALLBACK_SET = ["PTT.BK", "CPALL.BK", "ADVANC.BK", "AOT.BK", "KBANK.BK", "SCB.BK"]
FALLBACK_US = ["AAPL", "NVDA", "TSLA", "MSFT", "SPY", "QQQ", "GOOGL", "AMZN"]
FALLBACK_IDX = [
    "^SET.BK", "^GSPC", "^IXIC", "^DJI",
    "^N225", "^HSI", "000001.SS", "^KS11", "^TWII", "^STI",
    "^FTSE", "^GDAXI", "^FCHI", "^AEX",
    "THBUSD=X", "GC=F",
]

# ── Market slot definitions ───────────────────────────────────────────────────
# Each slot: (label, filter_fn, market_hours_fn)
#   filter_fn(symbol) → bool  — which symbols belong to this slot
#   market_hours_fn(utc_now)  → bool  — is this market open now?

ASIA_SUFFIXES = frozenset({".T", ".HK", ".SS", ".SZ", ".KS", ".TW", ".SI"})
EU_SUFFIXES = frozenset({".L", ".DE", ".PA", ".AS", ".MI"})


def _is_asia(sym: str) -> bool:
    return any(sym.endswith(s) for s in ASIA_SUFFIXES)


def _is_europe(sym: str) -> bool:
    return any(sym.endswith(s) for s in EU_SUFFIXES)


def _is_us(sym: str) -> bool:
    return not is_thai_stock(sym) and not _is_asia(sym) and not _is_europe(sym)


def _set_hours(utc_now: datetime) -> bool:
    """SET: Mon-Fri 10:00-16:30 ICT = 03:00-09:30 UTC."""
    if utc_now.weekday() >= 5:
        return False
    t = utc_now.hour * 60 + utc_now.minute  # minutes since midnight UTC
    return 2 * 60 + 30 <= t <= 9 * 60 + 45  # 02:30-09:45 UTC (with buffer)


def _us_hours(utc_now: datetime) -> bool:
    """US: Mon-Fri 09:30-16:00 ET ≈ 13:30-21:00 UTC (+ pre/post buffer)."""
    if utc_now.weekday() >= 5:
        return False
    t = utc_now.hour * 60 + utc_now.minute
    return 13 * 60 <= t <= 21 * 60 + 30  # 13:00-21:30 UTC


def _asia_hours(utc_now: datetime) -> bool:
    """Asia (JP/HK/CN/KR): Mon-Fri ~01:00-08:00 UTC (covers JST, HKT, CST, KST)."""
    if utc_now.weekday() >= 5:
        return False
    t = utc_now.hour * 60 + utc_now.minute
    return 0 * 60 + 30 <= t <= 8 * 60 + 30  # 00:30-08:30 UTC


def _eu_hours(utc_now: datetime) -> bool:
    """Europe (UK/DE/FR/NL): Mon-Fri 08:00-16:30 CET ≈ 07:00-16:30 UTC."""
    if utc_now.weekday() >= 5:
        return False
    t = utc_now.hour * 60 + utc_now.minute
    return 7 * 60 <= t <= 17 * 60  # 07:00-17:00 UTC


def _always(_: datetime) -> bool:
    return True


MARKET_SLOTS = [
    ("SET", is_thai_stock, _set_hours),
    ("US", _is_us, _us_hours),
    ("Asia", _is_asia, _asia_hours),
    ("Europe", _is_europe, _eu_hours),
    ("Overview", None, _always),  # None = use FALLBACK_IDX only
]

NUM_SLOTS = len(MARKET_SLOTS)
REDIS_SLOT_KEY = "price_fetcher:slot_idx"


# ── Pure helper: batch fetch quotes via yfinance ──────────────────────────────

def yfinance_batch_quotes(symbols: list[str]) -> dict[str, dict]:
    """Fetch quotes for a list of symbols using yfinance batch download.

    Returns:
        {symbol: {symbol, price, change, change_pct, volume}}
    """
    import yfinance as yf

    if not symbols:
        return {}

    results: dict[str, dict] = {}
    yahoo_syms = [normalize_for_yahoo(s) for s in symbols]
    reverse_map = {normalize_for_yahoo(s): s for s in symbols}

    tickers = yf.Tickers(" ".join(yahoo_syms))
    for ysym in yahoo_syms:
        sym = reverse_map.get(ysym, ysym)
        try:
            t = tickers.tickers.get(ysym)
            if t is None:
                continue
            info = t.fast_info
            price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
            prev = getattr(info, "previous_close", None)
            vol = getattr(info, "three_month_average_volume", None) or getattr(info, "regular_market_volume", None)

            if not price or price <= 0:
                continue

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


# ── Main task: round-robin across all markets ─────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
@timed_task("fetch_prices")
def fetch_prices(self):
    """Round-robin price fetcher — picks next market slot each minute.

    Flow:
      1. Read slot index from Redis (atomic INCR)
      2. Determine which market slot to fetch
      3. If market is closed → skip, try next slot (up to NUM_SLOTS tries)
      4. Filter watched symbols for this slot
      5. Batch fetch via yfinance + cache + publish
    """
    import redis as redis_lib
    from core.config import settings

    r = redis_lib.from_url(settings.redis_url)
    utc_now = datetime.now(timezone.utc)

    # Get all watched symbols once
    all_syms = get_watched_symbols(fallback=FALLBACK_SET + FALLBACK_US)

    # Atomic increment to get current slot
    raw_idx = r.incr(REDIS_SLOT_KEY)
    # Set TTL so key doesn't live forever (reset daily)
    r.expire(REDIS_SLOT_KEY, 86400)

    # Try up to NUM_SLOTS times to find an open market
    for attempt in range(NUM_SLOTS):
        slot_idx = (raw_idx + attempt) % NUM_SLOTS
        label, filter_fn, hours_fn = MARKET_SLOTS[slot_idx]

        # Check if market is open
        if not hours_fn(utc_now):
            logger.debug("Market closed, skipping", slot=label)
            continue

        # Build symbol list for this slot
        if filter_fn is None:
            # Overview slot — only indices/FX/commodities
            syms = deduplicate(FALLBACK_IDX)
        else:
            syms = [s for s in all_syms if filter_fn(s)]
            # Add fallback indices for the first two core markets
            if label == "SET":
                syms += [s for s in FALLBACK_IDX if is_thai_stock(s)]
            syms = deduplicate(syms)

        if not syms:
            logger.debug("No symbols for slot", slot=label)
            continue

        # Fetch + cache + publish
        quotes = yfinance_batch_quotes(syms)
        count = cache_and_publish_quotes(quotes, r)

        logger.info(
            "Prices fetched",
            slot=label,
            slot_idx=slot_idx,
            total=len(syms),
            priced=count,
            ts=utc_now.isoformat(),
        )

        # If we skipped slots, advance the counter so next run continues properly
        if attempt > 0:
            r.set(REDIS_SLOT_KEY, raw_idx + attempt)

        return {"slot": label, "total": len(syms), "priced": count}

    # All markets closed (e.g., weekend)
    logger.info("All markets closed, fetching overview only", ts=utc_now.isoformat())
    quotes = yfinance_batch_quotes(FALLBACK_IDX)
    count = cache_and_publish_quotes(quotes, r)
    return {"slot": "fallback_overview", "priced": count}


# ── Keep old task names as aliases (backward compat for any manual calls) ─────

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def fetch_set_prices(self):
    """Legacy alias — delegates to unified fetch_prices task body directly.

    NOTE: Cannot use fetch_prices.apply().get() inside a Celery task (RuntimeError).
    Instead call the task function directly via apply(args=[], kwargs={}) with no get(),
    or simply re-use the same underlying logic inline.
    """
    fetch_prices.delay()


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def fetch_us_prices(self):
    """Legacy alias — delegates to unified fetch_prices task body directly.

    NOTE: Cannot use fetch_prices.apply().get() inside a Celery task (RuntimeError).
    """
    fetch_prices.delay()


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
@timed_task("fetch_overview_prices")
def fetch_overview_prices(self):
    """Keep global indices + USD/THB + Gold cached for Dashboard."""
    import redis as redis_lib
    from core.config import settings

    quotes = yfinance_batch_quotes(FALLBACK_IDX)
    r = redis_lib.from_url(settings.redis_url)
    count = cache_and_publish_quotes(quotes, r)

    logger.info("Overview prices refreshed", count=count)
