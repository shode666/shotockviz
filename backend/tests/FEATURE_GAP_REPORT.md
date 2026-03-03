# ShotockViz Feature Gap Report — Professional Trader Perspective

**Date:** 2026-03-02
**Analyst:** Senior Trading Expert (15+ years SET/US markets)
**Target User:** Thai swing trader, 8yr SET, 4yr US, 40-60 symbols, swing+position holds
**Review Basis:** REQUIREMENTS.md, master_plan.md, trade-prompt.md (15 strategies), current implementation

---

## Executive Summary

ShotockViz has **strong foundations** (chart infrastructure, basic indicators, watchlist, alerts) but **critical gaps** prevent daily professional trading:

- **Chart & Indicators:** 5 out of 15 Pine Script strategies can be screened; 10 missing patterns
- **Portfolio:** No realized P&L, dividend tracking, or tax-lot accounting
- **Alerts:** Price alerts work but no technical pattern alerts (Golden Cross, Volume Spike)
- **Screener:** Basic RSI/MACD only; missing multi-indicator confluence and strategy pattern matching
- **Data Quality:** Thai mutual funds block portfolio queries; .BK data unreliable

**Critical blockers for daily use:** P&L calculation, realized gains reporting, screener strategy patterns

---

## A. Chart & Technical Analysis

### What the Trader Uses (from trade-prompt.md — 15 Strategies)

**Thai (SET) Focus:**
1. Mean Reversion (Bollinger Bands + RSI 14)
2. Breakout (Donchian Channels + Volume)
3. Scalping (Hull MA + Stochastic)
4. Multi-Timeframe Filter (Daily EMA 200 + 15m EMA 9/21)
5. Gold Dipper Pro (EMA 50 + pullback dips)

**US/Gold Focus (additional 10 strategies):**
6. Trend Following (EMA 21/50/200 + ADX)
7. Mean Reversion (RSI < 30 + BB + Stochastic + MACD divergence)
8. Breakout (Consolidation + Donchian + Volume)
9. News Trading (1-min spikes, pre-news consolidation)
10. Range Trading (ATR bands, oversold/overbought)
... (+ 5 more complex strategies with momentum scoring, correlation, Hurst exponent)

### Current Implementation Status

**IMPLEMENTED (✅):**
- SMA (Simple Moving Average) — 20 default
- EMA (Exponential Moving Average) — 50 default
- Bollinger Bands — 20, 2.0 std dev
- RSI — 14 period
- MACD — 12, 26, 9
- Volume overlay
- ATR (via chart API)
- Candlestick, Line, Area charts
- Timeframe switching (1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M)

**MISSING (❌) — Critical for Strategies:**

