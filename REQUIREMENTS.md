# StockViz — Software Requirements Specification (SRS)

**Version:** 1.0
**Date:** 2026-02-24
**Author:** StockViz Team
**Status:** Draft

---

## 1. Overview

### 1.1 Product Vision

StockViz คือ self-hosted web application สำหรับติดตามและวิเคราะห์หุ้นไทย (SET/mai) และหุ้นอเมริกา (NYSE/NASDAQ) พร้อมเครื่องมือ technical analysis, portfolio tracking, และ AI-powered features โดยไม่มีค่าใช้จ่ายรายเดือน — ทุกอย่าง run บน Docker ของผู้ใช้เอง

### 1.2 Target Users

| User Type | Description | Key Needs |
|-----------|-------------|-----------|
| Guest | ผู้เยี่ยมชมที่ไม่ได้ login | ดูกราฟ, ราคา, ข่าว |
| Registered User | สมัครแล้ว login แล้ว | ตีเส้นกราฟ, watchlist, portfolio, alerts |
| Admin | ผู้ดูแลระบบ | จัดการ users, ดู system health |

### 1.3 Tech Stack

| Layer | Technology | License |
|-------|-----------|---------|
| Frontend | React 19 + Vite 7 + Tailwind CSS 4 | MIT |
| Charts | TradingView Lightweight Charts v5 | Apache 2.0 |
| Backend | FastAPI 0.131 (Python 3.13+ / uv) | MIT |
| WebSocket | FastAPI WebSocket | MIT |
| Auth | JWT (PyJWT) + bcrypt 5 | MIT / Apache |
| Database | PostgreSQL 16 + TimescaleDB | Apache 2.0 |
| Cache | Redis 7 | BSD |
| Task Queue | Celery 5.6 + Redis Broker | BSD |
| Alerts | Telegram Bot API | Free |
| Stock Data | yfinance + Finnhub Free Tier | Free |
| AI (optional) | Ollama (local LLM) | MIT |
| DevOps | Docker + Docker Compose | Apache 2.0 |
| Reverse Proxy | Nginx | BSD |

---

## 2. Functional Requirements

### 2.1 Authentication & Authorization

#### FR-AUTH-001: User Registration
- ผู้ใช้สามารถสมัครสมาชิกด้วย email + password
- Password ต้องมีอย่างน้อย 8 ตัวอักษร, 1 ตัวพิมพ์ใหญ่, 1 ตัวเลข
- Email ต้อง unique ในระบบ
- Hash password ด้วย bcrypt (cost factor ≥ 12)

#### FR-AUTH-002: Login / Logout
- Login ด้วย email + password
- ออก JWT access token (expire 15 นาที) + refresh token (expire 7 วัน)
- Refresh token rotation: ใช้ refresh token ได้ครั้งเดียว ออกอันใหม่ทุกครั้ง
- Logout ทำให้ refresh token ถูก revoke

#### FR-AUTH-003: Role-Based Access

| Feature | Guest | User | Admin |
|---------|-------|------|-------|
| ดูกราฟ + ราคา | ✅ | ✅ | ✅ |
| ดู Indicators | ✅ | ✅ | ✅ |
| ดูข่าว | ✅ | ✅ | ✅ |
| ค้นหาหุ้น | ✅ | ✅ | ✅ |
| Drawing Tools | ❌ | ✅ | ✅ |
| Watchlist | ❌ | ✅ | ✅ |
| Portfolio | ❌ | ✅ | ✅ |
| Alerts | ❌ | ✅ | ✅ |
| Screener | ❌ | ✅ | ✅ |
| Backtesting | ❌ | ✅ | ✅ |
| Export CSV | ❌ | ✅ | ✅ |
| User Management | ❌ | ❌ | ✅ |
| System Health | ❌ | ❌ | ✅ |

#### FR-AUTH-004: Rate Limiting
- Guest: 30 requests/min
- User: 120 requests/min
- Admin: 300 requests/min
- Login endpoint: 5 attempts / 15 นาที per IP

---

### 2.2 Stock Data

#### FR-DATA-001: Supported Markets
- **Thai Market (SET/mai)**: suffix `.BK` via yfinance (เช่น PTT.BK, CPALL.BK)
- **US Market (NYSE/NASDAQ)**: ไม่มี suffix via yfinance (เช่น AAPL, NVDA)
- **Market Indices**: SET Index, S&P 500, NASDAQ Composite, Dow Jones

