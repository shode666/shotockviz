# ShotockViz — Production Deployment Guide

> Version 0.1.3 BETA · Updated 2026-03-02

ขั้นตอนนี้ครอบคลุมการ pack production build และ deploy ขึ้น production server ตั้งแต่ต้นจนรันได้จริง

---

## Prerequisites (สิ่งที่ต้องมีก่อน)

| ข้อกำหนด | รายละเอียด |
|---------|-----------|
| **Production server** | Ubuntu 22.04 LTS แนะนำ, RAM ≥ 4GB (8GB ถ้ารัน Ollama), Disk ≥ 50GB |
| **Docker Engine** | ≥ 26.x + Docker Compose v2 (`docker compose` ไม่ใช่ `docker-compose`) |
| **Domain name** | ชี้ A record ไปที่ IP server ก่อน เพราะ Caddy ต้องการ DNS propagate แล้วถึงออก TLS cert ได้ |
| **Ports** | 80, 443 เปิดใน firewall (ufw allow 80 && ufw allow 443) |
| **Git access** | server ต้อง clone repo ได้ หรือ rsync ก็ได้ |
| **Google OAuth** | ต้องเพิ่ม production domain ใน Google Cloud Console → OAuth Authorized JS origins |

---

## Step 1 — ส่ง Code ขึ้น Server

### Option A: Git (แนะนำ)
```bash
# บน production server
git clone https://github.com/your-org/ShotockViz.git /opt/shotviz
cd /opt/shotviz
git checkout main   # หรือ release branch
```

### Option B: rsync จาก local machine
```bash
# รันบน local machine (ไม่รวม node_modules, __pycache__, .git)
rsync -avz --exclude='.git' \
           --exclude='node_modules' \
           --exclude='__pycache__' \
           --exclude='*.pyc' \
           --exclude='.env' \
           ./ShotockViz/ user@your-server:/opt/shotviz/
```

> ⚠️ **อย่า rsync ไฟล์ `.env`** — ให้สร้างใหม่บน server ทุกครั้ง

---

## Step 2 — สร้างไฟล์ `.env` บน Production Server

```bash
cd /opt/shotviz
cp .env.example .env
nano .env   # หรือ vim
```

ค่าที่ **ต้องเปลี่ยน** จาก dev:

```env
# ===== DATABASE =====
POSTGRES_USER=shotviz_prod
POSTGRES_PASSWORD=<strong-random-password>   # อย่าใช้ค่า dev
POSTGRES_DB=shotviz_prod
DATABASE_URL=postgresql://shotviz_prod:<password>@db:5432/shotviz_prod

# ===== REDIS =====
REDIS_URL=redis://redis:6379/0

# ===== SECURITY =====
JWT_SECRET_KEY=<64-char-random-string>       # openssl rand -hex 32

# ===== DOMAIN (สำคัญมาก) =====
DOMAIN=shotviz.yourdomain.com               # ไม่ใส่ https://
CADDY_EMAIL=admin@yourdomain.com            # Caddy ใช้สมัคร Let's Encrypt

# ===== GOOGLE OAUTH =====
VITE_GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<your-secret>          # ถ้า backend verify

# ===== CORS =====
CORS_ORIGINS=https://shotviz.yourdomain.com

# ===== EXTERNAL APIs =====
FINNHUB_API_KEY=<your-finnhub-key>
TELEGRAM_BOT_TOKEN=<your-bot-token>         # optional

# ===== OLLAMA =====
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2                       # หรือ llama3.2:1b ถ้า RAM น้อย

# ===== APP =====
TZ=Asia/Bangkok
WORKERS=4                                   # gunicorn workers = (2 × CPU cores) + 1
```

ล็อก permission ไฟล์:
```bash
chmod 600 .env
```

---

## Step 3 — Build Docker Images

Build ทุก service พร้อมกัน (ใช้เวลา 5-15 นาทีแรกรัน):

```bash
cd /opt/shotviz

# Build ทุก service ที่มี Dockerfile (backend, frontend, caddy)
docker compose -f docker-compose.prod.yml build --no-cache

# หรือ build ทีละ service ถ้าอยากดู log ชัดๆ
docker compose -f docker-compose.prod.yml build backend
docker compose -f docker-compose.prod.yml build frontend
docker compose -f docker-compose.prod.yml build caddy
```

> 📝 `--no-cache` ทำให้ build ใหม่ทั้งหมด ปลอดภัยกว่าสำหรับ production deploy ครั้งแรก

