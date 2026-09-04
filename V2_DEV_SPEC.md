# ShotockViz V2 — Developer Technical Specification

**Version:** 2.0.0-dev
**Date:** 2026-03-04
**Source:** V2_Features.md analysis
**Status:** Ready for Development
**Target:** 1.5.0+ (Institutional-Grade)

---

## System Analysis Summary

V2 ประกอบด้วย 12 features ใน 4 กลุ่ม แบ่งเป็น **4 phases** การพัฒนา ระยะเวลารวมประมาณ 6-8 สัปดาห์

### Gap Analysis vs Current State (v0.1.3)

| Feature | Current State | V2 Requirement | Gap |
|---------|--------------|----------------|-----|
| Symbol Mapping | ใช้ Yahoo suffix โดยตรง | Internal mapping layer | New layer needed |
| Adjusted Price | Raw price only | Dividend/split adjusted | New table + logic |
| Hybrid Fetch | Celery-only | Celery + asyncio fallback | Fallback missing |
| RS Line | ไม่มี | Compare vs benchmark | New indicator |
| Financial Scorecard | P/E, P/BV only (1 ปี) | 10-year history | New table + worker |
| Earnings Surprise | ไม่มี | Actual vs estimate | New feature |
| Flower | ไม่มี | Added to Docker | New service |
| pgvector/RAG | Vector search ไม่มี | AI context retrieval | New extension |
| Retention UI | Hardcoded housekeeping | User-configurable | New UI + API |
| Volume Profile | ไม่มี | VPVR overlay | New chart component |
| Multi-Chart | ไม่มี | Split view | New layout system |
| Backtesting | ไม่มี | Strategy simulation | New engine |

---

## Phase 2.1 — Infrastructure (สัปดาห์ 1-2)

### Feature 1: Flower Monitoring Dashboard

**Priority:** HIGH (unblocks Celery visibility, low risk)

#### Docker Changes

**File:** `docker-compose.dev.yml`

เพิ่ม service ต่อจาก `celery_beat`:
```yaml
flower:
  image: mher/flower:2.0
  container_name: shotockviz-flower
  command: celery --broker=redis://redis:6379/0 flower --port=5555 --url_prefix=flower
  ports:
    - "5555:5555"
  depends_on:
    - redis
    - celery_worker
  networks:
    - stockviz-net
  restart: unless-stopped
```

**File:** `caddy/Caddyfile.dev`

เพิ่ม reverse proxy rule:
```caddyfile
handle /flower/* {
    reverse_proxy flower:5555
}
```

#### ไม่มี backend/frontend changes

**Test:** เปิด `https://localhost/flower/` → เห็น Celery task dashboard

---

### Feature 2: Hybrid Fetching Logic (Asyncio Fallback)

**Priority:** HIGH (แก้ Quote 202 pending ที่เกิดบ่อย)

#### Files to Modify

**`backend/services/stock_service.py`**

เพิ่ม method `_trigger_fetch_with_fallback()`:
```python
# Pattern: ลอง Celery ก่อน, ถ้า broker ไม่ตอบใน 2s → asyncio fallback
async def _trigger_fetch_with_fallback(self, symbol: str, task_type: str):
    try:
        # ลอง ping broker ก่อน
        inspect = celery_app.control.inspect(timeout=2.0)
        if inspect.ping():
            request_data_fetch(symbol, task_type)
            return "celery"
    except Exception:
        pass
    # Fallback: asyncio background task
    asyncio.create_task(self._fetch_quote_direct(symbol))
    return "asyncio"
```

**`backend/workers/on_demand_listener.py`**

เพิ่ม health check mechanism ที่ตรวจ broker connectivity

#### ⚠️ Pitfalls
- `apply_async()` fails from FastAPI event loop → ใช้ `delay()` เท่านั้น
- asyncio fallback ต้องไม่เรียก yfinance มากกว่า 8 concurrent (Semaphore มีอยู่แล้ว)
- Fallback ไม่ควร persist ลง DB โดยตรง — ควร cache Redis เท่านั้น แล้วปล่อย Celery ทำงานปกติต่อ

