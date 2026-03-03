# ShotockViz Next Phase Plan — TDD Development Roadmap

**Document:** Development Plan for Phase 2 (Data Reliability + Real-time)
**Timeline:** 3 weeks (21 days)
**Target:** Reach P0 (daily trading viable) + P1 (professional polish)
**Methodology:** Test-Driven Development (TDD) — write failing tests first, then implement

---

## Phase Overview

**Phase 1 (Current):** Stabilization — fix bugs, get core working
**Phase 2 (This Plan):** Data Reliability & Feature Completeness — make daily trading possible

### Phase 2 Goals
1. ✅ Realized P&L calculation (enable tax reporting)
2. ✅ Missing indicators on chart (Stochastic, Donchian, Hull MA, ADX)
3. ✅ Technical alerts (Golden/Death cross, Volume spike)
4. ✅ Enhanced screener (filters for above indicators)
5. ✅ Portfolio FIFO cost basis (correct accounting)
6. ✅ Telegram alert delivery (make alerts actionable)
7. ✅ Dashboard realized P&L card (daily performance visibility)

---

## Feature 1: Realized P&L Tracking

### Why (Trader Perspective)
*"I sold PTT.BK at 38.50 after buying at 36.00. I made 250 baht profit. I need to see this in my portfolio so I can track my daily win rate and file taxes correctly."*

### User Story
```
As a swing trader
I want to track realized gains/losses from closed positions
So that I can calculate tax obligations and measure trading performance
```

### Test Cases (TDD Red Phase)

**File:** `backend/tests/test_portfolio_realized_pl.py`

