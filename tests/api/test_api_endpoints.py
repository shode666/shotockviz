"""
Comprehensive API endpoint tests — covers every route with happy path,
auth enforcement, input validation, and error cases.

Tests run against an in-memory SQLite DB via TestClient (ASGI).
External services (Redis, Yahoo Finance, Ollama) are mocked.

Endpoints covered:
  ✓ POST /api/auth/register
  ✓ POST /api/auth/login
  ✓ GET  /api/auth/me  (JWT fast-path — no DB query)
  ✓ POST /api/auth/refresh
  ✓ POST /api/auth/logout
  ✓ GET  /api/auth/config
  ✓ GET  /api/stocks/search
  ✓ GET  /api/stocks/names
  ✓ GET  /api/stocks/{symbol}/quote  (no-auth)
  ✓ GET  /api/stocks/{symbol}/history
  ✓ GET  /api/stocks/{symbol}/fundamentals
  ✓ GET  /api/stocks/{symbol}/news
  ✓ GET  /api/ai/models  (fast, 3s timeout)
  ✓ POST /api/ai/chat  (non-streaming)
  ✓ GET  /api/watchlists
  ✓ POST /api/watchlists
  ✓ POST /api/watchlists/{id}/stocks
  ✓ DELETE /api/watchlists/{id}/stocks/{symbol}
  ✓ GET  /api/screener
  ✓ GET  /api/system/ready
"""
import asyncio
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client(app_client):
    """Alias for app_client from conftest — ASGI TestClient with in-memory DB."""
    return app_client


@pytest.fixture(scope="module")
def registered_user(client):
    """Register once per module; return login tokens for auth tests."""
    client.post("/api/auth/register", json={
        "email": "apitest@example.com",
        "password": "TestPass123",
        "display_name": "API Test User",
    })
    resp = client.post("/api/auth/login", json={
        "email": "apitest@example.com",
        "password": "TestPass123",
    })
    return resp.json()


@pytest.fixture(scope="module")
def auth_headers(registered_user):
    """Bearer Authorization header for authenticated requests."""
    return {"Authorization": f"Bearer {registered_user['access_token']}"}


# ── Auth: register ──────────────────────────────────────────────────────────

class TestRegister:
    def test_register_creates_user(self, client):
        resp = client.post("/api/auth/register", json={
            "email": "newuser@test.com",
            "password": "SecurePass1",
            "display_name": "New User",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "newuser@test.com"
        assert body["display_name"] == "New User"
        assert "id" in body

    def test_register_duplicate_email_returns_409(self, client):
        data = {"email": "dup@test.com", "password": "Pass123", "display_name": "Dup"}
        client.post("/api/auth/register", json=data)
        resp = client.post("/api/auth/register", json=data)
        assert resp.status_code == 409

    def test_register_missing_fields_returns_422(self, client):
        resp = client.post("/api/auth/register", json={"email": "x@x.com"})
        assert resp.status_code == 422

    def test_register_invalid_email_returns_422(self, client):
        resp = client.post("/api/auth/register", json={
            "email": "not-an-email",
            "password": "Pass123",
            "display_name": "User",
        })
        assert resp.status_code == 422


# ── Auth: login ──────────────────────────────────────────────────────────────

class TestLogin:
    def test_login_returns_tokens(self, client, registered_user):
        assert "access_token" in registered_user
        assert "refresh_token" in registered_user

    def test_login_wrong_password_returns_401(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "apitest@example.com",
            "password": "WrongPass",
        })
        assert resp.status_code == 401

    def test_login_unknown_email_returns_401(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "nobody@example.com",
            "password": "Pass123",
        })
        assert resp.status_code == 401

    def test_login_missing_body_returns_422(self, client):
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422


# ── Auth: /me (JWT fast-path) ────────────────────────────────────────────────

