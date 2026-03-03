"""Celery task: fetch news for watched symbols via Google News RSS.

Runs every 30 minutes. For each watched symbol, fetches news from Google
News RSS (Thai first, English fallback) and caches in Redis. News is NOT
user-specific — all users viewing the same symbol share the same cache.

Cache key: news:{CLEAN_SYMBOL}  (e.g. news:PTT, news:AAPL, news:NVDA)
Cache TTL: 30 minutes (matches beat schedule)
"""
from __future__ import annotations
import json
import re
import time
from urllib.parse import quote_plus

from celery import shared_task
from core.logger import get_logger
from core import cache_keys

logger = get_logger(__name__)

# ─── Symbol → human-readable search query ────────────────────────────────────
SYMBOL_ALIAS = {
    "GSPC": "S&P 500",
    "IXIC": "NASDAQ",
    "DJI": "Dow Jones",
    "N225": "Nikkei 225",
    "HSI": "Hang Seng",
    "FTSE": "FTSE 100",
    "GDAXI": "DAX index",
    "FCHI": "CAC 40",
    "AEX": "AEX index",
    "KS11": "KOSPI",
    "SETBK": "SET index Thailand",
    "THBUSD": "USD THB exchange rate",
    "GC": "gold price",
}

# Max symbols to fetch per run (avoid overloading Google News)
MAX_SYMBOLS_PER_RUN = 30

# Cache TTL: 30 minutes
NEWS_CACHE_TTL = 1800


def _clean_symbol(raw: str) -> str:
    """Strip Yahoo suffixes to get a clean search-friendly symbol."""
    clean = raw.upper().strip()
    clean = re.sub(r"\^", "", clean)
    clean = re.sub(r"=X$", "", clean)
    clean = re.sub(r"=F$", "", clean)
    clean = re.sub(r"\.(BK|MAI|T|HK|SS|SZ|L|DE|PA|AS|KS)$", "", clean)
    clean = re.sub(r"[^A-Z0-9/\- ]", "", clean)
    return clean


def _fetch_news_for_symbol(symbol_clean: str, redis_client) -> int:
    """Fetch news for one cleaned symbol. Returns number of articles cached."""
    import feedparser

    query_term = SYMBOL_ALIAS.get(symbol_clean, f"{symbol_clean} stock")
    encoded = quote_plus(query_term)

    urls = [
        f"https://news.google.com/rss/search?q={encoded}&hl=th&gl=TH&ceid=TH:th",
        f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en",
    ]

    items: list[dict] = []

    for url in urls:
        try:
            feed = feedparser.parse(url)
            if not feed or not hasattr(feed, "entries") or not feed.entries:
                continue

            for entry in feed.entries[:12]:
                source_obj = entry.get("source", None)
                source_name = (
                    source_obj.get("title", "Google News")
                    if isinstance(source_obj, dict)
                    else "Google News"
                )
                items.append({
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "source": source_name,
                    "published_at": entry.get("published", ""),
                    "summary": entry.get("summary", ""),
                })

            if items:
                break  # got results from this language
        except Exception as e:
            logger.debug("RSS fetch failed", symbol=symbol_clean, url=url, error=str(e))
            continue

    # Cache regardless of count (empty = no news, which is valid)
    cache_key = cache_keys.news(symbol_clean)
    try:
        redis_client.setex(cache_key, NEWS_CACHE_TTL, json.dumps(items, default=str))
    except Exception as e:
        logger.warning("Redis cache write failed", symbol=symbol_clean, error=str(e))

    return len(items)


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def prefetch_news(self):
    """Fetch news for all watched symbols and cache in Redis.

    Runs on schedule (every 30 min). For each unique symbol in user
    watchlists + portfolios, fetches Google News RSS and caches the
    results. Skips symbols that already have fresh cache.
    """
    start = time.time()
    try:
        import redis as redis_lib
        from core.config import settings
        from workers.helpers.symbol_loader import get_watched_symbols

        redis_client = redis_lib.from_url(settings.redis_url)
        symbols = get_watched_symbols()

        if not symbols:
            logger.info("No watched symbols, skipping news fetch")
            return

        # Deduplicate cleaned symbols (PTT.BK and PTT share same news)
        clean_map: dict[str, str] = {}
        for sym in symbols:
            clean = _clean_symbol(sym)
            if clean and len(clean) >= 1:
                clean_map[clean] = sym  # keep mapping for logging

        # Skip symbols that already have fresh cache
        to_fetch: list[str] = []
        for clean_sym in list(clean_map.keys())[:MAX_SYMBOLS_PER_RUN]:
            ck = cache_keys.news(clean_sym)
            if not redis_client.exists(ck):
                to_fetch.append(clean_sym)

        if not to_fetch:
            elapsed = time.time() - start
            logger.info("All news cache fresh, nothing to fetch",
                        total_symbols=len(clean_map), elapsed_sec=f"{elapsed:.2f}")
            return

        # Fetch news for each symbol (sequential to avoid rate-limiting)
        fetched = 0
        total_articles = 0
        for clean_sym in to_fetch:
            try:
                count = _fetch_news_for_symbol(clean_sym, redis_client)
                total_articles += count
                fetched += 1
                # Small delay to avoid hammering Google News
                time.sleep(0.5)
            except Exception as e:
                logger.debug("News fetch failed for symbol", symbol=clean_sym, error=str(e))
                continue

        elapsed = time.time() - start
        logger.info(
            "News prefetch completed",
            symbols_fetched=fetched,
            symbols_skipped=len(clean_map) - len(to_fetch),
            total_articles=total_articles,
            elapsed_sec=f"{elapsed:.2f}",
        )

    except Exception as exc:
        elapsed = time.time() - start
        logger.error("prefetch_news failed", error=str(exc), elapsed_sec=f"{elapsed:.2f}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=1, default_retry_delay=10)
def fetch_news_on_demand(self, symbol: str):
    """Fetch news for a single symbol on-demand (triggered by API cache miss).

    Used when a user views a stock that isn't in anyone's watchlist
    (so the scheduled prefetch doesn't cover it).
    """
    start = time.time()
    try:
        import redis as redis_lib
        from core.config import settings

        redis_client = redis_lib.from_url(settings.redis_url)
        clean = _clean_symbol(symbol)

        if not clean:
            return

        # Skip if already cached
        ck = cache_keys.news(clean)
        if redis_client.exists(ck):
            return

        count = _fetch_news_for_symbol(clean, redis_client)

        elapsed = time.time() - start
        logger.debug("On-demand news fetch", symbol=clean, articles=count,
                      elapsed_sec=f"{elapsed:.2f}")

    except Exception as exc:
        logger.debug("fetch_news_on_demand failed", symbol=symbol, error=str(exc))
        raise self.retry(exc=exc)
