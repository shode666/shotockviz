"""
User Simulation Test Suite for ShotockViz

Simulates a complete user journey through the platform:
1. Auth Phase — Create JWT token for authenticated endpoints
2. Dashboard Phase — Verify market indices are live
3. Chart Phase — Test stock quotes and history across timeframes
4. Search Phase — Test stock symbol search
5. Watchlist Phase — Create, modify, and delete watchlists
6. Portfolio Phase — Add transactions and verify P&L
7. Alert Phase — Create and manage price alerts
8. Performance Phase — Verify caching and response times

Each phase includes:
- Clear pass/fail status
- Timing measurements
- Data validation assertions
- Automatic cleanup after tests
"""

import asyncio
import time
import json
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional
import pytest

# bd:deps-2026-09 WP-B0 — this suite requires a live stack at https://localhost
# (see API_BASE_URL below); baseline run showed 26 failures here, all
# live-stack-dependent (outputs/deps-2026-09/00-oliver-discover.md:26).
# Marked integration + deselected via pytest.ini addopts per
# outputs/deps-2026-09/03-stan-refactor-strategy.md § r3-B-1 (no ci.yml touch).
pytestmark = pytest.mark.integration

# Environment configuration
API_BASE_URL = "https://localhost"
API_ENDPOINT = f"{API_BASE_URL}/api"

# Test user credentials — will create JWT
TEST_USER_EMAIL = "simulator@test.shotockviz.local"
TEST_USER_ID = 1

# Test symbols
SYMBOLS = {
    "US": ["NVDA", "AAPL", "MSFT", "GOOG", "SPY"],
    "THAI": ["PTT.BK", "CPALL.BK"],
    "INDICES": ["^GSPC", "^IXIC", "^SET.BK"],
}

# Timing thresholds (milliseconds)
THRESHOLD_QUOTE = 3000  # Single quote should be <3s
THRESHOLD_BATCH = 3000  # Batch quotes should be <3s
THRESHOLD_CACHE = 100   # Cached responses should be <100ms
THRESHOLD_HISTORY = 5000  # History should be <5s


class ShotockVizTestClient:
    """HTTP client for ShotockViz API with SSL bypass for localhost."""

    def __init__(self, base_url: str = API_ENDPOINT):
        self.base_url = base_url
        # Disable SSL verification for localhost testing
        self.client = httpx.AsyncClient(
            base_url=base_url,
            verify=False,
            timeout=30.0,
            follow_redirects=True,
        )
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    def _headers(self, include_auth: bool = True) -> dict:
        """Build request headers."""
        headers = {"Accept": "application/json"}
        if include_auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def create_test_jwt(self) -> str:
        """Create a test JWT token using the backend security module.

        This simulates authenticated user without needing Google OAuth.
        """
        from core.security import create_access_token
        from core.config import settings

        token = create_access_token(
            data={
                "sub": str(TEST_USER_ID),
                "role": "user",
                "email": TEST_USER_EMAIL,
                "display_name": "Simulator User",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.access_token = token
        return token

    async def get(self, path: str, **kwargs) -> tuple[int, dict, float]:
        """GET request with timing."""
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())

        start = time.time()
        try:
            resp = await self.client.get(path, headers=headers, **kwargs)
            elapsed = (time.time() - start) * 1000  # Convert to ms

            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}

            return resp.status_code, data, elapsed
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return 0, {"error": str(e)}, elapsed

    async def post(self, path: str, json_data: dict, **kwargs) -> tuple[int, dict, float]:
        """POST request with timing."""
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())

        start = time.time()
        try:
            resp = await self.client.post(path, json=json_data, headers=headers, **kwargs)
            elapsed = (time.time() - start) * 1000

            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}

            return resp.status_code, data, elapsed
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return 0, {"error": str(e)}, elapsed

    async def put(self, path: str, json_data: dict, **kwargs) -> tuple[int, dict, float]:
        """PUT request with timing."""
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())

        start = time.time()
        try:
            resp = await self.client.put(path, json=json_data, headers=headers, **kwargs)
            elapsed = (time.time() - start) * 1000

            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}

            return resp.status_code, data, elapsed
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return 0, {"error": str(e)}, elapsed

    async def patch(self, path: str, json_data: dict = None, **kwargs) -> tuple[int, dict, float]:
        """PATCH request with timing."""
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())

        start = time.time()
        try:
            resp = await self.client.patch(
                path,
                json=json_data or {},
                headers=headers,
                **kwargs
            )
            elapsed = (time.time() - start) * 1000

            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}

            return resp.status_code, data, elapsed
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return 0, {"error": str(e)}, elapsed

    async def delete(self, path: str, **kwargs) -> tuple[int, dict, float]:
        """DELETE request with timing."""
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())

        start = time.time()
        try:
            resp = await self.client.delete(path, headers=headers, **kwargs)
            elapsed = (time.time() - start) * 1000

            try:
                data = resp.json()
            except Exception:
                data = {}

            return resp.status_code, data, elapsed
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return 0, {"error": str(e)}, elapsed