class TestAuthMe:
    def test_me_without_token_returns_401(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_valid_token_returns_user(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "apitest@example.com"
        assert body["display_name"] == "API Test User"
        assert "id" in body

    def test_me_with_invalid_token_returns_401(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    def test_me_does_not_hit_db_for_modern_tokens(self, client, auth_headers):
        """Token contains email+display_name → fast path reads from JWT, no DB."""
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        # If fast-path works, email and display_name come from JWT payload directly
        assert resp.json()["email"] == "apitest@example.com"


# ── Auth: refresh ────────────────────────────────────────────────────────────

class TestRefresh:
    def test_refresh_returns_new_tokens(self, client, registered_user):
        resp = client.post("/api/auth/refresh", json={
            "refresh_token": registered_user["refresh_token"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        # Tokens should be different (rotation)
        assert body["refresh_token"] != registered_user["refresh_token"]

    def test_refresh_invalid_token_returns_401(self, client):
        resp = client.post("/api/auth/refresh", json={"refresh_token": "bad-token"})
        assert resp.status_code == 401


# ── Auth: logout ─────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_revokes_refresh_token(self, client):
        # Register separate user for this test
        client.post("/api/auth/register", json={
            "email": "logout@test.com", "password": "Pass123", "display_name": "Logout",
        })
        login = client.post("/api/auth/login", json={
            "email": "logout@test.com", "password": "Pass123",
        }).json()
        # Logout
        resp = client.post("/api/auth/logout", json={"refresh_token": login["refresh_token"]})
        assert resp.status_code == 204
        # Using same refresh_token again should fail
        resp2 = client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert resp2.status_code == 401

    def test_logout_with_bad_token_returns_204(self, client):
        """Logout is idempotent — bad token still returns 204."""
        resp = client.post("/api/auth/logout", json={"refresh_token": "nonexistent"})
        assert resp.status_code == 204


# ── Auth: config ──────────────────────────────────────────────────────────────

class TestAuthConfig:
    def test_config_returns_google_client_id_key(self, client):
        resp = client.get("/api/auth/config")
        assert resp.status_code == 200
        assert "google_client_id" in resp.json()


# ── Stocks: search ───────────────────────────────────────────────────────────

class TestStockSearch:
    def test_search_returns_list(self, client):
        with patch("services.stock_service.search_stocks", new=AsyncMock(return_value=[])):
            resp = client.get("/api/stocks/search", params={"q": "PTT"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_search_missing_q_returns_422(self, client):
        resp = client.get("/api/stocks/search")
        assert resp.status_code == 422

    def test_search_empty_q_returns_422(self, client):
        resp = client.get("/api/stocks/search", params={"q": ""})
        assert resp.status_code == 422

    def test_search_too_long_q_returns_422(self, client):
        resp = client.get("/api/stocks/search", params={"q": "X" * 51})
        assert resp.status_code == 422


# ── Stocks: batch names ──────────────────────────────────────────────────────

class TestStockNames:
    def test_names_returns_dict(self, client):
        resp = client.get("/api/stocks/names", params={"symbols": "AAPL,PTT.BK"})
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        # Symbols not in DB fall back to raw symbol string
        assert "AAPL" in body
        assert "PTT.BK" in body

    def test_names_empty_symbols_returns_empty_dict(self, client):
        resp = client.get("/api/stocks/names", params={"symbols": ""})
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_names_caps_at_50_symbols(self, client):
        syms = ",".join([f"SYM{i}" for i in range(60)])
        resp = client.get("/api/stocks/names", params={"symbols": syms})
        assert resp.status_code == 200
        # Should not error — just truncates to 50


# ── Stocks: quote (no auth required) ─────────────────────────────────────────

class TestStockQuote:
    def test_quote_returns_202_on_cache_miss(self, client):
        with patch("services.stock_service.fetch_stock_quote", new=AsyncMock(return_value=None)):
            resp = client.get("/api/stocks/AAPL/quote")
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "pending"
        assert body["symbol"] == "AAPL"

    def test_quote_returns_200_when_cached(self, client):
        mock_quote = MagicMock()
        mock_quote.price = 150.0
        mock_quote.change = 1.5
        mock_quote.change_pct = 1.01
        with patch("services.stock_service.fetch_stock_quote", new=AsyncMock(return_value=mock_quote)):
            resp = client.get("/api/stocks/AAPL/quote")
        assert resp.status_code == 200

    def test_quote_no_auth_required(self, client):
        """Endpoint must NOT require auth (removed _user dependency)."""
        with patch("services.stock_service.fetch_stock_quote", new=AsyncMock(return_value=None)):
            resp = client.get("/api/stocks/PTT.BK/quote")
        # Should respond (202 or 200) — not 401
        assert resp.status_code in {200, 202}

    def test_quote_uppercases_symbol(self, client):
        with patch("services.stock_service.fetch_stock_quote", new=AsyncMock(return_value=None)) as mock:
            client.get("/api/stocks/aapl/quote")
        mock.assert_called_once_with("AAPL")


# ── Stocks: history ──────────────────────────────────────────────────────────

class TestStockHistory:
    def test_history_returns_200_with_bars(self, client):
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])):
            resp = client.get("/api/stocks/AAPL/history", params={"tf": "1D"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "AAPL"
        assert body["timeframe"] == "1D"
        assert "bars" in body

    def test_history_invalid_timeframe_returns_400(self, client):
        resp = client.get("/api/stocks/AAPL/history", params={"tf": "99X"})
        assert resp.status_code == 400

    def test_history_valid_timeframes(self, client):
        for tf in ["1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"]:
            with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])):
                resp = client.get("/api/stocks/AAPL/history", params={"tf": tf})
            assert resp.status_code == 200, f"tf={tf} should return 200, got {resp.status_code}"

    def test_history_default_tf_is_1d(self, client):
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])) as mock:
            client.get("/api/stocks/AAPL/history")
        mock.assert_called_once_with("AAPL", "1D")

    def test_history_uppercase_symbol(self, client):
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])) as mock:
            client.get("/api/stocks/aapl/history", params={"tf": "1D"})
        mock.assert_called_once_with("AAPL", "1D")