#### FR-DATA-002: Price Data
- ดึงข้อมูลจาก yfinance เป็นหลัก, Finnhub เป็น fallback
- ข้อมูล delayed ≤ 15 นาที (free tier limitation)
- เก็บ OHLCV (Open, High, Low, Close, Volume)
- รองรับ timeframes: 1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M

#### FR-DATA-003: Data Fetching Schedule
- ช่วงตลาดเปิด: ดึงราคาทุก 1 นาที (via Celery beat)
- **SET**: จันทร์–ศุกร์ 09:30–16:30 ICT (พักเที่ยง 12:30–14:00)
- **US**: จันทร์–ศุกร์ 09:30–16:00 ET (= 21:30–04:00 ICT+1)
- ช่วงตลาดปิด: ไม่ดึงข้อมูล (ประหยัด API quota)

#### FR-DATA-004: Thai-Specific Data
- XD Date (Ex-Dividend) แสดงเป็น marker บนกราฟ
- XR Date (Ex-Rights) แสดงเป็น marker บนกราฟ
- Dividend amount แสดงเป็น tooltip
- ข้อมูลจาก SET website (scraping) หรือ yfinance

#### FR-DATA-005: Search & Autocomplete
- ค้นหาได้ด้วย symbol หรือ ชื่อบริษัท (ภาษาไทย + อังกฤษ)
- Autocomplete dropdown แสดง top 10 ผลลัพธ์
- แสดง market badge (SET / US) ในผลลัพธ์
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
- แต่ละ timeframe ดึงข้อมูลจำนวน bars ที่เหมาะสม:
  - 1m → 1 วัน
  - 5m → 5 วัน
  - 15m → 15 วัน
  - 1h → 60 วัน
  - 4h → 120 วัน
  - 1D → 1 ปี
  - 1W → 3 ปี
  - 1M → 10 ปี

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
- Tooltip สำหรับ markers (XD date, alerts, etc.)

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
| VWAP | — | — |
| Ichimoku Cloud | Conversion, Base, Span | 9, 26, 52 |

#### FR-IND-002: Oscillator Indicators (panel แยกใต้กราฟ)
| Indicator | Parameters | Default |
|-----------|-----------|---------|
| RSI | Period | 14 |
| MACD | Fast, Slow, Signal | 12, 26, 9 |
| Stochastic | K, D, Smooth | 14, 3, 3 |
| ATR | Period | 14 |
| Volume | — | — |

#### FR-IND-003: Indicator Management
- เพิ่ม/ลบ indicator ได้ทันที
- ปรับ parameter ได้ผ่าน settings panel
- เปลี่ยนสี indicator ได้
- เก็บ indicator settings per user per chart

---

### 2.5 Watchlist

#### FR-WATCH-001: CRUD
- เพิ่มหุ้นเข้า watchlist (ไม่จำกัดจำนวน)
- ลบหุ้นออกจาก watchlist
- สร้างหลาย watchlist ได้ (เช่น "หุ้นไทย", "US Tech")
- ลาก drag-and-drop เรียงลำดับ

#### FR-WATCH-002: Display
- แสดงราคาปัจจุบัน, % change, volume ใน sidebar
- สี เขียว = ขึ้น, แดง = ลง
- คลิกที่หุ้นเพื่อเปิดกราฟ
- Mini sparkline (optional)

---

### 2.6 Portfolio Tracking

#### FR-PORT-001: Transaction Management
- เพิ่ม Buy/Sell transaction (symbol, qty, price, date, fee)
- แก้ไข/ลบ transaction
- รองรับทั้งหุ้นไทย (THB) และหุ้น US (USD)

#### FR-PORT-002: Analytics
- มูลค่าพอร์ตรวม (ราคาตลาดปัจจุบัน)
- กำไร/ขาดทุน (Unrealized P&L) per stock + รวม
- % allocation pie chart
- P&L chart ย้อนหลัง

#### FR-PORT-003: Risk Metrics
- **Sharpe Ratio**: ผลตอบแทนต่อความเสี่ยง
- **Max Drawdown**: ขาดทุนสูงสุดจาก peak
- **Beta**: ความสัมพันธ์กับตลาด (SET หรือ S&P500)
- **Correlation Heatmap**: ความสัมพันธ์ระหว่างหุ้นในพอร์ต

---

### 2.7 Alerts

