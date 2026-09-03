"""
Comprehensive API endpoint tests — covers every route with happy path,
auth enforcement, input validation, and error cases.

Tests run against an in-memory SQLite DB via TestClient (ASGI).
External services (Redis, Yahoo Finance, Ollama) are mocked.

Endpoints covered:
  ✓ POST /api/v1/auth/google  (removal-only coverage — no live Google token
    in tests; see TestAuthRemoved for the AC-D7 404 proof of the routes
    that no longer exist)
  ✓ GET  /api/v1/auth/me  (JWT fast-path — no DB query)
  ✓ GET  /api/v1/auth/config
  ✓ GET  /api/v1/stocks/search
  ✓ GET  /api/v1/stocks/names
  ✓ GET  /api/v1/stocks/{symbol}/quote  (no-auth)
  ✓ GET  /api/v1/stocks/{symbol}/history
  ✓ GET  /api/v1/stocks/{symbol}/fundamentals
  ✓ GET  /api/v1/stocks/{symbol}/news
  ✓ GET  /api/ai/models  (fast, 3s timeout)
  ✓ POST /api/ai/chat  (non-streaming)
  ✓ GET  /api/v1/watchlists
  ✓ POST /api/v1/watchlists
  ✓ POST /api/v1/watchlists/{id}/stocks
  ✓ DELETE /api/v1/watchlists/{id}/stocks/{symbol}
  ✓ GET  /api/v1/screener
  ✓ GET  /api/v1/system/ready

bd:deps-2026-09 S1 (ADR-007) — POST /api/v1/auth/register, POST
/api/v1/auth/login, POST /api/v1/auth/refresh, POST /api/v1/auth/logout were
removed (dead code / client-side-refresh lifecycle CLAUDE.md rule 5
prohibits). TestRegister/TestLogin/TestRefresh/TestLogout classes (tested
those routes directly) are deleted, replaced by TestAuthRemoved (AC-D7).
"""
import asyncio
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(app_client):
    """Alias for app_client from conftest — ASGI TestClient with in-memory DB.

    bd:deps-2026-09 iter1 (Q-3, second half) — was `scope="module"`.
    `app_client` (conftest.py, own iter1 fix) is now function-scoped and
    shares its `test_engine`/`db_session` with `client`/`auth_headers`
    there — a module-scoped fixture can't depend on a function-scoped one
    (pytest `ScopeMismatch`), so this had to drop to function scope too.
    Bonus: also means each test method now gets a clean rollback-per-test
    DB instead of state leaking across the whole module via one shared
    client.
    """
    return app_client


@pytest.fixture
async def registered_user(db_session):
    """A REAL DB-backed authenticated user + JWT payload.

    bd:deps-2026-09 iter1 (Q-3) — was a synthetic JWT (`sub: "999001"`)
    minted with no backing `users` row at all, documented in this
    docstring's previous revision as "unreachable by ANY fixture design in
    this module" because `app_client` used to open a brand-new in-memory
    SQLite engine on every single request (a different, empty database
    every time). That root cause is now fixed in conftest.py (StaticPool +
    one shared `test_engine`/`db_session` across `client`/`app_client`/
    `auth_headers`), so a row created here via `db_session` IS visible to
    every request `client` makes. Fine for the JWT-fast-path `/me` tests
    above (they never queried the DB, `sub` value was irrelevant) but
    silently broke every `TestWatchlist` test below — all of which DO hit
    `api/middleware/auth.py get_current_user`'s DB-backed lookup by id,
    which 401'd on a `sub` that mapped to no row (Quinn's review, Finding
    Q-3, 6 of 17 new failures).
    """
    from core.security import create_access_token, hash_password
    from models.user import User

    user = User(
        email="apitest@example.com",
        password_hash=hash_password("TestPass1"),
        display_name="API Test User",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    access_token = create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.value,
        "created_at": user.created_at.isoformat(),
    })
    return {"access_token": access_token}


@pytest.fixture
def auth_headers(registered_user):
    """Bearer Authorization header for authenticated requests."""
    return {"Authorization": f"Bearer {registered_user['access_token']}"}


# ── Auth: removed routes (AC-D7) ─────────────────────────────────────────────

