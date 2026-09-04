# ShotockViz V2 — QA Test Plan

**Version:** 2.0.0-dev
**Date:** 2026-03-04
**Source:** V2_Features.md + V2_DEV_SPEC.md analysis
**Status:** Ready for QA Review
**Test Environment:** Docker stack at `https://localhost`

---

## QA Overview

### Scope
V2 มี 12 features ใหม่ ใน 4 phases — เอกสารนี้ครอบคลุม:
1. **Acceptance Criteria** ต่อ feature (นิยาม "Done")
2. **Test Cases** — Happy Path + Edge Cases + Error Cases
3. **Regression Checklist** — V1 features ที่ต้องทดสอบซ้ำ
4. **Performance Benchmarks** — Non-functional requirements
5. **Known Risk Areas** — จุดที่มีโอกาส fail สูง

### Test Environment Setup
```bash
# Start stack
docker-compose -f docker-compose.dev.yml up -d

# Verify all services healthy
docker-compose -f docker-compose.dev.yml ps

# Access points
App:    https://localhost
Flower: https://localhost/flower/
API:    https://localhost/api/health
```

---

## Phase 2.1 — Infrastructure

### TC-FLOWER-001: Flower Dashboard Accessible

**Feature:** Flower Monitoring Dashboard
**Priority:** HIGH

**Acceptance Criteria:**
- [ ] `https://localhost/flower/` โหลดสำเร็จ (HTTP 200)
- [ ] แสดง worker list ครบทุก worker (ไม่น้อยกว่า 8 ตัว)
- [ ] แสดง active tasks / processed tasks ได้
- [ ] แสดง task history ย้อนหลัง

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| F01 | เปิด `/flower/` โดยไม่ login | แสดง Flower UI (no auth required) | |
| F02 | ดู Workers tab | เห็น `celery@worker` online | |
| F03 | ดู Tasks tab | เห็น `fetch_prices`, `check_all_alerts` etc. | |
| F04 | กด refresh | หน้าไม่ crash, ข้อมูล refresh | |
| F05 | ปิด celery_worker container แล้วเปิด Flower | แสดงว่า worker offline | |

---

### TC-HYBRID-001: Asyncio Fallback When Celery Down

**Feature:** Hybrid Fetching Logic
**Priority:** HIGH

**Acceptance Criteria:**
- [ ] ถ้า Celery broker ไม่ตอบสนองใน 2 วินาที → ระบบ fallback ไป asyncio fetch
- [ ] Quote ยังคง return data ไม่ใช่ 202 ค้างตลอด
- [ ] Log แสดง `"fallback": "asyncio"` เมื่อใช้ fallback

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| H01 | Load AAPL quote (Celery ปกติ) | HTTP 200, data ภายใน 5s | |
| H02 | Stop Redis container, load PTT.BK quote | HTTP 200 พร้อม data (ไม่ใช่ 202) | |
| H03 | หลัง Redis กลับมา | Celery ทำงานปกติ, log ไม่มี fallback | |
| H04 | Load 5 stocks พร้อมกัน ขณะ Celery down | ทั้ง 5 ตัวได้ข้อมูล ไม่ timeout | |
| H05 | Fallback asyncio — ตรวจ concurrent limit | ไม่เกิน 8 concurrent yfinance requests | |

---

## Phase 2.2 — Data Engine

### TC-SYMMAP-001: Symbol Mapping Accuracy

**Feature:** Multi-Source Symbol Mapping
**Priority:** HIGH

**Acceptance Criteria:**
- [ ] PTT.BK → Yahoo: "PTT.BK", Finnhub: "PTT"
- [ ] AAPL → Yahoo: "AAPL", Finnhub: "AAPL"
- [ ] Thai fund → thinav symbol ถูกต้อง
- [ ] Symbol ที่ไม่มีใน mapping → fallback ใช้ internal symbol โดยตรง (ไม่ crash)