#### FR-ALERT-001: Alert Types
| Type | Description | Example |
|------|-------------|---------|
| Price Above | ราคาขึ้นเกิน target | PTT > 38.00 |
| Price Below | ราคาลงต่ำกว่า target | AAPL < 170.00 |
| RSI Overbought | RSI > threshold | NVDA RSI > 70 |
| RSI Oversold | RSI < threshold | PTT RSI < 30 |
| Golden Cross | MA สั้นตัด MA ยาวขึ้น | MA20 × MA50 |
| Death Cross | MA สั้นตัด MA ยาวลง | MA20 × MA50 |
| Volume Spike | Volume > X เท่าของค่าเฉลี่ย | Volume > 3x avg |

#### FR-ALERT-002: Notification Channels
- **Telegram Bot**: primary channel (ฟรี, ไม่จำกัด)
- **In-App Notification**: แสดงใน alerts panel
- **Email** (optional, ถ้า user config SMTP)

#### FR-ALERT-003: Alert Management
- สร้าง/แก้ไข/ลบ alert
- เปิด/ปิด alert ได้ (toggle active/inactive)
- แสดงประวัติ alert ที่เคย trigger
- สถานะ: Active, Triggered, Expired

---

### 2.8 Stock Screener

#### FR-SCREEN-001: Filter Criteria
- **Market**: SET, US, หรือ ทั้งหมด
- **Price Range**: min-max
- **Market Cap**: min-max
- **P/E Ratio**: min-max
- **RSI**: min-max
- **MACD Signal**: Buy / Sell / Neutral
- **Volume**: X เท่าของค่าเฉลี่ย
- **Price vs MA**: > MA200, < MA50 etc.

#### FR-SCREEN-002: Results
- แสดงตาราง results พร้อม columns ที่กรอง
- คลิกที่ row เปิดกราฟหุ้นนั้น
- บันทึก filter preset ได้ per user
- Export results เป็น CSV

---

### 2.9 Backtesting

#### FR-BACK-001: Strategy Builder
- เลือก entry/exit conditions จาก indicators
- ตั้งค่า initial capital, position size, commission
- เลือกช่วงเวลา backtest (start date - end date)

#### FR-BACK-002: Results
- Total Return, Annualized Return
- Max Drawdown, Sharpe Ratio, Win Rate
- Trade log (list of all trades)
- Equity curve chart
- Benchmark comparison (SET Index / S&P500)

---

### 2.10 News Feed

#### FR-NEWS-001: Sources
- **Google News RSS**: ข่าวทั่วไป Thai + US
- **Finnhub News API**: ข่าวหุ้น US (free tier)
- Filter by: market (SET/US), symbol (watchlist), ทั้งหมด

#### FR-NEWS-002: AI Sentiment (Optional — requires Ollama)
- วิเคราะห์ sentiment: Positive / Negative / Neutral
- แสดง sentiment badge ข้างข่าว
- Sentiment trend chart per symbol

---

### 2.11 Fundamental Data

#### FR-FUND-001: Key Metrics
- P/E, P/BV, EPS, Dividend Yield, Market Cap
- ดึงจาก yfinance (มีทั้งหุ้นไทยและ US)
- แสดงใน side panel ข้างกราฟ

#### FR-FUND-002: Financial Statements (หุ้นไทย)
- งบกำไรขาดทุน, งบดุล (ย้อนหลัง 5 ปี)
- ดึงจาก yfinance หรือ SET website
- แสดงเป็นตาราง + กราฟ bar chart

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Metric | Target |
|--------|--------|
| Page Load Time (initial) | < 2 วินาที |
| Chart Render Time | < 500ms |
| API Response Time (P95) | < 200ms |
| WebSocket Latency | < 100ms |
| Max Concurrent Users | 50 (self-hosted) |
| Database Query Time (P95) | < 50ms |

### 3.2 Database Housekeeping

เพื่อลดขนาด database ระบบจะ compress ข้อมูลเก่าอัตโนมัติ:

| Age | Resolution | Action |
|-----|-----------|--------|
| < 7 วัน | 1-minute bars | เก็บ raw data |
| 7 – 90 วัน | 5-minute bars | Aggregate แล้วลบ 1-min data |
| 90 วัน – 2 ปี | 1-day bars | Aggregate แล้วลบ 5-min data |
| > 2 ปี | 1-week bars | Aggregate แล้วลบ 1-day data |

Implementation:
- ใช้ Celery beat schedule: run housekeeping ทุกวัน 03:00 ICT
- TimescaleDB continuous aggregates สำหรับ 5m, 1D, 1W
- เก็บ log ว่าลบข้อมูลไปเท่าไหร่

### 3.3 Security