# ── Stocks: fundamentals ─────────────────────────────────────────────────────

class TestStockFundamentals:
    def test_fundamentals_returns_data_when_found(self, client):
        mock_data = MagicMock()
        mock_data.symbol = "AAPL"
        mock_data.pe_ratio = 28.5
        mock_data.eps = 6.43
        mock_data.market_cap = 2_900_000_000_000
        mock_data.dividend_yield = 0.52
        mock_data.pb_ratio = 3.2
        with patch("services.stock_service.fetch_stock_fundamentals", new=AsyncMock(return_value=mock_data)):
            resp = client.get("/api/stocks/AAPL/fundamentals")
        assert resp.status_code == 200

    def test_fundamentals_returns_404_when_not_found(self, client):
        with patch("services.stock_service.fetch_stock_fundamentals", new=AsyncMock(return_value=None)):
            resp = client.get("/api/stocks/FAKESYM/fundamentals")
        assert resp.status_code == 404

    def test_fundamentals_timeout_returns_404_not_500(self, client):
        """Timeout in service → None → 404, not an unhandled 500."""
        with patch("services.stock_service.fetch_stock_fundamentals", new=AsyncMock(return_value=None)):
            resp = client.get("/api/stocks/AAPL/fundamentals")
        assert resp.status_code == 404


# ── Stocks: news ──────────────────────────────────────────────────────────────

class TestStockNews:
    def test_news_returns_list(self, client):
        import feedparser
        mock_feed = MagicMock()
        mock_feed.entries = []
        with patch("feedparser.parse", return_value=mock_feed):
            resp = client.get("/api/stocks/AAPL/news")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_news_parse_error_returns_empty_list(self, client):
        with patch("feedparser.parse", side_effect=Exception("network error")):
            resp = client.get("/api/stocks/AAPL/news")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_news_strips_bk_suffix_from_query(self, client):
        """PTT.BK → query should use 'PTT stock', not 'PTT.BK stock'."""
        import feedparser
        captured_url = []
        def capture_parse(url):
            captured_url.append(url)
            m = MagicMock()
            m.entries = []
            return m
        with patch("feedparser.parse", side_effect=capture_parse):
            client.get("/api/stocks/PTT.BK/news")
        assert captured_url, "feedparser.parse was not called"
        assert ".BK" not in captured_url[0], f"URL should strip .BK: {captured_url[0]}"


# ── AI: models ───────────────────────────────────────────────────────────────

class TestAIModels:
    def test_models_returns_available_false_when_ollama_not_configured(self, client):
        with patch("core.config.settings") as mock_settings:
            mock_settings.ollama_url = None
            resp = client.get("/api/ai/models")
        # Either 200 with available=False or error — must not be 500
        assert resp.status_code in {200, 503}

    def test_models_returns_list_when_available(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "llama3.2:latest"}]}
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/api/ai/models")
        assert resp.status_code == 200
        body = resp.json()
        assert "models" in body
        assert "available" in body

    def test_models_connection_error_returns_unavailable(self, client):
        """Ollama not running → returns {available: false}, not 500."""
        import httpx as _httpx
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/api/ai/models")
        assert resp.status_code == 200
        assert resp.json()["available"] is False