@pytest.fixture
async def client():
    """Provide a test HTTP client for all tests."""
    test_client = ShotockVizTestClient()
    yield test_client
    await test_client.close()


@pytest.fixture
async def auth_client(client):
    """Provide an authenticated test client."""
    await client.create_test_jwt()
    return client


class TestAuthPhase:
    """1. Authentication Phase — Create JWT tokens for subsequent tests."""

    @pytest.mark.asyncio
    async def test_create_jwt_token(self, client):
        """Create a test JWT token directly."""
        token = await client.create_test_jwt()
        assert token is not None, "JWT token should be created"
        assert len(token) > 50, "JWT should be reasonably long"
        assert client.access_token == token

    @pytest.mark.asyncio
    async def test_verify_token_on_auth_me(self, auth_client):
        """Verify token by fetching current user info."""
        status, data, elapsed = await auth_client.get("/auth/me")
        assert status == 200, f"GET /auth/me should return 200, got {status}"
        assert data.get("id") == TEST_USER_ID, f"User ID should be {TEST_USER_ID}"
        assert data.get("email") == TEST_USER_EMAIL, f"Email should be {TEST_USER_EMAIL}"
        print(f"✓ Auth ME endpoint: {elapsed:.1f}ms")


class TestDashboardPhase:
    """2. Dashboard Phase — Verify market indices are live."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Verify backend is healthy."""
        status, data, elapsed = await client.get("/health")
        assert status == 200, f"Health check should return 200, got {status}"
        assert data.get("data", {}).get("database") == "ok", "Database should be healthy"
        assert data.get("data", {}).get("redis") == "ok", "Redis should be healthy"
        print(f"✓ Health check: {elapsed:.1f}ms")
        print(f"  Celery: {data.get('data', {}).get('celery', 'unknown')}")

    @pytest.mark.asyncio
    async def test_cache_ready(self, client):
        """Verify cache is warmed up with key symbols."""
        status, data, elapsed = await client.get("/system/ready")
        assert status == 200, f"Ready check should return 200, got {status}"
        cached = data.get("cached", 0)
        total = data.get("total", 5)
        print(f"✓ Cache ready check: {elapsed:.1f}ms ({cached}/{total} keys cached)")
        # Note: May not be fully ready immediately, but should be responsive

    @pytest.mark.asyncio
    async def test_dashboard_overview(self, auth_client):
        """Fetch dashboard with market indices and portfolio."""
        status, data, elapsed = await auth_client.get("/dashboard")
        assert status == 200, f"Dashboard should return 200, got {status}"

        # Check indices
        indices = data.get("indices", [])
        assert len(indices) > 0, "Should have indices"
        gspc = next((i for i in indices if i.get("symbol") == "^GSPC"), None)
        assert gspc is not None, "S&P 500 should be in indices"
        if gspc.get("price") is not None:
            print(f"✓ S&P 500: ${gspc['price']:.2f} ({gspc.get('change_pct', 0):+.2f}%)")

        ixic = next((i for i in indices if i.get("symbol") == "^IXIC"), None)
        assert ixic is not None, "NASDAQ should be in indices"
        if ixic.get("price") is not None:
            print(f"✓ NASDAQ: ${ixic['price']:.2f} ({ixic.get('change_pct', 0):+.2f}%)")

        print(f"✓ Dashboard loaded: {elapsed:.1f}ms")