---

## Phase 2.2 — Data Engine (สัปดาห์ 2-3)

### Feature 3: Multi-Source Symbol Mapping

**Priority:** HIGH (prerequisite ของ adjusted price และ RAG)

#### New Database Table

```sql
-- Migration file: backend/migrations/add_symbol_mappings.sql
CREATE TABLE IF NOT EXISTS symbol_mappings (
    id          SERIAL PRIMARY KEY,
    internal_symbol  VARCHAR(20) NOT NULL UNIQUE,  -- เช่น "PTT.BK"
    yahoo_symbol     VARCHAR(20),                   -- เช่น "PTT.BK"
    finnhub_symbol   VARCHAR(20),                   -- เช่น "PTT"
    thinav_symbol    VARCHAR(50),                   -- เช่น "T-ES-MEGA-A"
    display_name     VARCHAR(100),
    market           VARCHAR(10),
    currency         VARCHAR(5),
    is_active        BOOLEAN DEFAULT true,
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_symbol_mappings_internal ON symbol_mappings(internal_symbol);
```

#### New Files

**`backend/services/symbol_mapper.py`** (new)
```python
# ทำหน้าที่: internal_symbol → source-specific symbol
# เช่น: get_yahoo_symbol("PTT.BK") → "PTT.BK"
#        get_finnhub_symbol("AAPL") → "AAPL"
#        get_thinav_symbol("SCBFIX-A") → "T-SCBFIX-A"
```

#### Files to Modify

- `backend/workers/price_fetcher.py` → ใช้ `symbol_mapper.get_yahoo_symbol()`
- `backend/workers/fundamentals_fetcher.py` → ใช้ mapper
- `backend/workers/fund_fetcher.py` → ใช้ `symbol_mapper.get_thinav_symbol()`
- `backend/services/stock_service.py` → `_normalize_symbol()` wrapper

#### 📐 Pattern
ดู `backend/core/cache_keys.py` เป็นตัวอย่างของ centralized key management — ทำแบบเดียวกัน

---

### Feature 4: Corporate Action Adjustments (Adjusted Price)

**Priority:** MEDIUM (สำคัญสำหรับ Technical Analysis ที่แม่นยำ)

#### New Database Table

```sql
CREATE TABLE IF NOT EXISTS corporate_actions (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(20) NOT NULL REFERENCES stocks(symbol),
    action_type VARCHAR(10) NOT NULL,  -- 'DIV', 'SPLIT', 'RIGHTS'
    ex_date     DATE NOT NULL,
    value       NUMERIC(15, 6),        -- dividend amount หรือ split ratio
    ratio       NUMERIC(10, 6),        -- split ratio (เช่น 0.5 สำหรับ 2:1 split)
    source      VARCHAR(20),           -- 'yfinance', 'manual'
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_corp_actions_symbol ON corporate_actions(symbol, ex_date DESC);
```

#### New Files

**`backend/workers/corporate_actions_fetcher.py`** (new Celery worker)
- Schedule: ทุก 24h หรือ triggered หลัง earnings
- Data source: `yfinance.Ticker(symbol).dividends` + `yfinance.Ticker(symbol).splits`

**`backend/services/price_adjuster.py`** (new)
- `adjust_prices(bars: list, symbol: str) → list` — คำนวณ adjusted close ย้อนหลัง

#### API Changes

**`backend/api/routes/stocks.py`** — history endpoint

เพิ่ม query param:
```python
GET /api/stocks/{symbol}/history?timeframe=1D&adjusted=false
# adjusted=true → คำนวณ adjusted price ก่อน return
# default: false (backward compatible)
```

#### celery_app.py — เพิ่ม beat schedule

```python
"fetch_corporate_actions": {
    "task": "workers.corporate_actions_fetcher.fetch_corporate_actions",
    "schedule": crontab(hour="2", minute="0"),  # ทุกวัน 02:00 ICT
}
```

