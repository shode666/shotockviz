#!/usr/bin/env bash
# bootstrap-server.sh — ONE-TIME setup for a fresh droplet (188.166.234.146 / ssh alias my-do)
#
# Run from your Mac (nothing is installed on the server yet):
#   ssh my-do 'bash -s' < scripts/bootstrap-server.sh
#
# Idempotent: safe to re-run. Installs Docker Engine + compose plugin, opens
# ufw for 22/80/443 (OpenSSH allowed FIRST so re-running never locks you out),
# creates /opt/shotockviz and a starter .env (ONLY if one doesn't already exist —
# never overwrites a real .env).
set -euo pipefail

APP_DIR="/opt/shotockviz"
ENV_FILE="${APP_DIR}/.env"

log() { printf '==> %s\n' "$1"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must run as root on the server (ssh my-do defaults to root@188.166.234.146)." >&2
  exit 1
fi

log "apt update"
apt-get update -y

# ---------- Docker Engine + Compose plugin (official apt repo, pinned/idempotent) ----------
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker Engine + compose plugin via official apt repo"
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
  fi
  ARCH="$(dpkg --print-architecture)"
  # shellcheck disable=SC1091  # /etc/os-release is a runtime file on the target server, not source-checkable here
  CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
  log "Docker already installed ($(docker --version)) — skipping install"
fi

if ! docker compose version >/dev/null 2>&1; then
  log "Installing docker-compose-plugin"
  apt-get install -y docker-compose-plugin
else
  log "docker compose plugin present ($(docker compose version --short 2>/dev/null || true)) — skipping"
fi

systemctl enable --now docker

# ---------- Firewall: OpenSSH FIRST, then app ports, then enable ----------
if ! command -v ufw >/dev/null 2>&1; then
  log "Installing ufw"
  apt-get install -y ufw
fi

log "Allowing OpenSSH before enabling ufw (avoid lockout)"
ufw allow OpenSSH || ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
if ufw status | grep -q "Status: active"; then
  log "ufw already active — rules ensured above"
else
  log "Enabling ufw"
  ufw --force enable
fi

# ---------- App directory ----------
log "Ensuring ${APP_DIR}"
mkdir -p "${APP_DIR}"

# ---------- .env — created ONLY if absent, NEVER overwritten ----------
if [ -f "${ENV_FILE}" ]; then
  log "${ENV_FILE} already exists — leaving it untouched"
else
  log "Creating starter ${ENV_FILE} (chmod 600) — YOU MUST EDIT THE VALUES before first deploy"
  cat > "${ENV_FILE}" <<'ENVEOF'
# ============================================================
# ShotockViz — production .env for the GHCR deploy (docker-compose.ghcr.yml)
# Fill in every value below before running the deploy workflow.
# This file NEVER leaves the server and is NOT read by the GitHub Actions job.
# ============================================================

# ----- Database -----
DATABASE_URL=postgresql+asyncpg://stockviz:CHANGE_ME@db:5432/stockviz_prod
POSTGRES_USER=stockviz
POSTGRES_PASSWORD=CHANGE_ME
POSTGRES_DB=stockviz_prod

# ----- Redis -----
REDIS_URL=redis://redis:6379/0

# ----- JWT (generate with: openssl rand -hex 32) -----
JWT_SECRET_KEY=CHANGE_ME
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# ----- External APIs -----
FINNHUB_API_KEY=CHANGE_ME
TELEGRAM_BOT_TOKEN=

# ----- App -----
APP_ENV=production
DEBUG=False
WORKERS=2
CORS_ORIGINS=https://CHANGE_ME.example.com
TZ=Asia/Bangkok

# ----- Caddy (reverse proxy / auto TLS) -----
# DOMAIN's DNS A record MUST already point at this droplet's IP before first
# deploy, or Caddy's Let's Encrypt TLS issuance will fail.
DOMAIN=CHANGE_ME.example.com
CADDY_EMAIL=CHANGE_ME@example.com

# ----- Google OAuth -----
GOOGLE_CLIENT_ID=CHANGE_ME
VITE_GOOGLE_CLIENT_ID=CHANGE_ME
ENVEOF
  chmod 600 "${ENV_FILE}"
fi

log "Bootstrap done."
echo
echo "Next steps:"
echo "  1. Edit ${ENV_FILE} on the server with real values (chmod already 600)."
echo "  2. On your Mac: bash scripts/setup-gh-secrets.sh --repo shode666/shotockviz"
echo "  3. Point DOMAIN's DNS A record at 188.166.234.146 (required before first deploy)."
echo "  4. Run the deploy workflow: gh workflow run deploy.yml --repo shode666/shotockviz"