| Area | Requirement |
|------|------------|
| Password Hashing | bcrypt, cost factor ≥ 12 |
| JWT | RS256, access 15min, refresh 7d |
| HTTPS | บังคับใน production (Nginx TLS termination) |
| CORS | Whitelist frontend origin เท่านั้น |
| SQL Injection | ใช้ parameterized queries / ORM เท่านั้น |
| XSS | Sanitize ทุก user input, Content-Security-Policy header |
| CSRF | CSRF token สำหรับ state-changing requests |
| Rate Limiting | Per IP + per user ด้วย Redis |
| Secrets | เก็บใน .env, ห้าม commit เข้า git |
| Container | Run as non-root user, read-only filesystem |
| Dependencies | Audit ด้วย `pip-audit` + `npm audit` ทุก build |

### 3.4 Reliability

- Graceful degradation: ถ้า yfinance ล่ม → ใช้ Finnhub fallback
- ถ้า Finnhub ล่ม → แสดง cached data + warning badge
- WebSocket auto-reconnect ด้วย exponential backoff (1s, 2s, 4s, 8s, max 30s)
- Health check endpoint: `GET /api/health` ตอบ status ของ DB, Redis, Celery
- Celery task retry: 3 ครั้ง ด้วย exponential backoff

### 3.5 Scalability

- Stateless backend: horizontal scaling ได้ถ้าต้องการ
- Database connection pooling (asyncpg, pool size 20)
- Redis caching สำหรับ hot data (ราคาปัจจุบัน, search results)
- Cache TTL: ราคาหุ้น 60 วินาที, search results 5 นาที, fundamentals 1 ชม.

### 3.6 Observability

- Structured logging (JSON format) ด้วย Python `structlog`
- Log levels: DEBUG (dev), INFO (prod)
- Request logging: method, path, status, duration
- Error tracking: full stack trace + request context
- Metrics endpoint: `GET /api/metrics` (Prometheus format, optional)

---

## 4. UI/UX Requirements

### 4.1 Design System (2026 Trends)

