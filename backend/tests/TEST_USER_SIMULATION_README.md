# ShotockViz User Simulation Test Suite

Comprehensive end-to-end test suite that simulates a complete user journey through the ShotockViz platform. Tests real user behavior including authentication, dashboard viewing, stock charting, search, watchlists, portfolio management, price alerts, and performance characteristics.

## Overview

### What Gets Tested

| Phase | Endpoints | Focus |
|-------|-----------|-------|
| **Auth** | `/auth/me` | JWT token creation and validation |
| **Dashboard** | `/health`, `/system/ready`, `/dashboard` | System health, cache readiness, market indices |
| **Chart** | `/stocks/{symbol}/quote`, `/stocks/{symbol}/history`, `/stocks/{symbol}/fundamentals`, `/stocks/{symbol}/news` | Stock data across all timeframes (1m–1M) |
| **Search** | `/stocks/search` | Symbol lookup by prefix, Thai and US markets |
| **Watchlist** | `/watchlists`, `/watchlists/{id}`, `/watchlists/{id}/stocks` | Create, modify, delete watchlists |
| **Portfolio** | `/portfolio`, `/portfolio/transactions`, `/portfolio/analytics` | Buy/sell transactions, P&L, holdings |
| **Alerts** | `/alerts`, `/alerts/{id}`, `/alerts/{id}/toggle` | Price alerts, activation, cleanup |
| **Performance** | Batch quotes, caching, concurrency | Response time thresholds, cache hits |

### Market Coverage

- **US Markets:** NVDA, AAPL, MSFT, GOOG, SPY, TSLA, AMD, INTC
- **Thai Market:** PTT.BK, CPALL.BK
- **Indices:** ^GSPC (S&P 500), ^IXIC (NASDAQ), ^SET.BK (SET index)
- **Forex:** THBUSD=X (USD/THB exchange)
- **Commodities:** GC=F (Gold)

## Quick Start

### Prerequisites

- Docker Compose stack running: `docker-compose -f docker-compose.dev.yml up -d`
- Backend container must be healthy (database, Redis, Celery workers)
- Python 3.13+ with `httpx`, `pytest`, `pytest-asyncio`

### Run All Tests

```bash
# Make script executable
chmod +x backend/tests/simulate_user.sh

# Run with verbose output
./backend/tests/simulate_user.sh

# Run quietly (pass/fail only)
./backend/tests/simulate_user.sh -q

# Generate HTML report
./backend/tests/simulate_user.sh --html
```

### Run Specific Test Class

```bash
# Run only dashboard phase
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py::TestDashboardPhase -v -s

# Run only authentication
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py::TestAuthPhase -v -s

# Run single test
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py::TestChartPhase::test_history_all_timeframes -v -s
```

## Test Structure

### 1. TestAuthPhase

Creates JWT tokens for authenticated endpoints.

```python
# Test user credentials
TEST_USER_EMAIL = "simulator@test.shotockviz.local"
TEST_USER_ID = 1
```

**Tests:**
- `test_create_jwt_token`: Directly create JWT using `security.py`
- `test_verify_token_on_auth_me`: Verify token by calling `/auth/me`

### 2. TestDashboardPhase

Verifies system health and market readiness.

**Tests:**
- `test_health_check`: Database, Redis, Celery status
- `test_cache_ready`: Verify cache has key symbols (threshold: 3/5 keys)
- `test_dashboard_overview`: Get market indices (S&P 500, NASDAQ, SET index)

### 3. TestChartPhase

Stock quotes, history, fundamentals, and news.

**Tests:**
- `test_single_quote_nvda`: Get NVDA price (benchmark: <3s cold)
- `test_single_quote_ptt_bk`: Get Thai stock (may be slower/unavailable)
- `test_quote_cached`: Verify cached quotes are <100ms
- `test_history_all_timeframes`: Test all 8 timeframes (1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M)
- `test_fundamentals`: Get P/E, dividend yield
- `test_news`: Get news via Google News RSS
- `test_symbol_switch_*`: Rapid symbol switching (NVDA→AAPL→MSFT)

### 4. TestSearchPhase

Stock symbol search across markets.

**Tests:**
- `test_search_nv`: Search for "NV" (should find NVDA)
- `test_search_ptt`: Search for "PTT" (Thai stock)
- `test_search_aapl`: Search for "AAPL"

### 5. TestWatchlistPhase

Create, populate, and delete watchlists.