```python
import pytest
from datetime import date
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

class TestRealizedPL:
    """Portfolio realized P&L tracking — TDD tests."""

    @pytest.fixture
    async def portfolio_setup(self, client: AsyncClient, auth_headers: dict):
        """Create test user + initial holdings."""
        # Assume auth_headers fixture already provides logged-in client
        pass

    async def test_realized_pl_simple_round_trip(self, client, auth_headers):
        """
        BUY 100 AAPL @ $150
        SELL 100 AAPL @ $160
        → realized_pl = (160 - 150) * 100 = $1000
        """
        # Add BUY transaction
        resp = await client.post("/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "BUY",
                "qty": 100.0,
                "price": 150.0,
                "fee": 0.0,
                "date": "2026-01-01",
            },
            headers=auth_headers
        )
        assert resp.status_code == 201
        buy_txn = resp.json()

        # Add SELL transaction
        resp = await client.post("/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "SELL",
                "qty": 100.0,
                "price": 160.0,
                "fee": 0.0,
                "date": "2026-01-05",
            },
            headers=auth_headers
        )
        assert resp.status_code == 201

        # Check analytics
        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        # WILL FAIL until realized P&L tracking is implemented
        assert "realized_pl" in data
        assert data["realized_pl"] == 1000.0  # (160-150)*100
        assert data["realized_pl_pct"] == 6.67  # 1000 / 15000

        # Holdings should be empty (all closed)
        assert len(data["holdings"]) == 0

    async def test_realized_pl_partial_sell(self, client, auth_headers):
        """
        BUY 100 @ $150
        SELL 40 @ $160
        → realized_pl = (160-150) * 40 = $400
        → unrealized holding = 60 @ $150 = cost_basis $9000
        """
        # BUY
        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "PTT.BK",
                "type": "BUY",
                "qty": 100.0,
                "price": 150.0,
                "fee": 0.0,
                "date": "2026-01-01",
            },
            headers=auth_headers
        )

        # SELL 40
        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "PTT.BK",
                "type": "SELL",
                "qty": 40.0,
                "price": 160.0,
                "fee": 0.0,
                "date": "2026-01-05",
            },
            headers=auth_headers
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert data["realized_pl"] == 400.0  # (160-150)*40
        assert len(data["holdings"]) == 1
        assert data["holdings"][0]["symbol"] == "PTT.BK"
        assert data["holdings"][0]["qty"] == 60.0
        assert data["holdings"][0]["cost_basis"] == 9000.0  # 60*150

    async def test_realized_pl_with_multiple_buys_fifo(self, client, auth_headers):
        """
        FIFO cost basis:
        BUY 100 @ $100 (1/1)
        BUY 100 @ $120 (1/5)
        SELL 150 (1/10)
        → realized_pl = (100*(P-100) + 50*(P-120))

        Assuming SELL price $130:
        First 100 @ 100 → profit (130-100)*100 = $3000
        Next 50 @ 120 → profit (130-120)*50 = $500
        Total realized = $3500
        """
        # BUY 100 @ 100
        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "NVDA",
                "type": "BUY",
                "qty": 100.0,
                "price": 100.0,
                "fee": 0.0,
                "date": "2026-01-01",
            },
            headers=auth_headers
        )

        # BUY 100 @ 120
        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "NVDA",
                "type": "BUY",
                "qty": 100.0,
                "price": 120.0,
                "fee": 0.0,
                "date": "2026-01-05",
            },
            headers=auth_headers
        )

        # SELL 150 @ 130
        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "NVDA",
                "type": "SELL",
                "qty": 150.0,
                "price": 130.0,
                "fee": 0.0,
                "date": "2026-01-10",
            },
            headers=auth_headers
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        # WILL FAIL: current code doesn't implement FIFO
        assert data["realized_pl"] == 3500.0  # 3000 + 500

        # Remaining: 50 @ 120
        assert len(data["holdings"]) == 1
        assert data["holdings"][0]["qty"] == 50.0

    async def test_realized_pl_with_fees(self, client, auth_headers):
        """
        BUY 100 @ $150, fee $10
        SELL 100 @ $160, fee $10
        → realized_pl = (160*100 - 10) - (150*100 + 10) = $15990 - $15010 = $980
        """
        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "BUY",
                "qty": 100.0,
                "price": 150.0,
                "fee": 10.0,
                "date": "2026-01-01",
            },
            headers=auth_headers
        )

        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "SELL",
                "qty": 100.0,
                "price": 160.0,
                "fee": 10.0,
                "date": "2026-01-05",
            },
            headers=auth_headers
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert data["realized_pl"] == 980.0

    async def test_realized_pl_loss(self, client, auth_headers):
        """
        BUY 100 @ $150
        SELL 100 @ $140
        → realized_pl = (140-150)*100 = -$1000 (loss)
        """
        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "TSLA",
                "type": "BUY",
                "qty": 100.0,
                "price": 150.0,
                "fee": 0.0,
                "date": "2026-01-01",
            },
            headers=auth_headers
        )

        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "TSLA",
                "type": "SELL",
                "qty": 100.0,
                "price": 140.0,
                "fee": 0.0,
                "date": "2026-01-05",
            },
            headers=auth_headers
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert data["realized_pl"] == -1000.0

    async def test_realized_pl_by_symbol(self, client, auth_headers):
        """
        PTT: BUY 100@100, SELL 100@105 → realized $500
        AAPL: BUY 50@200, SELL 50@190 → realized -$500
        → total realized = $0

        Each holding should include realized_pl breakdown.
        """
        # PTT profit
        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "PTT.BK",
                "type": "BUY",
                "qty": 100.0,
                "price": 100.0,
                "fee": 0.0,
                "date": "2026-01-01",
            },
            headers=auth_headers
        )

        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "PTT.BK",
                "type": "SELL",
                "qty": 100.0,
                "price": 105.0,
                "fee": 0.0,
                "date": "2026-01-05",
            },
            headers=auth_headers
        )

        # AAPL loss
        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "BUY",
                "qty": 50.0,
                "price": 200.0,
                "fee": 0.0,
                "date": "2026-01-02",
            },
            headers=auth_headers
        )

        await client.post("/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "SELL",
                "qty": 50.0,
                "price": 190.0,
                "fee": 0.0,
                "date": "2026-01-06",
            },
            headers=auth_headers
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert data["realized_pl"] == 0.0  # 500 + (-500)

        # No open holdings (all closed)
        assert len(data["holdings"]) == 0

    async def test_realized_pl_with_dividend(self, client, auth_headers):
        """
        BUY 100 @ $100
        DIVIDEND $2 per share → +$200
        SELL 100 @ $105
        → realized_pl = (105*100 - 0) - (100*100) + 200 = $500 + $200 = $700

        NOTE: Dividend handling TBD — may be separate from realized_pl
        """
        # Placeholder: test if dividend adds to realized_pl
        pass
```

### Implementation Plan (TDD Green Phase)

**Step 1: Schema Update**

Modify `backend/models/portfolio.py`:

```python
# Add realized_pl tracking table
class ClosedPosition(Base):
    """Track closed positions for realized P&L and tax reporting."""
    __tablename__ = "closed_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String(20))

    qty: Mapped[float]  # How many shares closed
    avg_cost: Mapped[float]  # Average cost of those shares (FIFO)
    sell_price: Mapped[float]  # Sale price
    realized_pl: Mapped[float]  # (sell_price - avg_cost) * qty - fees
    realized_pl_pct: Mapped[float]  # realized_pl / (avg_cost * qty)

    buy_date: Mapped[date]
    sell_date: Mapped[date]
    holding_days: Mapped[int]  # sell_date - buy_date

    buy_fees: Mapped[float] = mapped_column(default=0.0)
    sell_fees: Mapped[float] = mapped_column(default=0.0)

    long_term: Mapped[bool]  # holding_days > 365 (tax implications)

    created_at: Mapped[datetime] = mapped_column(default=func.now())

    # Relationships
    user: Mapped[User] = relationship("User")
```

**Step 2: Update PortfolioAnalytics Response**

Modify `backend/models/schemas.py`:

```python
class PortfolioAnalytics(BaseModel):
    total_value: float
    total_cost: float
    unrealized_pl: float
    unrealized_pl_pct: float

    # NEW: Realized P&L
    realized_pl: float  # Sum of all closed positions
    realized_pl_pct: float  # realized_pl / total_cost (if meaningful)

    holdings: list[HoldingResponse]
    closed_positions: list[ClosedPositionResponse]  # NEW: closed trade history

    # Metrics
    total_trades: int
    win_rate: float  # % of trades that were profitable
    profit_factor: float  # sum(gains) / sum(losses)
    avg_holding_days: float

class ClosedPositionResponse(BaseModel):
    symbol: str
    qty: float
    avg_cost: float
    sell_price: float
    realized_pl: float
    realized_pl_pct: float
    holding_days: int
    long_term: bool
    buy_date: date
    sell_date: date
```

**Step 3: Update Portfolio Analytics Endpoint**

Modify `backend/api/routes/portfolio.py`:

```python
@router.get("/analytics", response_model=PortfolioAnalytics)
async def get_analytics(user: User = Depends(...), db: AsyncSession = Depends(...)):
    """Calculate realized + unrealized P&L."""

    # 1. Get all transactions
    txns = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date)
    )
    txns = txns.scalars().all()

    # 2. FIFO accounting: track open lots
    holdings: dict[str, list[dict]] = {}  # symbol → [{"qty": 100, "cost": 150, "date": ...}]
    realized_trades: list[dict] = []

    for txn in txns:
        if txn.type.value == "BUY":
            # Add to holdings
            if txn.symbol not in holdings:
                holdings[txn.symbol] = []
            holdings[txn.symbol].append({
                "qty": txn.qty,
                "cost": txn.price,
                "date": txn.date,
                "fee": txn.fee,
            })
        else:  # SELL
            # Close FIFO lots
            remaining_qty = txn.qty
            lot_idx = 0

            while remaining_qty > 0 and lot_idx < len(holdings[txn.symbol]):
                lot = holdings[txn.symbol][lot_idx]

                if lot["qty"] <= remaining_qty:
                    # Close entire lot
                    closed_qty = lot["qty"]
                    closed_cost = lot["cost"]
                    closed_fee = lot["fee"]

                    realized_pl = (txn.price - closed_cost) * closed_qty - txn.fee - closed_fee

                    realized_trades.append({
                        "symbol": txn.symbol,
                        "qty": closed_qty,
                        "avg_cost": closed_cost,
                        "sell_price": txn.price,
                        "realized_pl": realized_pl,
                        "buy_date": lot["date"],
                        "sell_date": txn.date,
                        "holding_days": (txn.date - lot["date"]).days,
                    })

                    remaining_qty -= closed_qty
                    lot_idx += 1
                else:
                    # Partial close
                    closed_qty = remaining_qty
                    closed_cost = lot["cost"]

                    realized_pl = (txn.price - closed_cost) * closed_qty - txn.fee

                    realized_trades.append({...})

                    lot["qty"] -= remaining_qty
                    remaining_qty = 0

            # Remove empty lots
            holdings[txn.symbol] = [lot for lot in holdings[txn.symbol] if lot["qty"] > 0]

    # 3. Calculate totals
    total_realized_pl = sum(t["realized_pl"] for t in realized_trades)

    # 4. Get current prices, calculate unrealized P&L (existing code)
    # ...

    return PortfolioAnalytics(
        realized_pl=total_realized_pl,
        realized_pl_pct=total_realized_pl / total_cost if total_cost > 0 else 0,
        closed_positions=[...],
        # ... rest of analytics
    )
```