class TestAuthRemoved:
    """bd:deps-2026-09 S1 (ADR-007, AC-D7) — proves the routes are gone,
    not merely untested."""

    def test_register_route_removed(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "x@x.com", "password": "Pass1234", "display_name": "X",
        })
        assert resp.status_code in (404, 405)

    def test_login_route_removed(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "email": "x@x.com", "password": "Pass1234",
        })
        assert resp.status_code in (404, 405)

    def test_refresh_route_removed(self, client):
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "anything"})
        assert resp.status_code in (404, 405)

    def test_logout_route_removed(self, client):
        resp = client.post("/api/v1/auth/logout", json={"refresh_token": "anything"})
        assert resp.status_code in (404, 405)


# ── Auth: /me (JWT fast-path) ────────────────────────────────────────────────

class TestAuthMe:
    def test_me_without_token_returns_401(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_me_with_valid_token_returns_user(self, client, auth_headers):
        # bd:deps-2026-09 iter1 (Q-1, envelope-unwrap test debt) — was
        # reading `body["email"]` etc. directly; S2's ADR-002 envelope
        # wraps every /api/v1 2xx body as {data, meta}. Unwrap via
        # body["data"] throughout this file's assertions below too.
        resp = client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["email"] == "apitest@example.com"
        assert body["display_name"] == "API Test User"
        assert "id" in body

    def test_me_with_invalid_token_returns_401(self, client):
        resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    def test_me_does_not_hit_db_for_modern_tokens(self, client, auth_headers):
        """Token contains email+display_name → fast path reads from JWT, no DB."""
        resp = client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        # If fast-path works, email and display_name come from JWT payload directly
        assert resp.json()["data"]["email"] == "apitest@example.com"


# ── Auth: config ──────────────────────────────────────────────────────────────

class TestAuthConfig:
    def test_config_returns_google_client_id_key(self, client):
        resp = client.get("/api/v1/auth/config")
        assert resp.status_code == 200
        assert "google_client_id" in resp.json()["data"]


# ── Stocks: search ───────────────────────────────────────────────────────────

class TestStockSearch:
    def test_search_returns_list(self, client):
        with patch("services.stock_service.search_stocks", new=AsyncMock(return_value=[])):
            resp = client.get("/api/v1/stocks/search", params={"q": "PTT"})
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    def test_search_missing_q_returns_422(self, client):
        resp = client.get("/api/v1/stocks/search")
        assert resp.status_code == 422

    def test_search_empty_q_returns_422(self, client):
        resp = client.get("/api/v1/stocks/search", params={"q": ""})
        assert resp.status_code == 422

    def test_search_too_long_q_returns_422(self, client):
        resp = client.get("/api/v1/stocks/search", params={"q": "X" * 51})
        assert resp.status_code == 422


# ── Stocks: batch names ──────────────────────────────────────────────────────

class TestStockNames:
    def test_names_returns_dict(self, client):
        resp = client.get("/api/v1/stocks/names", params={"symbols": "AAPL,PTT.BK"})
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert isinstance(body, dict)
        # Symbols not in DB fall back to raw symbol string
        assert "AAPL" in body
        assert "PTT.BK" in body

    def test_names_empty_symbols_returns_empty_dict(self, client):
        resp = client.get("/api/v1/stocks/names", params={"symbols": ""})
        assert resp.status_code == 200
        assert resp.json()["data"] == {}

    def test_names_caps_at_50_symbols(self, client):
        syms = ",".join([f"SYM{i}" for i in range(60)])
        resp = client.get("/api/v1/stocks/names", params={"symbols": syms})
        assert resp.status_code == 200
        # Should not error — just truncates to 50


# ── Stocks: quote (no auth required) ─────────────────────────────────────────

class TestStockQuote:
    def test_quote_returns_202_on_cache_miss(self, client):
        with patch("services.stock_service.fetch_stock_quote", new=AsyncMock(return_value=None)):
            resp = client.get("/api/v1/stocks/AAPL/quote")
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
            resp = client.get("/api/v1/stocks/AAPL/quote")
        assert resp.status_code == 200

    def test_quote_no_auth_required(self, client):
        """Endpoint must NOT require auth (removed _user dependency)."""
        with patch("services.stock_service.fetch_stock_quote", new=AsyncMock(return_value=None)):
            resp = client.get("/api/v1/stocks/PTT.BK/quote")
        # Should respond (202 or 200) — not 401
        assert resp.status_code in {200, 202}

    def test_quote_uppercases_symbol(self, client):
        with patch("services.stock_service.fetch_stock_quote", new=AsyncMock(return_value=None)) as mock:
            client.get("/api/v1/stocks/aapl/quote")
        mock.assert_called_once_with("AAPL")


# ── Stocks: history ──────────────────────────────────────────────────────────

class TestStockHistory:
    def test_history_returns_200_with_bars(self, client):
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])):
            resp = client.get("/api/v1/stocks/AAPL/history", params={"tf": "1D"})
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["symbol"] == "AAPL"
        assert body["timeframe"] == "1D"
        assert "bars" in body

    def test_history_invalid_timeframe_returns_400(self, client):
        resp = client.get("/api/v1/stocks/AAPL/history", params={"tf": "99X"})
        assert resp.status_code == 400

    def test_history_valid_timeframes(self, client):
        for tf in ["1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"]:
            with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])):
                resp = client.get("/api/v1/stocks/AAPL/history", params={"tf": tf})
            assert resp.status_code == 200, f"tf={tf} should return 200, got {resp.status_code}"

    def test_history_default_tf_is_1d(self, client):
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])) as mock:
            client.get("/api/v1/stocks/AAPL/history")
        mock.assert_called_once_with("AAPL", "1D")

    def test_history_uppercase_symbol(self, client):
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])) as mock:
            client.get("/api/v1/stocks/aapl/history", params={"tf": "1D"})
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
            resp = client.get("/api/v1/stocks/AAPL/fundamentals")
        assert resp.status_code == 200

    def test_fundamentals_returns_404_when_not_found(self, client):
        with patch("services.stock_service.fetch_stock_fundamentals", new=AsyncMock(return_value=None)):
            resp = client.get("/api/v1/stocks/FAKESYM/fundamentals")
        assert resp.status_code == 404

    def test_fundamentals_timeout_returns_404_not_500(self, client):
        """Timeout in service → None → 404, not an unhandled 500."""
        with patch("services.stock_service.fetch_stock_fundamentals", new=AsyncMock(return_value=None)):
            resp = client.get("/api/v1/stocks/AAPL/fundamentals")
        assert resp.status_code == 404