**Tests:**
- `test_get_watchlists`: List existing watchlists
- `test_create_watchlist`: Create new "Simulator Test Watchlist"
- `test_add_stock_nvda`: Add NVDA
- `test_add_stock_aapl`: Add AAPL
- `test_batch_quotes`: Get quotes for 5 symbols (<3s)
- `test_remove_stock_aapl`: Remove AAPL
- `test_delete_watchlist`: Clean up (DELETE /watchlists/{id})

### 6. TestPortfolioPhase

Transactions and P&L analytics.

**Tests:**
- `test_get_transactions_initial`: List existing portfolio
- `test_add_transaction_aapl`: BUY 10 AAPL @ $150 (USD)
- `test_add_transaction_ptt`: BUY 100 PTT.BK @ ฿35 (THB)
- `test_get_portfolio_analytics`: Fetch holdings with current market prices
- `test_cleanup_transactions`: Delete all test transactions (cleanup)

### 7. TestAlertPhase

Price alerts and notification management.

**Tests:**
- `test_get_alerts_initial`: List existing alerts
- `test_create_alert_nvda`: Create NVDA > $200 alert
- `test_create_alert_aapl`: Create AAPL < $140 alert
- `test_toggle_alert`: Toggle active/inactive
- `test_cleanup_alerts`: Delete all test alerts (cleanup)

### 8. TestPerformancePhase

Caching and response time validation.

**Tests:**
- `test_batch_performance_warm`: Batch quotes—first cold, second cached
- `test_history_caching`: History endpoint caching
- `test_concurrent_quotes`: 8 parallel quote requests

### 9. TestUserJourney

Full integration test simulating a complete user session.

Covers all phases in sequence, demonstrating real-world usage patterns.

## Performance Thresholds

| Operation | Target | Threshold |
|-----------|--------|-----------|
| Single quote (cold) | ~2–3s | 3000ms |
| Single quote (cached) | <100ms | 100ms |
| Batch quotes (5 symbols) | ~2–3s | 3000ms |
| Stock history | ~2–5s | 5000ms |
| Dashboard | ~1–2s | (diagnostic) |
| Fundamentals | ~1–2s | (diagnostic) |
| News | ~2–8s | (diagnostic) |

**Interpretation:**
- ✓ Green: Below threshold (good)
- ⚠ Amber: Above threshold (investigate)
- ✗ Red: Test fails (critical issue)

## Key Features

### Automatic JWT Creation

Tests create JWT tokens directly using `security.py`, bypassing Google OAuth:

```python
from core.security import create_access_token

token = create_access_token({
    "sub": str(TEST_USER_ID),
    "role": "user",
    "email": TEST_USER_EMAIL,
    "display_name": "Simulator User",
    "created_at": datetime.now(timezone.utc).isoformat(),
})
```

### SSL/TLS Bypass for Localhost

All HTTP clients use `verify=False` for Caddy's self-signed cert:

```python
httpx.AsyncClient(
    base_url=API_ENDPOINT,
    verify=False,  # Accept self-signed for localhost testing
    timeout=30.0,
)
```

### Automatic Cleanup

All tests clean up after themselves:
- Created watchlists are deleted
- Transactions are removed
- Alerts are cleaned up
- No test data persists

### Timing Measurements

Every request includes millisecond timing for performance analysis:

```python
status, data, elapsed = await client.get("/stocks/NVDA/quote")
# elapsed is in milliseconds
print(f"Request took {elapsed:.1f}ms")
```

### Async/Await Pattern

All tests are async for realistic concurrent behavior:

```python
@pytest.mark.asyncio
async def test_concurrent_quotes(self, client):
    results = await asyncio.gather(
        *[client.get(f"/stocks/{sym}/quote") for sym in symbols],
        return_exceptions=True
    )
```

## Example Output

