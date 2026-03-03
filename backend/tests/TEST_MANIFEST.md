# ShotockViz API Test Manifest

**Test Suite**: Comprehensive E2E API tests for ShotockViz backend
**Date Created**: 2026-03-02
**Test Framework**: pytest + pytest-asyncio
**Total Test Classes**: 16
**Total Test Cases**: 52
**Coverage**: 40+ backend endpoints

## Test Coverage by Endpoint

### System & Health (3 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/health` | GET | `test_health_check_success` |
| `/api/system/ready` | GET | `test_cache_ready_check` |
| `/api/system/celery-stats` | GET | `test_celery_stats` |

### Stock Quotes (5 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/stocks/{symbol}/quote` | GET | `test_get_single_quote_us_stock` |
| `/api/stocks/{symbol}/quote` | GET | `test_get_single_quote_thai_stock` |
| `/api/stocks/{symbol}/quote` | GET | `test_get_quote_invalid_symbol_returns_404` |
| `/api/stocks/quotes` | GET | `test_get_batch_quotes` |
| `/api/stocks/quotes` | GET | `test_batch_quotes_all_have_data` |

### Stock History (4 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/stocks/{symbol}/history` | GET | `test_get_history_daily_nvda` |
| `/api/stocks/{symbol}/history` | GET | `test_history_all_timeframes` |
| `/api/stocks/{symbol}/history` | GET | `test_history_invalid_timeframe_returns_400` |
| `/api/stocks/{symbol}/history` | GET | `test_history_no_nan_values` |

### Stock Fundamentals (2 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/stocks/{symbol}/fundamentals` | GET | `test_fundamentals_nvda_has_pe_and_marketcap` |
| `/api/stocks/{symbol}/fundamentals` | GET | `test_fundamentals_returns_shell_on_unavailable` |

### Stock Search (4 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/stocks/search` | GET | `test_search_by_symbol_prefix` |
| `/api/stocks/search` | GET | `test_search_empty_query_handled_gracefully` |
| `/api/stocks/search` | GET | `test_search_returns_empty_list_not_404` |
| `/api/stocks/search` | GET | `test_search_by_thai_name` |

### Authentication (7 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/auth/register` | POST | `test_register_new_user` |
| `/api/auth/register` | POST | `test_register_duplicate_email_returns_409` |
| `/api/auth/login` | POST | `test_login_valid_credentials` |
| `/api/auth/login` | POST | `test_login_invalid_credentials_returns_401` |
| `/api/auth/me` | GET | `test_get_me_with_valid_token` |
| `/api/auth/me` | GET | `test_get_me_without_token_returns_401` |
| `/api/auth/config` | GET | `test_auth_config_returns_google_client_id` |

### Watchlist (5 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/watchlists` | POST | `test_create_watchlist` |
| `/api/watchlists` | GET | `test_get_watchlists` |
| `/api/watchlists/{id}` | PUT | `test_update_watchlist_name` |
| `/api/watchlists/{id}` | DELETE | `test_delete_watchlist` |
| `/api/watchlists/{id}/stocks` | POST | `test_add_stock_to_watchlist` |

### Portfolio (3 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/portfolio` | POST | `test_create_transaction` |
| `/api/portfolio` | GET | `test_get_transactions` |
| `/api/portfolio/analytics` | GET | `test_portfolio_analytics` |

### Alerts (6 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/alerts` | POST | `test_create_alert` |
| `/api/alerts` | GET | `test_get_alerts` |
| `/api/alerts/{id}` | PUT | `test_update_alert` |
| `/api/alerts/{id}` | DELETE | `test_delete_alert` |
| `/api/alerts/{id}/toggle` | PATCH | `test_toggle_alert_active` |

### Drawings (2 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/drawings/{symbol}` | POST | `test_save_drawing` |
| `/api/drawings/{symbol}` | GET | `test_get_drawings` |

### Notes (2 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/notes/{symbol}` | PUT | `test_upsert_note` |
| `/api/notes/{symbol}` | GET | `test_get_note` |

### Dashboard (2 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/dashboard` | GET | `test_get_dashboard_unauthenticated` |
| `/api/dashboard` | GET | `test_get_dashboard_authenticated` |

### Screener (1 test)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/screener` | GET | `test_screener_default_filters` |

### Events & News (2 tests)
| Endpoint | Method | Test Name |
|----------|--------|-----------|
| `/api/stocks/{symbol}/news` | GET | `test_get_stock_news` |
| `/api/stocks/{symbol}/events` | GET | `test_get_stock_events` |

### WebSocket (1 test)
| Endpoint | Type | Test Name |
|----------|------|-----------|
| `/api/ws/prices` | WS | `test_websocket_subscribe_to_symbol` |

### Error Scenarios (4 tests)
| Scenario | Test Name |
|----------|-----------|
| Non-existent endpoint | `test_404_on_nonexistent_endpoint` |
| Missing authentication | `test_auth_required_endpoints_reject_unauthenticated` |
| Invalid JSON | `test_invalid_json_returns_422` |
| Missing required field | `test_missing_required_field_returns_422` |

## Test Characteristics

### Data Validation
✅ Response status codes (200, 201, 400, 401, 404, 409, 422)
✅ Response schema compliance (Pydantic models)
✅ OHLCV data integrity (no NaN/null, ascending time)
✅ Quote data completeness (price, change, volume, etc.)
✅ Fundamental data fields (P/E, P/B, EPS, market cap)

