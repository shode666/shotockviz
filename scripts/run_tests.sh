#!/bin/bash
# run_tests.sh — Run all backend pytest + frontend Playwright E2E tests.
#
# Usage (from project root):
#   bash scripts/run_tests.sh
#
# Prerequisites:
#   Backend:  pip install -r backend/requirements.txt
#   Frontend: cd frontend && npm install
#
# Environment:
#   The backend tests require PostgreSQL + Redis from the dev Docker stack.
#   Start with: docker compose -f docker-compose.dev.yml up -d
#   The Playwright tests require the full stack running at http://localhost.
#
# Exit codes:
#   0  — all test suites passed
#   1  — one or more suites failed (individual exit codes are preserved)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Colours ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No colour

banner() {
    echo ""
    echo -e "${YELLOW}══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  $1${NC}"
    echo -e "${YELLOW}══════════════════════════════════════════════════════════${NC}"
}

# ── Backend pytest ─────────────────────────────────────────────────────────────
banner "Running Backend Tests (pytest)"

BACKEND_DIR="$PROJECT_ROOT/backend"

if [ ! -f "$BACKEND_DIR/pytest.ini" ]; then
    echo -e "${RED}ERROR: $BACKEND_DIR/pytest.ini not found.${NC}"
    echo "Ensure you are running from the ShotockViz project root."
    exit 1
fi

# Activate venv if present
if [ -f "$BACKEND_DIR/.venv/bin/activate" ]; then
    source "$BACKEND_DIR/.venv/bin/activate"
elif [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

BACKEND_EXIT=0
python -m pytest \
    "$BACKEND_DIR/tests/" \
    -v \
    --tb=short \
    --no-header \
    -p no:cacheprovider \
    2>&1 || BACKEND_EXIT=$?

if [ $BACKEND_EXIT -eq 0 ]; then
    echo -e "\n${GREEN}✓ Backend tests passed.${NC}"
else
    echo -e "\n${RED}✗ Backend tests failed (exit $BACKEND_EXIT).${NC}"
fi

# ── Frontend Playwright E2E ────────────────────────────────────────────────────
banner "Running Frontend E2E Tests (Playwright)"

FRONTEND_DIR="$PROJECT_ROOT/frontend"

if [ ! -f "$FRONTEND_DIR/package.json" ]; then
    echo -e "${RED}ERROR: $FRONTEND_DIR/package.json not found.${NC}"
    exit 1
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "node_modules not found — running npm install..."
    (cd "$FRONTEND_DIR" && npm install)
fi

PLAYWRIGHT_EXIT=0
(cd "$FRONTEND_DIR" && npx playwright test) 2>&1 || PLAYWRIGHT_EXIT=$?

if [ $PLAYWRIGHT_EXIT -eq 0 ]; then
    echo -e "\n${GREEN}✓ Playwright E2E tests passed.${NC}"
else
    echo -e "\n${RED}✗ Playwright E2E tests failed (exit $PLAYWRIGHT_EXIT).${NC}"
    echo "    View report:  cd frontend && npm run test:e2e:report"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
banner "Test Summary"

if [ $BACKEND_EXIT -eq 0 ] && [ $PLAYWRIGHT_EXIT -eq 0 ]; then
    echo -e "${GREEN}All test suites passed!${NC}"
    exit 0
else
    [ $BACKEND_EXIT -ne 0 ]  && echo -e "${RED}Backend:  FAILED${NC}"
    [ $PLAYWRIGHT_EXIT -ne 0 ] && echo -e "${RED}Frontend: FAILED${NC}"
    exit 1
fi