```
================================================================================
                    SHOTOCKVIZ USER JOURNEY SIMULATION
================================================================================

[1] AUTHENTICATION
✓ Created test JWT: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

[2] SYSTEM HEALTH
✓ System healthy: 45.3ms

[3] DASHBOARD
      S&P500:      +5234.67 (  +0.82%)
     NASDAQ:      +16820.42 (  +1.05%)
        SET:         1420.35 (  -0.15%)
    USD/THB:         33.75 (  +0.12%)
       Gold:         2050.00 (  -0.25%)

[4] STOCK SEARCH
✓ Found 8 results for 'NV'

[5] CHART VIEW
  NVDA    :   124.56 (78.4ms)
  AAPL    :   182.33 (65.2ms)
  PTT.BK  :   35.25 (2350.1ms)

[6] WATCHLIST
✓ Created watchlist (ID: 42)
  Added NVDA
  Added AAPL
✓ Batch quotes: 234.5ms

[7] PORTFOLIO
✓ Added transaction (ID: 123)
✓ Portfolio: 1 positions (567.8ms)
  AAPL: 750.00 USD (+2.50%)

[8] ALERTS
✓ Created alert (ID: 456)

================================================================================
                JOURNEY COMPLETE — All features verified!
================================================================================
```

## Troubleshooting

### Backend Container Not Running

```bash
docker-compose -f docker-compose.dev.yml up -d
docker-compose -f docker-compose.dev.yml logs -f backend
```

### Missing Python Packages

The test runner automatically installs missing packages. Manual install:

```bash
docker-compose -f docker-compose.dev.yml exec backend pip install httpx pytest-asyncio
```

### SSL Certificate Error

If you see `CERTIFICATE_VERIFY_FAILED`, the Caddy reverse proxy certificate is not recognized. The test suite uses `verify=False` to bypass this for localhost testing. In production, use a proper certificate.

### Timeout Errors

Check if services are responsive:

```bash
# Check backend
docker-compose -f docker-compose.dev.yml exec backend ping redis
docker-compose -f docker-compose.dev.yml exec backend python -c "import asyncpg; print('DB OK')"

# Check Redis
docker-compose -f docker-compose.dev.yml exec redis redis-cli ping

# Check Celery workers
docker-compose -f docker-compose.dev.yml logs celery-beat
```

### Thai Stock Data Issues

Thai stocks (PTT.BK, CPALL.BK) may return null prices if:
1. Yahoo Finance doesn't support SET tickers
2. Market is closed (SET hours: 10:00–12:30, 14:00–16:30 ICT)
3. Data not yet cached from Celery fetcher

The test suite handles these gracefully with `⚠ PTT.BK unavailable` messages.

### No Data Returned

Verify Celery workers are running and cache is warming:

```bash
# Check cache readiness
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py::TestDashboardPhase::test_cache_ready -v -s

# Check Celery stats
curl -s https://localhost/api/system/celery-stats | jq .
```

## Advanced Usage

### Generate HTML Report

```bash
./backend/tests/simulate_user.sh --html
# Opens: tests/report.html (requires pytest-html)
```

### Run with Custom Base URL

Edit `test_user_simulation.py`:

```python
API_BASE_URL = "https://your-hostname.com"
```

### Filter by Keyword

```bash
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py -k "performance" -v -s
```

### Run with Coverage

```bash
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py --cov=api --cov=services -v
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
- name: Run ShotockViz User Simulation Tests
  run: |
    docker-compose -f docker-compose.dev.yml exec -T backend \
      python -m pytest tests/test_user_simulation.py -v --tb=short
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All tests passed |
| 1 | One or more tests failed |
| 2 | Test collection error (syntax, etc.) |

## Files

| File | Purpose |
|------|---------|
| `test_user_simulation.py` | Pytest test suite (1000+ LOC) |
| `simulate_user.sh` | Bash runner with Docker integration |
| `TEST_USER_SIMULATION_README.md` | This documentation |

## Version History

- **v1.0** (2026-03-02): Initial user simulation suite
  - 8 test phases covering full user journey
  - 40+ individual tests
  - Performance threshold validation
  - Automatic cleanup and resource management
  - Async/concurrent testing support
  - HTML report generation
  - Thai + US market coverage

## Contributing

When adding new endpoints or features:

1. Add corresponding test phase class
2. Follow the naming convention: `Test<Phase>Phase`
3. Ensure tests clean up after themselves
4. Include timing measurements
5. Test both Thai and US markets where applicable
6. Update thresholds in test class docstring
7. Document assumptions (e.g., market hours, data availability)

## Support

For issues or questions:
- Check backend logs: `docker-compose logs -f backend`
- Check Redis: `docker-compose exec redis redis-cli KEYS '*'`
- View system stats: `curl https://localhost/api/system/celery-stats`

---

**Last Updated:** 2026-03-02
**ShotockViz Version:** 0.1.3 BETA
**Tested Platforms:** Linux (x86_64), macOS (M1/Intel)