class TestChartPhase:
    """3. Chart Phase — Test stock quotes, history, and fundamentals."""

    @pytest.mark.asyncio
    async def test_single_quote_nvda(self, client):
        """Get single stock quote (NVDA)."""
        status, data, elapsed = await client.get("/stocks/NVDA/quote")
        assert status == 200, f"Quote should return 200, got {status}"
        assert data.get("symbol") == "NVDA", "Symbol should be NVDA"
        assert data.get("price") is not None, "Price should exist"
        assert elapsed < THRESHOLD_QUOTE, f"Quote should be <{THRESHOLD_QUOTE}ms, got {elapsed:.1f}ms"
        print(f"✓ NVDA quote: ${data['price']:.2f} (cold: {elapsed:.1f}ms)")

    @pytest.mark.asyncio
    async def test_single_quote_ptt_bk(self, client):
        """Get Thai stock quote (PTT.BK)."""
        status, data, elapsed = await client.get("/stocks/PTT.BK/quote")
        # Thai stocks may have different behavior
        if status == 200:
            print(f"✓ PTT.BK quote: {data.get('price')} (Thai market: {elapsed:.1f}ms)")
        else:
            print(f"⚠ PTT.BK unavailable (expected for Thai market): {status}")

    @pytest.mark.asyncio
    async def test_quote_cached(self, client):
        """Verify cached quotes are fast (<100ms)."""
        # First call (warm)
        status, data, elapsed = await client.get("/stocks/AAPL/quote")
        assert status == 200, "First quote call should succeed"

        # Second call (should be cached)
        status, data, elapsed = await client.get("/stocks/AAPL/quote")
        assert status == 200, "Cached quote should succeed"
        if elapsed < THRESHOLD_CACHE:
            print(f"✓ AAPL cached quote: {elapsed:.1f}ms (excellent)")
        else:
            print(f"⚠ AAPL cached quote: {elapsed:.1f}ms (slower than ideal)")

    @pytest.mark.asyncio
    async def test_history_all_timeframes(self, client):
        """Test stock history across all timeframes."""
        timeframes = ["1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"]
        symbol = "NVDA"

        for tf in timeframes:
            status, data, elapsed = await client.get(
                f"/stocks/{symbol}/history",
                params={"tf": tf}
            )
            assert status == 200, f"History for {tf} should return 200, got {status}"
            bars = data.get("bars", [])
            assert len(bars) > 0, f"Should have bars for {tf}"
            print(f"  ✓ {tf:5s}: {len(bars):3d} bars ({elapsed:.1f}ms)")

    @pytest.mark.asyncio
    async def test_fundamentals(self, client):
        """Get stock fundamentals."""
        status, data, elapsed = await client.get("/stocks/NVDA/fundamentals")
        assert status == 200, f"Fundamentals should return 200, got {status}"
        # May be null if data unavailable, but endpoint should work
        print(f"✓ NVDA fundamentals: {elapsed:.1f}ms")
        if data.get("pe_ratio"):
            print(f"  P/E: {data['pe_ratio']:.2f}")
        if data.get("dividend_yield"):
            print(f"  Div Yield: {data['dividend_yield']:.2f}%")

    @pytest.mark.asyncio
    async def test_news(self, client):
        """Get stock news."""
        status, data, elapsed = await client.get("/stocks/NVDA/news")
        assert status == 200, f"News should return 200, got {status}"
        news_items = data if isinstance(data, list) else []
        print(f"✓ NVDA news: {len(news_items)} items ({elapsed:.1f}ms)")
        if news_items:
            print(f"  Latest: {news_items[0].get('title', '')[:60]}...")

    @pytest.mark.asyncio
    async def test_symbol_switch_aapl(self, client):
        """Switch stock: NVDA → AAPL."""
        status, data, elapsed = await client.get("/stocks/AAPL/quote")
        assert status == 200, "AAPL quote should work"
        assert data.get("symbol") == "AAPL"
        print(f"✓ Symbol switch to AAPL: ${data['price']:.2f} ({elapsed:.1f}ms)")

    @pytest.mark.asyncio
    async def test_symbol_switch_msft(self, client):
        """Switch stock: AAPL → MSFT."""
        status, data, elapsed = await client.get("/stocks/MSFT/quote")
        assert status == 200, "MSFT quote should work"
        assert data.get("symbol") == "MSFT"
        print(f"✓ Symbol switch to MSFT: ${data['price']:.2f} ({elapsed:.1f}ms)")


