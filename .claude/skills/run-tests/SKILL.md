---
name: run-tests
description: Run ShotockViz test suite. Use when the user asks to run tests, check if tests pass, or verify changes. Tests live in /tests/ (separate from frontend/backend Docker contexts). Specify "api", "e2e", or leave blank for both.
allowed-tools: Bash
argument-hint: "[api|e2e|all]"
---

# ShotockViz Test Runner

Tests are in `/Users/shode/development/ShotockViz/tests/` — NOT in frontend/ or backend/.

## Test locations
- API tests: `tests/api/` — pytest with in-memory SQLite
- E2E tests: `tests/e2e/` — Playwright against https://localhost (Docker stack must be running)

## Run based on argument: $ARGUMENTS

### If "api" or blank:
```bash
cd /Users/shode/development/ShotockViz/tests/api && pip install -q -r requirements.txt 2>/dev/null && pytest -v --tb=short 2>&1
```

### If "e2e":
```bash
cd /Users/shode/development/ShotockViz/tests/e2e
# Install deps if needed
[ -d node_modules ] || npm install 2>&1
# Run tests (requires Docker stack at https://localhost)
npx playwright test --reporter=list 2>&1
```

### If "all" or both:
Run API tests first, then E2E tests.

## Notes
- API tests use in-memory SQLite — no Docker needed
- E2E tests require `docker compose -f docker-compose.dev.yml up -d` running
- If E2E fails with "browser not installed": run `npx playwright install chromium`
- Run specific test class: `pytest -v -k "TestAuth"`
- Run specific E2E spec: `npx playwright test chart-timeframes.spec.ts`

Report test results clearly — pass/fail counts, any failing test names with error messages.
