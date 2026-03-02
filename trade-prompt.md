# 5 Super Prompts ที่ออกแบบมาให้ AI เขียนโค้ด Pine Script V5 ได้อย่างแม่นยำ ครบถ้วนทั้งระบบจัดการความเสี่ยงและการแสดงผล

### 1. ระบบ Mean Reversion (Bollinger Bands + RSI)
**จุดเด่น:** เหมาะสำหรับการหาจุดกลับตัวเมื่อราคา "ถูกเกินไป" หรือ "แพงเกินไป"
****Super Prompt:**** "เขียน Pine Script V5 สำหรับ Strategy โดยมีรายละเอียดดังนี้:
**Inputs:** สร้าง Input สำหรับ Bollinger Bands (Length: 20, Mult: 2.0) และ RSI (Length: 14)
**Long **Entry:**** ราคาปิดต้องอยู่ต่ำกว่า Lower Band ของ Bollinger Bands และค่า RSI ต้องน้อยกว่า 30
**Short **Entry:**** ราคาปิดต้องอยู่สูงกว่า Upper Band ของ Bollinger Bands และค่า RSI ต้องมากกว่า 70
**Long **Exit:**** ปิดออเดอร์เมื่อราคาแตะเส้น Basis (เส้นกลาง) ของ Bollinger Bands หรือ RSI มากกว่า 70
Risk Management: กำหนดอัตราส่วน Risk/Reward ที่ 1:2 โดยตั้ง Stop Loss ไว้ที่ราคาต่ำสุดของแท่งเทียนก่อนหน้า (Previous Swing Low)
**Visuals:** ระบายสีพื้นหลังเป็นสีเขียวเมื่อเงื่อนไขครบ และแสดง Label คำว่า 'BUY' บนกราฟ
**Coding:** ห้ามมีการ Repaint สัญญาณย้อนหลัง และใส่คอมเมนต์อธิบายทุกบรรทัด"

### 2. ระบบ Breakout ตามแนวโน้ม (Donchian Channels + Volume)
**จุดเด่น:** จับจังหวะที่ราคา "ระเบิด" ออกจากกรอบเดิมด้วยวอลุ่มที่หนาแน่น
**Super Prompt:** "เขียน Pine Script V5 สำหรับ Strategy เพื่อจับจังหวะ Breakout:
**Logic:** ใช้ Donchian Channels (Length: 20) เพื่อหาจุดสูงสุดและต่ำสุดในรอบ 20 แท่ง
Entry Condition: เข้าซื้อ Long เมื่อราคาปิดสูงกว่า Upper Channel และ Volume ของแท่งนั้นต้องสูงกว่าค่าเฉลี่ย Volume EMA 20 วันอย่างน้อย 50%
Exit Condition: ปิดออเดอร์เมื่อราคาปิดต่ำกว่าเส้น Basis (เส้นกลางช่อง)
**Safety:** ใส่ฟังก์ชัน Trailing Stop Loss โดยให้ขยับจุดตัดขาดทุนตามราคาขึ้นไปเรื่อยๆ ที่ระยะ 2% จากจุดสูงสุดใหม่
**Table:** แสดงตารางสรุป Win Rate และ Maximum Drawdown ที่มุมขวาล่างของหน้าจอ"

### 3. ระบบ Scalping ความไวสูง (Hull MA + Stochastic)
**จุดเด่น:** เน้นความไว ลดความหน่วงของอินดิเคเตอร์ เหมาะกับ Timeframe เล็ก
**Super Prompt:** "เขียน Pine Script V5 สำหรับ Indicator สำหรับสาย Scalping:
Trend Filter: ใช้ Hull Moving Average (HMA Length: 9) เพื่อดูความชันของราคา
Momentum: ใช้ Stochastic Oscillator (14, 3, 3) เพื่อหาจุด Oversold/Overbought
Buy Signal: เมื่อ HMA มีความชันเป็นบวก (Slope Up) และ Stochastic %K ตัดเหนือ %D ในโซนต่ำกว่า 20
Visuals: เปลี่ยนสีแท่งเทียนเป็นสีเขียวเมื่ออยู่ในแนวโน้มขาขึ้นตาม HMA และแสดงสัญญาณ Alert เมื่อเกิดการตัดกันของ Stochastic"