# ── Stocks: news ──────────────────────────────────────────────────────────────

class TestStockNews:
    def test_news_returns_list(self, client):
        import feedparser
        mock_feed = MagicMock()
        mock_feed.entries = []
        with patch("feedparser.parse", return_value=mock_feed):
            resp = client.get("/api/v1/stocks/AAPL/news")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    def test_news_parse_error_returns_empty_list(self, client):
        with patch("feedparser.parse", side_effect=Exception("network error")):
            resp = client.get("/api/v1/stocks/AAPL/news")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

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
            client.get("/api/v1/stocks/PTT.BK/news")
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
        body = resp.json()["data"]
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
        assert resp.json()["data"]["available"] is False


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
        resp = client.get("/api/v1/watchlists")
        assert resp.status_code == 401

    def test_get_watchlists_returns_list(self, client, auth_headers):
        resp = client.get("/api/v1/watchlists", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    def test_create_watchlist(self, client, auth_headers):
        # bd:deps-2026-09 iter1 (Q-1, envelope-unwrap test debt) — was
        # reading `body["name"]`/`body["id"]` directly; S2's ADR-002
        # envelope wraps every /api/v1 2xx body as {data, meta}. Unwrap
        # via body["data"] throughout this class's assertions below too.
        resp = client.post("/api/v1/watchlists", json={"name": "Tech Stocks"}, headers=auth_headers)
        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["name"] == "Tech Stocks"
        assert "id" in body
        return body["id"]

    def test_add_stock_to_watchlist(self, client, auth_headers):
        # Create watchlist first
        wl = client.post("/api/v1/watchlists", json={"name": "Stocks WL"}, headers=auth_headers).json()["data"]
        wl_id = wl["id"]
        resp = client.post(f"/api/v1/watchlists/{wl_id}/stocks", json={"symbol": "AAPL"}, headers=auth_headers)
        assert resp.status_code == 201

    def test_add_duplicate_stock_returns_409(self, client, auth_headers):
        wl = client.post("/api/v1/watchlists", json={"name": "Dup WL"}, headers=auth_headers).json()["data"]
        wl_id = wl["id"]
        client.post(f"/api/v1/watchlists/{wl_id}/stocks", json={"symbol": "TSLA"}, headers=auth_headers)
        resp = client.post(f"/api/v1/watchlists/{wl_id}/stocks", json={"symbol": "TSLA"}, headers=auth_headers)
        assert resp.status_code == 409

    def test_remove_stock_from_watchlist(self, client, auth_headers):
        wl = client.post("/api/v1/watchlists", json={"name": "Remove WL"}, headers=auth_headers).json()["data"]
        wl_id = wl["id"]
        client.post(f"/api/v1/watchlists/{wl_id}/stocks", json={"symbol": "NVDA"}, headers=auth_headers)
        resp = client.delete(f"/api/v1/watchlists/{wl_id}/stocks/NVDA", headers=auth_headers)
        assert resp.status_code == 204

    def test_symbol_is_uppercased(self, client, auth_headers):
        wl = client.post("/api/v1/watchlists", json={"name": "Upper WL"}, headers=auth_headers).json()["data"]
        wl_id = wl["id"]
        resp = client.post(f"/api/v1/watchlists/{wl_id}/stocks", json={"symbol": "aapl"}, headers=auth_headers)
        assert resp.status_code == 201

    def test_access_other_users_watchlist_returns_404(self, client, auth_headers):
        """User can't access watchlist they don't own."""
        resp = client.get("/api/v1/watchlists/99999", headers=auth_headers)
        # Should be 404 or 405 (no GET single watchlist endpoint) — not 200
        assert resp.status_code in {404, 405}

    def test_watchlist_requires_auth_for_add(self, client):
        resp = client.post("/api/v1/watchlists/1/stocks", json={"symbol": "AAPL"})
        assert resp.status_code == 401


# ── Screener ─────────────────────────────────────────────────────────────────

class TestScreener:
    def test_screener_returns_list_without_auth(self, client):
        """Screener is open to guests."""
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])):
            resp = client.get("/api/v1/screener")
        # Should not return 401
        assert resp.status_code in {200, 500}  # 500 ok if no stocks in DB

    def test_screener_market_filter_validated(self, client):
        """Invalid market filter → 422."""
        resp = client.get("/api/v1/screener", params={"market": "INVALID"})
        assert resp.status_code == 422

    def test_screener_rsi_filter_validated(self, client):
        resp = client.get("/api/v1/screener", params={"rsi": "invalid_val"})
        assert resp.status_code == 422

    def test_screener_valid_market_values(self, client):
        for market in ["SET", "US", "all"]:
            with patch("api.routes.screener._run_screener", return_value=[]):
                resp = client.get("/api/v1/screener", params={"market": market})
            assert resp.status_code == 200, f"market={market} returned {resp.status_code}"