---

## Step 4 — Start Database และ Redis ก่อน

เริ่ม infra services ก่อนให้ healthcheck ผ่าน:

```bash
docker compose -f docker-compose.prod.yml up -d db redis

# รอ healthcheck ผ่าน (~10-20s)
docker compose -f docker-compose.prod.yml ps
# ดูให้ db และ redis แสดง "healthy"
```

---

## Step 5 — Run Database Migrations

```bash
# เข้าไปใน backend container ชั่วคราว
docker compose -f docker-compose.prod.yml run --rm backend \
  alembic upgrade head
```

ถ้ายังไม่มี alembic migration (first deploy):
```bash
# สร้าง schema ตรงๆ จาก SQLAlchemy models
docker compose -f docker-compose.prod.yml run --rm backend \
  python -c "from core.database import Base, engine; Base.metadata.create_all(engine)"
```

---

## Step 6 — Seed ข้อมูล Initial

```bash
# Seed หุ้นเริ่มต้น (SET + US symbols)
docker compose -f docker-compose.prod.yml run --rm backend \
  python scripts/seed_stocks.py

# Seed international markets (JP/HK/UK/DE/CN/FR/NL/KR) จาก Wikipedia
docker compose -f docker-compose.prod.yml run --rm backend \
  python scripts/fetch_real_constituents.py
```

---

## Step 7 — Start ทุก Services

```bash
docker compose -f docker-compose.prod.yml up -d

# ดู log real-time เพื่อตรวจ startup
docker compose -f docker-compose.prod.yml logs -f --tail=100
```

**ลำดับ startup ที่ถูกต้อง** (Docker Compose จัดการ `depends_on` ให้อัตโนมัติ):
```
db → redis → backend → celery-worker + celery-beat → frontend → caddy
```

Caddy จะ auto-obtain TLS certificate จาก Let's Encrypt เมื่อ DNS ชี้ถูก ใช้เวลา ~30s ครั้งแรก

---

## Step 8 — Pull Ollama Model (ครั้งแรกใช้เวลานาน)

```bash
# ดู log ollama เพื่อรอ model download เสร็จ
docker compose -f docker-compose.prod.yml logs -f ollama
# จะเห็น "Model ready. Ollama is running." เมื่อเสร็จ

# หรือ pull manual แล้วรอ
docker compose -f docker-compose.prod.yml exec ollama ollama pull llama3.2
```

> ⚠️ llama3.2 ขนาด ~2GB ถ้า bandwidth ช้าอาจใช้เวลาหลายนาที

---

## Step 9 — Verify ระบบทำงานถูกต้อง

```bash
# 1. ดูสถานะทุก container
docker compose -f docker-compose.prod.yml ps

# 2. Health check API
curl -s https://shotviz.yourdomain.com/api/health | python3 -m json.tool

# 3. ตรวจ backend logs หา errors
docker compose -f docker-compose.prod.yml logs backend --tail=50

# 4. ตรวจ Celery ทำงานไหม
docker compose -f docker-compose.prod.yml logs celery-worker --tail=30

# 5. ตรวจ database connection
docker compose -f docker-compose.prod.yml exec db \
  psql -U shotviz_prod -d shotviz_prod -c "\dt"
```

Expected healthy output จาก `/api/health`:
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "celery": "active"
}
```

---

## Step 10 — ทดสอบ Frontend

เปิด browser ไปที่ `https://shotviz.yourdomain.com`:

