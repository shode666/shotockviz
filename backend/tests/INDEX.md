# ShotockViz Test Suite Index

## Overview

Complete end-to-end user simulation test suite with 37 test methods across 9 test classes, covering the entire ShotockViz platform user journey.

## Files

### 1. `test_user_simulation.py` (867 lines)
**Location:** `/sessions/epic-sleepy-davinci/mnt/ShotockViz/backend/tests/test_user_simulation.py`

The core pytest test suite with async HTTP client and comprehensive test coverage.

**Contents:**
- `ShotockVizTestClient` — HTTP client with SSL bypass and JWT support
- `TestAuthPhase` — 2 tests: JWT creation, token validation
- `TestDashboardPhase` — 3 tests: health, cache ready, dashboard overview
- `TestChartPhase` — 7 tests: quotes, history (all timeframes), fundamentals, news, symbol switching
- `TestSearchPhase` — 3 tests: symbol search (US, Thai, generic)
- `TestWatchlistPhase` — 7 tests: CRUD, batch quotes
- `TestPortfolioPhase` — 5 tests: transactions, analytics
- `TestAlertPhase` — 5 tests: create, toggle, delete
- `TestPerformancePhase` — 3 tests: caching, concurrency
- `TestUserJourney` — 1 integration test: complete user session

**Features:**
✅ Async/await pattern for realistic concurrency
✅ Automatic cleanup (no test data persists)
✅ Response time measurements (all in milliseconds)
✅ JWT creation using `core/security.py`
✅ SSL/TLS bypass for localhost testing
✅ Thai + US market coverage
✅ Error handling and graceful degradation

**Run:**
```bash
# All tests
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py -v -s

# Single phase
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py::TestChartPhase -v -s

# Single test
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py::TestChartPhase::test_history_all_timeframes -v -s
```

---

### 2. `simulate_user.sh` (172 lines)
**Location:** `/sessions/epic-sleepy-davinci/mnt/ShotockViz/backend/tests/simulate_user.sh`

Bash runner script with Docker integration and dependency management.

**Features:**
✅ Auto-checks Docker Compose stack status
✅ Auto-installs Python dependencies (httpx, pytest-asyncio)
✅ Colored terminal output (green/red pass/fail)
✅ Quiet mode (`-q` flag)
✅ HTML report generation (`--html` flag)
✅ Helpful error messages with troubleshooting tips

**Run:**
```bash
# Verbose output
./backend/tests/simulate_user.sh

# Quiet (pass/fail only)
./backend/tests/simulate_user.sh -q

# Generate HTML report
./backend/tests/simulate_user.sh --html
```

---

### 3. `TEST_USER_SIMULATION_README.md` (600+ lines)
**Location:** `/sessions/epic-sleepy-davinci/mnt/ShotockViz/backend/tests/TEST_USER_SIMULATION_README.md`

Complete technical documentation with examples, troubleshooting, and advanced usage.

**Sections:**
- Overview (what gets tested)
- Quick Start
- Detailed test structure (each phase explained)
- Performance thresholds
- Key features
- Example output
- Troubleshooting guide
- Advanced usage (custom URLs, coverage, CI/CD)
- Version history

---

### 4. `TESTING_QUICK_START.md`
**Location:** `/sessions/epic-sleepy-davinci/mnt/ShotockViz/TESTING_QUICK_START.md`

Quick reference guide for running tests in seconds.

**Sections:**
- 30-second setup
- Test matrix (phases, counts, coverage)
- Common commands
- Expected output
- Troubleshooting table
- Performance benchmarks

---

## Test Matrix

| Phase | Tests | Endpoints | Coverage |
|-------|-------|-----------|----------|
| 🔐 Auth | 2 | `/auth/me` | JWT creation + validation |
| 📊 Dashboard | 3 | `/health`, `/system/ready`, `/dashboard` | Health + cache + indices |
| 📈 Chart | 7 | `/stocks/{sym}/quote`, `/history`, `/fundamentals`, `/news` | All timeframes (1m–1M) |
| 🔍 Search | 3 | `/stocks/search` | US + Thai markets |
| 👁️ Watchlist | 7 | `/watchlists`, `/watchlists/{id}`, `/watchlists/{id}/stocks` | CRUD + batch quotes |
| 💼 Portfolio | 5 | `/portfolio`, `/portfolio/transactions`, `/portfolio/analytics` | BUY/SELL + P&L |
| 🔔 Alerts | 5 | `/alerts`, `/alerts/{id}`, `/alerts/{id}/toggle` | CRUD + toggle |
| ⚡ Performance | 3 | Caching, concurrency | Response times |
| 🚀 Journey | 1 | Full integration | Complete user session |

**Total: 36 focused tests + 1 integration test = 37 tests**

---

## Quick Commands