#### ⚠️ Pitfalls
- Thai SET หุ้น XD/XR ข้อมูลจาก yfinance บางตัว incomplete → ต้องมี manual override
- Adjusted price ต้อง recalculate ย้อนหลังเมื่อเพิ่ม corporate action ใหม่
- อย่า overwrite raw price ใน DB — เก็บ raw data ไว้เสมอ, adjusted เป็น derived value

---

## Phase 2.3 — Institutional Features (สัปดาห์ 3-5)

### Feature 5: Relative Strength (RS) Line

**Priority:** HIGH (trader ต้องการมาก)

#### New API Endpoint

```python
# backend/api/routes/stocks.py
GET /api/stocks/{symbol}/rs?benchmark=^SET.BK&timeframe=1D&period=252
# Return: list of {time, rs_value} — normalized ratio
```

#### Frontend Changes

**`frontend/src/utils/indicators.js`** — เพิ่ม RS calculation:
```js
// calculateRS(symbolBars, benchmarkBars) → [{time, value}]
// RS = (symbolClose / symbol_close_N_days_ago) / (benchmarkClose / benchmark_close_N_days_ago)
```

**`frontend/src/components/chart/TradingChart.tsx`**
- เพิ่ม RS line series (LineSeries) แยก panel ใต้ volume
- สี: `#f59e0b` (amber) เพื่อแยกจาก price

**`frontend/src/components/chart/ChartToolbar.tsx`**
- เพิ่ม benchmark selector dropdown (^SET.BK, ^GSPC, ^IXIC, etc.)

#### 📐 Pattern
ดู MACD ใน `TradingChart.tsx` เป็นตัวอย่าง oscillator panel แยกใต้กราฟ

---

### Feature 6: Financial Health Scorecard (10-Year)

**Priority:** HIGH (institutional-grade differentiation)

#### New Database Table

```sql
CREATE TABLE IF NOT EXISTS financial_history (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(20) NOT NULL REFERENCES stocks(symbol),
    fiscal_year     INTEGER NOT NULL,
    revenue         NUMERIC(20, 2),
    net_profit      NUMERIC(20, 2),
    roe             NUMERIC(8, 4),       -- % เช่น 18.5
    debt_equity     NUMERIC(8, 4),
    eps             NUMERIC(10, 4),
    dividend        NUMERIC(10, 4),
    gross_margin    NUMERIC(8, 4),
    operating_margin NUMERIC(8, 4),
    currency        VARCHAR(5),
    source          VARCHAR(20),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, fiscal_year)
);
```

#### New Files

**`backend/workers/financials_history_fetcher.py`** (new Celery worker)
- Data source: `yfinance.Ticker(symbol).financials` + `.balance_sheet`
- Schedule: ทุก 24h (ข้อมูล annual ไม่เปลี่ยนบ่อย)
- Store up to 10 fiscal years per symbol

#### New API Endpoint

```python
GET /api/stocks/{symbol}/financials?years=10
# Response: { symbol, years: [{fiscal_year, revenue, net_profit, roe, debt_equity, ...}] }
```

#### New Frontend Component

**`frontend/src/components/chart/FinancialScorecard.tsx`** (new)

UI: Bento Grid layout ใน BottomPanel tab
```
┌──────────┬──────────┬──────────┬──────────┐
│ Revenue  │ Net Profit│   ROE    │   D/E    │
│ Bar Chart│ Bar Chart │ Line     │ Line     │
│ 10yr     │ 10yr     │ 10yr     │ 10yr     │
└──────────┴──────────┴──────────┴──────────┘
```

**`frontend/src/components/chart/BottomPanel.tsx`**
- เพิ่ม tab "Financials" ต่อจาก "Fundamentals"

---

### Feature 7: Earnings Surprise Tracker

**Priority:** MEDIUM

#### New Database Table

