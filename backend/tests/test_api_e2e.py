"""
Comprehensive E2E API tests for ShotockViz backend.

Test coverage:
  TC-001: System health & readiness
  TC-002: Stock quote endpoints
  TC-003: Stock history & bars
  TC-004: Stock fundamentals
  TC-005: Stock search
  TC-006: Auth endpoints (register, login, refresh, logout, me)
  TC-007: Watchlist CRUD
  TC-008: Portfolio & transactions
  TC-009: Alerts CRUD
  TC-010: Drawings CRUD
  TC-011: Notes CRUD
  TC-012: Dashboard aggregated data
  TC-013: Screener filtering
  TC-014: AI Chat (SSE stream)
  TC-015: Stock events & news
"""
import json
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

import pytest

# bd:deps-2026-09 WP-B0 — quarantined: `AlertCondition` does not exist in
# `backend/models/alert.py` (only AlertType/AlertStatus/AlertChannel — verified
# `grep -rn AlertCondition backend --include='*.py' -l | grep -v tests` → empty).
# This suite predates the current alert model and needs a rewrite against the
# real schema; tracked as an open question to Oliver (03-stan-refactor-strategy.md
# §6 Q1) whether the rewrite becomes its own bd. Not fixed on this branch
# (out of scope per 02-bella-brd-ac.md §1.2 "not gated" pre-existing breakage).
pytest.skip(
    "quarantined bd:deps-2026-09 WP-B0 — imports AlertCondition which does not "
    "exist in models.alert; needs rewrite against real Alert model, see "
    "outputs/deps-2026-09/03-stan-refactor-strategy.md §6 Q1",
    allow_module_level=True,
)

from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    StockQuote, StockHistory, OHLCVBar, StockFundamentals,
    RegisterRequest, LoginRequest, WatchlistCreate, WatchlistItemAdd,
    TransactionCreate, AlertCreate, DrawingCreate,
)
from models.user import User
from models.watchlist import Watchlist, WatchlistItem
from models.portfolio import Transaction, TransactionType
from models.alert import Alert, AlertType, AlertCondition, AlertChannel


# ─────────────────────────────────────────────────────────────────────────────
# TC-001: System Health & Readiness
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemHealth:
    """Health check and system readiness endpoints."""

    @pytest.mark.asyncio
    async def test_health_check_success(self, async_client: AsyncClient):
        """Health endpoint should return 200 with database/redis/celery status."""
        response = await async_client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "database" in data["data"]
        assert "redis" in data["data"]
        assert "celery" in data["data"]
        assert data["meta"]["data_status"] in ["fresh", "partial"]

    @pytest.mark.asyncio
    async def test_cache_ready_check(self, async_client: AsyncClient):
        """Ready endpoint should report cache status."""
        response = await async_client.get("/api/system/ready")

        assert response.status_code == 200
        data = response.json()
        assert "ready" in data
        assert "cached" in data
        assert "total" in data
        assert isinstance(data["ready"], bool)
        assert isinstance(data["cached"], int)

    @pytest.mark.asyncio
    async def test_celery_stats(self, async_client: AsyncClient):
        """Celery stats should return success/failure counters."""
        response = await async_client.get("/api/system/celery-stats")

        assert response.status_code == 200
        data = response.json()
        assert "success_count" in data
        assert "failure_count" in data
        assert "last_success_at" in data
        assert "last_error" in data