**Test Cases:**

| TC# | Symbol | Source | Expected Mapped Symbol | Pass/Fail |
|-----|--------|--------|----------------------|-----------|
| S01 | PTT.BK | Yahoo | PTT.BK | |
| S02 | PTT.BK | Finnhub | PTT | |
| S03 | AAPL | Yahoo | AAPL | |
| S04 | SCBFIXED-A | ThaiNAV | T-SCBFIX-A (หรือค่าที่ถูกต้อง) | |
| S05 | UNKNOWN123 | Any | Fallback → UNKNOWN123, no crash | |
| S06 | 7203.T | Yahoo | 7203.T | |

---

### TC-ADJPRICE-001: Adjusted Price Calculation

**Feature:** Corporate Action Adjustments
**Priority:** MEDIUM

**Acceptance Criteria:**
- [ ] `GET /api/stocks/{symbol}/history?adjusted=true` return HTTP 200
- [ ] `adjusted=false` (default) return ราคา raw เหมือนเดิม (backward compatible)
- [ ] ราคาหุ้นที่มี XD ในอดีต → adjusted ราคาย้อนหลังต่ำกว่า raw อย่างสม่ำเสมอ
- [ ] ราคา raw ใน DB ไม่เปลี่ยน

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| A01 | GET /history?adjusted=false | HTTP 200, raw price data | |
| A02 | GET /history?adjusted=true | HTTP 200, adjusted price data | |
| A03 | หุ้นที่มี dividend (เช่น PTT.BK) adjusted=true | Close ก่อน XD < raw close | |
| A04 | หุ้น US stock split (เช่น NVDA 10:1) adjusted=true | Close ก่อน split * split_ratio | |
| A05 | ตรวจ DB ว่า raw price ไม่เปลี่ยน | stock_prices_1m ยังเป็น raw | |
| A06 | หุ้นที่ไม่มี corporate action | adjusted = raw (ค่าเหมือนกัน) | |
| A07 | กราฟ toggle adjusted mode | กราฟ re-render ไม่มี flash | |

---

## Phase 2.3 — Institutional Features

### TC-RS-001: Relative Strength Line Rendering

**Feature:** RS Line Indicator
**Priority:** HIGH

**Acceptance Criteria:**
- [ ] RS Line แสดงเป็น panel แยกใต้กราฟ (เหมือน MACD)
- [ ] สามารถเลือก benchmark ได้ (^SET.BK, ^GSPC, ^IXIC)
- [ ] RS > 1.0 = stock outperform benchmark
- [ ] RS sync กับ timeframe ปัจจุบัน

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| R01 | เปิด PTT.BK + RS panel + benchmark ^SET.BK | RS line แสดงในกราฟ | |
| R02 | เปลี่ยน benchmark เป็น ^GSPC | RS line อัพเดทตาม | |
| R03 | เปลี่ยน timeframe 1D → 1W | RS line อัพเดทตาม timeframe | |
| R04 | GET /api/stocks/PTT.BK/rs?benchmark=^SET.BK | HTTP 200, [{time, value}] array | |
| R05 | ช่วงที่ PTT.BK ขึ้นแรงกว่า SET | RS > 1.0 | |
| R06 | ช่วงที่ PTT.BK underperform | RS < 1.0 | |
| R07 | Benchmark symbol ไม่มีในระบบ | HTTP 404 พร้อม error message | |

---

### TC-FINSCR-001: Financial Health Scorecard Display

**Feature:** Financial Health Scorecard
**Priority:** HIGH