```sql
CREATE TABLE IF NOT EXISTS earnings_events (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(20) NOT NULL REFERENCES stocks(symbol),
    report_date     DATE NOT NULL,
    fiscal_period   VARCHAR(10),          -- เช่น "Q3 2025"
    estimated_eps   NUMERIC(10, 4),
    actual_eps      NUMERIC(10, 4),
    surprise_pct    NUMERIC(8, 4),        -- (actual - estimate) / |estimate| * 100
    price_1d_before NUMERIC(15, 4),
    price_1d_after  NUMERIC(15, 4),
    price_impact_pct NUMERIC(8, 4),
    source          VARCHAR(20),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, report_date)
);
```

#### New API Endpoint

```python
GET /api/stocks/{symbol}/earnings?limit=8
# Response: list of earnings events + price impact
```

#### Frontend: Chart Overlay

**`frontend/src/components/chart/TradingChart.tsx`**
- เพิ่ม earnings markers บนกราฟ (marker สีเขียว/แดง ขึ้นอยู่กับ surprise positive/negative)
- Tooltip แสดง EPS actual vs estimate

---

## Phase 2.4 — AI/Observability (สัปดาห์ 5-7)

### Feature 8: ~~pgvector Integration (RAG)~~ — REMOVED

> bd:deps-2026-09 (2026-09) — the AI chat feature this was a
> prerequisite for was removed entirely (local LLM runtime already
> dropped from prod). Spec kept struck through for history only; do
> not implement.

---

### Feature 9: Data Retention UI

**Priority:** LOW (nice-to-have สำหรับ local storage management)

#### New API Endpoints

```python
GET  /api/admin/retention-policy
# Response: { policy: [{age_days, resolution, action}], disk_usage_mb }

PUT  /api/admin/retention-policy
# Body: { policy: [{max_age_days: 7, resolution: "1m"}, ...] }

POST /api/admin/retention-policy/run-now
# Trigger housekeeping immediately
```

#### New Frontend Component

**`frontend/src/components/modals/SettingsModal.tsx`** — เพิ่ม tab "Data Retention"

UI:
```
┌─────────────────────────────────────┐
│  Data Retention Settings            │
│                                     │
│  1-min data kept for: [7 days ▼]   │
│  5-min data kept for: [90 days ▼]  │
│  1-day data kept for: [2 years ▼]  │
│                                     │
│  Disk Usage: 2.4 GB / ~10 GB est.  │
│  [Run Cleanup Now]  [Save Settings] │
└─────────────────────────────────────┘
```

#### Backend Changes

**`backend/workers/housekeeping.py`**
- อ่าน policy จาก Redis config (set โดย API)
- ไม่ hardcode อีกต่อไป

---

## Phase 2.5 — Professional Tools (สัปดาห์ 6-8)

### Feature 10: Volume Profile (Visible Range — VPVR)

**Priority:** HIGH (trader ต้องการมาก สำหรับ support/resistance)

#### Frontend-Only Feature

**`frontend/src/components/chart/VolumeProfile.tsx`** (new)

Algorithm:
```
1. รับ bars array ที่ visible บนหน้าจอ (hook into chart's visibleRange)
2. หา price range (highest high, lowest low)
3. แบ่ง price range เป็น N levels (default: 100 buckets)
4. Sum volume ของแต่ละ level
5. Render เป็น horizontal bars ทาง right ของกราฟ
   - Point of Control (POC) = level ที่มี volume มากสุด → สีแดง/ทอง
   - Value Area (70% of volume) → สีอ่อน
```

**`frontend/src/components/chart/TradingChart.tsx`**
- เพิ่ม `showVolumeProfile` state
- Overlay VolumeProfile canvas บน TradingView chart (absolute positioned)
- Update เมื่อ chart range เปลี่ยน (subscribe to `visibleLogicalRange` event)

#### ⚠️ Pitfalls
- VPVR เป็น canvas overlay — ต้องซิงค์ coordinate กับ TradingView chart canvas
- Performance: คำนวณใหม่ทุกครั้งที่ visible range เปลี่ยน → ใช้ `useMemo` + debounce 100ms

---

### Feature 11: Multi-Chart Layout

**Priority:** MEDIUM

#### New Files