```bash
# Run all tests with output
./backend/tests/simulate_user.sh

# Run quietly
./backend/tests/simulate_user.sh -q

# Run specific phase
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py::TestChartPhase -v -s

# Run specific test
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py::TestChartPhase::test_history_all_timeframes -v -s

# Run with coverage
docker-compose -f docker-compose.dev.yml exec backend \
  python -m pytest tests/test_user_simulation.py --cov=api --cov=services -v

# Generate HTML report
./backend/tests/simulate_user.sh --html
# → opens backend/tests/report.html
```

---

## Getting Started

### Prerequisites
- Docker Compose stack running: `docker-compose -f docker-compose.dev.yml up -d`
- Backend container healthy (database, Redis, Celery)
- Python 3.13+ with httpx, pytest, pytest-asyncio

### Run Tests
```bash
chmod +x backend/tests/simulate_user.sh
./backend/tests/simulate_user.sh
```

### Expected Result
```
✓ ALL TESTS PASSED — 37 tests in ~15-30 seconds
```

---

## Key Features

✅ **Comprehensive** — 37 tests covering entire user journey
✅ **Realistic** — Async/concurrent patterns simulate real behavior
✅ **Fast** — Completes in 15–30 seconds
✅ **Clean** — Auto-cleanup, no test data persists
✅ **Observable** — Response times measured for every request
✅ **Robust** — Graceful handling of missing/slow data
✅ **Documented** — 600+ lines of detailed docs + examples
✅ **CI/CD Ready** — Exit codes, quiet mode, HTML reports
✅ **Market Coverage** — US (NVDA, AAPL, SPY) + Thai (PTT.BK) + Indices

---

## Architecture

```
test_user_simulation.py (867 lines)
├── ShotockVizTestClient
│   ├── JWT creation (_create_test_jwt)
│   ├── HTTP methods (get, post, put, patch, delete)
│   ├── Response timing (all requests return elapsed_ms)
│   └── SSL/TLS bypass (verify=False for localhost)
├── Fixtures
│   ├── client (basic HTTP client)
│   └── auth_client (authenticated client with JWT)
├── Test Classes (9 total)
│   ├── TestAuthPhase (2 tests)
│   ├── TestDashboardPhase (3 tests)
│   ├── TestChartPhase (7 tests)
│   ├── TestSearchPhase (3 tests)
│   ├── TestWatchlistPhase (7 tests)
│   ├── TestPortfolioPhase (5 tests)
│   ├── TestAlertPhase (5 tests)
│   ├── TestPerformancePhase (3 tests)
│   └── TestUserJourney (1 test)
└── Entry Point
    └── async test_complete_user_flow()

simulate_user.sh (172 lines)
├── Environment checks
│   ├── Docker Compose stack status
│   ├── Python dependency installation
│   └── Color-coded terminal output
├── Argument parsing
│   ├── -q/--quiet (minimal output)
│   ├── --html (generate report)
│   └── -h/--help (show help)
└── Test execution
    └── Runs pytest with appropriate flags
```

---

## Performance Thresholds

The test suite validates these response time targets:

| Operation | Threshold | Target |
|-----------|-----------|--------|
| Single quote (cold) | 3000ms | ~2–3s |
| Single quote (cached) | 100ms | <100ms |
| Batch quotes (5) | 3000ms | ~2–3s |
| Stock history | 5000ms | ~2–5s |
| Dashboard | (diagnostic) | ~1–2s |
| Concurrent (8 quotes) | (diagnostic) | ~5–10s total |

---

## Troubleshooting Reference

| Issue | Solution |
|-------|----------|
| Backend not running | `docker-compose -f docker-compose.dev.yml up -d` |
| Missing httpx | `docker-compose -f docker-compose.dev.yml exec backend pip install httpx` |
| SSL verify failed | Normal for localhost—test uses `verify=False` |
| Redis timeout | `docker-compose exec redis redis-cli ping` |
| PTT.BK null | Expected if market closed or data unavailable—test handles gracefully |
| Tests hang | Check Celery workers: `docker-compose logs celery-worker` |

---

## Files Reference

| File | Purpose | Size |
|------|---------|------|
| `test_user_simulation.py` | Pytest suite (9 classes, 37 tests) | 33 KB |
| `simulate_user.sh` | Bash runner with Docker integration | 5.9 KB |
| `TEST_USER_SIMULATION_README.md` | Complete technical documentation | 13 KB |
| `TESTING_QUICK_START.md` | Quick reference guide | 6.4 KB |
| `INDEX.md` (this file) | File index and overview | — |

---

## Support & Questions

- **Documentation:** See `TEST_USER_SIMULATION_README.md`
- **Quick Start:** See `TESTING_QUICK_START.md`
- **Code Examples:** See `test_user_simulation.py` docstrings
- **Issues:** Check backend logs with `docker-compose logs -f backend`

---

**Created:** 2026-03-02
**ShotockViz Version:** 0.1.3 BETA
**Test Suite Version:** 1.0
**Total Code:** 1,039 lines (867 test + 172 runner)
**Test Count:** 37 async tests + 1 integration test
**Estimated Runtime:** 15–30 seconds