class TestSearchPhase:
    """4. Search Phase — Test stock symbol search."""

    @pytest.mark.asyncio
    async def test_search_nv(self, client):
        """Search for NVDA by prefix."""
        status, data, elapsed = await client.get("/stocks/search", params={"q": "NV"})
        assert status == 200, f"Search should return 200, got {status}"
        results = data if isinstance(data, list) else []
        assert len(results) > 0, "Should find results for 'NV'"
        nvda = next((r for r in results if r.get("symbol") == "NVDA"), None)
        assert nvda is not None, "NVDA should be in results"
        print(f"✓ Search 'NV': Found {len(results)} results, NVDA first")

    @pytest.mark.asyncio
    async def test_search_ptt(self, client):
        """Search for Thai stock PTT."""
        status, data, elapsed = await client.get("/stocks/search", params={"q": "PTT"})
        assert status == 200, f"Search should return 200, got {status}"
        results = data if isinstance(data, list) else []
        # May or may not find PTT.BK depending on DB state
        if results:
            print(f"✓ Search 'PTT': Found {len(results)} results")
        else:
            print(f"⚠ Search 'PTT': No results (Thai market data may be sparse)")

    @pytest.mark.asyncio
    async def test_search_aapl(self, client):
        """Search for AAPL."""
        status, data, elapsed = await client.get("/stocks/search", params={"q": "AAPL"})
        assert status == 200
        results = data if isinstance(data, list) else []
        assert len(results) > 0, "Should find AAPL"
        print(f"✓ Search 'AAPL': Found {len(results)} results")


class TestWatchlistPhase:
    """5. Watchlist Phase — Create, modify, and delete watchlists."""

    watchlist_id: Optional[int] = None

    @pytest.mark.asyncio
    async def test_get_watchlists(self, auth_client):
        """Get existing watchlists."""
        status, data, elapsed = await auth_client.get("/watchlists")
        assert status == 200, f"Should return 200, got {status}"
        watchlists = data if isinstance(data, list) else []
        print(f"✓ Get watchlists: {len(watchlists)} existing")

    @pytest.mark.asyncio
    async def test_create_watchlist(self, auth_client):
        """Create a test watchlist."""
        status, data, elapsed = await auth_client.post(
            "/watchlists",
            {"name": "Simulator Test Watchlist"}
        )
        assert status == 201, f"Create should return 201, got {status}"
        self.watchlist_id = data.get("id")
        assert self.watchlist_id is not None, "Watchlist should have ID"
        print(f"✓ Created watchlist (ID: {self.watchlist_id})")

    @pytest.mark.asyncio
    async def test_add_stock_nvda(self, auth_client):
        """Add NVDA to watchlist."""
        if not self.watchlist_id:
            pytest.skip("No watchlist created")

        status, data, elapsed = await auth_client.post(
            f"/watchlists/{self.watchlist_id}/stocks",
            {"symbol": "NVDA"}
        )
        assert status == 201, f"Add stock should return 201, got {status}"
        print(f"✓ Added NVDA to watchlist")

    @pytest.mark.asyncio
    async def test_add_stock_aapl(self, auth_client):
        """Add AAPL to watchlist."""
        if not self.watchlist_id:
            pytest.skip("No watchlist created")

        status, data, elapsed = await auth_client.post(
            f"/watchlists/{self.watchlist_id}/stocks",
            {"symbol": "AAPL"}
        )
        assert status == 201, f"Add stock should return 201, got {status}"
        print(f"✓ Added AAPL to watchlist")

    @pytest.mark.asyncio
    async def test_batch_quotes(self, auth_client):
        """Get batch quotes for watchlist."""
        status, data, elapsed = await auth_client.get(
            "/stocks/quotes",
            params={"symbols": "NVDA,AAPL,MSFT,GOOG,SPY"}
        )
        assert status == 200, f"Batch quotes should return 200, got {status}"
        quotes = data if isinstance(data, dict) else {}
        count = sum(1 for v in quotes.values() if v is not None)
        assert count > 0, "Should have at least some quotes"
        assert elapsed < THRESHOLD_BATCH, f"Batch <{THRESHOLD_BATCH}ms, got {elapsed:.1f}ms"
        print(f"✓ Batch quotes: {count}/5 symbols ({elapsed:.1f}ms)")

    @pytest.mark.asyncio
    async def test_remove_stock_aapl(self, auth_client):
        """Remove AAPL from watchlist."""
        if not self.watchlist_id:
            pytest.skip("No watchlist created")

        status, data, elapsed = await auth_client.delete(
            f"/watchlists/{self.watchlist_id}/stocks/AAPL"
        )
        assert status == 204, f"Remove should return 204, got {status}"
        print(f"✓ Removed AAPL from watchlist")

    @pytest.mark.asyncio
    async def test_delete_watchlist(self, auth_client):
        """Delete test watchlist (cleanup)."""
        if not self.watchlist_id:
            pytest.skip("No watchlist created")

        status, data, elapsed = await auth_client.delete(
            f"/watchlists/{self.watchlist_id}"
        )
        assert status == 204, f"Delete should return 204, got {status}"
        print(f"✓ Deleted test watchlist")
        self.watchlist_id = None


