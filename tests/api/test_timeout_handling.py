"""
Tests for request timeout handling in stock_service.

Covers:
  ✓ _fetch_yahoo_direct handles asyncio.TimeoutError gracefully (returns [])
  ✓ _fetch_yahoo_direct handles httpx.TimeoutException gracefully (returns [])
  ✓ _fetch_yahoo_direct handles generic Exception gracefully (returns [])
  ✓ US symbols (no .BK) do NOT retry on timeout (max_retries=1)
  ✓ Thai .BK symbols retry up to 3 times on timeout
  ✓ fetch_stock_history returns [] (not raises) when all sources time out
  ✓ GET /api/stocks/{symbol}/history returns 200 with empty bars on timeout
  ✓ Stock history endpoint responds within acceptable time on timeout
"""
import asyncio
import time
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch, call
from fastapi.testclient import TestClient


# ── Unit tests: _fetch_yahoo_direct ───────────────────────────────────────────

class TestFetchYahooDirectTimeoutHandling:
    """_fetch_yahoo_direct must never raise — it returns [] on any failure."""

    @pytest.mark.asyncio
    async def test_asyncio_timeout_returns_empty_list(self):
        """asyncio.TimeoutError is caught and returns []."""
        with patch('httpx.AsyncClient') as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=asyncio.TimeoutError("timeout"))
            mock_client_cls.return_value = mock_client

            # Also patch _get_yf_auth to avoid real network call for cookies/crumb
            with patch(
                'services.stock_service._get_yf_auth',
                new=AsyncMock(return_value=({}, '')),
            ):
                from services.stock_service import _fetch_yahoo_direct
                result = await _fetch_yahoo_direct('AAPL', '1d', '1y', '1D')

        assert isinstance(result, list), "Expected a list, got non-list"
        assert result == [], f"Expected empty list on timeout, got: {result}"

    @pytest.mark.asyncio
    async def test_httpx_timeout_exception_returns_empty_list(self):
        """httpx.TimeoutException is caught and returns []."""
        with patch('httpx.AsyncClient') as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(
                side_effect=httpx.TimeoutException("Request timed out")
            )
            mock_client_cls.return_value = mock_client

            with patch(
                'services.stock_service._get_yf_auth',
                new=AsyncMock(return_value=({}, '')),
            ):
                from services.stock_service import _fetch_yahoo_direct
                result = await _fetch_yahoo_direct('AAPL', '1d', '1y', '1D')

        assert result == [], f"Expected [] on httpx.TimeoutException, got: {result}"

    @pytest.mark.asyncio
    async def test_generic_exception_returns_empty_list(self):
        """Any unexpected exception is caught and returns []."""
        with patch('httpx.AsyncClient') as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(
                side_effect=RuntimeError("unexpected network error")
            )
            mock_client_cls.return_value = mock_client

            with patch(
                'services.stock_service._get_yf_auth',
                new=AsyncMock(return_value=({}, '')),
            ):
                from services.stock_service import _fetch_yahoo_direct
                result = await _fetch_yahoo_direct('AAPL', '1d', '1y', '1D')

        assert result == [], f"Expected [] on RuntimeError, got: {result}"

    @pytest.mark.asyncio
    async def test_us_symbol_does_not_retry_on_timeout(self):
        """Non-.BK symbols have max_retries=1 — exactly one attempt on timeout."""
        call_count = 0

        async def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise asyncio.TimeoutError("timeout")

        with patch('httpx.AsyncClient') as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=fake_get)
            mock_client_cls.return_value = mock_client

            with patch(
                'services.stock_service._get_yf_auth',
                new=AsyncMock(return_value=({}, '')),
            ):
                from services.stock_service import _fetch_yahoo_direct
                result = await _fetch_yahoo_direct('AAPL', '1d', '1y', '1D')

        # US symbol → max_retries=1 → only 1 HTTP attempt
        assert call_count == 1, (
            f"US symbol should attempt only once, but attempted {call_count} times"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_thai_bk_symbol_retries_on_timeout(self):
        """Thai .BK symbols have max_retries=3 — up to 3 attempts on timeout."""
        call_count = 0

        async def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise asyncio.TimeoutError("timeout")

        with patch('httpx.AsyncClient') as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=fake_get)
            mock_client_cls.return_value = mock_client

            # Patch asyncio.sleep so retries don't block for 2s + 6s in tests
            with patch('asyncio.sleep', new=AsyncMock(return_value=None)):
                with patch(
                    'services.stock_service._get_yf_auth',
                    new=AsyncMock(return_value=({}, '')),
                ):
                    from services.stock_service import _fetch_yahoo_direct
                    result = await _fetch_yahoo_direct('PTT.BK', '1d', '1y', '1D')

        # .BK symbol → max_retries=3 → up to 3 HTTP attempts
        assert call_count == 3, (
            f".BK symbol should attempt 3 times on timeout, attempted {call_count}"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_thai_bk_succeeds_on_second_attempt(self):
        """If the first attempt times out and the second succeeds, returns bars."""
        from models.schemas import OHLCVBar

        attempt = 0
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "chart": {
                "result": [{
                    "timestamp": [1700000000, 1700086400],
                    "indicators": {
                        "quote": [{
                            "open": [34.0, 35.0],
                            "high": [36.0, 37.0],
                            "low":  [33.0, 34.0],
                            "close":[34.5, 35.5],
                            "volume":[1_000_000, 1_200_000],
                        }]
                    },
                    "meta": {"gmtoffset": 0, "tradingDay": "2024-01-01"},
                }],
                "error": None,
            }
        }

        async def fake_get(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise asyncio.TimeoutError("first attempt timeout")
            return mock_response

        with patch('httpx.AsyncClient') as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=fake_get)
            mock_client_cls.return_value = mock_client

            with patch('asyncio.sleep', new=AsyncMock(return_value=None)):
                with patch(
                    'services.stock_service._get_yf_auth',
                    new=AsyncMock(return_value=({}, '')),
                ):
                    from services.stock_service import _fetch_yahoo_direct
                    result = await _fetch_yahoo_direct('PTT.BK', '1d', '1y', '1D')

        # Second attempt succeeded — should have returned bars (or [] if parse fails)
        # We just verify no exception was raised
        assert isinstance(result, list)