### 4. ระบบ Multi-Timeframe Filter (Daily Trend + 15M Entry)
**จุดเด่น:** เทรดตามแนวโน้มใหญ่ เพื่อลดสัญญาณหลอก (False Signal)
**Super Prompt:** "เขียน Pine Script V5 สำหรับ Strategy แบบ Multi-Timeframe (MTF):
HTF Filter: ดึงข้อมูลจาก Timeframe 'Daily' หากราคาปัจจุบันอยู่เหนือเส้น EMA 200 ของ Daily ให้มองว่าเป็นขาขึ้น
Entry (15M): ใน Timeframe 15 นาที หากเงื่อนไข Daily เป็นขาขึ้น ให้เข้าซื้อเมื่อ EMA 9 ตัดเหนือ EMA 21
Risk: ตั้งค่า Stop Loss คงที่ที่ 150 pips และ Take Profit ที่ 300 pips
UI: แสดงสถานะเทรนด์ของ Daily (Bullish/Bearish) เป็นข้อความขนาดใหญ่ที่มุมซ้ายบนของกราฟ"

### 5. ระบบ Gold Dipper Pro (Standard Deviation + Pullback)
**จุดเด่น:** ยกระดับ Gold Dipper ให้เป็นระบบกึ่งอัตโนมัติที่แม่นยำขึ้น
**Super Prompt:** "เขียน Pine Script V5 สำหรับ Strategy ชื่อ 'Gold Dipper Pro':
**Trend Setup:** ใช้ EMA 50 เป็นเส้นแบ่งแนวโน้มหลัก
**Dip Detection:** สร้างโซน 'Buy Zone' โดยใช้เส้น EMA 10 และลบออกด้วยค่า 1 Standard Deviation
**Entry:** เมื่อราคาย่อตัวลงมาสัมผัส (Touch) ในโซน Buy Zone ขณะที่ราคายังอยู่เหนือ EMA 50 ให้ส่งสัญญาณเข้าซื้อ
**Exit:** ปิดออเดอร์เมื่อเกิดแท่งเทียน Bearish Reversal (เช่น Pin Bar หรือ Engulfing) ที่ด้านบน
**Constraint:** จำกัดการเปิดออเดอร์ไม่เกิน 1 ออเดอร์ต่อครั้ง และห้ามเปิดออเดอร์ในช่วงเวลา 23:00 - 08:00 (Market Close/Low Liquidity)"
10 Super Prompts for Gold Trading Strategies
1. Scalping Strategy - 5 Minute Chart
Create a Pine Script v6 scalping strategy for XAUUSD on 5-minute timeframe:

### Entry Rules:
- Long: Price crosses above VWAP + RSI(7) crosses above 50 + Volume > 1.5x average
- Short: Price crosses below VWAP + RSI(7) crosses below 50 + Volume > 1.5x average
- Only trade during London (8:00-12:00 GMT) and New York sessions (13:00-17:00 GMT)

### Filters:
- Only trade when ATR(14) > $5 (sufficient volatility)
- Avoid trading 15 minutes before/after major news events
- No trades if spread > $0.50

### Exit Rules:
- Take profit: 1:2 risk-reward ratio
- Stop loss: 0.3% of entry price or $3, whichever is larger
- Trailing stop: activate after 50% profit, trail by 0.15%
- Exit if position open > 30 minutes

### Visual Elements:
- VWAP line with session reset
- Dynamic support/resistance boxes
- Session time highlights (London=blue, NY=yellow)
- Real-time P&L display
- Win rate counter on chart

### Settings:
- Risk 1% per trade
- Max 5 trades per session
- Commission: $10 per trade


## 2. Trend Following - 4 Hour Chart
Build a Pine Script v6 trend-following strategy for gold 4H timeframe:

### Entry Rules:
- Long: Price breaks above 20-bar high + EMA(21) > EMA(50) > EMA(200) + ADX > 25
- Short: Price breaks below 20-bar low + EMA(21) < EMA(50) < EMA(200) + ADX > 25
- Confirm with MACD histogram turning positive/negative
- Wait for pullback to 21 EMA after initial breakout, then enter on bounce

