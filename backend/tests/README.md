# ShotockViz Backend API Tests

Comprehensive pytest-based E2E test suite for all ShotockViz backend endpoints.

## Test Files

### `conftest.py`
Shared pytest fixtures and configuration:
- **Database fixtures**: `test_db` (in-memory SQLite), `override_db` (dependency override)
- **User fixtures**: `test_user`, `valid_token`, `auth_headers`
- **HTTP client**: `async_client` (AsyncClient for testing)
- **Mocks**: `mock_redis`, `mock_stock_service`
- **Sample data**: Quote, history, fundamentals, transactions, alerts, etc.

### `test_api_e2e.py`
End-to-end API tests organized by endpoint/feature:

#### TC-001: System Health & Readiness
- `test_health_check_success` — Verify health endpoint returns db/redis/celery status
- `test_cache_ready_check` — Verify cache readiness probe
- `test_celery_stats` — Verify Celery task stats

#### TC-002: Stock Quotes
- `test_get_single_quote_us_stock` — US stock quote (NVDA)
- `test_get_single_quote_thai_stock` — Thai stock quote (PTT.BK)
- `test_get_quote_invalid_symbol_returns_404` — Invalid symbol returns 404, not 500
- `test_get_batch_quotes` — Batch quotes endpoint
- `test_batch_quotes_all_have_data` — No null values in batch response

#### TC-003: Stock History & Bars
- `test_get_history_daily_nvda` — Daily bars with ascending time
- `test_history_all_timeframes` — All timeframes (1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M)
- `test_history_invalid_timeframe_returns_400` — Invalid timeframe handling
- `test_history_no_nan_values` — No NaN/null in OHLCV data

#### TC-004: Stock Fundamentals
- `test_fundamentals_nvda_has_pe_and_marketcap` — P/E and market cap present
- `test_fundamentals_returns_shell_on_unavailable` — Graceful null when data unavailable

#### TC-005: Stock Search
- `test_search_by_symbol_prefix` — Search "NV" returns NVDA
- `test_search_empty_query_handled_gracefully` — Empty search handling
- `test_search_returns_empty_list_not_404` — Non-existent symbol returns 200 + empty list
- `test_search_by_thai_name` — Thai name search

#### TC-006: Auth Endpoints
- `test_register_new_user` — Register creates user (201)
- `test_register_duplicate_email_returns_409` — Duplicate email returns 409
- `test_login_valid_credentials` — Login returns access + refresh tokens
- `test_login_invalid_credentials_returns_401` — Wrong password returns 401
- `test_get_me_with_valid_token` — GET /me with valid token
- `test_get_me_without_token_returns_401` — GET /me without auth returns 401
- `test_auth_config_returns_google_client_id` — Auth config endpoint

#### TC-007: Watchlist CRUD
- `test_create_watchlist` — Create watchlist (201)
- `test_get_watchlists` — List all user watchlists
- `test_update_watchlist_name` — Update watchlist name
- `test_delete_watchlist` — Delete watchlist (204)
- `test_add_stock_to_watchlist` — Add stock to watchlist

#### TC-008: Portfolio & Transactions
- `test_create_transaction` — Create transaction (buy/sell)
- `test_get_transactions` — List all transactions
- `test_portfolio_analytics` — Portfolio P&L and analytics

#### TC-009: Alerts CRUD
- `test_create_alert` — Create price/indicator alert
- `test_get_alerts` — List all alerts
- `test_update_alert` — Update alert condition/value
- `test_delete_alert` — Delete alert
- `test_toggle_alert_active` — Toggle alert active/inactive

#### TC-010: Drawings CRUD
- `test_save_drawing` — Save chart drawing (line, trendline, etc.)
- `test_get_drawings` — Get all drawings for symbol

#### TC-011: Notes CRUD
- `test_upsert_note` — Create/update investment thesis
- `test_get_note` — Retrieve note for symbol

#### TC-012: Dashboard
- `test_get_dashboard_unauthenticated` — Dashboard without auth (guest mode)
- `test_get_dashboard_authenticated` — Dashboard with auth (includes portfolio)

#### TC-013: Screener
- `test_screener_default_filters` — Stock filtering by technical indicators

#### TC-014: Stock Events & News
- `test_get_stock_news` — Fetch news via Google News RSS
- `test_get_stock_events` — Fetch corporate events (XD, XR, earnings)

#### TC-015: WebSocket
- `test_websocket_subscribe_to_symbol` — WebSocket real-time price subscription