**Acceptance Criteria:**
- [ ] แสดงข้อมูล Revenue, Net Profit, ROE, D/E ย้อนหลัง ≥ 5 ปี (ถ้ามีข้อมูล)
- [ ] Bento Grid layout แสดงถูกต้องใน Desktop resolution
- [ ] หุ้น SET ที่แสดงเป็น THB, หุ้น US เป็น USD
- [ ] ข้อมูลที่ไม่มี (N/A) แสดงเป็น "N/A" ไม่ crash

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| FS01 | เปิด AAPL → tab "Financials" | Bento grid แสดงข้อมูล 10 ปี | |
| FS02 | เปิด PTT.BK → tab "Financials" | ข้อมูลเป็น THB | |
| FS03 | GET /api/stocks/AAPL/financials?years=10 | HTTP 200, ≥ 5 years data | |
| FS04 | GET /api/stocks/AAPL/financials?years=5 | HTTP 200, ≤ 5 years data | |
| FS05 | หุ้นที่ไม่มี financial data (เช่น ETF) | แสดง "ข้อมูลไม่พร้อม" ไม่ crash | |
| FS06 | ดู Revenue chart | Bar chart แสดงค่า Revenue ต่อปี | |
| FS07 | ดู ROE chart | Line chart แสดงค่า ROE ต่อปี | |
| FS08 | Worker fetch financial history | ตรวจ DB → `financial_history` table มีข้อมูล | |

---

### TC-EARNINGS-001: Earnings Surprise Tracker

**Feature:** Earnings Surprise Tracker
**Priority:** MEDIUM

**Acceptance Criteria:**
- [ ] Chart มี marker แสดงจุด earnings release
- [ ] Marker สีเขียว = EPS beat, สีแดง = EPS miss
- [ ] Tooltip แสดง actual EPS vs estimated EPS
- [ ] แสดงผลกระทบราคา % หลังประกาศ 1 วัน

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| E01 | เปิด AAPL chart | เห็น earnings markers บนกราฟ | |
| E02 | Hover บน marker | Tooltip: "Q3 2025: EPS $1.64 vs est $1.60 (+2.5%)" | |
| E03 | EPS beat marker | สีเขียว | |
| E04 | EPS miss marker | สีแดง | |
| E05 | GET /api/stocks/AAPL/earnings?limit=8 | HTTP 200, ≤ 8 earnings records | |
| E06 | หุ้น SET ที่ไม่มี EPS estimate | marker แสดงเฉพาะ actual, ไม่ crash | |
| E07 | ปิด earnings markers ใน settings | marker หายไปจากกราฟ | |

---

## Phase 2.4 — AI/Observability

### TC-RAG-001: ~~pgvector Semantic Search Accuracy~~ — REMOVED

> bd:deps-2026-09 (2026-09) — the AI chat feature this test plan
> targeted was removed entirely (local LLM runtime already dropped
> from prod). No test cases apply; section kept struck through for
> history only.

---

### TC-RETENTION-001: Data Retention Policy UI

**Feature:** Data Retention UI
**Priority:** LOW

**Acceptance Criteria:**
- [ ] Settings → "Data Retention" tab เปิดได้
- [ ] สามารถเปลี่ยน retention period แต่ละ resolution ได้
- [ ] "Run Cleanup Now" ทำงานและแสดง feedback
- [ ] แสดง disk usage ปัจจุบัน (approximate)

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| RT01 | เปิด Settings → Retention tab | แสดง current policy | |
| RT02 | GET /api/admin/retention-policy | HTTP 200, policy JSON | |
| RT03 | เปลี่ยน 1-min retention จาก 7 → 14 days | UI อัพเดท, บันทึกสำเร็จ | |
| RT04 | PUT /api/admin/retention-policy | HTTP 200, policy บันทึก | |
| RT05 | POST /api/admin/retention-policy/run-now | HTTP 200, housekeeping triggered | |
| RT06 | กด "Run Cleanup Now" | แสดง loading + success message | |
| RT07 | ตั้งค่า retention period เป็น 0 วัน | Validation error, ไม่บันทึก | |
| RT08 | ตั้งค่า 1-min period > 5-min period | Validation warning (logic conflict) | |

---

## Phase 2.5 — Professional Tools

### TC-VPVR-001: Volume Profile Visible Range