**Step 4: Update Frontend Display**

Modify `frontend/src/components/pages/PortfolioPage.tsx`:

```tsx
// Add Realized P&L Card
<div className="grid grid-cols-3 gap-4">
  <Card className="col-span-1">
    <h3 className="text-sm font-medium text-gray-500">Realized P&L</h3>
    <div className={`text-2xl font-bold ${analytics.realized_pl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
      ฿{analytics.realized_pl.toLocaleString('th-TH', {minimumFractionDigits: 2})}
    </div>
    <p className="text-xs text-gray-400">{analytics.realized_pl_pct.toFixed(2)}%</p>
  </Card>

  <Card className="col-span-1">
    <h3 className="text-sm font-medium text-gray-500">Win Rate</h3>
    <div className="text-2xl font-bold text-blue-500">{analytics.win_rate.toFixed(1)}%</div>
    <p className="text-xs text-gray-400">{analytics.total_trades} trades</p>
  </Card>

  <Card className="col-span-1">
    <h3 className="text-sm font-medium text-gray-500">Profit Factor</h3>
    <div className="text-2xl font-bold">{analytics.profit_factor.toFixed(2)}</div>
    <p className="text-xs text-gray-400">Gains/Losses</p>
  </Card>
</div>

// Closed Positions Table
<Table>
  <thead>
    <tr>
      <th>Symbol</th>
      <th>Qty</th>
      <th>Entry</th>
      <th>Exit</th>
      <th>P&L</th>
      <th>Days Held</th>
    </tr>
  </thead>
  <tbody>
    {analytics.closed_positions.map(pos => (
      <tr key={...}>
        <td>{pos.symbol}</td>
        <td>{pos.qty}</td>
        <td>฿{pos.avg_cost.toFixed(2)}</td>
        <td>฿{pos.sell_price.toFixed(2)}</td>
        <td className={pos.realized_pl >= 0 ? 'text-green-500' : 'text-red-500'}>
          ฿{pos.realized_pl.toFixed(2)}
        </td>
        <td>{pos.holding_days}d</td>
      </tr>
    ))}
  </tbody>
</Table>
```

### Acceptance Criteria

- [ ] FIFO cost basis correctly assigned to SELL orders
- [ ] Realized P&L calculated with fees included
- [ ] Win rate ≥ 80% of closed positions show correct P&L
- [ ] Portfolio analytics shows realized + unrealized breakdown
- [ ] Frontend displays realized P&L card with % change
- [ ] Closed positions table shows history with holding days
- [ ] Long-term vs short-term gain flagged (>365 days)

---

## Feature 2: Stochastic Oscillator Indicator

### Why (Trader Perspective)
*"Stochastic %K crossing above %D in the oversold zone (<20) is my scalping entry signal. I need it on the chart."*

### User Story
```
As a swing trader using scalping strategies
I want to see Stochastic Oscillator on my chart
So that I can identify oversold bounces and entry points
```

### Test Cases (TDD Red Phase)

**File:** `backend/tests/test_stochastic_indicator.py`

```python
import pytest
import pandas as pd
import numpy as np
from backend.services.indicators import StochasticOscillator

class TestStochasticIndicator:
    """Stochastic %K/%D oscillator — TDD tests."""

    @pytest.fixture
    def sample_closes(self):
        """Sample closing prices for indicator testing."""
        return pd.Series([
            100, 102, 101, 103, 105, 104, 106, 107, 105, 104,  # Day 1-10
            103, 102, 101, 100, 99, 98, 97, 96, 97, 98,        # Day 11-20
            99, 100, 101, 102, 103, 104, 105, 106, 107, 108,   # Day 21-30
        ])

    async def test_stochastic_basic_calculation(self, sample_closes):
        """
        Stochastic = 100 * (Close - Low[period]) / (High[period] - Low[period])
        Period 14 default.

        For simple test: verify formula correctness.
        """
        stoch = StochasticOscillator(k_period=14, d_period=3)
        result = stoch.calculate(sample_closes)

        # Should return dict with %K and %D
        assert "stoch_k" in result
        assert "stoch_d" in result
        assert "stoch_k_signal" in result

        # Both should be 0-100 range
        assert all(0 <= v <= 100 for v in result["stoch_k"].dropna())
        assert all(0 <= v <= 100 for v in result["stoch_d"].dropna())

    async def test_stochastic_oversold_zone(self, sample_closes):
        """
        When stoch_k < 20, it's oversold (good for long entry).
        """
        stoch = StochasticOscillator(k_period=14, d_period=3)
        result = stoch.calculate(sample_closes)

        # Last 10 bars have downtrend → should have some oversold readings
        oversold = result["stoch_k"][-10:] < 20
        assert oversold.any(), "Should have oversold readings in downtrend"

    async def test_stochastic_overbought_zone(self, sample_closes):
        """
        When stoch_k > 80, it's overbought (signal for short or pullback).
        """
        stoch = StochasticOscillator(k_period=14, d_period=3)
        result = stoch.calculate(sample_closes)

        # Last 10 bars have uptrend → should have overbought readings
        overbought = result["stoch_k"][-10:] > 80
        assert overbought.any(), "Should have overbought readings in uptrend"

    async def test_stochastic_crossover_signal(self, sample_closes):
        """
        Buy signal: %K crosses above %D in oversold zone.
        Sell signal: %K crosses below %D in overbought zone.
        """
        stoch = StochasticOscillator(k_period=14, d_period=3)
        result = stoch.calculate(sample_closes)

        # Detect crossovers
        k = result["stoch_k"]
        d = result["stoch_d"]

        # Bullish cross: K goes from below D to above D
        bullish_cross = (k.shift(1) < d.shift(1)) & (k > d)

        # There should be at least 1 crossover in 30-bar sample
        assert bullish_cross.any()

    async def test_stochastic_api_endpoint(self, client, auth_headers):
        """
        GET /api/stocks/{symbol}/indicators?indicator=stochastic&period=14
        → returns { stoch_k: [...], stoch_d: [...] }
        """
        # Load sample data
        resp = await client.get(
            "/api/stocks/AAPL/history?tf=1D&from=2026-01-01&to=2026-02-01",
            headers=auth_headers
        )
        assert resp.status_code == 200

        # Get stochastic indicator
        resp = await client.get(
            "/api/stocks/AAPL/indicators?indicator=stochastic&k_period=14&d_period=3",
            headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "stoch_k" in data
        assert "stoch_d" in data
        assert len(data["stoch_k"]) == len(data["stoch_d"])

    async def test_stochastic_slow_vs_fast(self):
        """
        Fast Stochastic: %K (14,3), %D = SMA(%K, 3)
        Slow Stochastic: %K = SMA(Fast %K, 3), %D = SMA(%K, 3)

        Slow is smoother; trader likely uses Slow (5, 3) or Fast (14, 3).
        """
        # Test both variants
        pass
```

### Implementation Plan

**Step 1: Add Stochastic Calculator**

Create `backend/services/indicators.py`:

```python
import pandas as pd
import numpy as np

class StochasticOscillator:
    """Fast and Slow Stochastic Oscillator."""

    def __init__(self, k_period: int = 14, d_period: int = 3, smooth_k: int = 1):
        """
        k_period: lookback for high/low
        d_period: SMA period for %D
        smooth_k: 1 = Fast, 3+ = Slow (smooth the %K first)
        """
        self.k_period = k_period
        self.d_period = d_period
        self.smooth_k = smooth_k

    def calculate(self, df: pd.DataFrame) -> dict:
        """
        Input: DataFrame with 'high', 'low', 'close' columns
        Output: { 'stoch_k': Series, 'stoch_d': Series, 'signal': Series }
        """
        high = df['high'].rolling(window=self.k_period).max()
        low = df['low'].rolling(window=self.k_period).min()
        close = df['close']

        # Raw %K
        k_percent = 100 * (close - low) / (high - low)

        # Smooth %K (Fast = no smooth, Slow = SMA)
        if self.smooth_k > 1:
            k_percent = k_percent.rolling(window=self.smooth_k).mean()

        # %D = SMA of %K
        d_percent = k_percent.rolling(window=self.d_period).mean()

        # Signal line (optional)
        signal = d_percent.rolling(window=self.d_period).mean()

        return {
            'stoch_k': k_percent.fillna(50),  # 50 default when not enough data
            'stoch_d': d_percent.fillna(50),
            'signal': signal.fillna(50),
        }
```

**Step 2: Add Frontend Chart Display**

Modify `frontend/src/components/chart/TradingChart.tsx`:

```tsx
// Add stochastic to chart
useEffect(() => {
  if (indicators.includes('STOCHASTIC')) {
    const stochData = calculateStochastic(candleData, 14, 3);

    // Create separate pane below RSI
    const stochPane = lightweightChart.addLineSeries({
      color: '#8B5CF6', // Purple
    });

    stochPane.setData(stochData.k);

    const dLine = lightweightChart.addLineSeries({
      color: '#EC4899', // Pink
    });
    dLine.setData(stochData.d);
  }
}, [indicators, candleData]);
```

**Step 3: Update API Endpoint**

Modify `backend/api/routes/stocks.py`:

```python
@router.get("/{symbol}/indicators")
async def get_indicators(
    symbol: str,
    indicator: str = Query(..., description="rsi,macd,stochastic,bollinger,etc"),
    period: int = 14,
    tf: str = "1D",
):
    """Get technical indicator values for a symbol."""

    # Fetch OHLCV
    history = await fetch_symbol_history(symbol, tf)

    if indicator == "stochastic":
        calc = StochasticOscillator(k_period=period, d_period=3)
        result = calc.calculate(history)
        return {
            "symbol": symbol,
            "indicator": "stochastic",
            "period": period,
            "k": result['stoch_k'].tolist(),
            "d": result['stoch_d'].tolist(),
        }
```

### Acceptance Criteria

- [ ] Stochastic %K/%D calculated correctly (0-100 range)
- [ ] API endpoint returns stochastic values
- [ ] Chart displays stochastic in separate pane below price
- [ ] Oversold (<20) and overbought (>80) zones highlighted
- [ ] %K/%D crossovers detected programmatically
- [ ] Performance: stochastic calculated in <100ms for 500-bar chart

---

## Feature 3: Donchian Channels

### Why (Trader Perspective)
*"Donchian Channel high is my breakout level. When price closes above the 20-bar high with volume, I enter long."*

### Implementation Summary

**Calculation:**
```
Donchian High = max(high) over last 20 bars
Donchian Low = min(low) over last 20 bars
Donchian Midline = (High + Low) / 2
```

**Frontend Display:**
- Draw 3 lines on chart (high, mid, low)
- Shade band between high/low (light color)
- Alert when price crosses above/below

**Test Cases:**
```python
# Test 1: Channel width = max - min of last 20 bars
# Test 2: Price breakout above high with volume
# Test 3: Channel contraction (setup for breakout)
# Test 4: API endpoint /api/stocks/{symbol}/indicators?indicator=donchian
```

**Effort:** S (2 hours)

---

## Feature 4: Hull Moving Average (HMA)

### Why (Trader Perspective)
*"HMA has less lag than EMA. On 5m chart, HMA 9 is my trend filter for scalping."*

### Implementation Summary

**Calculation:**
```
HMA = WMA(2*WMA(price, period/2) - WMA(price, period), sqrt(period))
```

**Frontend Display:**
- Single line overlaid on price chart
- Color: green when uptrend, red when downtrend (based on slope)

**Effort:** S (2 hours)

---

## Feature 5: Golden/Death Cross Alerts

### Why (Trader Perspective)
*"When 20-SMA crosses above 50-SMA (Golden Cross), that's a strong buy signal. Alert me immediately."*

### Test Cases

**File:** `backend/tests/test_golden_death_cross_alerts.py`

```python
async def test_golden_cross_alert_triggers(self, client, auth_headers):
    """
    20-SMA crosses above 50-SMA → alert triggered.
    """
    # Create alert
    resp = await client.post("/api/alerts",
        json={
            "symbol": "AAPL",
            "alert_type": "GOLDEN_CROSS",
            "condition": "20_above_50",
            "value": None,  # Pattern-based, no numeric value
            "channel": "telegram",
        },
        headers=auth_headers
    )
    assert resp.status_code == 201

    # Simulate price data where 20-SMA crosses above 50-SMA
    # ... (add test data)

    # Check alert was triggered
    resp = await client.get("/api/alerts", headers=auth_headers)
    alert = resp.json()[0]
    assert alert["triggered_at"] is not None

async def test_death_cross_alert_triggers(self, client, auth_headers):
    """
    50-SMA crosses below 200-SMA → alert triggered.
    """
    # Similar to golden cross
    pass
```

### Implementation (Celery Worker Update)

Modify `backend/workers/alert_checker.py`:

```python
async def check_golden_cross(symbol: str, db: AsyncSession):
    """Check if 20-SMA just crossed above 50-SMA."""

    # Get last 60 daily bars
    history = await fetch_symbol_history(symbol, tf='1D', limit=60)

    # Calculate SMAs
    sma20 = history['close'].rolling(20).mean()
    sma50 = history['close'].rolling(50).mean()

    # Check for crossover: previous bar had 20<50, current bar has 20>50
    prev = sma20.iloc[-2] < sma50.iloc[-2] if len(sma20) >= 2 else False
    curr = sma20.iloc[-1] > sma50.iloc[-1]

    return prev and curr  # True if golden cross happened
```

**Effort:** M (4 hours)

---

## Feature 6: ADX (Average Directional Index)

### Why (Trader Perspective)
*"ADX > 25 confirms strong trend. I only trade breakouts when ADX is rising, not in choppy markets."*

**Implementation Summary:**
- Calculate +DI, -DI, DX, then ADX = SMA(DX, 14)
- Display on separate pane
- Filter screener to ADX > 25

**Effort:** M (4 hours)

---

## Timeline & Dependency Graph

```
Week 1 (Days 1-7):
├─ Realized P&L (Day 1-3) ← BLOCKS dashboard P&L card
├─ Stochastic Oscillator (Day 2-3)
├─ Donchian Channels (Day 3)
└─ Hull Moving Average (Day 4)

Week 2 (Days 8-14):
├─ Golden/Death Cross Alerts (Day 8-9) ← BLOCKS screener filter
├─ Golden/Death Cross Screener Filter (Day 9-10)
├─ ADX Indicator + Filter (Day 11-12)
├─ FIFO Cost Basis Refinement (Day 12-13)
└─ Dashboard P&L Card (Day 14) ← depends on Realized P&L

Week 3 (Days 15-21):
├─ Alert History Table (Day 15-16)
├─ Telegram Alert Delivery Wire-up (Day 17-18)
├─ Screener Multi-Indicator Confluence (Day 19-20)
└─ Polish & Testing (Day 21)
```

---

## Acceptance Criteria (Overall Phase 2)

- [ ] **Realized P&L** — 95% accuracy on test trades; FIFO enforced
- [ ] **Stochastic Oscillator** — Displays correctly; oversold/overbought zones marked
- [ ] **Donchian Channels** — High/low levels updated daily; breakout alerts work
- [ ] **Hull MA** — Overlaid on chart; color-coded by trend direction
- [ ] **ADX** — Displayed; trend strength meter works
- [ ] **Golden/Death Cross Alerts** — Trigger correctly; notify user (Telegram)
- [ ] **Screener Filters** — All P0 indicators (Stochastic, Donchian, Golden Cross, ADX, Volume 3x) available as filter options
- [ ] **Dashboard P&L Card** — Shows realized P&L, win rate, profit factor
- [ ] **Alert History** — All triggered alerts logged with timestamp, price, alert type
- [ ] **Backend Test Coverage** — ≥ 70% on portfolio, alerts, screener modules
- [ ] **Performance** — All API endpoints < 200ms (P95); chart render < 500ms

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| FIFO cost basis complex; hard to test | Write exhaustive unit tests first (TDD); cover partial fills, multiple lots |
| Celery alert_checker slow with 50+ symbols | Add caching; batch computation; run in parallel with asyncio |
| Stochastic/Donchian lag on new bars | Ensure real-time chart updates; use WebSocket for price pushes |
| Thai .BK data still unreliable | Phase 2 assumes data present; Phase 3 will add alternative sources |
| Too much to fit in 3 weeks | Drop ADX if needed; move to Phase 3 |

---

## Success Metrics (Phase 2 Complete)

1. **Can run 5-strategy screener** — at least 3 of the 15 Pine Script strategies (Mean Reversion, Breakout, Trend Follow)
2. **Daily P&L visible** — realized gains/losses on dashboard; can calculate taxes
3. **Alerts actionable** — Golden Cross alerts trigger; Telegram delivery works
4. **Portfolio accurate** — FIFO cost basis correct; closed position history available
5. **Chart professional** — Stochastic, Donchian, HMA, ADX all rendered correctly

---

*End of Phase 2 Plan*