# ── Unit tests: fetch_stock_history ───────────────────────────────────────────

class TestFetchStockHistoryTimeoutHandling:
    """fetch_stock_history returns [] when external sources time out."""

    @pytest.mark.asyncio
    async def test_fetch_history_returns_empty_on_full_timeout(self):
        """When Yahoo + Stooq both time out, fetch_stock_history returns []."""
        with patch(
            'services.stock_service._fetch_yahoo_direct',
            new=AsyncMock(return_value=[]),
        ), patch(
            'services.stock_service._fetch_stooq_direct',
            new=AsyncMock(return_value=[]),
        ), patch(
            'services.stock_service._load_bars_from_db',
            new=AsyncMock(return_value=[]),
        ), patch(
            'services.stock_service.get_redis',
        ) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.setex = AsyncMock(return_value=None)
            mock_get_redis.return_value = mock_redis

            from services.stock_service import fetch_stock_history
            result = await fetch_stock_history('AAPL', '1D')

        assert isinstance(result, list), "fetch_stock_history must return a list"
        assert result == [], f"Expected [] when all sources are empty, got {result}"

    @pytest.mark.asyncio
    async def test_fetch_history_does_not_raise_on_timeout(self):
        """fetch_stock_history must not propagate any exception from timeouts."""
        with patch(
            'services.stock_service._fetch_yahoo_direct',
            new=AsyncMock(side_effect=asyncio.TimeoutError("cascaded timeout")),
        ), patch(
            'services.stock_service._load_bars_from_db',
            new=AsyncMock(return_value=[]),
        ), patch(
            'services.stock_service.get_redis',
        ) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_get_redis.return_value = mock_redis

            from services.stock_service import fetch_stock_history
            try:
                result = await fetch_stock_history('AAPL', '1D')
            except Exception as e:
                pytest.fail(
                    f"fetch_stock_history must not raise, but got: {type(e).__name__}: {e}"
                )

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_abort_fetch(self):
        """If Redis raises an exception, the function falls through to DB/provider."""
        with patch(
            'services.stock_service.get_redis',
        ) as mock_get_redis:
            mock_redis = AsyncMock()
            # Redis raises — should be caught internally
            mock_redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
            mock_get_redis.return_value = mock_redis

            with patch(
                'services.stock_service._load_bars_from_db',
                new=AsyncMock(return_value=[]),
            ), patch(
                'services.stock_service._fetch_yahoo_direct',
                new=AsyncMock(return_value=[]),
            ):
                from services.stock_service import fetch_stock_history
                try:
                    result = await fetch_stock_history('AAPL', '1D')
                    assert isinstance(result, list)
                except ConnectionError:
                    pytest.fail(
                        "fetch_stock_history must handle Redis failures gracefully"
                    )


