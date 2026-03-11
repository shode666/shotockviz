"""Service-layer tests for stock_service facade and cache_orchestrator.

These tests verify the read-only CQRS pattern using mocked Redis/DB.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── stock_service facade tests ────────────────────────────────────────────────

class TestStockServiceFacade:
    """Verify the thin facade delegates to sub-modules correctly."""

    @pytest.mark.asyncio
    async def test_read_quote_cache_hit(self):
        """read_quote returns cached data on Redis hit."""
        from services.stock_service import read_quote
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps({"price": 180.05, "symbol": "NVDA"}))

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            result = await read_quote("NVDA")

        assert result is not None
        assert result["price"] == 180.05
        assert result["symbol"] == "NVDA"

    @pytest.mark.asyncio
    async def test_read_quote_cache_miss(self):
        """read_quote returns None on cache miss."""
        from services.stock_service import read_quote
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            result = await read_quote("INVALID")

        assert result is None

    @pytest.mark.asyncio
    async def test_read_quote_redis_error(self):
        """read_quote returns None gracefully on Redis error."""
        from services.stock_service import read_quote
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            result = await read_quote("AAPL")

        assert result is None

    @pytest.mark.asyncio
    async def test_read_fundamentals_cache_hit(self):
        """read_fundamentals returns cached data."""
        from services.stock_service import read_fundamentals
        mock_redis = AsyncMock()
        fundamentals = {"pe_ratio": 33.34, "eps": 7.91, "market_cap": 3.8e12}
        mock_redis.get = AsyncMock(return_value=json.dumps(fundamentals))

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            result = await read_fundamentals("AAPL")

        assert result is not None
        assert result["pe_ratio"] == 33.34

    @pytest.mark.asyncio
    async def test_read_fundamentals_negative_cache(self):
        """read_fundamentals returns None for negative cache sentinel (__null__)."""
        from services.stock_service import read_fundamentals
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps("__null__"))

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            result = await read_fundamentals("INVALID_FUND")

        assert result is None

    @pytest.mark.asyncio
    async def test_read_fundamentals_cache_miss(self):
        """read_fundamentals returns None on cache miss."""
        from services.stock_service import read_fundamentals
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            result = await read_fundamentals("NEWSTOCK")

        assert result is None

    @pytest.mark.asyncio
    async def test_search_stocks_cache_hit(self):
        """search_stocks returns cached results without calling Yahoo."""
        from services.stock_service import search_stocks
        cached_results = [{"symbol": "AAPL", "name": "Apple Inc."}]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_results))

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            result = await search_stocks("AAPL")

        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_search_stocks_cache_miss_calls_yahoo(self):
        """search_stocks calls Yahoo when cache misses."""
        from services.stock_service import search_stocks
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        yahoo_results = [{"symbol": "NVDA", "name": "NVIDIA Corp."}]

        with patch("services.stock_service.get_redis", return_value=mock_redis), \
             patch("services.stock_service._search_yahoo_direct", new_callable=AsyncMock, return_value=yahoo_results):
            result = await search_stocks("NVDA")

        assert len(result) == 1
        assert result[0]["symbol"] == "NVDA"
        # Verify cached
        mock_redis.setex.assert_called_once()

    def test_tf_config_completeness(self):
        """TF_CONFIG covers all 8 timeframes."""
        from services.stock_service import TF_CONFIG
        expected = {"1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"}
        assert set(TF_CONFIG.keys()) == expected

    def test_daily_timeframes(self):
        """DAILY_TIMEFRAMES contains correct set."""
        from services.stock_service import DAILY_TIMEFRAMES
        assert DAILY_TIMEFRAMES == {"1D", "1W", "1M"}

    def test_facade_reexports(self):
        """Facade re-exports all expected functions."""
        from services import stock_service
        expected_names = [
            "get_redis", "fetch_stock_history", "fetch_quote_now",
            "fetch_stock_fundamentals", "search_stocks", "read_quote",
            "read_history", "read_fundamentals", "request_data_fetch",
            "TF_CONFIG", "DAILY_TIMEFRAMES",
        ]
        for name in expected_names:
            assert hasattr(stock_service, name), f"Missing re-export: {name}"


# ── cache_keys integration ────────────────────────────────────────────────────

class TestCacheKeyUsageInService:
    """Verify stock_service uses cache_keys module (not hardcoded strings)."""

    @pytest.mark.asyncio
    async def test_read_quote_uses_cache_key(self):
        """read_quote uses cache_keys.quote() not f-string."""
        from services.stock_service import read_quote
        from core import cache_keys

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            await read_quote("NVDA")

        # Verify the exact key format
        mock_redis.get.assert_called_once_with(cache_keys.quote("NVDA"))

    @pytest.mark.asyncio
    async def test_read_fundamentals_uses_cache_key(self):
        """read_fundamentals uses cache_keys.fundamentals()."""
        from services.stock_service import read_fundamentals
        from core import cache_keys

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            await read_fundamentals("AAPL")

        mock_redis.get.assert_called_once_with(cache_keys.fundamentals("AAPL"))

    @pytest.mark.asyncio
    async def test_search_uses_cache_key(self):
        """search_stocks uses cache_keys.search()."""
        from services.stock_service import search_stocks
        from core import cache_keys

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps([]))

        with patch("services.stock_service.get_redis", return_value=mock_redis):
            await search_stocks("aapl")

        mock_redis.get.assert_called_once_with(cache_keys.search("aapl"))