**Feature:** Volume Profile (VPVR)
**Priority:** HIGH

**Acceptance Criteria:**
- [ ] VPVR toggle button ใน ChartToolbar
- [ ] Horizontal bars แสดงทางขวาของกราฟ
- [ ] Point of Control (POC) แสดงสีแตกต่าง
- [ ] VPVR อัพเดทเมื่อ scroll/zoom chart
- [ ] Performance: คำนวณ + render < 100ms

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| V01 | เปิด PTT.BK 1D, กด VPVR toggle | Horizontal bars ปรากฏ | |
| V02 | POC level | Bar ยาวที่สุด = สีแดง/ทอง | |
| V03 | Zoom in | VPVR recalculate สำหรับ visible range ใหม่ | |
| V04 | Zoom out | VPVR expand ตาม visible range | |
| V05 | เปลี่ยน timeframe 1D → 1h | VPVR recalculate สำหรับ 1h bars | |
| V06 | ปิด VPVR | Bars หายไป, กราฟกลับปกติ | |
| V07 | Performance: scroll chart | ไม่มี jank, frame rate ≥ 30fps | |
| V08 | เปิดพร้อมกับ indicators อื่น (MA, MACD) | ไม่มี visual conflict | |

---

### TC-MULTICHART-001: Multi-Chart Layout

**Feature:** Multi-Chart Layout
**Priority:** MEDIUM

**Acceptance Criteria:**
- [ ] รองรับ layout: 1x1, 2x1, 1x2, 2x2
- [ ] แต่ละ cell เลือก symbol อิสระได้
- [ ] WebSocket subscription ทำงานสำหรับทุก symbol ที่แสดง
- [ ] ไม่มี memory leak เมื่อเปลี่ยน layout

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| M01 | เลือก 2x1 layout | หน้าจอแบ่ง 2 charts แนวตั้ง | |
| M02 | เลือก 2x2 layout | หน้าจอแบ่ง 4 charts | |
| M03 | เปลี่ยน symbol ใน cell 1 (PTT.BK) | เฉพาะ cell 1 อัพเดท, cell อื่นไม่เปลี่ยน | |
| M04 | เปลี่ยน timeframe ใน cell 2 | เฉพาะ cell 2 อัพเดท | |
| M05 | Real-time price update | ทุก cell รับ WS updates ตาม symbol ตัวเอง | |
| M06 | กลับ 1x1 | กราฟเดียว, memory ไม่รั่ว | |
| M07 | 4 charts พร้อมกัน — memory | ไม่เกิน +200MB จาก baseline | |
| M08 | Reload page ขณะอยู่ใน multi-chart | กลับมา multi-chart (ถ้า persist) หรือ 1x1 | |

---

### TC-BACKTEST-001: Strategy Backtesting

**Feature:** Strategy Backtesting UI
**Priority:** LOW

**Acceptance Criteria:**
- [ ] เลือก symbol, strategy, period ได้
- [ ] Run backtest return ผลภายใน 30 วินาที
- [ ] แสดง Win Rate, Max Drawdown, Sharpe Ratio, Total Return
- [ ] Trade list แสดงทุก trade

**Test Cases:**

| TC# | Input | Expected | Pass/Fail |
|-----|-------|----------|-----------|
| B01 | PTT.BK + Golden Cross + 1Y | ผลลัพธ์ backtest ใน 30s | |
| B02 | AAPL + MACD Cross + 2Y | ผลลัพธ์ backtest ใน 30s | |
| B03 | ช่วงที่ไม่มี trade signals | Win Rate N/A, Total Return 0%, ไม่ crash | |
| B04 | Sharpe Ratio > 0 | Return > Risk-free rate | |
| B05 | Max Drawdown | แสดงเป็น % ติดลบ เช่น "-12.3%" | |
| B06 | Trade list | แสดง entry/exit/P&L ต่อ trade | |
| B07 | POST /api/backtest/run | HTTP 200, BacktestResult JSON | |
| B08 | Invalid date range (future) | Validation error, 422 | |