### Filters:
- Only trade if price is >2% away from major round numbers ($1700, $1800, $1900, $2000, etc.)
- Avoid trading when Bollinger Bands width < 1% (low volatility)
- Check market structure: require 3 consecutive higher highs for long, 3 lower lows for short

### Exit Rules:
- Initial stop: below/above 50 EMA
- Move stop to breakeven when profit reaches 1:1
- Trail stop using parabolic SAR
- Exit if ADX drops below 20 (trend weakening)
- Maximum holding time: 10 bars (40 hours)

### Visual Elements:
- Triple EMA system with color gradient
- ADX strength meter on chart
- Trend strength zones (weak=gray, medium=yellow, strong=green/red)
- Entry/exit arrows with profit/loss labels
- Chandelier exit overlay

### Settings:
- Risk 2% per trade
- Position size based on ATR
- Min reward:risk = 3:1


## 3. Reversal Trading - 1 Hour Chart
Create a Pine Script v6 mean-reversion strategy for XAUUSD on 1H:

### Entry Rules:
- Long: RSI(14) < 30 + Price touches lower Bollinger Band + Stochastic oversold + bullish divergence on MACD
- Short: RSI(14) > 70 + Price touches upper Bollinger Band + Stochastic overbought + bearish divergence on MACD
- Require price rejection wick (wick > 60% of candle size)
- Volume must be declining (exhaustion signal)

### Filters:
- Only trade against the trend (counter-trend reversals)
- Check 4H timeframe: must be at key support/resistance zones
- Avoid if VIX equivalent (gold volatility) > 30
- Minimum distance from 200 SMA: 1%

### Exit Rules:
- Target: middle Bollinger Band or opposite BB
- Stop loss: 1.5x ATR beyond entry
- Scale out: 50% at 1:1.5, 50% at 1:3
- Emergency exit if RSI crosses back through 50

### Visual Elements:
- Bollinger Bands with color fill (green/red zones)
- RSI with divergence detection lines
- Support/resistance levels from daily/weekly
- Risk zones highlighted
- Statistics table showing win rate for oversold/overbought trades

### Settings:
- Risk 1.5% per trade
- Max 3 positions per day
- Slippage: 2 ticks


## 4. Breakout Strategy - 15 Minute Chart
Design a Pine Script v6 breakout strategy for gold 15-minute charts:

### Entry Rules:
- Identify consolidation zones (price range < 0.5% for minimum 20 bars)
- Long: Price breaks above consolidation high + volume spike (2x average) + momentum increasing
- Short: Price breaks below consolidation low + volume spike + momentum decreasing
- Use Donchian Channel (20 periods) to identify breakout levels
- Confirm with Squeeze Momentum indicator firing

### Filters:
- Only trade first breakout of the day (avoid false breakouts)
- Consolidation must last minimum 5 hours
- Must be at least 3 hours away from Federal Reserve announcements
- Check if price just broke a major psychological level

### Exit Rules:
- Initial target: measured move (consolidation height projected from breakout)
- Stop loss: middle of consolidation range
- Partial exit at 1x range, let runner go to 2x range
- Exit all if price re-enters consolidation zone

### Visual Elements:
- Consolidation boxes drawn automatically
- Breakout strength meter
- Volume profile at consolidation zones
- Measured move projections
- False breakout markers

### Settings:
- Risk 2% per trade
- Max 2 trades per day
- Alert system for consolidation formation


## 5. Swing Trading - Daily Chart
Build a Pine Script v6 swing trading strategy for XAUUSD daily timeframe:

### Entry Rules:
- Long: Golden cross (50 SMA crosses above 200 SMA) + price retests 50 SMA + hammer/bullish engulfing candle
- Short: Death cross (50 SMA crosses below 200 SMA) + price retests 50 SMA + shooting star/bearish engulfing
- Require weekly trend alignment (weekly 20 EMA direction matches trade)
- Wait for 3-bar consolidation after the cross before entering

### Filters:
- Only trade if monthly trend is clear (price > or < monthly 50 SMA)
- Avoid trading during summer months (June-August) - historically low trending
- Check US Dollar Index (DXY): inverse correlation confirmation
- Minimum ATR(14) > $15 for sufficient movement

