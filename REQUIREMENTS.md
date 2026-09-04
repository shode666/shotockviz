# ShotockViz — Software Requirements Specification (SRS)

**Version:** 2.0
**Date:** 2026-03-03
**Author:** ShotockViz Team
**Status:** Active (v0.1.3 BETA)

---

## 1. Overview

### 1.1 Product Vision

ShotockViz คือ self-hosted web application สำหรับติดตามและวิเคราะห์หุ้นจาก 10 ตลาดทั่วโลก (Thai SET/MAI, US NYSE/NASDAQ, Japan, Hong Kong, China, UK, Germany, France, Netherlands, Korea) พร้อมเครื่องมือ technical analysis, portfolio tracking, alerts, และ real-time price updates โดยไม่มีค่าใช้จ่ายรายเดือน — ทุกอย่าง run บน Docker ของผู้ใช้เอง

### 1.2 Target Users

| User Type | Description | Key Needs |
|-----------|-------------|-----------|
| Registered User | Login ด้วย Google Account | ดูกราฟ, ตีเส้น, watchlist, portfolio, alerts, screener |
| Admin | ผู้ดูแลระบบ | จัดการ users, ดู system health |

> Note: ไม่มี Guest access — ต้อง login ด้วย Google OAuth ก่อนใช้งานทุก feature

### 1.3 Tech Stack