#### Error Scenarios
- `test_404_on_nonexistent_endpoint` — Non-existent endpoint returns 404
- `test_auth_required_endpoints_reject_unauthenticated` — Protected endpoints need auth
- `test_invalid_json_returns_422` — Invalid JSON returns 422
- `test_missing_required_field_returns_422` — Missing required field returns 422

## Running Tests

### Run all tests
```bash
docker-compose -f docker-compose.dev.yml exec backend pytest tests/test_api_e2e.py -v
```

### Run specific test class
```bash
docker-compose -f docker-compose.dev.yml exec backend pytest tests/test_api_e2e.py::TestStockQuotes -v
```

### Run specific test
```bash
docker-compose -f docker-compose.dev.yml exec backend pytest tests/test_api_e2e.py::TestStockQuotes::test_get_single_quote_us_stock -v
```

### Run with coverage report
```bash
docker-compose -f docker-compose.dev.yml exec backend pytest tests/test_api_e2e.py --cov=api --cov=services --cov-report=html
```

### Run with detailed output
```bash
docker-compose -f docker-compose.dev.yml exec backend pytest tests/test_api_e2e.py -vv -s
```

## Test Strategy

### Mocking
- **Database**: In-memory SQLite for fast, isolated tests
- **Redis**: AsyncMock for cache operations
- **Stock Service**: Mock `fetch_quote_now()`, `fetch_stock_history()`, etc.
- **External APIs**: Mocked (Yahoo Finance, Google News)

### Authentication
- Test user created in `test_user` fixture
- JWT token generated in `valid_token` fixture
- Auth headers provided in `auth_headers` fixture
- Tests verify 401 on missing/invalid tokens

### Data Validation
- All responses validated against Pydantic schemas
- OHLCV bars checked for NaN/null values
- Time series data verified for ascending order
- Quote responses verified for all required fields

### Error Cases
- Invalid symbols return 404 (not 500)
- Missing auth returns 401
- Invalid JSON returns 422
- Duplicate resources return 409
- Non-existent resources return 404

## Test Coverage

The test suite covers:
- ✅ 40+ API endpoints
- ✅ Authentication & authorization
- ✅ CRUD operations (watchlist, portfolio, alerts, drawings, notes)
- ✅ Data aggregation (dashboard, screener, analytics)
- ✅ Real-time (WebSocket price subscription)
- ✅ Error handling & edge cases
- ✅ Thai & US market data

## Extending Tests

To add new tests:

1. Create a new test class in `test_api_e2e.py`:
```python
class TestNewFeature:
    """Description of feature."""

    @pytest.mark.asyncio
    async def test_new_endpoint(self, async_client: AsyncClient):
        """Test description."""
        response = await async_client.get("/api/new-endpoint")
        assert response.status_code == 200
```

2. Use fixtures from `conftest.py`:
```python
async def test_with_auth(
    self, async_client: AsyncClient, auth_headers: dict, test_user: User
):
    """Test requires authentication."""
    response = await async_client.get(
        "/api/protected",
        headers=auth_headers,
    )
    assert response.status_code == 200
```

3. Run the test:
```bash
pytest tests/test_api_e2e.py::TestNewFeature::test_new_endpoint -v
```

## Dependencies

Tests require:
- `pytest` — Test runner
- `pytest-asyncio` — Async test support
- `httpx[http2]` — Async HTTP client
- `sqlalchemy[asyncio]` — Async database
- `aiosqlite` — SQLite async driver
- FastAPI & Starlette (from main app)

All are already in `requirements.txt`.

## Known Limitations

- WebSocket tests are simplified (full integration testing recommended separately)
- External API calls (Yahoo Finance, Google News) are mocked
- Tests use in-memory SQLite (production DB may behave differently)
- Celery task mocking doesn't test actual background job execution
- Rate limiting is not tested (would require Redis setup)

## Debugging

### View test output
```bash
pytest tests/test_api_e2e.py -v -s
```

### Drop into debugger
```python
import pdb; pdb.set_trace()
```

### Print statements
```bash
pytest tests/test_api_e2e.py -v -s --capture=no
```

### Check what fixtures are available
```bash
pytest tests/test_api_e2e.py --fixtures
```

## Integration with CI/CD

Add to GitHub Actions or equivalent:
```yaml
- name: Run API tests
  run: |
    docker-compose -f docker-compose.dev.yml exec backend \
      pytest tests/test_api_e2e.py -v --tb=short
```
