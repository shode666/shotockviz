"""
Cache key builders — single source of truth for all Redis key formats.

Rules:
  - All keys are lowercase
  - Namespace prefix separates domain (quote:, ohlcv:, fund:, screener:, lock:)
  - No spaces; special characters in symbols are preserved as-is
    (Redis handles "^GSPC", "PRINCIPAL iPROP-D" fine as key segments)
  - Lock keys mirror their data key with a "lock:" prefix

Key formats
-----------
  quote:{symbol}
  ohlcv:{symbol}:{tf}
  fundamentals:{symbol}
  search:{query}
  fund:{symbol}
  screener:{params_hash}
  lock:{data_key}           ← SingleFlight lock

Examples
--------
  quote:PTT.BK
  ohlcv:AAPL:1D
  ohlcv:^GSPC:1W
  fundamentals:TSLA
  search:ptt
  fund:SCBS&P500
  screener:a3f2e1d4
  lock:ohlcv:PTT.BK:1D
"""

from __future__ import annotations


def quote(symbol: str) -> str:
    """Current-price cache key."""
    return f"quote:{symbol}"


def ohlcv(symbol: str, tf: str) -> str:
    """OHLCV bars cache key (timeframe already validated by caller)."""
    return f"ohlcv:{symbol}:{tf}"


def fundamentals(symbol: str) -> str:
    """Company fundamentals cache key."""
    return f"fundamentals:{symbol}"


def search(query: str) -> str:
    """Symbol search results cache key (query stored as-is, lowercased)."""
    return f"search:{query.lower().strip()}"


def fund(symbol: str) -> str:
    """Mutual-fund NAV cache key."""
    return f"fund:{symbol}"


def screener(params_hash: str) -> str:
    """
    Screener snapshot cache key.

    ``params_hash`` should be the hex digest of the serialized screener
    parameters so that different filter sets map to different keys.
    """
    return f"screener:{params_hash}"


def lock(data_key: str) -> str:
    """
    SingleFlight lock key for any data cache key.

    Acquire this lock before fetching from a provider so that concurrent
    requests for the same key trigger only ONE upstream fetch.
    """
    return f"lock:{data_key}"


def name(symbol: str) -> str:
    """Stock short name cache key (from Yahoo Finance meta.shortName)."""
    return f"cache:name:{symbol}"


def quote_not_found(symbol: str) -> str:
    """Negative cache key for symbols that don't exist on Yahoo Finance.

    Used to avoid hammering Yahoo for mutual funds or delisted symbols
    that will never return data.
    """
    return f"cache:quote:notfound:{symbol}"