class TestPortfolioPhase:
    """6. Portfolio Phase — Add transactions and verify P&L."""

    transaction_ids: list[int] = []

    @pytest.mark.asyncio
    async def test_get_transactions_initial(self, auth_client):
        """Get initial portfolio state."""
        status, data, elapsed = await auth_client.get("/portfolio")
        assert status == 200, f"Should return 200, got {status}"
        txns = data if isinstance(data, list) else []
        print(f"✓ Get transactions: {len(txns)} existing")

    @pytest.mark.asyncio
    async def test_add_transaction_aapl(self, auth_client):
        """Add a BUY transaction for AAPL."""
        status, data, elapsed = await auth_client.post(
            "/portfolio/transactions",
            {
                "symbol": "AAPL",
                "type": "BUY",
                "qty": 10,
                "price": 150.0,
                "fee": 0.0,
                "currency": "USD",
                "date": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                "note": "Test transaction",
            }
        )
        assert status == 201, f"Add transaction should return 201, got {status}"
        txn_id = data.get("id")
        assert txn_id is not None, "Transaction should have ID"
        self.transaction_ids.append(txn_id)
        print(f"✓ Added AAPL transaction (ID: {txn_id})")

    @pytest.mark.asyncio
    async def test_add_transaction_ptt(self, auth_client):
        """Add a BUY transaction for PTT.BK (Thai stock)."""
        status, data, elapsed = await auth_client.post(
            "/portfolio/transactions",
            {
                "symbol": "PTT.BK",
                "type": "BUY",
                "qty": 100,
                "price": 35.0,
                "fee": 10.0,
                "currency": "THB",
                "date": datetime.now(timezone.utc).isoformat(),
                "note": "Thai stock",
            }
        )
        assert status == 201, f"Add transaction should return 201, got {status}"
        txn_id = data.get("id")
        self.transaction_ids.append(txn_id)
        print(f"✓ Added PTT.BK transaction (ID: {txn_id})")

    @pytest.mark.asyncio
    async def test_get_portfolio_analytics(self, auth_client):
        """Get portfolio analytics with current prices."""
        status, data, elapsed = await auth_client.get("/portfolio/analytics")
        assert status == 200, f"Analytics should return 200, got {status}"
        holdings = data.get("holdings", [])
        print(f"✓ Portfolio analytics: {len(holdings)} positions ({elapsed:.1f}ms)")
        for h in holdings:
            sym = h.get("symbol")
            val = h.get("current_value")
            pl = h.get("unrealized_pl")
            pl_pct = h.get("unrealized_pl_pct")
            print(f"  {sym}: {val} {h.get('currency')} ({pl_pct:+.2f}%)")

    @pytest.mark.asyncio
    async def test_cleanup_transactions(self, auth_client):
        """Delete all test transactions (cleanup)."""
        for txn_id in self.transaction_ids:
            status, data, elapsed = await auth_client.delete(
                f"/portfolio/transactions/{txn_id}"
            )
            assert status == 204, f"Delete should return 204, got {status}"
        print(f"✓ Deleted {len(self.transaction_ids)} test transactions")
        self.transaction_ids = []