**`frontend/src/components/chart/MultiChartLayout.tsx`** (new)
- Supports: 1x1, 2x1, 1x2, 2x2 layouts
- แต่ละ cell เป็น independent `<ChartPage>` instance พร้อม symbol selector

**`frontend/src/store/appStore.js`**
- เพิ่ม `multiChartMode: boolean`
- เพิ่ม `chartSlots: [{symbol, timeframe}]` (max 4)

#### Route Change

**`frontend/src/routes/index.tsx`** หรือ layout toggle button ใน Navbar

#### ⚠️ Pitfalls
- WebSocket subscription ต้องรองรับ multiple symbols พร้อมกัน (ปัจจุบัน subscribe ทีละตัว)
- Memory: 4 charts พร้อมกัน → อาจ OOM บน low-RAM machines → ใส่ warning ถ้า RAM < 4GB

---

### Feature 12: Strategy Backtesting UI

**Priority:** LOW (complex, ทำหลังสุด)

#### New Files

**`backend/services/backtesting_engine.py`** (new)
```python
# run_backtest(symbol, strategy, start_date, end_date, initial_capital) → BacktestResult
# strategy: {"type": "golden_cross", "params": {...}}
# BacktestResult: {trades, total_return, win_rate, max_drawdown, sharpe_ratio}
```

**`backend/api/routes/backtesting.py`** (new)
```python
POST /api/backtest/run
# Body: { symbol, strategy_type, params, start_date, end_date, capital }
# Response: BacktestResult (async via WebSocket or polling)
```

**`frontend/src/routes/backtest.tsx`** (new page)

UI:
```
┌─────────────────────────────────────────┐
│  Strategy Backtester                    │
│  Symbol: [PTT.BK ▼]  Period: [1Y ▼]   │
│  Strategy: [Golden Cross ▼]             │
│  Capital: ฿1,000,000                    │
│  [Run Backtest]                         │
├─────────────────────────────────────────┤
│  Results:                               │
│  Win Rate: 62%  Max DD: -12.3%         │
│  Sharpe: 1.42   Return: +28.5%         │
│  Trade List: [table]                   │
└─────────────────────────────────────────┘
```

---

## Database Migration Plan

### มี migration ใหม่ทั้งหมด 6 tables (ทำตามลำดับ):

```
Phase 2.1: (ไม่มี DB changes)
Phase 2.2:
  1. symbol_mappings
  2. corporate_actions
Phase 2.3:
  3. financial_history
  4. earnings_events
Phase 2.4:
  5. ~~vector-search table (requires pgvector extension)~~ — REMOVED, see Feature 8
  6. (retention policy ใช้ Redis config แทน DB)
Phase 2.5:
  (ไม่มี DB changes — backtest เป็น stateless computation)
```

**Migration strategy:** เก็บไว้ใน `backend/migrations/` เป็น plain SQL files
ชื่อไฟล์: `v2_001_symbol_mappings.sql`, `v2_002_corporate_actions.sql` ฯลฯ

---

## New API Endpoints Summary

| Method | Path | Phase | Feature |
|--------|------|-------|---------|
| GET | `/api/stocks/{symbol}/history?adjusted=true` | 2.2 | Adjusted Price |
| GET | `/api/stocks/{symbol}/rs?benchmark=...` | 2.3 | RS Line |
| GET | `/api/stocks/{symbol}/financials?years=10` | 2.3 | Financial Scorecard |
| GET | `/api/stocks/{symbol}/earnings?limit=8` | 2.3 | Earnings Surprise |
| GET | `/api/admin/retention-policy` | 2.4 | Retention UI |
| PUT | `/api/admin/retention-policy` | 2.4 | Retention UI |
| POST | `/api/admin/retention-policy/run-now` | 2.4 | Retention UI |
| POST | `/api/backtest/run` | 2.5 | Backtesting |

---

## New Celery Workers Summary

| Worker | Schedule | Phase | Purpose |
|--------|----------|-------|---------|
| `fetch_corporate_actions` | Daily 02:00 ICT | 2.2 | Dividend/split data |
| `fetch_financials_history` | Daily 01:00 ICT | 2.3 | 10-year financials |
| `fetch_earnings_events` | Daily 06:00 ICT | 2.3 | EPS actual/estimate |