| Layer | Technology | License |
|-------|-----------|---------|
| Frontend | React 19 + TanStack Start (SSR) + Vite 7 + Tailwind CSS 4 + Zustand 5 | MIT |
| Charts | TradingView Lightweight Charts v5 | Apache 2.0 |
| Backend | FastAPI (Python 3.13) + SQLAlchemy 2 + Pydantic 2 | MIT |
| WebSocket | FastAPI WebSocket + Redis Pub/Sub | MIT |
| Auth | Google OAuth One-Tap (`@react-oauth/google`) | MIT |
| Database | PostgreSQL 16 + TimescaleDB | Apache 2.0 |
| Cache | Redis 7 (L1 cache + Celery broker + WebSocket pub/sub) | BSD |
| Task Queue | Celery 5.6 + Beat (10 scheduled workers) | BSD |
| Alerts | Telegram Bot API + In-App | Free |
| Stock Data | yfinance + pythainav (Thai fund NAV) + Finnhub (free tier) | Free |
| DevOps | Docker + Docker Compose | Apache 2.0 |
| Reverse Proxy | Caddy 2 (auto TLS via Let's Encrypt) | Apache 2.0 |

All open source and free. No paid dependencies.

---

## 2. Functional Requirements

### 2.1 Authentication & Authorization

#### FR-AUTH-001: Google OAuth One-Tap Login
- Login ด้วย Google Account ผ่าน `@react-oauth/google` + `useGoogleOneTapLogin`
- Backend verify Google ID token → issue JWT access token
- First login สร้าง user record อัตโนมัติ (auto-register)
- ไม่มี email+password registration — Google OAuth เท่านั้น

#### FR-AUTH-002: Session Management
- JWT access token (expire ตาม config)
- Token refresh ผ่าน Google credential refresh
- Frontend ใช้ `useGoogleOneTapLogin` ใน `__root.tsx` สำหรับ seamless re-auth
- **ห้ามมี custom token management บน frontend** — ใช้ Google library จัดการทั้งหมด

#### FR-AUTH-003: Access Control

| Feature | Logged Out | Logged In |
|---------|-----------|-----------|
| ดูกราฟ + ราคา | ❌ | ✅ |
| Drawing Tools | ❌ | ✅ |
| Watchlist | ❌ | ✅ |
| Portfolio | ❌ | ✅ |
| Alerts | ❌ | ✅ |
| Screener | ❌ | ✅ |

---

### 2.2 Stock Data

#### FR-DATA-001: Supported Markets (10 ตลาด)

| Market | Suffix | Exchange | Trading Hours (ICT) | Currency |
|--------|--------|----------|---------------------|----------|
| SET | `.BK` | Stock Exchange of Thailand | Mon-Fri 10:00-16:30 (break 12:30-14:00) | THB ฿ |
| US | — | NYSE / NASDAQ | Mon-Fri 21:30-04:00 (next day) | USD $ |
| Japan | `.T` | Tokyo Stock Exchange | Mon-Fri 08:00-14:00 | JPY ¥ |
| Hong Kong | `.HK` | HKEX | Mon-Fri 09:30-16:00 | HKD HK$ |
| China | `.SS` `.SZ` | Shanghai / Shenzhen | Mon-Fri 09:30-15:00 | CNY ¥ |
| UK | `.L` | London Stock Exchange | Mon-Fri 15:00-23:30 | GBP £ |
| Germany | `.DE` | XETRA / Frankfurt | Mon-Fri 14:00-22:30 | EUR € |
| France | `.PA` | Euronext Paris | Mon-Fri 14:00-22:30 | EUR € |
| Netherlands | `.AS` | Euronext Amsterdam | Mon-Fri 14:00-22:30 | EUR € |
| Korea | `.KS` | Korea Exchange | Mon-Fri 09:00-15:30 | KRW ₩ |

Indices tracked: ^SET.BK, ^GSPC (S&P 500), ^IXIC (NASDAQ), ^DJI, ^N225 (Nikkei), ^HSI (Hang Seng), ^FTSE, ^GDAXI (DAX), ^FCHI (CAC 40), ^AEX, ^KS11 (KOSPI), plus THBUSD=X and GC=F (Gold).

#### FR-DATA-002: Price Data
- แหล่งข้อมูลหลัก: yfinance (ครอบคลุมทุก 10 ตลาด)
- ข้อมูล delayed ≤ 15 นาที (free tier limitation)
- เก็บ OHLCV (Open, High, Low, Close, Volume)
- รองรับ timeframes: 1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M

#### FR-DATA-003: Round-Robin Price Fetching (CQRS Write Side)
- Celery task `fetch_prices` runs ทุก 1 นาที
- หมุนสลับ 5 market slots: SET → US → Asia (JP/HK/CN/KR) → Europe (UK/DE/FR/NL) → Overview
- แต่ละตลาด update ทุก ~5 นาที
- ตลาดที่ปิดจะถูก auto-skip → ตลาดที่เปิดได้ update ถี่ขึ้น
- Backup: `fetch_overview_prices` ทุก 5 นาที (indices, USD/THB, Gold)

#### FR-DATA-004: CQRS Architecture
- **API (Read Side):** Pure-read endpoints — ดึงจาก Redis L1 → PostgreSQL L2 เท่านั้น ไม่เรียก external API
- **Celery (Write Side):** Sole data ingesters — ดึงจาก Yahoo Finance, pythainav, Finnhub แล้ว cache ลง Redis + DB
- **On Cache Miss:** API triggers Celery task via `request_data_fetch()` → worker fetches → caches → publishes WebSocket `data_ready` → frontend re-fetches อัตโนมัติ

#### FR-DATA-005: Thai-Specific Data
- XD Date (Ex-Dividend) แสดงเป็น marker บนกราฟ
- XR Date (Ex-Rights) แสดงเป็น marker บนกราฟ
- Thai mutual fund NAV via pythainav (daily at 19:00 ICT)

#### FR-DATA-006: Search & Autocomplete
- ค้นหาได้ด้วย symbol หรือ ชื่อบริษัท (Thai + English)
- Autocomplete dropdown แสดง top 10 ผลลัพธ์
- แสดง market badge (SET/US/JP/HK/UK/DE/CN/FR/NL/KR) พร้อมสีแยกตลาด
- แสดง currency code ข้างผลลัพธ์
- ใช้ keyboard shortcut `Ctrl+K` หรือ `Cmd+K` เปิด search

---

### 2.3 Charts

#### FR-CHART-001: Chart Types
- **Candlestick** (default)
- **Line**
- **Area**
- **Bar (OHLC)**

#### FR-CHART-002: Timeframes
- 1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M
- สลับ timeframe ได้ทันทีโดยไม่ต้อง reload หน้า
- แต่ละ timeframe ดึงจำนวน bars ที่เหมาะสม:
  - 1m → 1 วัน, 5m → 5 วัน, 15m → 15 วัน
  - 1h → 60 วัน, 4h → 120 วัน
  - 1D → 1 ปี, 1W → 3 ปี, 1M → 10 ปี

#### FR-CHART-003: Drawing Tools (Logged-in Users only)
- **Trend Line**: เส้นตรง 2 จุด
- **Horizontal Line**: เส้นแนวนอนที่ราคาที่กำหนด
- **Fibonacci Retracement**: 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%
- **Rectangle**: กล่องสี่เหลี่ยม highlight zone
- **Arrow**: ลูกศรชี้ขึ้น/ลง
- **Pitchfork (Andrew's Fork)**: 3 จุด

Drawing features:
- เปลี่ยนสี, ความหนาเส้น, line style (solid/dash/dot)
- ลบทีละเส้น หรือ ลบทั้งหมด
- บันทึก drawings per user per symbol per timeframe
- Undo/Redo (Ctrl+Z / Ctrl+Y)

#### FR-CHART-004: Crosshair & Tooltip
- Crosshair แสดง O, H, L, C, Volume ที่ position ของ mouse
- แสดงราคาและเวลาที่ Y-axis และ X-axis

#### FR-CHART-005: Compare Mode
- เปรียบเทียบ 2 หุ้นซ้อนกันบนกราฟเดียว (normalized %)
- เลือกสีแยกให้แต่ละหุ้น
- Legend แสดงชื่อทั้ง 2 ตัว

---

### 2.4 Technical Indicators

#### FR-IND-001: Overlay Indicators (บนกราฟราคา)
| Indicator | Parameters | Default |
|-----------|-----------|---------|
| SMA (Simple Moving Average) | Period | 20 |
| EMA (Exponential Moving Average) | Period | 50 |
| Bollinger Bands | Period, StdDev | 20, 2 |
| Ichimoku Cloud | Conversion, Base, Span | 9, 26, 52 |

#### FR-IND-002: Oscillator Indicators (panel แยกใต้กราฟ)
| Indicator | Parameters | Default |
|-----------|-----------|---------|
| RSI | Period | 14 |
| MACD | Fast, Slow, Signal | 12, 26, 9 |
| Stochastic | K, D, Smooth | 14, 3, 3 |
| Volume | — | — |

#### FR-IND-003: Indicator Management
- เพิ่ม/ลบ indicator ได้ทันที
- ปรับ parameter ได้ผ่าน settings panel
- เปลี่ยนสี indicator ได้

---

### 2.5 Watchlist

#### FR-WATCH-001: CRUD
- เพิ่มหุ้นเข้า watchlist (ไม่จำกัดจำนวน)
- ลบหุ้นออกจาก watchlist
- สร้างหลาย watchlist ได้ (เช่น "หุ้นไทย", "US Tech", "Japan Blue Chips")
- ลาก drag-and-drop เรียงลำดับ

#### FR-WATCH-002: Display
- แสดงราคาปัจจุบัน, % change, volume ใน sidebar
- สี เขียว = ขึ้น, แดง = ลง
- คลิกที่หุ้นเพื่อเปิดกราฟ
- Mini sparkline (optional)
- Market badge สีแยกตลาด

---

### 2.6 Portfolio Tracking

#### FR-PORT-001: Transaction Management
- เพิ่ม Buy/Sell transaction (symbol, qty, price, date, fee)
- แก้ไข/ลบ transaction
- รองรับทุกสกุลเงิน (THB, USD, JPY, HKD, GBP, EUR, CNY, KRW)
- Symbol autocomplete พร้อม auto-detect currency จากตลาด

#### FR-PORT-002: Analytics
- มูลค่าพอร์ตรวม (ราคาตลาดปัจจุบัน)
- กำไร/ขาดทุน (Unrealized P&L) per stock + รวม
- % allocation pie chart
- Fundamental overlay: P/E, P/BV, Dividend Yield, Market Cap

#### FR-PORT-003: Risk Metrics
- **Sharpe Ratio**: ผลตอบแทนต่อความเสี่ยง
- **Max Drawdown**: ขาดทุนสูงสุดจาก peak
- **Beta**: ความสัมพันธ์กับตลาด

---

### 2.7 Alerts

#### FR-ALERT-001: Alert Types
| Type | Description | Example |
|------|-------------|---------|
| Price Above | ราคาขึ้นเกิน target | PTT.BK > ฿38.00 |
| Price Below | ราคาลงต่ำกว่า target | AAPL < $170.00 |
| RSI Overbought | RSI > threshold | NVDA RSI > 70 |
| RSI Oversold | RSI < threshold | 7203.T RSI < 30 |
| MACD Golden Cross | MACD line ตัดขึ้น | — |
| MACD Death Cross | MACD line ตัดลง | — |
| Volume Spike | Volume > X เท่าของค่าเฉลี่ย | Volume > 3x avg |

#### FR-ALERT-002: Notification Channels
- **Telegram Bot**: primary channel (ฟรี, ไม่จำกัด)
- **In-App Notification**: แสดงใน alerts panel

#### FR-ALERT-003: Alert Management
- Symbol autocomplete พร้อม market badge + currency display
- Currency prefix บน value input (฿, $, ¥, £, €, ₩)
- สร้าง/แก้ไข/ลบ alert
- เปิด/ปิด alert ได้ (toggle active/inactive)
- สถานะ: Active, Triggered, Expired

---

### 2.8 Stock Screener

#### FR-SCREEN-001: Filter Criteria
- **Market**: SET, US, JP, HK, UK, DE, CN, FR, NL, KR, หรือทั้งหมด
- **Price Range**: min-max
- **P/E Ratio**: min-max
- **RSI**: min-max
- **MACD Signal**: Buy / Sell / Neutral
- **Volume**: X เท่าของค่าเฉลี่ย

#### FR-SCREEN-002: Results
- แสดงตาราง results พร้อม columns ที่กรอง
- คลิกที่ row เปิดกราฟหุ้นนั้น
- บันทึก filter preset ได้ per user

---

### 2.9 News Feed

#### FR-NEWS-001: Sources
- **Google News RSS**: ข่าวทั่วไป Thai + International
- **Finnhub News API**: ข่าวหุ้น US (free tier)
- Filter by: market, symbol, watchlist

#### FR-NEWS-002: Sentiment Badge
- วิเคราะห์ sentiment: Positive / Negative / Neutral (keyword-derived จาก title)
- แสดง sentiment badge ข้างข่าว

---

### 2.11 Fundamental Data

#### FR-FUND-001: Key Metrics
- P/E, P/BV, EPS, Dividend Yield, Market Cap
- ดึงจาก yfinance (ครอบคลุมทุก 10 ตลาด)
- Prefetch ทุก 4 ชั่วโมงโดย Celery worker

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Metric | Target |
|--------|--------|
| API Response Time (P95) | < 5 วินาที (cache-only reads) |
| Chart Render Time | < 500ms |
| WebSocket Latency | < 100ms |
| Max Concurrent Users | 50 (self-hosted) |

### 3.2 Database Housekeeping

เพื่อลดขนาด database ระบบจะ compress ข้อมูลเก่าอัตโนมัติ:

| Age | Resolution | Action |
|-----|-----------|--------|
| < 7 วัน | 1-minute bars | เก็บ raw data |
| 7 – 90 วัน | 5-minute bars | Aggregate แล้วลบ 1-min data |
| 90 วัน – 2 ปี | 1-day bars | Aggregate แล้วลบ 5-min data |
| > 2 ปี | 1-week bars | Aggregate แล้วลบ 1-day data |

Implementation: Celery beat runs `run_housekeeping` ทุกวัน 03:00 ICT. ใช้ TimescaleDB hypertables with auto-compression.

### 3.3 Security

| Area | Requirement |
|------|------------|
| Auth | Google OAuth One-Tap (no custom password management) |
| HTTPS | บังคับใน production (Caddy auto TLS via Let's Encrypt) |
| CORS | Whitelist frontend origin เท่านั้น |
| SQL Injection | ใช้ parameterized queries / ORM (SQLAlchemy) เท่านั้น |
| XSS | Sanitize ทุก user input, Content-Security-Policy header |
| Rate Limiting | Per IP + per user ด้วย Redis |
| Secrets | เก็บใน .env, ห้าม commit เข้า git |
| Container | Run as non-root user |

### 3.4 Reliability

- CQRS pattern: API pure-read จาก cache/DB → ไม่มี external API dependency ใน request path
- Graceful degradation: ถ้า yfinance ล่ม → Celery retry 3 ครั้ง ด้วย exponential backoff
- Cache stale-while-revalidate: แสดง cached data + background refresh
- WebSocket auto-reconnect ด้วย exponential backoff (1s, 2s, 4s, 8s, max 30s)
- Health check endpoint: `GET /api/health`

### 3.5 Scalability

- Stateless backend: horizontal scaling ได้ถ้าต้องการ
- Database connection pooling (asyncpg)
- Redis caching สำหรับ hot data (ราคาปัจจุบัน, search results)
- Cache TTL: ราคาหุ้น 60 วินาที, search results 5 นาที, fundamentals 4 ชั่วโมง

---

## 4. UI/UX Requirements

### 4.1 Design System

| Element | Specification |
|---------|--------------|
| Theme | Dark mode (default) + Light mode toggle |
| Colors | Deep navy bg (#0d0f17), Violet accent (#6366f1) |
| Border Radius | 12px–16px (rounded-xl/2xl) |
| Typography | Inter font, system fallback |
| Glass Effect | backdrop-blur panels (glassmorphism) |
| Animations | 200ms ease transitions |
| Density | Compact — maximize data density |

### 4.2 Layout

```
┌─────────────────────────────────────────────────┐
│ Top Nav: Logo | Tabs | Search | Theme | User    │
├──────┬──────────────────────────────┬───────────┤
│ Side │          Main Chart          │  Right    │
│ bar  │                              │  Panel    │
│      │  Toolbar: TF | Type | Ind    │  (Stats,  │
│ Watch│  Drawing: Tools              │  Alert,   │
│ list │                              │  RSI)     │
│      │  ┌──────────────────────┐    │           │
│      │  │  Candlestick Chart   │    │           │
│      │  │  + Overlays          │    │           │
│      │  │  + Volume            │    │           │
│      │  └──────────────────────┘    │           │
│      ├──────────────────────────────┤           │
│      │ Bottom: News | Port | Fund   │           │
├──────┴──────────────────────────────┴───────────┤
│ Status Bar: Live | Last Update | Version        │
└─────────────────────────────────────────────────┘
```

### 4.3 Responsive

- **Primary**: Desktop (≥ 1280px) — full layout
- **Secondary**: Tablet (768px–1279px) — collapse sidebar
- **Optional**: Mobile (< 768px) — stack layout (future phase)

---

## 5. Docker & Deployment

### 5.1 Development Mode

```yaml
# docker-compose.dev.yml — 8+ services
- Frontend: TanStack Start SSR + Vite dev server (HMR)
- Backend: Uvicorn --reload (auto-restart on code change)
- Database: PostgreSQL 16 + TimescaleDB
- Redis: Cache + Celery broker + WebSocket pub/sub
- Celery Worker: 10 scheduled tasks
- Celery Beat: Task scheduler
- Caddy: Reverse proxy + auto self-signed TLS
```

### 5.2 Production Mode

```yaml
# docker-compose.prod.yml
- Frontend: TanStack Start SSR (Nitro production build)
- Backend: Uvicorn + Gunicorn (4 workers)
- Database: PostgreSQL + TimescaleDB (persistent volume)
- Redis: Persistent volume
- Caddy: Reverse proxy + auto Let's Encrypt TLS
- Celery Worker + Beat
```

### 5.3 Environment Variables

```env
# Required
DATABASE_URL=postgresql://user:pass@db:5432/stockviz
REDIS_URL=redis://redis:6379/0
JWT_SECRET_KEY=<random-256-bit-key>
GOOGLE_CLIENT_ID=<your-google-client-id>.apps.googleusercontent.com

# Optional — enhances features
FINNHUB_API_KEY=<free-tier-key>
TELEGRAM_BOT_TOKEN=<from-botfather>
TZ=Asia/Bangkok
```

---

## 6. API Endpoints

### 6.1 Auth
```
POST   /api/auth/google          → Google OAuth token verification
GET    /api/auth/me               → Current user info
```

### 6.2 Stocks
```
GET    /api/stocks/search?q={query}
GET    /api/stocks/{symbol}/quote
GET    /api/stocks/{symbol}/history?tf={timeframe}
GET    /api/stocks/{symbol}/fundamentals
GET    /api/stocks/{symbol}/news
WS     /api/ws/prices             → Subscribe to realtime price updates
```

### 6.3 Watchlist
```
GET    /api/watchlists
POST   /api/watchlists
PUT    /api/watchlists/{id}
DELETE /api/watchlists/{id}
POST   /api/watchlists/{id}/stocks
DELETE /api/watchlists/{id}/stocks/{symbol}
```

### 6.4 Portfolio
```
GET    /api/portfolio
GET    /api/portfolio/analytics
POST   /api/portfolio/transactions
PUT    /api/portfolio/transactions/{id}
DELETE /api/portfolio/transactions/{id}
```

### 6.5 Alerts
```
GET    /api/alerts
POST   /api/alerts
PUT    /api/alerts/{id}
DELETE /api/alerts/{id}
PATCH  /api/alerts/{id}/toggle
```

### 6.6 Screener
```
POST   /api/screener/run          → body: filter conditions
GET    /api/screener/presets
POST   /api/screener/presets
DELETE /api/screener/presets/{id}
```

### 6.7 Drawings
```
GET    /api/drawings/{symbol}?tf={timeframe}
POST   /api/drawings/{symbol}
PUT    /api/drawings/{id}
DELETE /api/drawings/{id}
```

### 6.9 Dashboard
```
GET    /api/dashboard              → Indices, portfolio summary, alerts, movers
```

### 6.10 System
```
GET    /api/health
GET    /api/system/celery-stats
```

---

## 7. Celery Workers (CQRS Write Side)

| Worker | Schedule | What it does |
|--------|----------|-------------|
| `fetch_prices` | Every 1 min | Round-robin price fetch across 5 market slots |
| `fetch_overview_prices` | Every 5 min | Indices, USD/THB, Gold (backup) |
| `check_all_alerts` | Every 60s | Check active alerts against cached prices |
| `prefetch_names` | Every 6h | Company names for all watched symbols |
| `prefetch_fundamentals` | Every 4h | P/E, P/BV, EPS, dividend yield |
| `fetch_thai_fund_navs` | Daily 19:00 ICT | Thai mutual fund NAVs via pythainav |
| `prefetch_history` | Every 30 min | Warm OHLCV cache for charts |
| `scan_unregistered` | Every 15 min | Auto-register new user-added symbols |
| `populate_index_constituents` | Weekly (Sunday) | Refresh index constituents from Wikipedia |
| `run_housekeeping` | Daily 03:00 ICT | Compress old price data (1m → 5m → 1d → 1w) |

---

## 8. Database Schema

### 8.1 Core Tables

```sql
-- Users (via Google OAuth)
users (id, google_id, email, display_name, avatar_url, role, created_at, updated_at)

-- Stock metadata
stocks (id, symbol, name, name_th, market, sector, is_active)

-- Price data (TimescaleDB hypertable)
stock_prices_1m (time, symbol, open, high, low, close, volume)
ohlcv_bars (time, symbol, timeframe, open, high, low, close, volume)

-- Watchlists
watchlists (id, user_id, name, sort_order, created_at)
watchlist_items (id, watchlist_id, symbol, sort_order, added_at)

-- Portfolio
transactions (id, user_id, symbol, type[BUY/SELL], qty, price, fee, currency, date, note)

-- Alerts
alerts (id, user_id, symbol, alert_type, condition, value, is_active, triggered_at, channel)

-- Drawings
drawings (id, user_id, symbol, timeframe, tool_type, data_json, style_json, created_at, updated_at)

-- Screener presets
screener_presets (id, user_id, name, filters_json, created_at)

-- Events (XD, XR dates)
stock_events (id, symbol, event_type, event_date, value, description)

-- Notes
notes (id, user_id, symbol, content, created_at, updated_at)
```

---

## 9. Milestones

### Phase 1 — MVP: ✅ Complete (v0.1.0)
- Docker Compose dev + prod stack
- Google OAuth login
- Stock data fetching (yfinance)
- Candlestick/line/area/bar charts + 8 timeframes
- Technical indicators (MA, EMA, RSI, MACD, BB, Stochastic, Ichimoku)
- Drawing tools (6 types)
- Watchlist CRUD
- Search autocomplete
- Dark mode UI
- DB Housekeeping

### Phase 2 — Features: ✅ Complete (v0.1.3)
- CQRS architecture (API pure-read, Celery write)
- 10 international markets
- Round-robin price fetcher
- Portfolio tracking + analytics
- Alert system + Telegram notification
- News feed (RSS + Finnhub + sentiment badges)
- Stock screener
- Fundamental data panel
- Symbol autocomplete with market badges + currency

### Phase 3 — Polish (In Progress)
- Thai fund NAV integration
- Backtesting
- Compare mode enhancement
- Export CSV
- Performance optimization

---

## 10. Out of Scope (for now)

- Mobile app (React Native / Flutter)
- Real-time 0-delay data (requires exchange license)
- Crypto / Forex markets
- Social trading / idea sharing
- Broker integration (auto-trading)
- Cloud deployment (AWS/GCP)
- SMS notifications

---

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| yfinance API ล่ม/เปลี่ยน | ดึงข้อมูลไม่ได้ | CQRS: API ไม่พัง เพราะ read จาก cache/DB, Celery retry 3x |
| Finnhub free tier quota หมด | ข่าว US ขาด | ใช้ Google News RSS เป็น fallback |
| TimescaleDB performance | Query ช้า | Hypertable compression + housekeeping worker |
| Docker resource usage สูง | เครื่อง user ช้า | Optimize container limits, lazy loading |
| Google OAuth outage | Login ไม่ได้ | JWT token ยัง valid จนหมดอายุ, cache user session |

---

*End of Document*