---

## Regression Test Checklist (V1 Features)

หลังทุก phase build → ทดสอบ V1 features เหล่านี้ทุกครั้ง:

### Authentication
- [ ] Google OAuth One-Tap login ทำงานปกติ
- [ ] ไม่มี custom token management ที่ frontend
- [ ] JWT ยังใช้ได้หลัง Docker restart

### Chart (Critical)
- [ ] PTT.BK chart โหลดและแสดง candlestick
- [ ] NVDA chart โหลดเป็น default
- [ ] Timeframe switch: 1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M ทำงานทุกตัว
- [ ] Cross intraday ↔ daily boundary ไม่ crash
- [ ] Drawing tools: Trend Line, H-Line, Fibonacci, Rectangle, Arrow
- [ ] Drawing persist หลัง refresh

### Indicators
- [ ] SMA, EMA แสดงบนกราฟ
- [ ] RSI, MACD แสดงใน panel แยก
- [ ] Bollinger Bands, Ichimoku แสดง
- [ ] Volume bars แสดง

### Watchlist
- [ ] เพิ่ม/ลบ symbol
- [ ] ราคา + % change แสดงใน sidebar
- [ ] สี เขียว/แดง ตาม price movement

### Portfolio
- [ ] เพิ่ม/แก้ไข/ลบ transaction
- [ ] Unrealized P&L คำนวณถูกต้อง
- [ ] Pie chart allocation แสดง

### Alerts
- [ ] สร้าง Price Above/Below alert
- [ ] Toggle active/inactive
- [ ] ตรวจ alert_checker ทำงานทุก 60s (ดูใน Flower)

### Screener
- [ ] Filter by market, P/E, RSI
- [ ] Results table แสดง

### News
- [ ] ข่าวโหลดจาก RSS
- [ ] AI sentiment badge แสดง

### AI Chat
- [ ] SSE streaming ทำงาน
- [ ] Keepalive ไม่ timeout ภายใน 15s

### WebSocket
- [ ] WS connect ที่ `/api/ws/prices` (ไม่ใช่ `/undefined`)
- [ ] Real-time price update ทำงาน
- [ ] WS auto-reconnect เมื่อ disconnect

---

## Performance Benchmarks (Non-Functional)

### API Response Time (P95 — Cache Hit)

| Endpoint | Target | Measure How |
|----------|--------|-------------|
| GET /api/stocks/{s}/quote | < 200ms | curl timing |
| GET /api/stocks/{s}/history | < 500ms | curl timing |
| GET /api/stocks/{s}/fundamentals | < 200ms | curl timing |
| GET /api/stocks/{s}/rs | < 300ms | curl timing |
| GET /api/stocks/{s}/financials | < 500ms | curl timing |
| POST /api/backtest/run | < 30s | manual timing |

### Frontend Performance

| Metric | Target | Measure How |
|--------|--------|-------------|
| Chart render (NVDA 1D) | < 500ms | Chrome DevTools |
| VPVR calculation | < 100ms | console.time() |
| Multi-chart 4 panels load | < 3s | Chrome DevTools |
| Memory (single chart, 60s) | Stable (no growth) | Performance tab |
| Memory (4-chart layout) | < +200MB baseline | Performance tab |

### Celery Worker Performance

| Worker | Max acceptable time |
|--------|---------------------|
| fetch_prices | < 30s per cycle |
| embed_documents | < 60s per batch |
| fetch_financials_history | < 120s per batch |

ดู timing ได้จาก Flower dashboard (`https://localhost/flower/`)

---

## Known Risk Areas (High Failure Probability)