- [ ] HTTPS lock icon ปรากฏ (Let's Encrypt cert)
- [ ] หน้า Login โหลด, Google One-Tap ทำงาน
- [ ] Chart โหลดข้อมูล PTT.BK / AAPL ได้
- [ ] WebSocket price update ทำงาน (ดูที่ราคาในตลาดเวลา)
- [ ] AI Chat ตอบสนองได้ (stream ข้อความเห็น)

---

## Operations — คำสั่งที่ใช้บ่อย

```bash
# ดู logs service ใดก็ได้
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f celery-worker

# Restart service เดียว (ไม่ต้อง down ทั้งหมด)
docker compose -f docker-compose.prod.yml restart backend

# Update code + redeploy backend
git pull origin main
docker compose -f docker-compose.prod.yml build backend
docker compose -f docker-compose.prod.yml up -d backend

# Update frontend (ต้อง rebuild เสมอ เพราะ bundle อยู่ใน image)
git pull origin main
docker compose -f docker-compose.prod.yml build frontend
docker compose -f docker-compose.prod.yml up -d frontend

# Backup database
docker compose -f docker-compose.prod.yml exec db \
  pg_dump -U shotviz_prod shotviz_prod | gzip > backup_$(date +%Y%m%d).sql.gz

# เปิด psql prompt
docker compose -f docker-compose.prod.yml exec db \
  psql -U shotviz_prod -d shotviz_prod

# ดู Redis cache stats
docker compose -f docker-compose.prod.yml exec redis \
  redis-cli info stats | grep -E "keyspace_hits|keyspace_misses"

# ดู Celery stats (จาก monitoring endpoint ที่เพิ่มล่าสุด)
curl -s https://shotviz.yourdomain.com/api/system/celery-stats | python3 -m json.tool
```

---

## Update Code (Rolling Deploys)

สำหรับ production update ทั่วไปหลัง deploy ครั้งแรก:

```bash
cd /opt/shotviz
git pull origin main                  # ดึง code ใหม่

# ถ้ามีการเปลี่ยน backend หรือ schema:
docker compose -f docker-compose.prod.yml build backend celery-worker celery-beat
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.prod.yml up -d backend celery-worker celery-beat

# ถ้ามีการเปลี่ยน frontend:
docker compose -f docker-compose.prod.yml build frontend
docker compose -f docker-compose.prod.yml up -d frontend

# ถ้าเปลี่ยน Caddy config:
docker compose -f docker-compose.prod.yml build caddy
docker compose -f docker-compose.prod.yml up -d caddy
```

> 💡 **Zero-downtime tip:** Restart backend ก่อน → Caddy จะ retry connection ให้อัตโนมัติ ผู้ใช้จะเห็น downtime < 5s เท่านั้น

---

## Troubleshooting

| อาการ | สาเหตุ | วิธีแก้ |
|------|--------|--------|
| HTTPS ไม่ออก cert | DNS ยังไม่ propagate | รอ 5-10 นาที, ตรวจ `dig shotviz.yourdomain.com` |
| Backend `502 Bad Gateway` | Backend container crash | `docker logs shotviz-backend-1` ดู traceback |
| Frontend โหลดช้า / 404 | Image เก่า ยังไม่ rebuild | `docker compose build frontend && up -d frontend` |
| Celery ไม่รัน task | Redis ไม่ connect | ตรวจ `REDIS_URL` ใน `.env` ให้ตรงกับ service name `redis` |
| Ollama timeout | RAM ไม่พอหรือ model ยัง download | เพิ่ม RAM หรือใช้ `llama3.2:1b` แทน |
| Google Login loop | OAuth origin ไม่ถูก | เพิ่ม `https://shotviz.yourdomain.com` ใน Google Cloud Console |
| DB migration fail | Schema version conflict | ดู `alembic history` และ `alembic current` |

---

## Security Checklist ก่อน Go-Live

- [ ] `.env` มี permission `600` (ไม่ world-readable)
- [ ] `JWT_SECRET_KEY` เป็น random 64+ chars (`openssl rand -hex 32`)
- [ ] `POSTGRES_PASSWORD` แข็งแกร่ง
- [ ] `DEBUG=False` ใน env (production compose ตั้งไว้แล้ว)
- [ ] Firewall เปิดเฉพาะ port 80, 443 (ไม่ expose 8000, 5432, 6379 ออกนอก)
- [ ] Google OAuth → Production client ID (ไม่ใช้ development client)
- [ ] `CORS_ORIGINS` ชี้เฉพาะ domain production เท่านั้น
- [ ] ตั้ง cron backup database รายวัน

---

## Resource Requirements (Minimum vs Recommended)

| Service | Minimum | Recommended |
|---------|---------|-------------|
| Frontend (SSR) | 256MB RAM | 512MB RAM |
| Backend (4 workers) | 512MB RAM | 1GB RAM |
| PostgreSQL + TimescaleDB | 512MB RAM | 1GB RAM |
| Redis | 128MB RAM | 256MB RAM |
| Celery (worker + beat) | 256MB RAM | 512MB RAM |
| Ollama (llama3.2) | 4GB RAM | 8GB RAM |
| **รวม** | **~6GB** | **~12GB** |

> ถ้า server RAM น้อยกว่า 8GB ให้ใช้ `llama3.2:1b` (1B params, ~1GB RAM) แทน default 3B