### Exit Rules:
- Trail stop using 20-day EMA
- Exit if opposite crossover occurs
- Take 50% profit at 5% gain, let rest run
- Maximum hold time: 60 days
- Exit if price closes below/above 200 SMA on opposite side

### Visual Elements:
- 50/200 SMA with crossover markers
- Weekly and monthly trend indicators
- Support/resistance from weekly/monthly pivots
- Trend strength gauge
- Position tracker with days held

### Settings:
- Risk 3% per trade
- Max 2 positions open
- Compound profits
- Account for swap/overnight fees


## 6. News Trading - 1 Minute Chart
Create a Pine Script v6 news breakout strategy for gold 1-minute chart:

### Entry Rules:
- Detect 5-minute consolidation before news time (8:30 AM ET for NFP, CPI, etc.)
- Long: Explosive move up (price moves 0.3% in 1 minute) + volume 5x average + follow-through candle
- Short: Explosive move down + volume spike + follow-through
- Enter on first pullback (2-5 minutes after initial spike)

### Filters:
- Only trade high-impact news events (pre-programmed times)
- Ignore news trades if pre-news range < $3
- Check if initial spike broke previous daily high/low
- Avoid if first candle has long wick (false breakout indicator)

### Exit Rules:
- Fast **exit:** 0.5% profit target or 0.3% stop loss
- Close all positions within 30 minutes of news
- Use time-based stops: exit after 15 minutes regardless
- Trail aggressively: move stop to breakeven after 10 pips profit

### Visual Elements:
- News event markers with countdown
- Pre-news consolidation boxes
- Volatility explosion indicators
- Real-time profit tracker
- Speed-of-move meter

### Settings:
- Risk 0.5% per trade (high volatility)
- Max 1 trade per news event
- Wide spread tolerance: $2
- Fast execution mode


## 7. Range Trading - 30 Minute Chart
Build a Pine Script v6 range-bound strategy for XAUUSD 30-minute timeframe:

### Entry Rules:
- Identify trading range: price oscillating between support/resistance for min 2 days
- Long: Price at lower range + RSI < 40 + Stochastic oversold + bullish reversal pattern
- Short: Price at upper range + RSI > 60 + Stochastic overbought + bearish reversal pattern
- Use ATR bands to define dynamic range boundaries
- Confirm with decreasing ATR (range contraction)

### Filters:
- Range height must be 1-3% (not too tight, not too wide)
- Avoid if ADX > 25 (trending, not ranging)
- Must have touched each boundary at least 3 times
- Check hourly chart for no breakout setup forming

### Exit Rules:
- Target: opposite range boundary (90% of range)
- Stop: beyond range boundary by 0.5 ATR
- Exit if price breaks out of range with volume
- Scale out: 60% at 70% of range, 40% at target
- Maximum hold: until range boundary touched

### Visual Elements:
- Dynamic range boxes with support/resistance
- Range strength indicator (strong/weak range)
- Bounce probability meter
- Historical range success rate display
- Range breakout alert zones

### Settings:
- Risk 1.5% per trade
- High frequency: multiple trades per day
- Commission consideration important


## 8. Multi-Timeframe Confluence - 2 Hour Chart
Create a Pine Script v6 multi-timeframe strategy for gold 2H chart:

### Entry Rules:
- Long: Daily uptrend (price > 50 EMA) + 4H shows higher low + 2H shows bullish engulfing or pin bar at support
- Short: Daily downtrend + 4H shows lower high + 2H shows bearish pattern at resistance
- Require 3 timeframe alignment: Monthly, Weekly, Daily all showing same trend direction
- Use Fibonacci retracements from daily swing: enter at 50-61.8% retracement zones

### Filters:
- Check correlation with S&P500: risk-on vs risk-off environment
- Ensure clean market structure (no choppy patterns on higher TF)
- Volume must be increasing on entry timeframe
- Avoid if major moving averages are bunched together (indecision)

### Exit Rules:
- Trail stop using 4H ATR (2x ATR trailing)
- Take partials at Fibonacci extensions (1.272, 1.618)
- Exit if higher timeframe trend reversal signal appears
- Scale out strategy: 33% at each Fib level