| Risk | Why Risky | QA Action |
|------|-----------|-----------|
| pgvector + TimescaleDB combined image | Extension conflict บน custom build | ทดสอบ DB restart ก่อน feature test |
| VPVR canvas coordinate sync | TradingView chart API ไม่ expose pixel coords โดยตรง | ทดสอบ zoom in/out ทุก level |
| Adjusted Price: Thai SET stocks | yfinance dividend data สำหรับ .BK บางตัวไม่ครบ | ตรวจด้วย manual data จาก SET website |
| Multi-Chart WebSocket | Multiple symbol subscriptions อาจ conflict | ทดสอบ 4 symbols ที่ active trading |
| Backtesting performance | Historical data อาจต้อง query หลาย GB | ทดสอบด้วย 5Y data, ตรวจ timeout |
| Hybrid fetch fallback | Race condition ระหว่าง Celery กลับมา + asyncio ทำงาน | ทดสอบ Celery restart ขณะ load |
| Flower security | Flower accessible โดยไม่มี auth ใน dev | ยืนยันว่า prod config มี auth |

---

## Test Execution Summary Template

```
Date: __________
Tester: __________
Build/Commit: __________
Environment: Docker dev (https://localhost)

Phase 2.1 Infrastructure:
  FLOWER  : PASS [ ] / FAIL [ ] / SKIP [ ]
  HYBRID  : PASS [ ] / FAIL [ ] / SKIP [ ]

Phase 2.2 Data Engine:
  SYMMAP  : PASS [ ] / FAIL [ ] / SKIP [ ]
  ADJPRICE: PASS [ ] / FAIL [ ] / SKIP [ ]

Phase 2.3 Institutional:
  RS LINE : PASS [ ] / FAIL [ ] / SKIP [ ]
  FINSCR  : PASS [ ] / FAIL [ ] / SKIP [ ]
  EARNINGS: PASS [ ] / FAIL [ ] / SKIP [ ]

Phase 2.4 AI/Observability:
  RAG     : PASS [ ] / FAIL [ ] / SKIP [ ]
  RETAIN  : PASS [ ] / FAIL [ ] / SKIP [ ]

Phase 2.5 Pro Tools:
  VPVR    : PASS [ ] / FAIL [ ] / SKIP [ ]
  MCHART  : PASS [ ] / FAIL [ ] / SKIP [ ]
  BACKTEST: PASS [ ] / FAIL [ ] / SKIP [ ]

Regression:
  AUTH    : PASS [ ] / FAIL [ ]
  CHART   : PASS [ ] / FAIL [ ]
  WATCHLIST: PASS [ ] / FAIL [ ]
  PORTFOLIO: PASS [ ] / FAIL [ ]
  ALERTS  : PASS [ ] / FAIL [ ]
  SCREENER: PASS [ ] / FAIL [ ]
  NEWS    : PASS [ ] / FAIL [ ]
  AI CHAT : PASS [ ] / FAIL [ ]
  WEBSOCKET: PASS [ ] / FAIL [ ]

Performance Benchmarks:
  API < 500ms P95: PASS [ ] / FAIL [ ]
  Chart < 500ms  : PASS [ ] / FAIL [ ]
  Memory stable  : PASS [ ] / FAIL [ ]

Overall Status: PASS / FAIL / CONDITIONAL PASS
Notes:
_______________________________________________________
_______________________________________________________
```

---

## Bug Report Template

```
Bug ID: BUG-V2-XXX
Feature: [Feature Name]
Phase: 2.X
Severity: CRITICAL / HIGH / MEDIUM / LOW

Summary: [หนึ่งประโยคสั้น]

Steps to Reproduce:
1.
2.
3.

Expected: [ควรเป็นอย่างไร]
Actual: [เกิดอะไรขึ้นจริง]

Environment:
- Commit: xxxxxxx
- Docker image: [ชื่อ image + tag]
- Browser: Chrome/Firefox version

Evidence: [Screenshot / log snippet]
```

---

*End of QA Test Plan*
*Document generated by: System Analysis on 2026-03-04*