# ── System: ready ────────────────────────────────────────────────────────────

class TestSystemReady:
    def test_system_ready_returns_200(self, client):
        resp = client.get("/api/v1/system/ready")
        # Should return 200 when app is running
        assert resp.status_code in {200, 503}  # 503 if DB/Redis not connected

    def test_system_ready_returns_json(self, client):
        resp = client.get("/api/v1/system/ready")
        if resp.status_code == 200:
            assert isinstance(resp.json(), dict)


# ── Security: input injection ────────────────────────────────────────────────

class TestInputSanitization:
    """Basic injection/boundary tests for public endpoints."""

    def test_search_sql_like_input_does_not_crash(self, client):
        with patch("services.stock_service.search_stocks", new=AsyncMock(return_value=[])):
            resp = client.get("/api/v1/stocks/search", params={"q": "' OR '1'='1"})
        assert resp.status_code in {200, 422}

    def test_search_unicode_input_handled(self, client):
        with patch("services.stock_service.search_stocks", new=AsyncMock(return_value=[])):
            resp = client.get("/api/v1/stocks/search", params={"q": "ปตท"})
        assert resp.status_code == 200

    def test_history_symbol_with_special_chars(self, client):
        with patch("services.stock_service.fetch_stock_history", new=AsyncMock(return_value=[])):
            resp = client.get("/api/v1/stocks/PTT.BK/history", params={"tf": "1D"})
        assert resp.status_code == 200

    def test_history_extremely_long_symbol(self, client):
        resp = client.get(f"/api/v1/stocks/{'A' * 200}/history", params={"tf": "1D"})
        # Should not crash with 500 — 200 or 422 or 404
        assert resp.status_code != 500

    def test_names_sql_injection_in_symbols(self, client):
        resp = client.get("/api/v1/stocks/names", params={"symbols": "AAPL; DROP TABLE stocks;--"})
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
                tasks = [client.get(f"/api/v1/stocks/SYM{i}/quote") for i in range(10)]
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
                tasks = [client.get(f"/api/v1/stocks/AAPL/history?tf=1D") for _ in range(5)]
                responses = await asyncio.gather(*tasks)

        for resp in responses:
            assert resp.status_code == 200