# ─────────────────────────────────────────────────────────────────────────────
# TC-002: Stock Quote Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestStockQuotes:
    """Single and batch stock quote endpoints."""

    @pytest.mark.asyncio
    async def test_get_single_quote_us_stock(
        self, async_client: AsyncClient, sample_quote
    ):
        """Single quote for US stock (NVDA) should return 200 + price."""
        with patch("services.stock_service.fetch_quote_now") as mock_fetch:
            mock_quote = StockQuote(**sample_quote)
            mock_fetch.return_value = mock_quote

            response = await async_client.get("/api/stocks/NVDA/quote")

            assert response.status_code == 200
            data = response.json()
            assert data["symbol"] == "NVDA"
            assert "price" in data
            assert data["price"] == 875.50

    @pytest.mark.asyncio
    async def test_get_single_quote_thai_stock(
        self, async_client: AsyncClient
    ):
        """Single quote for Thai stock (PTT.BK) should return 200 or graceful null."""
        with patch("services.stock_service.fetch_quote_now") as mock_fetch:
            # Thai stock may return data or None (graceful)
            thai_quote = {
                "symbol": "PTT.BK",
                "price": 3240.00,
                "change": 15.0,
                "change_pct": 0.47,
                "open": 3230.0,
                "high": 3250.0,
                "low": 3225.0,
                "volume": 1_000_000,
                "market_cap": None,
            }
            mock_quote = StockQuote(**thai_quote)
            mock_fetch.return_value = mock_quote

            response = await async_client.get("/api/stocks/PTT.BK/quote")

            assert response.status_code == 200
            data = response.json()
            assert data["symbol"] == "PTT.BK"

    @pytest.mark.asyncio
    async def test_get_quote_invalid_symbol_returns_404(
        self, async_client: AsyncClient
    ):
        """Invalid symbol should return 404, not 500."""
        with patch("services.stock_service.fetch_quote_now") as mock_fetch:
            mock_fetch.return_value = None

            response = await async_client.get("/api/stocks/XYZINVALID/quote")

            assert response.status_code == 404
            data = response.json()
            assert data["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_get_batch_quotes(self, async_client: AsyncClient):
        """Batch quotes endpoint should return dict {symbol: quote}."""
        with patch("services.stock_service.get_redis") as mock_redis:
            with patch("services.stock_service.fetch_quote_now") as mock_fetch:
                mock_redis.return_value = AsyncMock(
                    pipeline=AsyncMock(return_value=AsyncMock(
                        execute=AsyncMock(return_value=[None, None])
                    ))
                )

                quote1 = {
                    "symbol": "NVDA", "price": 875.50, "change": 12.30,
                    "change_pct": 1.42, "open": 870.0, "high": 885.0,
                    "low": 865.0, "volume": 45_000_000, "market_cap": None,
                }
                quote2 = {
                    "symbol": "AAPL", "price": 175.25, "change": -2.10,
                    "change_pct": -1.18, "open": 177.0, "high": 178.0,
                    "low": 174.0, "volume": 58_000_000, "market_cap": None,
                }
                mock_fetch.side_effect = [
                    StockQuote(**quote1),
                    StockQuote(**quote2),
                ]

                response = await async_client.get(
                    "/api/stocks/quotes?symbols=NVDA,AAPL"
                )

                assert response.status_code == 200
                data = response.json()
                assert "NVDA" in data
                assert "AAPL" in data

    @pytest.mark.asyncio
    async def test_batch_quotes_all_have_data(
        self, async_client: AsyncClient
    ):
        """All symbols in batch response should have quote data (no nulls)."""
        with patch("services.stock_service.get_redis") as mock_redis:
            with patch("services.stock_service.fetch_quote_now") as mock_fetch:
                mock_redis.return_value = AsyncMock(
                    pipeline=AsyncMock(return_value=AsyncMock(
                        execute=AsyncMock(return_value=[None])
                    ))
                )

                quote = StockQuote(
                    symbol="NVDA", price=875.50, change=12.30,
                    change_pct=1.42, open=870.0, high=885.0,
                    low=865.0, volume=45_000_000, market_cap=None,
                )
                mock_fetch.return_value = quote

                response = await async_client.get(
                    "/api/stocks/quotes?symbols=NVDA"
                )

                assert response.status_code == 200
                data = response.json()
                assert data["NVDA"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# TC-003: Stock History & Bars
# ─────────────────────────────────────────────────────────────────────────────

class TestStockHistory:
    """Stock OHLCV history endpoints."""

    @pytest.mark.asyncio
    async def test_get_history_daily_nvda(
        self, async_client: AsyncClient, sample_history
    ):
        """Daily bars for NVDA should return ≥100 bars with ascending time."""
        with patch("services.stock_service.fetch_stock_history") as mock_fetch:
            bars = [
                OHLCVBar(**bar) for bar in sample_history["bars"]
            ]
            mock_fetch.return_value = bars

            response = await async_client.get(
                "/api/stocks/NVDA/history?tf=1D"
            )

            assert response.status_code == 200
            data = response.json()
            assert data["symbol"] == "NVDA"
            assert data["timeframe"] == "1D"
            assert len(data["bars"]) >= 1
            # Verify ascending time
            times = [bar["t"] for bar in data["bars"]]
            assert times == sorted(times)

    @pytest.mark.asyncio
    async def test_history_all_timeframes(self, async_client: AsyncClient):
        """All timeframes (1m,5m,15m,1h,4h,1D,1W,1M) should return data."""
        timeframes = ["1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"]

        for tf in timeframes:
            with patch("services.stock_service.fetch_stock_history") as mock_fetch:
                bars = [
                    OHLCVBar(
                        t=1700000000 + i*60, o=100.0, h=105.0,
                        l=95.0, c=102.0, v=1_000_000
                    )
                    for i in range(5)
                ]
                mock_fetch.return_value = bars

                response = await async_client.get(
                    f"/api/stocks/NVDA/history?tf={tf}"
                )

                assert response.status_code == 200
                data = response.json()
                assert len(data["bars"]) > 0

    @pytest.mark.asyncio
    async def test_history_invalid_timeframe_returns_400(
        self, async_client: AsyncClient
    ):
        """Invalid timeframe should return 400 Bad Request."""
        response = await async_client.get(
            "/api/stocks/NVDA/history?tf=INVALID"
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_history_no_nan_values(
        self, async_client: AsyncClient
    ):
        """OHLCV bars should not contain NaN or null values."""
        with patch("services.stock_service.fetch_stock_history") as mock_fetch:
            bars = [
                OHLCVBar(
                    t=1700000000, o=850.0, h=855.0,
                    l=845.0, c=852.5, v=50_000_000
                ),
                OHLCVBar(
                    t=1700086400, o=852.5, h=870.0,
                    l=850.0, c=868.0, v=55_000_000
                ),
            ]
            mock_fetch.return_value = bars

            response = await async_client.get(
                "/api/stocks/NVDA/history?tf=1D"
            )

            assert response.status_code == 200
            data = response.json()
            for bar in data["bars"]:
                assert bar["o"] is not None
                assert bar["h"] is not None
                assert bar["l"] is not None
                assert bar["c"] is not None
                assert bar["v"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# TC-004: Stock Fundamentals
# ─────────────────────────────────────────────────────────────────────────────

class TestStockFundamentals:
    """Stock fundamentals endpoints."""

    @pytest.mark.asyncio
    async def test_fundamentals_nvda_has_pe_and_marketcap(
        self, async_client: AsyncClient, sample_fundamentals
    ):
        """NVDA fundamentals should contain P/E and marketCap."""
        with patch("services.stock_service.fetch_stock_fundamentals") as mock_fetch:
            fundamentals = StockFundamentals(**sample_fundamentals)
            mock_fetch.return_value = fundamentals

            response = await async_client.get(
                "/api/stocks/NVDA/fundamentals"
            )

            assert response.status_code == 200
            data = response.json()
            assert data["symbol"] == "NVDA"
            assert data["pe_ratio"] is not None
            assert data["market_cap"] is not None

    @pytest.mark.asyncio
    async def test_fundamentals_returns_shell_on_unavailable(
        self, async_client: AsyncClient
    ):
        """When data unavailable, return 200 with null fields (not 500)."""
        with patch("services.stock_service.fetch_stock_fundamentals") as mock_fetch:
            mock_fetch.return_value = None

            response = await async_client.get(
                "/api/stocks/INVALIDXYZ/fundamentals"
            )

            assert response.status_code == 200
            data = response.json()
            assert data["pe_ratio"] is None


# ─────────────────────────────────────────────────────────────────────────────
# TC-005: Stock Search
# ─────────────────────────────────────────────────────────────────────────────

class TestStockSearch:
    """Stock search endpoints."""

    @pytest.mark.asyncio
    async def test_search_by_symbol_prefix(
        self, async_client: AsyncClient, test_db: AsyncSession
    ):
        """Search "NV" should return NVDA in results."""
        from models.stock import Stock, MarketType

        stock = Stock(
            symbol="NVDA",
            name="NVIDIA Corporation",
            name_th="บริษัท เอ็นวิเดีย",
            market=MarketType.US,
            is_active=True,
        )
        test_db.add(stock)
        await test_db.commit()

        response = await async_client.get("/api/stocks/search?q=NV")

        assert response.status_code == 200
        data = response.json()
        symbols = [item["symbol"] for item in data]
        assert "NVDA" in symbols

    @pytest.mark.asyncio
    async def test_search_empty_query_handled_gracefully(
        self, async_client: AsyncClient
    ):
        """Empty search should return empty list, not error."""
        response = await async_client.get("/api/stocks/search?q=")

        # Should either return 422 (validation) or 200 with empty results
        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_search_returns_empty_list_not_404(
        self, async_client: AsyncClient
    ):
        """Non-existent symbol search should return 200 with empty list."""
        response = await async_client.get(
            "/api/stocks/search?q=XYZNONEXISTENT"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_search_by_thai_name(
        self, async_client: AsyncClient, test_db: AsyncSession
    ):
        """Search by Thai name should find the stock."""
        from models.stock import Stock, MarketType

        stock = Stock(
            symbol="PTT.BK",
            name="PTT Public Company Limited",
            name_th="บริษัท ปตท. จำกัด (มหาชน)",
            market=MarketType.THAILAND,
            is_active=True,
        )
        test_db.add(stock)
        await test_db.commit()

        response = await async_client.get("/api/stocks/search?q=ปตท")

        assert response.status_code == 200
        data = response.json()
        assert any(item["symbol"] == "PTT.BK" for item in data)


# ─────────────────────────────────────────────────────────────────────────────
# TC-006: Auth Endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthEndpoints:
    """Authentication endpoints (register, login, refresh, logout, me)."""

    @pytest.mark.asyncio
    async def test_register_new_user(self, async_client: AsyncClient):
        """Register endpoint should create new user and return 201."""
        response = await async_client.post(
            "/api/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "SecurePass123!",
                "display_name": "New User",
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["display_name"] == "New User"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email_returns_409(
        self, async_client: AsyncClient, test_user: User
    ):
        """Registering with existing email should return 409 Conflict."""
        response = await async_client.post(
            "/api/auth/register",
            json={
                "email": test_user.email,
                "password": "AnotherPass123!",
                "display_name": "Another User",
            }
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_login_valid_credentials(
        self, async_client: AsyncClient, test_user: User
    ):
        """Login with valid credentials should return access + refresh tokens."""
        response = await async_client.post(
            "/api/auth/login",
            json={
                "email": test_user.email,
                "password": "password123",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["access_token"].startswith("eyJ")  # JWT format

    @pytest.mark.asyncio
    async def test_login_invalid_credentials_returns_401(
        self, async_client: AsyncClient, test_user: User
    ):
        """Login with wrong password should return 401."""
        response = await async_client.post(
            "/api/auth/login",
            json={
                "email": test_user.email,
                "password": "wrongpassword",
            }
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me_with_valid_token(
        self, async_client: AsyncClient, auth_headers: dict, test_user: User
    ):
        """GET /me with valid token should return user info."""
        response = await async_client.get(
            "/api/auth/me",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["id"] == test_user.id

    @pytest.mark.asyncio
    async def test_get_me_without_token_returns_401(
        self, async_client: AsyncClient
    ):
        """GET /me without token should return 401."""
        response = await async_client.get("/api/auth/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_config_returns_google_client_id(
        self, async_client: AsyncClient
    ):
        """Auth config should return google_client_id."""
        response = await async_client.get("/api/auth/config")

        assert response.status_code == 200
        data = response.json()
        assert "google_client_id" in data


# ─────────────────────────────────────────────────────────────────────────────
# TC-007: Watchlist CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestWatchlistEndpoints:
    """Watchlist creation, read, update, delete."""

    @pytest.mark.asyncio
    async def test_create_watchlist(
        self, async_client: AsyncClient, auth_headers: dict, test_user: User
    ):
        """POST /watchlists should create new watchlist and return 201."""
        response = await async_client.post(
            "/api/watchlists",
            json={"name": "My Tech Stocks"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My Tech Stocks"
        assert data["user_id"] == test_user.id
        assert "id" in data

    @pytest.mark.asyncio
    async def test_get_watchlists(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """GET /watchlists should return all user's watchlists."""
        # Create a watchlist
        wl = Watchlist(user_id=test_user.id, name="Test List")
        test_db.add(wl)
        await test_db.commit()

        response = await async_client.get(
            "/api/watchlists",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(item["name"] == "Test List" for item in data)

    @pytest.mark.asyncio
    async def test_update_watchlist_name(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """PUT /watchlists/{id} should update watchlist name."""
        wl = Watchlist(user_id=test_user.id, name="Old Name")
        test_db.add(wl)
        await test_db.commit()

        response = await async_client.put(
            f"/api/watchlists/{wl.id}",
            json={"name": "New Name"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_delete_watchlist(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """DELETE /watchlists/{id} should delete watchlist."""
        wl = Watchlist(user_id=test_user.id, name="To Delete")
        test_db.add(wl)
        await test_db.commit()
        wl_id = wl.id

        response = await async_client.delete(
            f"/api/watchlists/{wl_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_add_stock_to_watchlist(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """POST /watchlists/{id}/stocks should add stock to watchlist."""
        wl = Watchlist(user_id=test_user.id, name="Tech")
        test_db.add(wl)
        await test_db.commit()

        response = await async_client.post(
            f"/api/watchlists/{wl.id}/stocks",
            json={"symbol": "NVDA"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "NVDA"


# ─────────────────────────────────────────────────────────────────────────────
# TC-008: Portfolio & Transactions
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioEndpoints:
    """Portfolio transactions and analytics."""

    @pytest.mark.asyncio
    async def test_create_transaction(
        self, async_client: AsyncClient, auth_headers: dict, test_user: User
    ):
        """POST /portfolio should create transaction."""
        response = await async_client.post(
            "/api/portfolio",
            json={
                "symbol": "NVDA",
                "type": "BUY",
                "date": "2024-01-15",
                "qty": 10.0,
                "price": 750.00,
                "fee": 50.00,
                "notes": "Initial position",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "NVDA"
        assert data["qty"] == 10.0
        assert data["price"] == 750.00

    @pytest.mark.asyncio
    async def test_get_transactions(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """GET /portfolio should list all transactions."""
        txn = Transaction(
            user_id=test_user.id,
            symbol="AAPL",
            type=TransactionType.BUY,
            date="2024-01-10",
            qty=5.0,
            price=180.00,
            fee=25.00,
        )
        test_db.add(txn)
        await test_db.commit()

        response = await async_client.get(
            "/api/portfolio",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(item["symbol"] == "AAPL" for item in data)

    @pytest.mark.asyncio
    async def test_portfolio_analytics(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        """GET /portfolio/analytics should return analytics."""
        response = await async_client.get(
            "/api/portfolio/analytics",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_value" in data
        assert "total_cost" in data
        assert "unrealized_pl" in data
        assert "holdings" in data


# ─────────────────────────────────────────────────────────────────────────────
# TC-009: Alerts CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertEndpoints:
    """Alert creation, update, delete, toggle."""

    @pytest.mark.asyncio
    async def test_create_alert(
        self, async_client: AsyncClient, auth_headers: dict, test_user: User
    ):
        """POST /alerts should create new alert."""
        response = await async_client.post(
            "/api/alerts",
            json={
                "symbol": "NVDA",
                "alert_type": "PRICE",
                "condition": "ABOVE",
                "value": 900.0,
                "channel": "EMAIL",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "NVDA"
        assert data["alert_type"] == "PRICE"
        assert data["value"] == 900.0

    @pytest.mark.asyncio
    async def test_get_alerts(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """GET /alerts should list all user's alerts."""
        alert = Alert(
            user_id=test_user.id,
            symbol="AAPL",
            alert_type=AlertType.PRICE,
            condition=AlertCondition.BELOW,
            value=170.0,
            channel=AlertChannel.EMAIL,
        )
        test_db.add(alert)
        await test_db.commit()

        response = await async_client.get(
            "/api/alerts",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_update_alert(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """PUT /alerts/{id} should update alert."""
        alert = Alert(
            user_id=test_user.id,
            symbol="NVDA",
            alert_type=AlertType.PRICE,
            condition=AlertCondition.ABOVE,
            value=800.0,
            channel=AlertChannel.EMAIL,
        )
        test_db.add(alert)
        await test_db.commit()

        response = await async_client.put(
            f"/api/alerts/{alert.id}",
            json={"value": 850.0},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["value"] == 850.0

    @pytest.mark.asyncio
    async def test_delete_alert(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """DELETE /alerts/{id} should delete alert."""
        alert = Alert(
            user_id=test_user.id,
            symbol="TSLA",
            alert_type=AlertType.PRICE,
            condition=AlertCondition.ABOVE,
            value=200.0,
            channel=AlertChannel.EMAIL,
        )
        test_db.add(alert)
        await test_db.commit()
        alert_id = alert.id

        response = await async_client.delete(
            f"/api/alerts/{alert_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_toggle_alert_active(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """PATCH /alerts/{id}/toggle should toggle active status."""
        alert = Alert(
            user_id=test_user.id,
            symbol="MSFT",
            alert_type=AlertType.PRICE,
            condition=AlertCondition.ABOVE,
            value=300.0,
            channel=AlertChannel.EMAIL,
            is_active=True,
        )
        test_db.add(alert)
        await test_db.commit()

        response = await async_client.patch(
            f"/api/alerts/{alert.id}/toggle",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False


# ─────────────────────────────────────────────────────────────────────────────
# TC-010: Drawings CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestDrawingEndpoints:
    """Drawing save, get, update, delete."""

    @pytest.mark.asyncio
    async def test_save_drawing(
        self, async_client: AsyncClient, auth_headers: dict, test_user: User
    ):
        """POST /drawings/{symbol} should save new drawing."""
        response = await async_client.post(
            "/api/drawings/NVDA?tf=1D",
            json={
                "tool_type": "line",
                "data_json": '{"x1": 100, "y1": 200, "x2": 300, "y2": 400}',
                "style_json": '{"color": "#FF0000"}',
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "NVDA"
        assert data["tool_type"] == "line"

    @pytest.mark.asyncio
    async def test_get_drawings(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """GET /drawings/{symbol} should list all drawings for symbol."""
        from models.drawing import Drawing

        drawing = Drawing(
            user_id=test_user.id,
            symbol="NVDA",
            timeframe="1D",
            tool_type="line",
            data_json='{"x": 100}',
            style_json='{"color": "#FF0000"}',
        )
        test_db.add(drawing)
        await test_db.commit()

        response = await async_client.get(
            "/api/drawings/NVDA?tf=1D",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0


# ─────────────────────────────────────────────────────────────────────────────
# TC-011: Notes CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestNoteEndpoints:
    """Stock note save, get, update."""

    @pytest.mark.asyncio
    async def test_upsert_note(
        self, async_client: AsyncClient, auth_headers: dict, test_user: User
    ):
        """PUT /notes/{symbol} should create/update note."""
        response = await async_client.put(
            "/api/notes/NVDA",
            json={
                "content": "Strong technical setup, waiting for breakout above 900.",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "NVDA"
        assert "Strong technical" in data["content"]

    @pytest.mark.asyncio
    async def test_get_note(
        self, async_client: AsyncClient, auth_headers: dict,
        test_db: AsyncSession, test_user: User
    ):
        """GET /notes/{symbol} should retrieve note."""
        from models.note import StockNote

        note = StockNote(
            user_id=test_user.id,
            symbol="AAPL",
            content="Good dividend yield.",
        )
        test_db.add(note)
        await test_db.commit()

        response = await async_client.get(
            "/api/notes/AAPL",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert "dividend" in data["content"]


# ─────────────────────────────────────────────────────────────────────────────
# TC-012: Dashboard
# ─────────────────────────────────────────────────────────────────────────────

class TestDashboardEndpoints:
    """Dashboard aggregated data."""

    @pytest.mark.asyncio
    async def test_get_dashboard_unauthenticated(
        self, async_client: AsyncClient
    ):
        """GET /dashboard should work without auth (guest mode)."""
        with patch("services.stock_service.fetch_quote_now") as mock_fetch:
            mock_fetch.return_value = AsyncMock(
                price=4000.0, change=50.0, change_pct=1.25
            )

            response = await async_client.get("/api/dashboard")

            assert response.status_code == 200
            data = response.json()
            assert "indices" in data

    @pytest.mark.asyncio
    async def test_get_dashboard_authenticated(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        """GET /dashboard with auth should include portfolio summary."""
        with patch("services.stock_service.fetch_quote_now") as mock_fetch:
            mock_fetch.return_value = AsyncMock(
                price=4000.0, change=50.0, change_pct=1.25
            )

            response = await async_client.get(
                "/api/dashboard",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert "indices" in data


# ─────────────────────────────────────────────────────────────────────────────
# TC-013: Screener
# ─────────────────────────────────────────────────────────────────────────────

class TestScreenerEndpoints:
    """Stock screener filtering."""

    @pytest.mark.asyncio
    async def test_screener_default_filters(
        self, async_client: AsyncClient, test_db: AsyncSession
    ):
        """GET /screener should filter stocks by default criteria."""
        from models.stock import Stock, MarketType

        stocks = [
            Stock(symbol="NVDA", name="NVIDIA", market=MarketType.US, is_active=True),
            Stock(symbol="PTT.BK", name="PTT", market=MarketType.THAILAND, is_active=True),
        ]
        for stock in stocks:
            test_db.add(stock)
        await test_db.commit()

        response = await async_client.get("/api/screener")

        assert response.status_code == 200
        data = response.json()
        assert "stocks" in data


# ─────────────────────────────────────────────────────────────────────────────
# TC-014: Stock Events & News
# ─────────────────────────────────────────────────────────────────────────────

class TestStockEventsAndNews:
    """Stock events (dividends, earnings) and news."""

    @pytest.mark.asyncio
    async def test_get_stock_news(
        self, async_client: AsyncClient
    ):
        """GET /stocks/{symbol}/news should return news items."""
        with patch("asyncio.to_thread") as mock_thread:
            # Mock feedparser.parse
            mock_feed = AsyncMock()
            mock_feed.entries = [
                {
                    "title": "NVDA Q4 Earnings Beat",
                    "link": "https://example.com/news1",
                    "source": {"title": "Reuters"},
                    "published": "2024-03-01",
                    "summary": "Strong revenue growth...",
                },
            ]
            mock_thread.return_value = mock_feed

            response = await async_client.get(
                "/api/stocks/NVDA/news"
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_stock_events(
        self, async_client: AsyncClient, test_db: AsyncSession
    ):
        """GET /stocks/{symbol}/events should return events."""
        response = await async_client.get(
            "/api/stocks/NVDA/events"
        )

        assert response.status_code == 200
        data = response.json()
        assert "symbol" in data
        assert "events" in data


# ─────────────────────────────────────────────────────────────────────────────
# TC-015: WebSocket Price Subscription
# ─────────────────────────────────────────────────────────────────────────────

class TestWebSocketPrices:
    """WebSocket real-time price subscription."""

    @pytest.mark.asyncio
    async def test_websocket_subscribe_to_symbol(
        self, async_client: AsyncClient
    ):
        """WebSocket should accept subscribe action."""
        # Note: This test is simplified as full WebSocket testing requires
        # additional setup. A full integration test should be in a separate file.
        with patch("main.manager") as mock_manager:
            # Verify that the WebSocket endpoint exists
            response = await async_client.get("/docs")
            assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Integration & Error Scenarios
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorScenarios:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_404_on_nonexistent_endpoint(
        self, async_client: AsyncClient
    ):
        """Request to non-existent endpoint should return 404."""
        response = await async_client.get("/api/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_auth_required_endpoints_reject_unauthenticated(
        self, async_client: AsyncClient
    ):
        """Protected endpoints should reject requests without auth."""
        response = await async_client.get("/api/portfolio")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_json_returns_422(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        """Invalid JSON in request body should return 422."""
        response = await async_client.post(
            "/api/alerts",
            content="invalid json",
            headers=auth_headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_422(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        """POST with missing required field should return 422."""
        response = await async_client.post(
            "/api/alerts",
            json={"symbol": "NVDA"},  # Missing alert_type, condition, value, channel
            headers=auth_headers,
        )
        assert response.status_code == 422