**Register ทุกตัวใน:** `backend/workers/celery_app.py` beat schedule

---

## Docker Service Changes

| Service | Change | Phase |
|---------|--------|-------|
| `flower` | **New service** (mher/flower:2.0) | 2.1 |
| `db` | Image → pgvector/pgvector:pg16 (custom build) | 2.4 |
| `caddy` | เพิ่ม `/flower/` route | 2.1 |
| `celery_worker` | เพิ่ม worker modules ใหม่ | 2.2-2.4 |

---

## Frontend Package Dependencies

```json
// package.json additions
// ไม่มี new npm packages จำเป็น
// Volume Profile → ใช้ Canvas API native
// Financial Charts → ใช้ TradingView Lightweight Charts ที่มีอยู่แล้ว
// Multi-Chart → React composition เท่านั้น
```

---

## Breaking Changes & Backward Compatibility

| Change | Impact | Migration |
|--------|--------|-----------|
| Postgres image เปลี่ยน (pgvector) | DB restart required | `docker-compose down && docker-compose up -d db` |
| `/api/stocks/.../history` เพิ่ม `adjusted` param | Non-breaking (default=false) | ไม่มี |
| Retention policy → configurable | Non-breaking (defaults เหมือนเดิม) | ไม่มี |

---

## Architecture Diagram (V2 additions)

```
                   ┌─────────────────────────────────────┐
                   │            FRONTEND (V2)             │
                   │  + RS Line  + Financial Scorecard    │
                   │  + Volume Profile  + Multi-Chart     │
                   │  + Backtesting UI  + Retention UI    │
                   └──────────────┬──────────────────────┘
                                  │ HTTPS/WSS
                   ┌──────────────▼──────────────────────┐
                   │               CADDY                  │
                   │  + /flower/ → Flower:5555            │
                   └───────┬──────────────────────────────┘
                           │
              ┌────────────▼────────────────────────────┐
              │           BACKEND (FastAPI)              │
              │  + /rs  + /financials  + /earnings      │
              │  + /admin/retention-policy              │
              │  + /backtest/run                        │
              └────────────┬────────────────────────────┘
                           │
        ┌──────────────────┼────────────────────────┐
        │                  │                        │
  ┌─────▼──────┐    ┌──────▼──────┐    ┌──────────▼──────────┐
  │   REDIS    │    │  POSTGRES   │    │     CELERY (V2)      │
  │  (unchanged)│    │  (unchanged)│    │  + corporate_actions │
  │            │    │  + new tables│    │  + financials_history│
  └────────────┘    └─────────────┘    │  + earnings_events   │
                                        └──────────────────────┘
                                               +
                                        ┌──────────────┐
                                        │   FLOWER     │
                                        │  (NEW) :5555 │
                                        └──────────────┘
```

---

## Development Order Recommendation

```
Week 1: Phase 2.1
  Day 1-2: Flower Docker setup + test
  Day 3-5: Hybrid fetching fallback (asyncio)

Week 2-3: Phase 2.2
  Day 1-3: Symbol mapping table + service
  Day 4-7: Corporate actions fetcher + adjusted price
  Day 8-10: History endpoint adjusted param + frontend toggle

Week 3-5: Phase 2.3
  Day 1-4: Financial history table + worker
  Day 5-7: Financial Scorecard UI (Bento Grid)
  Day 8-10: RS Line backend endpoint
  Day 11-12: RS Line frontend overlay
  Day 13-15: Earnings Surprise table + worker + chart markers

Week 5-7: Phase 2.4
  (Feature 8 — RAG — removed, see above)
  Day 10-12: Data Retention UI + API

Week 7-8: Phase 2.5
  Day 1-4: Volume Profile canvas overlay
  Day 5-8: Multi-Chart layout
  Day 9-14: Backtesting engine + UI
```

---

*End of Developer Specification*
*Document generated by: System Analysis on 2026-03-04*
