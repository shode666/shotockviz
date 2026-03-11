# Deploy ShotockViz to DigitalOcean Droplet

> Shares the same droplet as ShoDe Town (`town.shode.dev`).
> Caddy reverse proxy is managed by ShoDe Town — ShotockViz does not run its own.

## Prerequisites

- ShoDe Town already deployed on the droplet (Caddy handles TLS for both domains)
- `stock` A record pointing to the droplet IP
- SSH access via `Host do` in `~/.ssh/config`

## 1. DNS

Add an **A record** in your DNS provider:

| Host    | Type | Value          |
| ------- | ---- | -------------- |
| `stock` | A    | `<DROPLET_IP>` |

## 2. Add `stock.shode.dev` to ShoDe Town's Caddy

The `stock.shode.dev` block is in ShoDe Town's `infrastructure/caddy/Caddyfile.production`.
It proxies to `stockviz-backend:8000` and `stockviz-frontend:3000` via the `shared-proxy` Docker network.

After updating, redeploy ShoDe Town's Caddy:

```bash
cd /path/to/shode-town
make deploy
```

## 3. Production `.env` on Server

```bash
ssh do 'mkdir -p /root/shotockviz'
```

Create `/root/shotockviz/.env`:

```env
# Database
DATABASE_URL=postgresql+asyncpg://stockviz:<password>@db:5432/stockviz_prod
POSTGRES_USER=stockviz
POSTGRES_PASSWORD=<same-password>
POSTGRES_DB=stockviz_prod

# Redis
REDIS_URL=redis://redis:6379/0

# JWT
JWT_SECRET_KEY=<openssl rand -hex 32>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# External APIs
FINNHUB_API_KEY=<your-key>
TELEGRAM_BOT_TOKEN=<your-token>

# App
APP_ENV=production
DEBUG=False
WORKERS=2
CORS_ORIGINS=https://stock.shode.dev

# Timezone
TZ=Asia/Bangkok

# Domain
DOMAIN=stock.shode.dev

# Google OAuth
GOOGLE_CLIENT_ID=<your-client-id>
VITE_GOOGLE_CLIENT_ID=<your-client-id>
```

> ⚠️ `DATABASE_URL` must use `postgresql+asyncpg://` (not `postgresql://`)

Lock permissions:

```bash
ssh do 'chmod 600 /root/shotockviz/.env'
```

## 4. Deploy

```bash
cd /path/to/ShotockViz
bash scripts/deploy.sh
```

This runs `scripts/deploy.sh` which:

1. Ensures `shared-proxy` Docker network exists
2. **rsync** project files to droplet (excludes `.git`, `node_modules`, `.env`, etc.)
3. **docker compose build** + **up** (prod compose, no Caddy, no Ollama)
4. Runs database migrations
5. Health checks

## 5. First Deploy — Create Tables & Seed

```bash
# Create tables from SQLAlchemy models
ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml run --rm backend python -c "
import asyncio
from core.database import create_tables
asyncio.run(create_tables())
"'

# Stamp alembic to current
ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml run --rm backend alembic stamp head'

# Seed stock data
ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml run --rm backend python -m scripts.seed_stocks'
```

## 6. Verify

```bash
curl -sI https://stock.shode.dev/
ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml ps'
```

## 7. Update Google OAuth

Add to Google Cloud Console → OAuth Authorized JavaScript origins:

```
https://stock.shode.dev
```

---

## Architecture

```
Client (HTTPS)
    ↓
[ShoDe Town Caddy :443]  ← shared-proxy network
    ├─ town.shode.dev  → ShoDe Town services
    └─ stock.shode.dev → ShotockViz services
        ├─ /api/ws/*   → stockviz-backend:8000 (WebSocket)
        ├─ /api/ai/*   → stockviz-backend:8000 (SSE streaming)
        ├─ /api/*      → stockviz-backend:8000 (REST)
        └─ /*          → stockviz-frontend:3000 (Nitro SSR)
```

## Subsequent Deploys

```bash
bash scripts/deploy.sh
```

No need to redo steps 1–5.

---

## Useful Commands

| Command                                                                                           | Description          |
| ------------------------------------------------------------------------------------------------- | -------------------- |
| `bash scripts/deploy.sh`                                                                          | Deploy to production |
| `ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml ps'`                    | Show containers      |
| `ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml logs backend --tail=50'`| Backend logs         |
| `ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml logs celery-worker --tail=30'` | Celery logs    |
| `ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head'` | Run migrations |
| `ssh do 'cd /root/shotockviz && docker compose -f docker-compose.prod.yml exec db psql -U stockviz -d stockviz_prod'` | DB shell |

## Resource Limits (shared droplet)

| Service        | CPU   | RAM    |
| -------------- | ----- | ------ |
| backend        | 1.0   | 512MB  |
| celery-worker  | 0.5   | 256MB  |
| celery-beat    | 0.5   | 256MB  |
| frontend       | 0.5   | 256MB  |
| TimescaleDB    | —     | ~512MB |
| Redis          | —     | ~128MB |
| **Total**      |       | ~1.9GB |
