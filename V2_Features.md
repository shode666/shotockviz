# ShotockViz V2 — Professional Feature Expansion

**Project:** ShotockViz (Self-hosted Stock Analysis Platform)
**Target Version:** 1.5.0+ (Institutional-Grade Features)
**Focus:** Data Integrity, Advanced Analysis, and System Observability

---

## 1. Advanced Data Engine (Reliability & Adjustments)
ยกระดับความแม่นยำของข้อมูลเพื่อให้รองรับการวิเคราะห์ทางเทคนิคระดับสูง

- **Multi-Source Symbol Mapping**: สร้างระบบ Internal Mapping เพื่อเชื่อมโยง Symbol ระหว่าง Yahoo Finance (.BK), Finnhub (US), และ ThaiNAV ให้แสดงผลเป็นหนึ่งเดียวบนหน้าจอ
- **Corporate Action Adjustments**: เพิ่มระบบคำนวณราคาแบบ **Adjusted Price** (ปันผล/แตกหุ้น) เพื่อป้องกันสัญญาณหลอก (False Signals) ใน Technical Indicators เมื่อเกิด XD/XR
- **Hybrid Fetching Logic**: พัฒนาระบบสำรองแบบ Asyncio background fetch เมื่อ Celery Worker ไม่ตอบสนอง เพื่อลดปัญหา Quote 202 (Pending)

## 2. Institutional-Grade Fundamentals (Koyfin Style)
เน้นการวิเคราะห์เชิงเปรียบเทียบและการดูสุขภาพการเงินแบบ Dashboard

- **Relative Strength (RS) Line**: เพิ่ม Indicator เปรียบเทียบความแข็งแกร่งของหุ้นรายตัวเทียบกับ Benchmark (เช่น PTT.BK vs ^SET.BK) เพื่อหาหุ้นที่ Outperform ตลาด
- **Financial Health Scorecard**: Dashboard แสดงงบการเงินย้อนหลัง 10 ปี (Revenue, Net Profit, ROE, D/E) ในรูปแบบ Bento Grid ที่สวยงามและอ่านง่าย
- **Earnings Surprise Tracker**: ระบบเปรียบเทียบกำไรจริง (Actual) เทียบกับคาดการณ์ (Estimates) พร้อมแสดงผลกระทบต่อราคาหลังประกาศงบ

## 3. Intelligent Observability (Operations)
ยกระดับการจัดการระบบหลังบ้านให้ตรวจสอบได้แบบ Real-time ตามมาตรฐาน Senior Dev

- **Flower Monitoring Dashboard**: ติดตั้ง Flower ใน Docker Compose เพื่อตรวจสอบสถานะและ Performance ของ Celery Workers ทั้ง 10 ตัวแบบละเอียด
- **pgvector Integration (RAG)**: ติดตั้ง Extension `pgvector` ใน PostgreSQL เพื่อทำ Semantic Search ให้ AI (Ollama) สามารถดึงข่าวสารที่เกี่ยวข้องที่สุดมาวิเคราะห์ได้อย่างแม่นยำ
- **Data Retention UI**: หน้าจอตั้งค่าระยะเวลาการเก็บข้อมูล (Housekeeping Policy) เพื่อให้ User บริหารจัดการพื้นที่ Disk บนเครื่อง Local ได้เอง

## 4. Professional Analysis Tools (TradingView Style)
เพิ่มเครื่องมือสำหรับ Trader มืออาชีพ

- **Volume Profile (Visible Range)**: แสดงความหนาแน่นของปริมาณการซื้อขายในแต่ละระดับราคาบนกราฟ เพื่อหาแนวรับ-ต้านที่แท้จริง
- **Multi-Chart Layout**: รองรับการแบ่งหน้าจอ (Split View) เพื่อดูหุ้นหลายตัวหรือหลาย Timeframe (เช่น 1D และ 15m) พร้อมกันในหน้าเดียว
- **Strategy Backtesting UI**: ระบบจำลองการเทรดจากสัญญาณ Alert (เช่น Golden Cross) เพื่อดูสถิติ Win Rate และ Max Drawdown ย้อนหลัง

---

## Technical Stack Update (V2)

| Layer | Component | Description |
|-------|-----------|-------------|
| **Database** | PostgreSQL 16 + **pgvector** | เพิ่มความสามารถในการทำ AI Context Retrieval (RAG) |
| **Observability** | **Flower** | ระบบ Monitor Celery Task Queue ผ่าน Web UI |
| **Data Flow** | **CQRS + Mapping Layer** | แยกส่วนงานอ่าน/เขียน และทำ Symbol Normalization |
| **Frontend** | React 19 + **Glassmorphism** | ปรับปรุง UI ให้ทันสมัยด้วย Backdrop Blur และ Micro-animations |

---

## Implementation Roadmap

1. **Phase 2.1**: ติดตั้ง Flower และแก้ปัญหา Celery Quote 202
2. **Phase 2.2**: พัฒนา Symbol Mapping และ Adjusted Price Logic
3. **Phase 2.3**: เพิ่มระบบ RS Line และ Financial Scorecard
4. **Phase 2.4**: ติดตั้ง pgvector และอัปเกรด AI Chat ให้ฉลาดขึ้น