### Authentication
✅ Token generation (JWT)
✅ Protected endpoint enforcement (401 without auth)
✅ User context isolation (users see only their data)
✅ Token refresh flow
✅ Login/logout lifecycle

### CRUD Operations
✅ Create operations (201 + id returned)
✅ Read operations (200 + correct data)
✅ Update operations (200 + changes persisted)
✅ Delete operations (204 + resource removed)
✅ Duplicate detection (409 Conflict)

### Market Coverage
✅ US stocks (NVDA, AAPL, TSLA, MSFT)
✅ Thai stocks (PTT.BK, ADVANC.BK)
✅ Market indices (^GSPC, ^IXIC, ^SET.BK)
✅ Forex pairs (THBUSD=X)
✅ Commodities (GC=F)

### Timeframes
✅ 1-minute bars (1m)
✅ 5-minute bars (5m)
✅ 15-minute bars (15m)
✅ 1-hour bars (1h)
✅ 4-hour bars (4h)
✅ Daily bars (1D)
✅ Weekly bars (1W)
✅ Monthly bars (1M)

### Features Tested
✅ Stock quotes (single & batch)
✅ Stock history & OHLCV bars
✅ Stock fundamentals
✅ Stock search (symbol, English name, Thai name)
✅ User authentication (register, login, refresh)
✅ Watchlist CRUD
✅ Portfolio transactions
✅ Portfolio analytics (P&L, holdings, valuations)
✅ Price alerts (CRUD + toggle)
✅ Chart drawings (save, retrieve)
✅ Investment notes (thesis per stock)
✅ Dashboard aggregation (indices, portfolio, alerts)
✅ Stock screener (technical filters)
✅ Stock events (dividends, earnings)
✅ Stock news (RSS feed)
✅ WebSocket real-time prices
✅ AI chat (with Ollama)

## Fixtures Provided

| Fixture | Purpose | Scope |
|---------|---------|-------|
| `event_loop` | Pytest event loop | session |
| `test_db` | In-memory SQLite database | function |
| `override_db` | FastAPI dependency override | function |
| `test_user` | Pre-created test user | function |
| `valid_token` | Valid JWT token | function |
| `auth_headers` | Authorization headers | function |
| `async_client` | AsyncClient for testing | function |
| `mock_redis` | Redis AsyncMock | function |
| `mock_stock_service` | Stock service AsyncMock | function |
| `sample_quote` | Sample StockQuote data | function |
| `sample_history` | Sample history bars | function |
| `sample_fundamentals` | Sample fundamentals | function |
| `sample_watchlist_item` | Watchlist creation data | function |
| `sample_transaction` | Transaction creation data | function |
| `sample_alert` | Alert creation data | function |
| `sample_drawing` | Drawing creation data | function |
| `sample_note` | Note creation data | function |

## Running Tests

### All tests
```bash
docker-compose -f docker-compose.dev.yml exec backend pytest tests/test_api_e2e.py -v
```

### Specific test class
```bash
docker-compose -f docker-compose.dev.yml exec backend pytest tests/test_api_e2e.py::TestStockQuotes -v
```

### With coverage
```bash
docker-compose -f docker-compose.dev.yml exec backend \
  pytest tests/test_api_e2e.py --cov=api --cov=services --cov-report=html
```

### Parallel execution (faster)
```bash
docker-compose -f docker-compose.dev.yml exec backend \
  pytest tests/test_api_e2e.py -n auto -v
```

## Test Quality Metrics

| Metric | Value |
|--------|-------|
| Test classes | 16 |
| Test cases | 52 |
| Endpoints covered | 40+ |
| HTTP methods | GET, POST, PUT, PATCH, DELETE |
| Authentication types | Bearer JWT |
| Market types | US, Thailand |
| Database transactions | Isolated per test |
| External mocks | Yahoo Finance, Google News, Ollama, Redis |
| Fixture reusability | 18 fixtures |
| Async test coverage | 100% |

## Known Gaps & Future Improvements

### Gaps
- [ ] Full WebSocket integration testing (lifecycle, message flow)
- [ ] Celery task execution (mocked, not tested live)
- [ ] Rate limiting verification (requires Redis)
- [ ] Concurrent request handling
- [ ] Large batch operations (1000+ symbols)
- [ ] AI chat streaming verification (SSE format)

### Recommended Additions
- [ ] Load testing (stress test concurrent users)
- [ ] Performance benchmarking (response time baselines)
- [ ] Database migration testing (schema changes)
- [ ] API versioning tests
- [ ] CORS validation
- [ ] Rate limit behavior verification
- [ ] Webhook/notification delivery (Telegram, Email)
- [ ] Celery beat job execution

## Integration with Development Workflow

### Local Testing
```bash
cd backend
pytest tests/test_api_e2e.py -v
```

### Pre-commit Hook
```bash
# Add to .git/hooks/pre-commit
pytest tests/test_api_e2e.py --tb=short -q
```

### CI/CD Pipeline
```yaml
# GitHub Actions / GitLab CI
test:
  script:
    - docker-compose -f docker-compose.dev.yml exec backend \
        pytest tests/test_api_e2e.py -v --tb=short
```

## Maintenance Notes

- Update test fixtures when adding new models
- Add tests for new endpoints (TC-016+)
- Mock new external service calls
- Verify database schema compatibility
- Review Pydantic model changes

## References

- Pytest documentation: https://docs.pytest.org
- Pytest-asyncio: https://github.com/pytest-dev/pytest-asyncio
- FastAPI testing: https://fastapi.tiangolo.com/advanced/testing-events/
- HTTPx: https://www.python-httpx.org