| Element | Specification |
|---------|--------------|
| Theme | Dark mode (default) + Light mode toggle |
| Colors | Deep navy bg (#0d0f17), Violet accent (#6366f1) |
| Border Radius | 12px–16px (rounded-xl/2xl) |
| Typography | Inter font, system fallback |
| Spacing | 4px grid system |
| Glass Effect | backdrop-blur panels (subtle) |
| Animations | 200ms ease transitions, no jarring motions |
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

### 4.4 Accessibility

- Keyboard navigation สำหรับ major actions
- Sufficient color contrast (WCAG AA)
- Focus indicators สำหรับ interactive elements
- Screen reader labels สำหรับ icons

---

## 5. Docker & Deployment

### 5.1 Development Mode

```yaml
# docker-compose.dev.yml
- Frontend: Vite dev server (HMR, port 5173)
- Backend: Uvicorn --reload (auto-restart on code change)
- Database: PostgreSQL + TimescaleDB
- Redis: Standard
- Volumes: mount source code for hot-reload
```

### 5.2 Production Mode

```yaml
# docker-compose.prod.yml
- Frontend: Nginx serving built React static files
- Backend: Uvicorn + Gunicorn (4 workers)
- Database: PostgreSQL + TimescaleDB (with persistent volume)
- Redis: Standard (with persistent volume)
- Nginx: Reverse proxy + TLS termination
- Celery: Worker + Beat scheduler
```

### 5.3 Environment Variables

```env
# .env.example
DATABASE_URL=postgresql://user:pass@db:5432/stockviz
REDIS_URL=redis://redis:6379/0
JWT_SECRET_KEY=<random-256-bit-key>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
FINNHUB_API_KEY=<free-tier-key>
TELEGRAM_BOT_TOKEN=<from-botfather>
OLLAMA_URL=http://ollama:11434 (optional)
TZ=Asia/Bangkok
```

---

## 6. API Endpoints (Draft)

### 6.1 Auth
```
POST   /api/auth/register
POST   /api/auth/login
POST   /api/auth/refresh
POST   /api/auth/logout
GET    /api/auth/me
```

### 6.2 Stocks
```
GET    /api/stocks/search?q={query}
GET    /api/stocks/{symbol}/quote
GET    /api/stocks/{symbol}/history?tf={timeframe}&from={date}&to={date}
GET    /api/stocks/{symbol}/fundamentals
GET    /api/stocks/{symbol}/news
WS     /api/ws/prices                  → subscribe to realtime prices
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
POST   /api/screener/run              → body: filter conditions
GET    /api/screener/presets
POST   /api/screener/presets
DELETE /api/screener/presets/{id}
```

### 6.7 Backtest
```
POST   /api/backtest/run              → body: strategy + params
GET    /api/backtest/history
GET    /api/backtest/{id}/results
```

### 6.8 Drawings
```
GET    /api/drawings/{symbol}?tf={timeframe}
POST   /api/drawings/{symbol}
PUT    /api/drawings/{id}
DELETE /api/drawings/{id}
```

### 6.9 System
```
GET    /api/health
GET    /api/metrics (optional, Prometheus)
```

---

## 7. Database Schema (Draft)

### 7.1 Core Tables

```sql
-- Users
users (id, email, password_hash, display_name, role, created_at, updated_at)

-- Stock metadata
stocks (id, symbol, name, name_th, market, sector, is_active)

-- Price data (TimescaleDB hypertable)
stock_prices_1m (time, symbol, open, high, low, close, volume)
stock_prices_5m (time, symbol, open, high, low, close, volume)  -- continuous aggregate
stock_prices_1d (time, symbol, open, high, low, close, volume)  -- continuous aggregate
stock_prices_1w (time, symbol, open, high, low, close, volume)  -- continuous aggregate

-- Watchlists
watchlists (id, user_id, name, sort_order, created_at)
watchlist_items (id, watchlist_id, symbol, sort_order, added_at)

-- Portfolio
transactions (id, user_id, symbol, type[BUY/SELL], qty, price, fee, date, note)

-- Alerts
alerts (id, user_id, symbol, alert_type, condition, value, is_active, triggered_at, channel)

-- Drawings
drawings (id, user_id, symbol, timeframe, tool_type, data_json, style_json, created_at, updated_at)

-- Screener presets
screener_presets (id, user_id, name, filters_json, created_at)

-- Backtest results
backtest_results (id, user_id, strategy_json, result_json, created_at)

-- Refresh tokens
refresh_tokens (id, user_id, token_hash, expires_at, revoked_at)

-- Events (XD, XR dates)
stock_events (id, symbol, event_type, event_date, value, description)
```

---

## 8. Milestones

### Phase 1 — MVP (Target: 6 weeks)
- [x] Project setup + Docker Compose (dev + prod)
- [ ] Auth (register, login, JWT)
- [ ] Stock data fetching (yfinance)
- [ ] Chart (candlestick, line) + timeframes
- [ ] Basic indicators (MA, EMA, RSI, MACD, BB)
- [ ] Drawing tools (trend line, h-line, fib)
- [ ] Watchlist CRUD
- [ ] Search autocomplete
- [ ] Dark/Light mode
- [ ] DB Housekeeping

### Phase 2 — Features (Target: 4 weeks after MVP)
- [ ] Portfolio tracking + analytics
- [ ] Alert system + Telegram notification
- [ ] News feed (RSS + Finnhub)
- [ ] Stock screener
- [ ] Fundamental data panel
- [ ] Compare mode
- [ ] Export CSV

### Phase 3 — Advanced (Target: 4 weeks after Phase 2)
- [ ] Backtesting
- [ ] AI Sentiment (Ollama)
- [ ] Additional indicators (Ichimoku, Stochastic, ATR, VWAP)
- [ ] Advanced drawing tools (rectangle, arrow, pitchfork)
- [ ] XD/XR markers on chart
- [ ] Correlation heatmap
- [ ] Admin dashboard

---

## 9. Out of Scope (for now)

- Mobile app (React Native / Flutter)
- Real-time 0-delay data (requires exchange license)
- Crypto / Forex markets
- Social trading / idea sharing
- Broker integration (auto-trading)
- White-label / API for third parties
- Multi-language (Thai only + English labels)
- SMS notifications
- Cloud deployment (AWS/GCP)

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| yfinance API ล่ม/เปลี่ยน | ดึงข้อมูลไม่ได้ | Finnhub fallback + cache layer |
| Finnhub free tier quota หมด | ข้อมูลไม่ครบ | ใช้ yfinance เป็นหลัก, Finnhub เป็น secondary |
| TimescaleDB performance | Query ช้า | Continuous aggregates + proper indexing |
| SET website เปลี่ยน structure | Thai data ขาด | ใช้ yfinance .BK symbols แทน |
| Docker resource usage สูง | เครื่อง user ช้า | Optimize container limits, lazy loading |
| Security breach | Data leak | Follow OWASP top 10, regular audit |

---

*End of Document*
