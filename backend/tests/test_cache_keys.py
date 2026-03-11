"""Unit tests for core.cache_keys — verify key format consistency."""
import pytest
from core import cache_keys


class TestCacheKeyFormats:
    """Verify every key builder produces the documented format."""

    def test_quote(self):
        assert cache_keys.quote("AAPL") == "quote:AAPL"
        assert cache_keys.quote("PTT.BK") == "quote:PTT.BK"
        assert cache_keys.quote("^GSPC") == "quote:^GSPC"

    def test_ohlcv(self):
        assert cache_keys.ohlcv("AAPL", "1D") == "ohlcv:AAPL:1D"
        assert cache_keys.ohlcv("PTT.BK", "1h") == "ohlcv:PTT.BK:1h"
        assert cache_keys.ohlcv("^GSPC", "1W") == "ohlcv:^GSPC:1W"

    def test_fundamentals(self):
        assert cache_keys.fundamentals("TSLA") == "fundamentals:TSLA"

    def test_search_lowercased(self):
        assert cache_keys.search("PTT") == "search:ptt"
        assert cache_keys.search("  AAPL  ") == "search:aapl"
        assert cache_keys.search("apple inc") == "search:apple inc"

    def test_fund(self):
        assert cache_keys.fund("SCBS&P500") == "fund:SCBS&P500"
        assert cache_keys.fund("PRINCIPAL iPROP-D") == "fund:PRINCIPAL iPROP-D"

    def test_screener(self):
        assert cache_keys.screener("abc123") == "screener:abc123"

    def test_lock(self):
        assert cache_keys.lock("ohlcv:AAPL:1D") == "lock:ohlcv:AAPL:1D"
        assert cache_keys.lock("quote:PTT.BK") == "lock:quote:PTT.BK"

    def test_name(self):
        assert cache_keys.name("AAPL") == "cache:name:AAPL"
        assert cache_keys.name("PTT.BK") == "cache:name:PTT.BK"

    def test_news(self):
        assert cache_keys.news("NVDA") == "news:NVDA"

    def test_quote_not_found(self):
        assert cache_keys.quote_not_found("INVALID") == "cache:quote:notfound:INVALID"


class TestCacheKeyConsistency:
    """Cross-check that lock keys mirror their data keys."""

    def test_lock_wraps_quote(self):
        key = cache_keys.quote("AAPL")
        lock_key = cache_keys.lock(key)
        assert lock_key == f"lock:{key}"

    def test_lock_wraps_ohlcv(self):
        key = cache_keys.ohlcv("PTT.BK", "1D")
        lock_key = cache_keys.lock(key)
        assert lock_key == f"lock:{key}"

    def test_no_key_collision(self):
        """Different key types for same symbol should not collide."""
        keys = {
            cache_keys.quote("AAPL"),
            cache_keys.fundamentals("AAPL"),
            cache_keys.name("AAPL"),
            cache_keys.news("AAPL"),
            cache_keys.ohlcv("AAPL", "1D"),
        }
        assert len(keys) == 5  # All unique