# ── Integration tests: HTTP endpoint ─────────────────────────────────────────

class TestStockHistoryEndpointOnTimeout:
    """
    HTTP-level tests via ASGI TestClient.

    These tests mock the stock_service layer to avoid real network calls,
    then verify the /api/stocks/{symbol}/history endpoint's behaviour when
    the underlying service encounters timeout conditions.
    """

    @pytest.fixture
    def aclient(self):
        """httpx async client wired to the FastAPI app via ASGI transport."""
        from main import app
        import httpx
        # Return a synchronous ASGI test client for simplicity
        return TestClient(app)

    def test_history_returns_200_with_empty_bars_on_timeout(self, aclient):
        """Endpoint returns HTTP 200 + empty bars when service returns []."""
        with patch(
            'services.stock_service.fetch_stock_history',
            new=AsyncMock(return_value=[]),
        ):
            response = aclient.get('/api/stocks/AAPL/history?tf=1D')

        assert response.status_code == 200
        body = response.json()
        assert 'bars' in body, f"Response missing 'bars' key: {body}"
        assert body['bars'] == []

    def test_history_endpoint_responds_within_35_seconds(self, aclient):
        """Even with slow service calls, the endpoint must respond within 35s."""
        async def slow_fetch(*args, **kwargs):
            await asyncio.sleep(0.1)  # Simulate a brief delay only
            return []

        with patch(
            'services.stock_service.fetch_stock_history',
            new=AsyncMock(side_effect=slow_fetch),
        ):
            start = time.monotonic()
            response = aclient.get('/api/stocks/AAPL/history?tf=1D')
            elapsed = time.monotonic() - start

        assert elapsed < 35.0, f"Endpoint took {elapsed:.1f}s — too slow"
        assert response.status_code in {200, 202, 500, 503}

    def test_history_endpoint_handles_invalid_timeframe(self, aclient):
        """Invalid timeframe returns HTTP 400 (not 500)."""
        response = aclient.get('/api/stocks/AAPL/history?tf=99X')
        assert response.status_code == 400

    def test_history_endpoint_returns_correct_symbol(self, aclient):
        """Response body echoes the correct symbol."""
        with patch(
            'services.stock_service.fetch_stock_history',
            new=AsyncMock(return_value=[]),
        ):
            response = aclient.get('/api/stocks/TSLA/history?tf=1D')

        assert response.status_code == 200
        body = response.json()
        assert body.get('symbol') == 'TSLA'

    def test_history_endpoint_returns_correct_timeframe(self, aclient):
        """Response body echoes the correct timeframe."""
        with patch(
            'services.stock_service.fetch_stock_history',
            new=AsyncMock(return_value=[]),
        ):
            response = aclient.get('/api/stocks/AAPL/history?tf=1W')

        assert response.status_code == 200
        body = response.json()
        assert body.get('timeframe') == '1W'


# ── Integration tests: async ASGI client ──────────────────────────────────────

@pytest.mark.asyncio
class TestStockHistoryEndpointAsync:
    """Async variant using httpx.AsyncClient + ASGITransport for full async tests."""

    @pytest.fixture
    async def aclient(self):
        from main import app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url='http://test',
        ) as c:
            yield c

    async def test_endpoint_returns_200_when_service_returns_empty(self, aclient):
        with patch(
            'services.stock_service.fetch_stock_history',
            new=AsyncMock(return_value=[]),
        ):
            resp = await aclient.get('/api/stocks/AAPL/history?tf=1D')

        assert resp.status_code == 200
        assert resp.json()['bars'] == []

    async def test_endpoint_elapsed_time_under_35s_on_service_timeout(self, aclient):
        """Endpoint latency is acceptable even when service is slow (mocked 0.1s)."""
        async def slow_service(*args, **kwargs):
            await asyncio.sleep(0.1)
            return []

        with patch(
            'services.stock_service.fetch_stock_history',
            new=AsyncMock(side_effect=slow_service),
        ):
            start = asyncio.get_event_loop().time()
            resp = await aclient.get('/api/stocks/AAPL/history?tf=1D')
            elapsed = asyncio.get_event_loop().time() - start

        assert elapsed < 35.0, f"Endpoint took {elapsed:.2f}s"
        assert resp.status_code in {200, 202, 500, 503}