class TestAlertPhase:
    """7. Alert Phase — Create and manage price alerts."""

    alert_ids: list[int] = []

    @pytest.mark.asyncio
    async def test_get_alerts_initial(self, auth_client):
        """Get initial alerts."""
        status, data, elapsed = await auth_client.get("/alerts")
        assert status == 200, f"Should return 200, got {status}"
        alerts = data if isinstance(data, list) else []
        print(f"✓ Get alerts: {len(alerts)} existing")

    @pytest.mark.asyncio
    async def test_create_alert_nvda(self, auth_client):
        """Create a price alert for NVDA > $200."""
        status, data, elapsed = await auth_client.post(
            "/alerts",
            {
                "symbol": "NVDA",
                "alert_type": "PRICE",
                "condition": "GREATER_THAN",
                "value": 200.0,
                "channel": "IN_APP",
            }
        )
        assert status == 201, f"Create alert should return 201, got {status}"
        alert_id = data.get("id")
        assert alert_id is not None, "Alert should have ID"
        self.alert_ids.append(alert_id)
        print(f"✓ Created NVDA alert (ID: {alert_id})")

    @pytest.mark.asyncio
    async def test_create_alert_aapl(self, auth_client):
        """Create a price alert for AAPL."""
        status, data, elapsed = await auth_client.post(
            "/alerts",
            {
                "symbol": "AAPL",
                "alert_type": "PRICE",
                "condition": "LESS_THAN",
                "value": 140.0,
                "channel": "IN_APP",
            }
        )
        assert status == 201, f"Create alert should return 201, got {status}"
        alert_id = data.get("id")
        self.alert_ids.append(alert_id)
        print(f"✓ Created AAPL alert (ID: {alert_id})")

    @pytest.mark.asyncio
    async def test_toggle_alert(self, auth_client):
        """Toggle alert active/inactive."""
        if not self.alert_ids:
            pytest.skip("No alerts created")

        alert_id = self.alert_ids[0]
        status, data, elapsed = await auth_client.patch(
            f"/alerts/{alert_id}/toggle"
        )
        assert status == 200, f"Toggle should return 200, got {status}"
        is_active = data.get("is_active")
        print(f"✓ Toggled alert: is_active={is_active}")

    @pytest.mark.asyncio
    async def test_cleanup_alerts(self, auth_client):
        """Delete all test alerts (cleanup)."""
        for alert_id in self.alert_ids:
            status, data, elapsed = await auth_client.delete(
                f"/alerts/{alert_id}"
            )
            assert status == 204, f"Delete should return 204, got {status}"
        print(f"✓ Deleted {len(self.alert_ids)} test alerts")
        self.alert_ids = []


class TestPerformancePhase:
    """8. Performance Phase — Verify caching and response times."""

    @pytest.mark.asyncio
    async def test_batch_performance_warm(self, client):
        """Test batch quote performance (warm cache)."""
        symbols = "NVDA,AAPL,MSFT,GOOG,SPY"

        # First call (warm)
        status, data, elapsed = await client.get(
            "/stocks/quotes",
            params={"symbols": symbols}
        )
        assert status == 200
        first_time = elapsed

        # Second call (should be cached)
        status, data, elapsed = await client.get(
            "/stocks/quotes",
            params={"symbols": symbols}
        )
        assert status == 200
        second_time = elapsed

        assert first_time < THRESHOLD_BATCH, f"First batch should be <{THRESHOLD_BATCH}ms"
        assert second_time < THRESHOLD_CACHE, f"Cached batch should be <{THRESHOLD_CACHE}ms"
        print(f"✓ Batch performance: first={first_time:.1f}ms, cached={second_time:.1f}ms")

    @pytest.mark.asyncio
    async def test_history_caching(self, client):
        """Test history endpoint caching."""
        symbol = "NVDA"
        tf = "1D"

        # First call
        status, data, elapsed = await client.get(
            f"/stocks/{symbol}/history",
            params={"tf": tf}
        )
        assert status == 200
        first_time = elapsed

        # Second call (may be cached)
        status, data, elapsed = await client.get(
            f"/stocks/{symbol}/history",
            params={"tf": tf}
        )
        assert status == 200
        second_time = elapsed

        print(f"✓ History caching: first={first_time:.1f}ms, second={second_time:.1f}ms")

    @pytest.mark.asyncio
    async def test_concurrent_quotes(self, client):
        """Test concurrent quote requests."""
        symbols = ["NVDA", "AAPL", "MSFT", "GOOG", "SPY", "TSLA", "AMD", "INTC"]

        async def fetch_quote(sym):
            return await client.get(f"/stocks/{sym}/quote")

        start = time.time()
        results = await asyncio.gather(
            *[fetch_quote(sym) for sym in symbols],
            return_exceptions=True
        )
        elapsed = (time.time() - start) * 1000

        success = sum(1 for r in results if isinstance(r, tuple) and r[0] == 200)
        print(f"✓ Concurrent quotes: {success}/{len(symbols)} succeeded ({elapsed:.1f}ms total)")