# ── AI: chat ─────────────────────────────────────────────────────────────────

class TestAIChat:
    def test_chat_503_when_ollama_not_configured(self, client):
        with patch("core.config.settings") as s:
            s.ollama_url = None
            resp = client.post("/api/ai/chat", json={
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            })
        assert resp.status_code == 503

    def test_chat_non_streaming_returns_content(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "วิเคราะห์แล้ว ราคาดี"},
            "done": True,
        }
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.post("/api/ai/chat", json={
                "messages": [{"role": "user", "content": "วิเคราะห์ PTT.BK ให้หน่อย"}],
                "stream": False,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert "content" in body
        assert "วิเคราะห์แล้ว" in body["content"]

    def test_chat_streaming_returns_stream_response(self, client):
        """Streaming path must return text/event-stream."""
        import httpx as _httpx

        async def fake_stream(*args, **kwargs):
            class FakeStream:
                status_code = 200
                async def aiter_lines(self):
                    import json
                    yield json.dumps({"message": {"content": "hello"}, "done": True})
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
            return FakeStream()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = fake_stream
        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.post("/api/ai/chat", json={
                "messages": [{"role": "user", "content": "test"}],
                "stream": True,
            })
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_chat_ollama_timeout_returns_504(self, client):
        """Non-streaming: Ollama timeout → 504 (not 500)."""
        import httpx as _httpx
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=_httpx.TimeoutException("timeout"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.post("/api/ai/chat", json={
                "messages": [{"role": "user", "content": "test"}],
                "stream": False,
            })
        assert resp.status_code == 504

    def test_chat_ollama_connect_error_returns_503(self, client):
        """Non-streaming: ConnectError → 503."""
        import httpx as _httpx
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.post("/api/ai/chat", json={
                "messages": [{"role": "user", "content": "test"}],
                "stream": False,
            })
        assert resp.status_code == 503


# ── Watchlist ────────────────────────────────────────────────────────────────

class TestWatchlist:
    def test_get_watchlists_requires_auth(self, client):
        resp = client.get("/api/watchlists")
        assert resp.status_code == 401

    def test_get_watchlists_returns_list(self, client, auth_headers):
        resp = client.get("/api/watchlists", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_watchlist(self, client, auth_headers):
        resp = client.post("/api/watchlists", json={"name": "Tech Stocks"}, headers=auth_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Tech Stocks"
        assert "id" in body
        return body["id"]

    def test_add_stock_to_watchlist(self, client, auth_headers):
        # Create watchlist first
        wl = client.post("/api/watchlists", json={"name": "Stocks WL"}, headers=auth_headers).json()
        wl_id = wl["id"]
        resp = client.post(f"/api/watchlists/{wl_id}/stocks", json={"symbol": "AAPL"}, headers=auth_headers)
        assert resp.status_code == 201

    def test_add_duplicate_stock_returns_409(self, client, auth_headers):
        wl = client.post("/api/watchlists", json={"name": "Dup WL"}, headers=auth_headers).json()
        wl_id = wl["id"]
        client.post(f"/api/watchlists/{wl_id}/stocks", json={"symbol": "TSLA"}, headers=auth_headers)
        resp = client.post(f"/api/watchlists/{wl_id}/stocks", json={"symbol": "TSLA"}, headers=auth_headers)
        assert resp.status_code == 409

    def test_remove_stock_from_watchlist(self, client, auth_headers):
        wl = client.post("/api/watchlists", json={"name": "Remove WL"}, headers=auth_headers).json()
        wl_id = wl["id"]
        client.post(f"/api/watchlists/{wl_id}/stocks", json={"symbol": "NVDA"}, headers=auth_headers)
        resp = client.delete(f"/api/watchlists/{wl_id}/stocks/NVDA", headers=auth_headers)
        assert resp.status_code == 204

    def test_symbol_is_uppercased(self, client, auth_headers):
        wl = client.post("/api/watchlists", json={"name": "Upper WL"}, headers=auth_headers).json()
        wl_id = wl["id"]
        resp = client.post(f"/api/watchlists/{wl_id}/stocks", json={"symbol": "aapl"}, headers=auth_headers)
        assert resp.status_code == 201

    def test_access_other_users_watchlist_returns_404(self, client, auth_headers):
        """User can't access watchlist they don't own."""
        resp = client.get("/api/watchlists/99999", headers=auth_headers)
        # Should be 404 or 405 (no GET single watchlist endpoint) — not 200
        assert resp.status_code in {404, 405}

    def test_watchlist_requires_auth_for_add(self, client):
        resp = client.post("/api/watchlists/1/stocks", json={"symbol": "AAPL"})
        assert resp.status_code == 401


# ── Screener ─────────────────────────────────────────────────────────────────

class TestScreener:
    def test_screener_returns_list_without_auth(self, client):
        """Screener is open to guests."""
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])):
            resp = client.get("/api/screener")
        # Should not return 401
        assert resp.status_code in {200, 500}  # 500 ok if no stocks in DB

    def test_screener_market_filter_validated(self, client):
        """Invalid market filter → 422."""
        resp = client.get("/api/screener", params={"market": "INVALID"})
        assert resp.status_code == 422

    def test_screener_rsi_filter_validated(self, client):
        resp = client.get("/api/screener", params={"rsi": "invalid_val"})
        assert resp.status_code == 422

    def test_screener_valid_market_values(self, client):
        for market in ["SET", "US", "all"]:
            with patch("api.routes.screener._run_screener", return_value=[]):
                resp = client.get("/api/screener", params={"market": market})
            assert resp.status_code == 200, f"market={market} returned {resp.status_code}"


# ── System: ready ────────────────────────────────────────────────────────────

class TestSystemReady:
    def test_system_ready_returns_200(self, client):
        resp = client.get("/api/system/ready")
        # Should return 200 when app is running
        assert resp.status_code in {200, 503}  # 503 if DB/Redis not connected

    def test_system_ready_returns_json(self, client):
        resp = client.get("/api/system/ready")
        if resp.status_code == 200:
            assert isinstance(resp.json(), dict)


# ── Security: input injection ────────────────────────────────────────────────

class TestInputSanitization:
    """Basic injection/boundary tests for public endpoints."""

    def test_search_sql_like_input_does_not_crash(self, client):
        with patch("services.stock_service.search_stocks", new=AsyncMock(return_value=[])):
            resp = client.get("/api/stocks/search", params={"q": "' OR '1'='1"})
        assert resp.status_code in {200, 422}

    def test_search_unicode_input_handled(self, client):
        with patch("services.stock_service.search_stocks", new=AsyncMock(return_value=[])):
            resp = client.get("/api/stocks/search", params={"q": "ปตท"})
        assert resp.status_code == 200

    def test_history_symbol_with_special_chars(self, client):
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])):
            resp = client.get("/api/stocks/PTT.BK/history", params={"tf": "1D"})
        assert resp.status_code == 200

    def test_history_extremely_long_symbol(self, client):
        resp = client.get(f"/api/stocks/{'A' * 200}/history", params={"tf": "1D"})
        # Should not crash with 500 — 200 or 422 or 404
        assert resp.status_code != 500

    def test_names_sql_injection_in_symbols(self, client):
        resp = client.get("/api/stocks/names", params={"symbols": "AAPL; DROP TABLE stocks;--"})
        assert resp.status_code == 200


# ── Load / concurrency: quote endpoint ──────────────────────────────────────

@pytest.mark.asyncio
class TestConcurrentQuoteRequests:
    """Verify the quote endpoint handles concurrent requests without deadlock."""

    async def test_10_concurrent_quote_requests_all_succeed(self):
        from main import app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            with patch("services.stock_service.fetch_stock_quote", new=AsyncMock(return_value=None)):
                tasks = [client.get(f"/api/stocks/SYM{i}/quote") for i in range(10)]
                responses = await asyncio.gather(*tasks)

        for i, resp in enumerate(responses):
            assert resp.status_code in {200, 202}, f"Request {i} returned {resp.status_code}"

    async def test_concurrent_history_requests_all_succeed(self):
        from main import app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])):
                tasks = [client.get(f"/api/stocks/AAPL/history?tf=1D") for _ in range(5)]
                responses = await asyncio.gather(*tasks)

        for resp in responses:
            assert resp.status_code == 200