### Visual Elements:
- Multi-timeframe panel showing trend on M, W, D, 4H
- Auto Fibonacci from higher timeframe
- Trend alignment indicator (green=all aligned, yellow=mixed, red=opposed)
- Key level markers from all timeframes
- Confluence zones highlighted

### Settings:
- Risk 2% per trade
- Position sizing based on daily ATR
- Hold time: days to weeks
- Prioritize quality over quantity


## 9. Session Breakout - 15 Minute Chart
Design a Pine Script v6 session-based breakout strategy for gold 15-min:

### Entry Rules:
- Define Asian session range (00:00-08:00 GMT): high and low
- Long: Price breaks above Asian high during London open (08:00-09:00 GMT) + momentum + volume
- Short: Price breaks below Asian low during London open + momentum + volume
- Confirm with 15-min close beyond the level
- Measure Asian range width: trade only if range is 0.3-1.2% (sweet spot)

### Filters:
- Monday: no trades (unpredictable after weekend)
- Friday after 12:00 GMT: no new trades (weekend risk)
- Avoid if Asian session already trending (not ranging)
- Check if breakout aligns with daily bias (trend direction)
- Require clean breakout candle (body > 70% of candle)

### Exit Rules:
- Target 1: Asian range height projected from breakout (1:1)
- Target 2: 1.5x Asian range height
- Stop loss: opposite side of Asian range + 0.1%
- Exit before NY close (20:00 GMT) if still in profit
- Breakeven stop after 30 minutes in profit

### Visual Elements:
- Asian session box auto-drawn each day
- Session separators (vertical lines)
- Breakout success rate stats by day of week
- Session volatility meter
- Time-to-target tracker

### Settings:
- Risk 1.5% per trade
- Max 1 trade per day (high probability setup)
- Time-based management crucial
- Consider spreads during session transitions


## 10. AI-Enhanced Momentum - 1 Hour Chart
Build an advanced Pine Script v6 momentum strategy for XAUUSD 1H with machine learning concepts:

### Entry Rules:
- Calculate momentum score: weighted average of RSI, MACD, rate of change, volume, and ADX
- Long: Momentum score > 70 + price > VWAP + breaking 10-hour high + increasing momentum over last 3 bars
- Short: Momentum score < 30 + price < VWAP + breaking 10-hour low + decreasing momentum
- Use Z-score to identify extreme momentum outliers (>2 standard deviations)
- Require 3 consecutive bars of momentum confirmation

### Filters:
- Adaptive filter: use different thresholds based on volatility regime (high/medium/low)
- Check correlation coefficient between price and momentum (>0.7 for entry)
- Avoid if price is consolidating (Bollinger Band width < 20th percentile)
- Use Hurst Exponent to determine trending vs mean-reverting state (trend only)
- Machine learning score: combine 5 different indicators with optimized weights

### Exit Rules:
- Exit when momentum score crosses back through 50 (neutral)
- Use Chandelier Exit (ATR-based trailing stop)
- Take profit at +3 standard deviations from entry
- Exit if momentum score reverses by 30 points
- Maximum hold: 24 hours

### Visual Elements:
- Momentum score gauge (0-100 scale)
- Regime indicator (trending/ranging/volatile)
- Multi-indicator dashboard with weights
- Probability-of-success meter based on historical patterns
- Heat map of momentum intensity
- Real-time correlation display

### Settings:
- Risk 2% per trade
- Adaptive position sizing based on confidence score
- Optimize weights quarterly using historical data
- Include slippage and commission modeling
- Backtesting period: minimum 5 years


### 💡 How to Use These Prompts:
Copy the entire prompt for your chosen strategy
Paste it to Claude , Gemini or ChatGPT with: "Create this Pine Script strategy"
Test the code in TradingView
Iterate: Ask AI to modify specific parts based on backtest results
Optimize: Request parameter tuning after initial testing
🎯 Quick Customization Tips:
Change timeframe: "Convert this to 30-minute instead of 1-hour"
Add filters: "Add a filter that avoids trading near round numbers"
Adjust risk: "Change risk to 1% and add position sizing based on volatility"
Visual tweaks: "Make the EMA green when bullish, red when bearish"

Remember: No strategy is perfect. Always backtest thoroughly, forward test on demo, and use proper risk management!