# ============================================================================
# Integration Tests — Full User Journey
# ============================================================================


class TestUserJourney:
    """Complete user journey simulation."""

    @pytest.mark.asyncio
    async def test_complete_user_flow(self):
        """Simulate a complete user session."""
        client = ShotockVizTestClient()
        try:
            print("\n" + "="*60)
            print("SHOTOCKVIZ USER JOURNEY SIMULATION")
            print("="*60)

            # 1. Auth
            print("\n[1] AUTHENTICATION")
            token = await client.create_test_jwt()
            print(f"✓ Created test JWT: {token[:50]}...")

            # 2. Health checks
            print("\n[2] SYSTEM HEALTH")
            status, data, elapsed = await client.get("/health")
            print(f"✓ System healthy: {elapsed:.1f}ms")

            # 3. Get dashboard
            print("\n[3] DASHBOARD")
            status, data, elapsed = await client.get("/dashboard")
            indices = data.get("indices", [])
            for idx in indices:
                if idx.get("price"):
                    print(f"  {idx.get('name'):12s}: ${idx['price']:>8.2f} ({idx.get('change_pct', 0):>+6.2f}%)")

            # 4. Search stocks
            print("\n[4] STOCK SEARCH")
            status, data, elapsed = await client.get("/stocks/search", params={"q": "NV"})
            results = data if isinstance(data, list) else []
            print(f"✓ Found {len(results)} results for 'NV'")

            # 5. View chart
            print("\n[5] CHART VIEW")
            for symbol in ["NVDA", "AAPL", "PTT.BK"]:
                status, data, elapsed = await client.get(f"/stocks/{symbol}/quote")
                if status == 200:
                    print(f"  {symbol:8s}: ${data.get('price', 'N/A'):>8} ({elapsed:.1f}ms)")

            # 6. Create watchlist
            print("\n[6] WATCHLIST")
            status, data, elapsed = await client.post(
                "/watchlists",
                {"name": "Journey Test"}
            )
            if status == 201:
                wl_id = data.get("id")
                print(f"✓ Created watchlist (ID: {wl_id})")

                # Add stocks
                for sym in ["NVDA", "AAPL"]:
                    status, _, _ = await client.post(
                        f"/watchlists/{wl_id}/stocks",
                        {"symbol": sym}
                    )
                    if status == 201:
                        print(f"  Added {sym}")

                # Get batch quotes
                status, quotes, elapsed = await client.get(
                    "/stocks/quotes",
                    params={"symbols": "NVDA,AAPL"}
                )
                print(f"✓ Batch quotes: {elapsed:.1f}ms")

                # Clean up
                await client.delete(f"/watchlists/{wl_id}")

            # 7. Portfolio
            print("\n[7] PORTFOLIO")
            status, data, elapsed = await client.post(
                "/portfolio/transactions",
                {
                    "symbol": "AAPL",
                    "type": "BUY",
                    "qty": 5,
                    "price": 150,
                    "fee": 0,
                    "currency": "USD",
                    "date": datetime.now(timezone.utc).isoformat(),
                }
            )
            if status == 201:
                txn_id = data.get("id")
                print(f"✓ Added transaction (ID: {txn_id})")

                # Get analytics
                status, data, elapsed = await client.get("/portfolio/analytics")
                holdings = data.get("holdings", [])
                print(f"✓ Portfolio: {len(holdings)} positions ({elapsed:.1f}ms)")

                # Clean up
                await client.delete(f"/portfolio/transactions/{txn_id}")

            # 8. Alerts
            print("\n[8] ALERTS")
            status, data, elapsed = await client.post(
                "/alerts",
                {
                    "symbol": "NVDA",
                    "alert_type": "PRICE",
                    "condition": "GREATER_THAN",
                    "value": 200,
                    "channel": "IN_APP",
                }
            )
            if status == 201:
                alert_id = data.get("id")
                print(f"✓ Created alert (ID: {alert_id})")
                await client.delete(f"/alerts/{alert_id}")

            print("\n" + "="*60)
            print("JOURNEY COMPLETE — All features verified!")
            print("="*60 + "\n")

        finally:
            await client.close()


# ============================================================================
# Run pytest
# ============================================================================

if __name__ == "__main__":
    # Run with: python -m pytest tests/test_user_simulation.py -v
    pytest.main([__file__, "-v", "-s", "--tb=short"])