| Indicator | Used in Strategy | Impact | Effort |
|-----------|-----------------|--------|--------|
| **Hull Moving Average (HMA)** | Scalping (#3) | Faster trend detection (9-period HMA < standard EMA) | S — 2 hrs |
| **Stochastic Oscillator** | Scalping (#3), Reversal (#7) | Oversold/Overbought zones; highly sensitive | S — 2 hrs |
| **Donchian Channels** | Breakout (#2, #8) | 20-bar high/low; core entry signal | S — 2 hrs |
| **ADX (Trend Strength)** | Trend Follow (#6) | Filter: only trade if ADX > 25; exit if < 20 | S — 2 hrs |
| **Ichimoku Cloud** | Overlay (spec, but not critical) | Thai traders love; support/resistance + trend | M — 4 hrs |
| **VWAP (Volume-Weighted Avg Price)** | Scalping gold (#1) | Price action anchor; volume confirmation | S — 2 hrs |
| **Fibonacci Retracement** | Multi-TF (#4), Confluence (#8) | Auto-draw 50%, 61.8%, 78.6% levels | M — 4 hrs |
| **Support/Resistance Auto-Detect** | Confluence analysis | Find swing highs/lows programmatically | M — 6 hrs |
| **Pivot Points (Daily/Weekly)** | Range trading, confluences | Quick daily levels without manual drawing | S — 2 hrs |
| **CCI (Commodity Channel Index)** | Advanced reversals | Overbought/oversold alternative to RSI | S — 2 hrs |

**Multi-Timeframe Analysis (Missing):**
- No HTF (Higher TimeFrame) data fetch for "Daily Trend Filter" (strategy #4)
- Can't overlay 4H/1D on 15m chart to confirm bias
- **Impact:** Strategy #4 requires checking daily EMA 200 from within 15m chart — not possible

**Chart Features Missing:**
- **Trend Lines + Trend Channels** — core tool for swing traders
- **Support/Resistance Zones** — visual grouping (not just horizontal lines)
- **Divergence Detection** — auto-find RSI divergences on peaks/troughs
- **Golden Cross / Death Cross Markers** — visual alerts for MA crossovers
- **Volume Spike Highlights** — automatically shade high-volume candles

### Gap Analysis — Chart & Indicators

| Feature | Priority | Effort | Impact | Notes |
|---------|----------|--------|--------|-------|
| Stochastic Oscillator | P0 | S | **High** — needed for 2 strategies (Scalp, Reversal) | Easy to implement; key oscillator |
| Donchian Channels | P0 | S | **High** — core for Breakout pattern (#2, #8) | Breakout strategies = 40% of trader's toolkit |
| Hull MA | P0 | S | **High** — Scalping sensitivity critical | Reduces lag vs EMA; must have |
| ADX (Trend Strength) | P1 | S | **Medium** — filter for Trend Following (#6) | Prevents low-conviction trades |
| Multi-Timeframe HTF | P1 | M | **High** — Strategy #4 depends on this | Daily bias on 15m chart = huge edge |
| Fibonacci Retracement (auto) | P1 | M | **Medium** — swing traders love levels | Confluence analysis; quality-of-life |
| Ichimoku Cloud | P2 | M | **Medium** — Thai traders familiar | Nice-to-have; not in main 5 strategies |
| VWAP | P2 | S | **Low** (US gold focus, not SET) | Gold Scalping but less critical for Thai stocks |
| CCI | P2 | S | **Low** — alternative to RSI | Niche; lower priority |

### Verdict: Chart & Technical Analysis

**Current: 35% complete** (5 core indicators + basic tools)
**Needed for 5-strategy rotation: 70%** (add Stochastic, Donchian, HMA, ADX, HTF)
**Professional standard: 85%** (+ Fibonacci, Support/Resistance auto-detect)

---

## B. Portfolio & P&L Tracking

### What the Trader Needs

**Holdings Snapshot:**
- ✅ Current market value (price × qty)
- ✅ Unrealized P&L (current value - cost basis)
- ✅ Unrealized P&L %
- ❌ **Realized P&L from closed positions** (MISSING — CRITICAL)
- ❌ **Realized gains per position** (for tax reporting)
- ❌ **Cost basis FIFO/LIFO/average cost** (partially done; FIFO not enforced)

**Multi-Currency Support:**
- ✅ THB (Thai Baht) for SET holdings
- ✅ USD for US stocks
- ❌ **Forex conversion** (store exchange rates for historical cost conversion)
- ❌ **Currency gains/losses** (if USD appreciate vs THB)
- ❌ **Base currency reporting** (all P&L in THB or USD view)

**Dividend & Corporate Events:**
- ❌ **Dividend tracking** (amount, ex-date, received date)
- ❌ **Dividend reinvestment** (automatic transaction creation)
- ❌ **XD/XR markers on chart** (partially in spec; not implemented)
- ❌ **Tax implications** (15% Thai dividend tax, 0% US qualified dividend)

**Advanced Analytics:**
- ✅ Sharpe Ratio, Max Drawdown, Beta (marked as P1 in REQUIREMENTS, but check if working)
- ❌ **Per-position Sharpe** (by symbol, not portfolio-wide)
- ❌ **Win Rate** (% of profitable closes vs total)
- ❌ **Profit Factor** (total gains / total losses)
- ❌ **Average Win/Loss** (trade-level metrics)
- ❌ **Holding Period Analysis** (median days held)

**Reporting:**
- ❌ **Realized Gains Report** (for tax form OR personal records)
- ❌ **Year-to-Date P&L** (Jan–Dec cumulative)
- ❌ **Monthly Return Attribution** (which stocks drove month's performance)

### Current Implementation

**What Works:**
- Transactions stored (BUY/SELL) with date, price, qty, fee
- Cost basis calculation (total_cost / qty)
- Unrealized P&L = (current_price - avg_cost) × qty

**What's Broken / Missing:**
1. **No realized P&L** — closing a position with SELL doesn't record profit/loss separately
2. **FIFO not enforced** — if you BUY 100 @ $10, BUY 100 @ $20, SELL 100 → system doesn't know which 100 you sold
3. **Mutual Funds ignored** — Thai funds (SCBS&P500, PRINCIPAL IPROP-D) return `current_price = NULL`, breaking analytics
4. **No dividend table** — can only add fake dividend as "DIVIDEND" transaction manually
5. **No currency conversion** — USD holdings cost is stored in USD but can't see in THB

### Gap Analysis — Portfolio & P&L

| Feature | Priority | Effort | Impact | Status |
|---------|----------|--------|--------|--------|
| **Realized P&L Tracking** | P0 | M | **CRITICAL** — daily trading decision | Partially; SELL closes position but doesn't record gain |
| **Trade-level Reporting** | P0 | M | **CRITICAL** — tax reporting | Missing completely |
| **FIFO Cost Basis** | P0 | M | **High** — correct cost calc | Not enforced; assumes avg cost |
| **Dividend Transactions** | P1 | S | **High** — income tracking | Manual workaround; should be auto-detected |
| **Multi-Currency P&L** | P1 | M | **Medium** — USD position reporting | USD holdings possible but no forex conversion |
| **Year-to-Date Summary** | P1 | S | **Medium** — quarterly review | Missing; needs dashboard card |
| **Per-Position Metrics** | P1 | M | **Medium** — trade analysis | Missing (Sharpe, Win%, profit factor by symbol) |
| **Tax Reporting Export** | P2 | M | **Medium** — end-of-year | Missing CSV export |

### Verdict: Portfolio & P&L

**Current: 30% complete** (transactions tracked; no realized P&L, no tax support)
**Needed for daily trading: 70%** (realized P&L, trade reports, FIFO cost)
**Professional: 85%** (+ dividends, multi-currency, tax exports)

---

## C. Screener & Discovery

### What the Trader Uses

**Pine Script Strategies as Screeners:**

The trader has **15 strategies** that should be runnable as screener filters:

1. **Mean Reversion** → Filter: RSI < 30 + Price < lower BB + Stochastic < 20
2. **Breakout** → Filter: Price > Donchian high + Volume > 1.5x avg
3. **Scalping** → Filter: Hull MA uptrend + Stochastic %K > %D in oversold
4. **Multi-TF** → Filter: Price > Daily EMA 200 + 15m EMA 9 > EMA 21
5. **Gold Dipper** → Filter: Price touches EMA 10 ± 1 SD while > EMA 50
6. **Trend Follow** → Filter: EMA 21 > 50 > 200 + ADX > 25
... (9 more complex patterns)

**Other Standard Filters:**
- Market: SET vs US
- Price Range: min/max
- Market Cap: min/max
- P/E Ratio: min/max
- Dividend Yield
- Volume Confirmation

### Current Implementation

**What Works:**
- Basic filters: RSI, Price range, Market cap (some via Finnhub)
- MACD signal (bullish/bearish)
- Volume ratio (1.5x, 2x avg)
- Price vs MA200/MA50

**What's Missing:**

| Pattern | Type | Effort | Impact |
|---------|------|--------|--------|
| **Stochastic Oversold** | Indicator | S | Core for mean reversion screening |
| **Donchian High Breakout** | Indicator | S | Breakout pattern screening |
| **Golden Cross** | Pattern | S | MA 50 × MA 200 crossover signal |
| **Death Cross** | Pattern | S | MA 50 ⊗ MA 200 crossover signal |
| **ADX > 25** | Filter | S | Trend strength gate |
| **Volume Spike 3x** | Volume | S | High-conviction setup |
| **Bollinger Band Position** | Position | S | Price at upper/lower band |
| **Hull MA Slope** | Trend | M | Positive slope direction |
| **MACD Divergence** | Pattern | M | RSI high but MACD low (reversal signal) |
| **Support/Resistance Break** | Level | M | Price breaks key level with volume |
| **Multi-TF Confluence** | Cross-TF | L | Daily trend + 4H level + 15m entry |

### Gap Analysis — Screener

| Feature | Priority | Effort | Impact | Strategies Using |
|---------|----------|--------|--------|-------------------|
| **Stochastic Filter** | P0 | S | **High** — 2/5 main strategies | Scalp, Reversal |
| **Donchian High/Low** | P0 | S | **High** — 2/5 main strategies | Breakout ×2 |
| **Golden/Death Cross** | P0 | S | **Medium** — common filter | Trend Following |
| **ADX Filter** | P0 | S | **Medium** — trend confirmation | Trend Following |
| **Volume 3x Spike** | P1 | S | **High** — breakout confirmation | Breakout |
| **Hull MA Slope** | P1 | S | **Medium** — trend direction | Scalping |
| **MACD Divergence** | P1 | M | **Medium** — reversal warning | Reversal |
| **Bollinger Band Squeeze** | P1 | S | **Low** — edge case | Breakout prep |
| **Multi-TF Confluence** | P2 | L | **High** but complex — future phase | Strategy #4 |

### Verdict: Screener

**Current: 25% complete** (basic RSI/MACD/volume only)
**Needed for 5-strategy rotation: 60%** (add Stochastic, Donchian, Golden/Death cross, ADX, Volume 3x)
**Professional: 80%** (+ divergence detection, MTF confluence)

---

## D. Alerts & Notifications

### What the Trader Needs

**Price Alerts:**
- ✅ Price crosses above target
- ✅ Price crosses below target

**Technical Alerts:**
- ❌ **RSI Crosses 30/50/70** (oversold entry, neutral zone, overbought)
- ❌ **Golden Cross** (MA 20 × MA 50, MA 50 × MA 200)
- ❌ **Death Cross** (MA 20 ⊗ MA 50, MA 50 ⊗ MA 200)
- ❌ **MACD Crossover** (MACD crosses above/below signal line)
- ❌ **Volume Spike** (today's volume > 2x avg volume)
- ❌ **Bollinger Band Touch** (price touches upper/lower band)
- ❌ **Stochastic Crossover** (%K crosses %D)
- ❌ **ATR Expansion** (daily ATR > 2x 20-day avg ATR)

**Notification Channels:**
- ✅ In-app notification (model exists)
- ✅ Telegram Bot (infrastructure ready; not fully wired)
- ❌ Email (SMTP config missing)
- ❌ Mobile push (out of scope)

**Alert Management:**
- ✅ Create/edit/delete alerts
- ✅ Toggle active/inactive
- ❌ **Alert History** (when did alert trigger, what was price)
- ❌ **Alert Statistics** (how often was this alert useful)
- ❌ **Snooze Alert** (silence for N hours, then re-enable)

### Current Implementation

**What Works:**
- Alert CRUD endpoints
- `alert_type` enum (PRICE_ABOVE, PRICE_BELOW, RSI_OVERBOUGHT, RSI_OVERSOLD, ...)
- Celery `alert_checker` worker runs every minute
- Basic price-level checking

**What's Broken:**
- `alert_checker.py` doesn't compute RSI/MACD/indicators in real-time; would need price data
- Telegram delivery endpoint exists but not called by alert_checker
- No alert trigger history table (loses record after notification)
- Missing: Golden Cross, Death Cross, Volume Spike, MACD, Stochastic alerts

### Gap Analysis — Alerts

| Feature | Priority | Effort | Impact | Status |
|---------|----------|--------|--------|--------|
| **Golden/Death Cross** | P0 | M | **High** — core swing signals | Missing |
| **Volume Spike Alert** | P0 | S | **High** — breakout warning | Missing |
| **RSI Pattern Alerts** | P0 | M | **High** — but RSI-based strategies | Partially (RSI > 70, < 30 exist) |
| **MACD Crossover** | P1 | M | **Medium** — trend confirmation | Missing |
| **Stochastic Crossover** | P1 | M | **Medium** — momentum signal | Missing |
| **Bollinger Band Touch** | P1 | S | **Medium** — mean reversion entry | Missing |
| **Alert History** | P1 | M | **Medium** — audit trail | Missing |
| **Telegram Delivery** | P1 | S | **High** but ready to wire | Infra ready; not hooked up |
| **Alert Snooze** | P2 | S | **Low** — nice-to-have | Missing |

### Verdict: Alerts

**Current: 40% complete** (price alerts work; technical alerts mostly missing)
**Needed for daily trading: 70%** (Golden/Death cross, Volume spike, MACD, Telegram delivery)
**Professional: 80%** (+ history, snooze, statistics)

---

## E. Dashboard & Overview

### What the Trader Needs

**Market Status:**
- ✅ SET & US indices (price, % change)
- ✅ Market open/closed indicator
- ✅ Trading hours display
- ❌ **Economic calendar** (upcoming news events)
- ❌ **Circuit breaker status** (for SET, when halted)

**Portfolio Snapshot:**
- ✅ Total portfolio value
- ✅ Unrealized P&L (THB / %)
- ✅ Top 3–5 holdings
- ❌ **Realized P&L today / YTD**
- ❌ **Daily return %**
- ❌ **Weighted sector allocation**

**Movers & Alerts:**
- ✅ Top gainers (SET + US)
- ✅ Top losers
- ✅ Alert proximity checks
- ❌ **Volume leaders** (which stocks had highest volume)
- ❌ **New 52-week highs/lows**

**Watchlist Quick View:**
- ✅ Price + % change
- ✅ Sparkline (7-day micro-chart)
- ❌ **Alert count** (how many active alerts on this stock)
- ❌ **Recent news count** (unread news articles)

### Current Implementation

**What Works:**
- Dashboard loads indices, portfolio summary, movers
- Alert proximity display
- Quick watchlist sidebar

**What's Broken:**
- Mutual fund symbols cause portfolio fetch to timeout (fixed in source, but slow)
- No realized P&L on dashboard
- No sector breakdown

### Gap Analysis — Dashboard

| Feature | Priority | Effort | Impact |
|---------|----------|--------|--------|
| **Realized P&L Card** | P0 | S | **High** — daily profit tracking | Depends on portfolio realized P&L feature |
| **Economic Calendar** | P1 | M | **Medium** — avoid news events | Finnhub API has events |
| **Volume Leaders** | P1 | S | **Medium** — breakout confirmation | Sort by volume |
| **Sector Allocation Pie** | P1 | M | **Medium** — risk management | Requires sector tagging |
| **52-Week Range Indicator** | P2 | S | **Low** — price context | Nice visual |

### Verdict: Dashboard

**Current: 70% complete** (core metrics present; missing realized P&L, sector breakdown)
**Needed for daily trading: 85%** (add realized P&L)
**Professional: 90%** (+ economic calendar, sector breakdown)

---

## F. Data Reliability & Sources

### Thai Stocks (.BK)

**Current Status:** ⚠️ Unreliable

| Issue | Impact | Workaround |
|-------|--------|-----------|
| Yahoo Finance intermittent (timeout/empty) | Slow portfolio loads | Increase retry; cache aggressively |
| Thai mutual funds (SCBS&P500, PRINCIPAL IPROP-D) rejected by Yahoo | Portfolio queries timeout | Filter out non-yahoo-fetchable symbols |
| No Thai economic data (earnings, dividends) from Yahoo | Missing fundamentals | Manual entry or SET website scraping |
| XD/XR dates not automatically fetched | Miss dividend impacts | Scrape SET website or manual marking |

**Solutions Implemented:**
- ✅ Period fallback (1y → 6m → 3m → 1m)
- ✅ Not-found cache to avoid hammering invalid symbols
- ✅ 12s timeout guard on batch queries

**Still Missing:**
- ❌ Alternative Thai data source (Stooq doesn't support .BK)
- ❌ SET website scraper for XD/XR dates
- ❌ Dividend calendar integration

### US Stocks (NYSE/NASDAQ)

**Current Status:** ✅ Reliable

| Metric | Status |
|--------|--------|
| Quote data | ✅ 15-min delayed via Yahoo Finance |
| Fundamentals | ✅ Finnhub (free tier 60 calls/min) |
| News | ✅ Finnhub + RSS |
| Options (future) | Blocked by free tier limitation |

**Future:** Consider Polygon.io or Alpaca (free tier available)

### Mutual Funds (Thai)

**Current Status:** ❌ Broken

| Fund | Issue | Impact |
|------|-------|--------|
| SCBS&P500 | Not on Yahoo Finance | Portfolio shows "ไม่มี NAV" |
| PRINCIPAL IPROP-D | Not on Yahoo Finance | Can't track NAV |
| MPDIVMF | Not on Yahoo Finance | Can't compute P&L |

**Solutions:**
- ❌ Scrape Thai fund NAV from SET website (complex, fragile)
- ❌ Use Thai broker API (requires registration)
- ✅ Manual entry of NAV (user enters current NAV periodically)

**Interim:** Allow user to manually set current NAV for portfolio calculations

### Gap Analysis — Data

| Source | Priority | Effort | Impact |
|--------|----------|--------|--------|
| **Alternative Thai data** (Stooq MTF?) | P1 | L | **Medium** — reduce Yahoo dependency | Complex |
| **SET XD/XR scraper** | P1 | M | **High** — dividend impact visibility | SET website fragile to scraping |
| **Thai fund NAV API** | P2 | L | **Medium** — manual workaround acceptable | Requires Thai broker partnership |
| **Fallback data source for US** (Polygon) | P2 | M | **Low** — Yahoo reliable | Future scale |

### Verdict: Data Reliability

**Current: 65% complete** (US good; Thai .BK flaky; funds broken)
**Needed for daily trading: 80%** (Thai more reliable; funds updateable manually)
**Professional: 90%** (+ SET scraper, Polygon fallback)

---

## Priority Ranking: All Gaps

### P0 — MUST HAVE (daily trading blocked without)

1. **Realized P&L Tracking** (Portfolio)
2. **Stochastic Oscillator** (Chart)
3. **Donchian Channels** (Chart)
4. **Hull Moving Average** (Chart)
5. **Golden/Death Cross Alerts** (Alerts)
6. **Volume Spike Alerts** (Alerts)
7. **Screener: Golden/Death Cross Filter** (Screener)

**Total Effort:** 10 days (distributed)

### P1 — HIGH VALUE (weekly trading workflow)

1. **ADX Trend Filter** (Chart + Screener)
2. **FIFO Cost Basis** (Portfolio)
3. **Multi-Timeframe HTF** (Chart)
4. **Dividend Tracking** (Portfolio)
5. **Alert History** (Alerts)
6. **Dashboard Realized P&L Card** (Dashboard)
7. **Screener: Stochastic Filter** (Screener)
8. **Telegram Alert Delivery** (Alerts)

**Total Effort:** 15 days

### P2 — NICE-TO-HAVE (professional refinement)

1. **Fibonacci Retracement** (Chart)
2. **Support/Resistance Auto-Detect** (Chart)
3. **Ichimoku Cloud** (Chart)
4. **Tax Reporting Export** (Portfolio)
5. **Economic Calendar** (Dashboard)
6. **MACD Divergence Detection** (Screener)
7. **Multi-TF Confluence Screener** (Screener)

**Total Effort:** 20 days

---

## Summary Table: Current vs. Needed

| Feature Area | Current | P0 Need | P1 Need | Professional |
|--------------|---------|---------|---------|--------------|
| **Chart & Indicators** | 35% | 70% | 75% | 85% |
| **Portfolio & P&L** | 30% | 70% | 80% | 90% |
| **Screener** | 25% | 60% | 70% | 85% |
| **Alerts** | 40% | 75% | 85% | 90% |
| **Dashboard** | 70% | 85% | 90% | 95% |
| **Data Quality** | 65% | 75% | 80% | 90% |
| **OVERALL** | **43%** | **73%** | **80%** | **89%** |

---

## Implementation Strategy

### Phase 2A: Critical Gaps (Week 1–2) — Get to P0
**Goal:** Enable daily swing trading with screener + alerts

1. **Stochastic, Donchian, Hull MA** (chart)
2. **Realized P&L engine** (portfolio)
3. **Golden/Death cross, Volume spike** (alerts)
4. **Golden/Death cross screener** (screener)

### Phase 2B: Trading Workflow (Week 3–4) — Reach P1
**Goal:** Professional feature completeness

1. **ADX filter** (chart + screener)
2. **Multi-TF HTF data** (chart)
3. **FIFO cost basis** (portfolio)
4. **Alert history + Telegram** (alerts)
5. **Dashboard P&L card** (dashboard)

### Phase 3: Refinement (Week 5–8) — Polish to Professional
**Goal:** Advanced analysis features

1. **Fibonacci, S/R auto-detect** (chart)
2. **Ichimoku** (chart)
3. **MACD divergence** (screener)
4. **Dividend tracking** (portfolio)
5. **Tax reporting** (portfolio)

---

## Conclusion

**ShotockViz is 43% feature-complete for professional trading.**
The app has solid **foundations** (chart engine, auth, data pipeline) but needs **15–20 days of work** to reach daily-trading readiness (P0 + P1).

**Critical blockers:**
1. No realized P&L → can't measure daily performance
2. Missing 10 indicators → screener can't run trader's 15 strategies
3. Technical alerts missing → can't automate entry signals
4. Thai data unreliable → portfolio loads slow

**Next phase should focus on:**
- Realized P&L calculation (blocks portfolio work)
- Missing indicators (Stochastic, Donchian, Hull MA) (blocks screener)
- Technical alerts (blocks automation)

These 3 features unlock 70% of daily workflow.

---

*End of Report*
