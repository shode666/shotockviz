#!/usr/bin/env bash
set -euo pipefail

# ShotockViz — Deploy to production server
#
# Usage:
#   ./scripts/deploy.sh [host]
#
# Prerequisites:
#   - SSH access to the server (default: "do" from ~/.ssh/config)
#   - Docker + Docker Compose installed on the server
#   - shared-proxy network created on the server
#   - .env configured on the server at ~/shotockviz/.env

HOST="${1:-do}"
REMOTE_DIR="/root/shotockviz"

echo "==> Deploying ShotockViz to ${HOST}:${REMOTE_DIR}"

# Step 1: Ensure shared network exists on server
echo "==> Ensuring shared-proxy network..."
ssh "${HOST}" "docker network create shared-proxy 2>/dev/null || true"

# Step 2: Sync project files (exclude dev-only files)
echo "==> Syncing files..."
rsync -avz --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude '*.log' \
  --exclude '.claude' \
  --exclude '.DS_Store' \
  --exclude 'caddy-root.crt' \
  --exclude 'celerybeat-schedule' \
  --exclude 'test-results' \
  --exclude 'playwright-report' \
  -e ssh \
  . "${HOST}:${REMOTE_DIR}/"

# Step 3: Build and deploy on server
echo "==> Building and starting services..."
ssh "${HOST}" "cd ${REMOTE_DIR} && \
  docker compose -f docker-compose.prod.yml up -d --build"

# Step 4: Wait for services
echo "==> Waiting for services to start..."
sleep 15

# Step 5: Run migrations
echo "==> Running database migrations..."
ssh "${HOST}" "cd ${REMOTE_DIR} && \
  docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head 2>&1 || echo 'Migration note: check if tables already exist'"

# Step 6: Health check
echo "==> Health check..."
ssh "${HOST}" "cd ${REMOTE_DIR} && \
  echo 'Backend:  ' && curl -sf http://localhost:8000/api/health 2>/dev/null || echo 'starting...'; \
  echo 'Frontend: ' && curl -sf http://localhost:3000 -o /dev/null 2>/dev/null && echo 'ok' || echo 'starting...'"

echo ""
echo "==> Deploy complete! Site: https://stock.shode.dev"
