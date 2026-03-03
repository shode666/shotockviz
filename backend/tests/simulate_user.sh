#!/bin/bash

################################################################################
# ShotockViz User Simulation Test Runner
#
# Runs the comprehensive user journey simulation against a live Docker stack.
# Simulates real user behavior including auth, dashboard, charts, watchlists,
# portfolio, alerts, and performance testing.
#
# Usage:
#   ./simulate_user.sh              # Run all tests with verbose output
#   ./simulate_user.sh -q           # Run quietly (minimal output)
#   ./simulate_user.sh --html       # Generate HTML report
#
# Requirements:
#   - Docker Compose stack running (docker-compose -f docker-compose.dev.yml up -d)
#   - Backend container with pytest installed
#   - Python 3.13+ with httpx, pytest-asyncio
#
################################################################################

set -e

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.dev.yml"
TEST_FILE="tests/test_user_simulation.py"
QUIET_MODE=false
HTML_REPORT=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -q|--quiet)
            QUIET_MODE=true
            shift
            ;;
        --html)
            HTML_REPORT=true
            shift
            ;;
        -h|--help)
            cat << EOF
Usage: $0 [OPTIONS]

OPTIONS:
    -q, --quiet         Minimal output (only show pass/fail)
    --html              Generate HTML report (requires pytest-html)
    -h, --help          Show this help message

EXAMPLES:
    # Run all tests with full output
    $0

    # Run quietly
    $0 -q

    # Generate HTML report
    $0 --html

EOF
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Colors for terminal output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Banner
echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║            ShotockViz User Simulation Test Suite                       ║"
echo "║                    Running Live Docker Stack Test                      ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if Docker Compose stack is running
echo ""
echo "Checking Docker Compose stack..."
if ! docker-compose -f "$COMPOSE_FILE" ps backend | grep -q "Up"; then
    echo -e "${RED}✗ Backend container is not running.${NC}"
    echo ""
    echo "Start the stack with:"
    echo "  docker-compose -f docker-compose.dev.yml up -d"
    exit 1
fi
echo -e "${GREEN}✓ Backend container is running${NC}"

# Check Python dependencies
echo ""
echo "Checking Python dependencies..."
REQUIRED_PACKAGES=("httpx" "pytest" "pytest-asyncio")
MISSING_PACKAGES=()

for package in "${REQUIRED_PACKAGES[@]}"; do
    if ! docker-compose -f "$COMPOSE_FILE" exec -T backend python -c "import $package" 2>/dev/null; then
        MISSING_PACKAGES+=("$package")
    fi
done

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo -e "${YELLOW}Installing missing packages: ${MISSING_PACKAGES[*]}${NC}"
    docker-compose -f "$COMPOSE_FILE" exec backend pip install -q "${MISSING_PACKAGES[@]}"
fi
echo -e "${GREEN}✓ All dependencies available${NC}"

# Build pytest command
echo ""
echo "Building test command..."

PYTEST_ARGS="-v --tb=short"

if [ "$QUIET_MODE" = true ]; then
    PYTEST_ARGS="${PYTEST_ARGS} -q"
else
    PYTEST_ARGS="${PYTEST_ARGS} -s"
fi

if [ "$HTML_REPORT" = true ]; then
    PYTEST_ARGS="${PYTEST_ARGS} --html=tests/report.html --self-contained-html"
    echo -e "${BLUE}HTML report will be saved to: tests/report.html${NC}"
fi

# Run tests
echo ""
echo -e "${BLUE}Running test suite...${NC}"
echo "Command: pytest ${TEST_FILE} ${PYTEST_ARGS}"
echo ""

if docker-compose -f "$COMPOSE_FILE" exec backend \
    python -m pytest "${TEST_FILE}" ${PYTEST_ARGS}; then

    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════════════╗"
    echo "║                    ✓ ALL TESTS PASSED                               ║"
    echo "╚════════════════════════════════════════════════════════════════════════╝${NC}"

    if [ "$HTML_REPORT" = true ]; then
        echo ""
        echo -e "${BLUE}View detailed report:${NC}"
        echo "  cat tests/report.html | open"
    fi

    exit 0
else
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════════════════════════════════╗"
    echo "║                    ✗ SOME TESTS FAILED                             ║"
    echo "╚════════════════════════════════════════════════════════════════════════╝${NC}"

    echo ""
    echo "Troubleshooting tips:"
    echo "  1. Check backend logs:"
    echo "     docker-compose -f docker-compose.dev.yml logs -f backend"
    echo ""
    echo "  2. Verify cache/Redis:"
    echo "     docker-compose -f docker-compose.dev.yml logs -f redis"
    echo ""
    echo "  3. Re-run with full output (no -q flag)"
    echo ""
    exit 1
fi
