"""
ShotockViz Next Features — TDD Test Suite

These are FAILING tests that define the specification for Phase 2 features.
When these tests pass, the features are complete.

Format:
- Each test class = one major feature
- Each test method = one user story / acceptance criterion
- Tests are independent and can run in parallel
- Test names describe the WHAT and WHY, not the HOW

Note: These tests are designed to FAIL until features are implemented.
They define the contract that implementation must satisfy.

Author: Senior Trading Expert QA
Date: 2026-03-02
"""

import pytest

# bd:deps-2026-09 WP-B0 — quarantined (discovered, not caused, by this WP).
# This file had a SyntaxError at line 630 (`class TestVolumeSpike Alerts:`)
# that made pytest fail to COLLECT it at all (00-oliver-discover.md:26) — so
# none of its 28 tests were ever part of the 107/26/5 baseline. Fixing that
# one-line typo (mandated by 03-stan-refactor-strategy.md WP-B0) unmasks a
# SEPARATE pre-existing bug: every test here takes a `client: AsyncClient`
# fixture that does not exist in conftest.py (only `async_client` does) —
# confirmed via `pytest --fixtures`, 0/28 tests can even reach setup, all
# ERROR before running. The file's own docstring also says these are
# "FAILING tests that define the specification for Phase 2 features... They
# define the contract that implementation must satisfy" — i.e. intentionally
# red TDD specs for unimplemented future work, not a regression surface for
# a dependency migration. Per 02-bella-brd-ac.md §1.2 ("pre-existing test
# baseline failures... not gated... unless Dave's plan explicitly elects to
# fix a specific one") this is NOT elected for a fix on this branch —
# quarantining consistent with test_api_e2e.py's treatment above.
pytest.skip(
    "quarantined bd:deps-2026-09 WP-B0 — unmasked by the :630 typo fix; "
    "every test needs a `client` fixture that doesn't exist (conftest.py "
    "only defines `async_client`), and the file is documented as "
    "intentionally-red Phase-2 TDD specs, not current-baseline coverage. "
    "See outputs/deps-2026-09/03-stan-refactor-strategy.md §6 Q1-adjacent.",
    allow_module_level=True,
)

from datetime import date, datetime, timedelta
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 1: REALIZED P&L TRACKING
# ─────────────────────────────────────────────────────────────────────────────

class TestRealizedPLTracking:
    """
    Feature: Realized Profit/Loss tracking for closed positions
    Priority: P0 — CRITICAL for daily trading and tax reporting

    User Story:
      As a swing trader,
      I want to track gains/losses from closed positions,
      So that I can calculate my daily win rate and file taxes correctly.
    """

    async def test_realized_pl_simple_round_trip(self, client: AsyncClient, auth_headers: dict):
        """
        Simple round trip: BUY 100 @ $150, SELL 100 @ $160

        Expected realized P&L = (160 - 150) * 100 = $1000
        Expected holdings after = [] (all closed)
        """
        # Add BUY transaction
        resp = await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "BUY",
                "qty": 100.0,
                "price": 150.0,
                "fee": 0.0,
                "date": "2026-01-01",
                "note": "test buy",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Failed to create buy transaction: {resp.text}"

        # Add SELL transaction
        resp = await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "SELL",
                "qty": 100.0,
                "price": 160.0,
                "fee": 0.0,
                "date": "2026-01-05",
                "note": "test sell",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Failed to create sell transaction: {resp.text}"

        # Check analytics — WILL FAIL until realized P&L is implemented
        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        # These assertions DEFINE the contract for realized P&L
        assert "realized_pl" in data, "Response missing 'realized_pl' field"
        assert data["realized_pl"] == 1000.0, f"Realized P&L should be 1000, got {data['realized_pl']}"

        assert "realized_pl_pct" in data, "Response missing 'realized_pl_pct' field"
        assert data["realized_pl_pct"] == pytest.approx(6.67, abs=0.01), \
            f"Realized P&L % should be ~6.67%, got {data['realized_pl_pct']}%"

        # All shares closed, no open holdings
        assert len(data["holdings"]) == 0, f"Should have 0 open holdings, got {len(data['holdings'])}"

    async def test_realized_pl_partial_sell(self, client: AsyncClient, auth_headers: dict):
        """
        Partial close: BUY 100 @ $150, SELL 40 @ $160

        Expected realized P&L = (160 - 150) * 40 = $400
        Expected holdings[0] = 60 shares remaining with cost basis $9000
        """
        # BUY 100
        await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "PTT.BK",
                "type": "BUY",
                "qty": 100.0,
                "price": 150.0,
                "fee": 0.0,
                "date": "2026-01-01",
            },
            headers=auth_headers,
        )

        # SELL 40
        await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "PTT.BK",
                "type": "SELL",
                "qty": 40.0,
                "price": 160.0,
                "fee": 0.0,
                "date": "2026-01-05",
            },
            headers=auth_headers,
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert data["realized_pl"] == 400.0, \
            f"Realized P&L should be 400, got {data['realized_pl']}"

        assert len(data["holdings"]) == 1, \
            f"Should have 1 open holding (60 shares), got {len(data['holdings'])}"

        holding = data["holdings"][0]
        assert holding["symbol"] == "PTT.BK"
        assert holding["qty"] == 60.0, f"Should have 60 shares remaining, got {holding['qty']}"
        assert holding["cost_basis"] == 9000.0, \
            f"Cost basis should be 9000 (60*150), got {holding['cost_basis']}"

    async def test_realized_pl_with_fifo_accounting(self, client: AsyncClient, auth_headers: dict):
        """
        FIFO (First-In-First-Out) cost basis:

        BUY 100 @ $100 on 1/1
        BUY 100 @ $120 on 1/5
        SELL 150 @ $130 on 1/10

        FIFO says:
          - First 100 shares @ $100 → profit (130-100)*100 = $3000
          - Next 50 shares @ $120 → profit (130-120)*50 = $500
        Total realized = $3500

        Remaining: 50 @ $120 cost basis = $6000
        """
        # BUY 100 @ 100
        await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "NVDA",
                "type": "BUY",
                "qty": 100.0,
                "price": 100.0,
                "fee": 0.0,
                "date": "2026-01-01",
            },
            headers=auth_headers,
        )

        # BUY 100 @ 120
        await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "NVDA",
                "type": "BUY",
                "qty": 100.0,
                "price": 120.0,
                "fee": 0.0,
                "date": "2026-01-05",
            },
            headers=auth_headers,
        )

        # SELL 150 @ 130
        await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "NVDA",
                "type": "SELL",
                "qty": 150.0,
                "price": 130.0,
                "fee": 0.0,
                "date": "2026-01-10",
            },
            headers=auth_headers,
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        # FIFO: first 100 @ 100 = 3000 profit, next 50 @ 120 = 500 profit
        assert data["realized_pl"] == 3500.0, \
            f"FIFO realized P&L should be 3500, got {data['realized_pl']}"

        # Remaining: 50 @ 120
        assert len(data["holdings"]) == 1
        holding = data["holdings"][0]
        assert holding["qty"] == 50.0, f"Should have 50 remaining, got {holding['qty']}"
        assert holding["cost_basis"] == 6000.0, \
            f"Cost basis should be 6000 (50*120), got {holding['cost_basis']}"

    async def test_realized_pl_with_fees(self, client: AsyncClient, auth_headers: dict):
        """
        BUY 100 @ $150 + $10 fee = $15,010 total cost
        SELL 100 @ $160 - $10 fee = $15,990 net proceeds

        Realized P&L = 15990 - 15010 = $980
        """
        await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "BUY",
                "qty": 100.0,
                "price": 150.0,
                "fee": 10.0,
                "date": "2026-01-01",
            },
            headers=auth_headers,
        )

        await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "AAPL",
                "type": "SELL",
                "qty": 100.0,
                "price": 160.0,
                "fee": 10.0,
                "date": "2026-01-05",
            },
            headers=auth_headers,
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert data["realized_pl"] == 980.0, \
            f"Realized P&L should be 980 (1000 - 20 fees), got {data['realized_pl']}"

    async def test_realized_pl_loss(self, client: AsyncClient, auth_headers: dict):
        """
        BUY 100 @ $150
        SELL 100 @ $140

        Realized P&L = (140 - 150) * 100 = -$1000 (loss)
        """
        await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "TSLA",
                "type": "BUY",
                "qty": 100.0,
                "price": 150.0,
                "fee": 0.0,
                "date": "2026-01-01",
            },
            headers=auth_headers,
        )

        await client.post(
            "/api/portfolio/transactions",
            json={
                "symbol": "TSLA",
                "type": "SELL",
                "qty": 100.0,
                "price": 140.0,
                "fee": 0.0,
                "date": "2026-01-05",
            },
            headers=auth_headers,
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert data["realized_pl"] == -1000.0, \
            f"Realized P&L should be -1000 (loss), got {data['realized_pl']}"

    async def test_realized_pl_win_rate(self, client: AsyncClient, auth_headers: dict):
        """
        Win Rate = % of closed trades with profit > 0

        3 trades:
        - AAPL: buy 100@150, sell 100@160 → +$1000 (WIN)
        - TSLA: buy 100@150, sell 100@140 → -$1000 (LOSS)
        - MSFT: buy 100@150, sell 100@155 → +$500 (WIN)

        Win rate = 2/3 = 66.67%
        """
        # AAPL win
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "AAPL", "type": "BUY", "qty": 100, "price": 150, "fee": 0, "date": "2026-01-01"},
            headers=auth_headers,
        )
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "AAPL", "type": "SELL", "qty": 100, "price": 160, "fee": 0, "date": "2026-01-02"},
            headers=auth_headers,
        )

        # TSLA loss
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "TSLA", "type": "BUY", "qty": 100, "price": 150, "fee": 0, "date": "2026-01-03"},
            headers=auth_headers,
        )
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "TSLA", "type": "SELL", "qty": 100, "price": 140, "fee": 0, "date": "2026-01-04"},
            headers=auth_headers,
        )

        # MSFT win
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "MSFT", "type": "BUY", "qty": 100, "price": 150, "fee": 0, "date": "2026-01-05"},
            headers=auth_headers,
        )
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "MSFT", "type": "SELL", "qty": 100, "price": 155, "fee": 0, "date": "2026-01-06"},
            headers=auth_headers,
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert "win_rate" in data, "Response missing 'win_rate' field"
        assert data["win_rate"] == pytest.approx(66.67, abs=0.1), \
            f"Win rate should be 66.67%, got {data['win_rate']}%"

        assert "total_trades" in data, "Response missing 'total_trades' field"
        assert data["total_trades"] == 3, f"Should have 3 closed trades, got {data['total_trades']}"

    async def test_realized_pl_profit_factor(self, client: AsyncClient, auth_headers: dict):
        """
        Profit Factor = sum(all gains) / sum(all losses)

        Gains: 1000 + 500 = 1500
        Losses: 1000
        Profit Factor = 1500 / 1000 = 1.5
        """
        # Two wins
        for i, price in enumerate([160, 155]):
            await client.post(
                "/api/portfolio/transactions",
                json={"symbol": f"SYM{i}", "type": "BUY", "qty": 100, "price": 150, "fee": 0, "date": f"2026-01-{i+1:02d}"},
                headers=auth_headers,
            )
            await client.post(
                "/api/portfolio/transactions",
                json={"symbol": f"SYM{i}", "type": "SELL", "qty": 100, "price": price, "fee": 0, "date": f"2026-01-{i+2:02d}"},
                headers=auth_headers,
            )

        # One loss
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "LOSS", "type": "BUY", "qty": 100, "price": 150, "fee": 0, "date": "2026-01-10"},
            headers=auth_headers,
        )
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "LOSS", "type": "SELL", "qty": 100, "price": 140, "fee": 0, "date": "2026-01-11"},
            headers=auth_headers,
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert "profit_factor" in data, "Response missing 'profit_factor' field"
        assert data["profit_factor"] == pytest.approx(1.5, abs=0.01), \
            f"Profit factor should be 1.5, got {data['profit_factor']}"

    async def test_closed_positions_history(self, client: AsyncClient, auth_headers: dict):
        """
        Closed positions should be queryable separately from open holdings.
        Each closed position should include:
        - symbol, qty, entry_price, exit_price, realized_pl, holding_days
        """
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "AAPL", "type": "BUY", "qty": 100, "price": 150, "fee": 0, "date": "2026-01-01"},
            headers=auth_headers,
        )
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "AAPL", "type": "SELL", "qty": 100, "price": 160, "fee": 0, "date": "2026-01-05"},
            headers=auth_headers,
        )

        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        data = resp.json()

        assert "closed_positions" in data, "Response missing 'closed_positions' field"
        assert len(data["closed_positions"]) == 1

        closed = data["closed_positions"][0]
        assert closed["symbol"] == "AAPL"
        assert closed["qty"] == 100.0
        assert closed["entry_price"] == 150.0
        assert closed["exit_price"] == 160.0
        assert closed["realized_pl"] == 1000.0
        assert closed["holding_days"] == 4

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 2: STOCHASTIC OSCILLATOR
# ─────────────────────────────────────────────────────────────────────────────

class TestStochasticOscillator:
    """
    Feature: Stochastic Oscillator indicator on chart
    Priority: P0 — Required for Scalping and Mean Reversion strategies

    User Story:
      As a scalp trader,
      I want to see Stochastic %K/%D on my chart,
      So that I can identify oversold bounces and time my entries.
    """

    async def test_stochastic_api_returns_k_and_d(self, client: AsyncClient, auth_headers: dict):
        """
        GET /api/stocks/{symbol}/indicators?indicator=stochastic

        Response should include:
        - stoch_k: array of %K values (0-100)
        - stoch_d: array of %D values (0-100)
        - Must have same length as input OHLC bars
        """
        # This test assumes AAPL has historical data available
        resp = await client.get(
            "/api/stocks/AAPL/indicators?indicator=stochastic&period=14",
            headers=auth_headers,
        )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        assert "stoch_k" in data, "Response missing 'stoch_k'"
        assert "stoch_d" in data, "Response missing 'stoch_d'"

        # Both should be lists of numbers
        assert isinstance(data["stoch_k"], list), "stoch_k should be a list"
        assert isinstance(data["stoch_d"], list), "stoch_d should be a list"

        # Same length
        assert len(data["stoch_k"]) == len(data["stoch_d"]), \
            f"stoch_k and stoch_d should have same length: {len(data['stoch_k'])} vs {len(data['stoch_d'])}"

        # All values in 0-100 range
        assert all(0 <= v <= 100 for v in data["stoch_k"] if v is not None), \
            "All stoch_k values should be 0-100"
        assert all(0 <= v <= 100 for v in data["stoch_d"] if v is not None), \
            "All stoch_d values should be 0-100"

    async def test_stochastic_oversold_detection(self, client: AsyncClient, auth_headers: dict):
        """
        When stoch_k < 20, it's oversold (buy signal for mean reversion).
        """
        resp = await client.get(
            "/api/stocks/AAPL/indicators?indicator=stochastic&period=14",
            headers=auth_headers,
        )
        data = resp.json()

        # Check if there are any oversold readings
        oversold_count = sum(1 for v in data["stoch_k"] if v is not None and v < 20)

        # Over a large enough sample, should have at least one oversold reading
        assert oversold_count > 0, \
            f"Expected to find oversold readings (<20) in stochastic, got none"

    async def test_stochastic_overbought_detection(self, client: AsyncClient, auth_headers: dict):
        """
        When stoch_k > 80, it's overbought (sell/pullback signal).
        """
        resp = await client.get(
            "/api/stocks/AAPL/indicators?indicator=stochastic&period=14",
            headers=auth_headers,
        )
        data = resp.json()

        # Check if there are any overbought readings
        overbought_count = sum(1 for v in data["stoch_k"] if v is not None and v > 80)

        # Over a large enough sample, should have at least one overbought reading
        assert overbought_count > 0, \
            f"Expected to find overbought readings (>80) in stochastic, got none"

    async def test_stochastic_crossover_signal(self, client: AsyncClient, auth_headers: dict):
        """
        Bullish signal: %K crosses above %D (especially in oversold zone)
        Bearish signal: %K crosses below %D (especially in overbought zone)
        """
        resp = await client.get(
            "/api/stocks/AAPL/indicators?indicator=stochastic&period=14",
            headers=auth_headers,
        )
        data = resp.json()

        k = data["stoch_k"]
        d = data["stoch_d"]

        # Find crossovers
        bullish_crosses = 0
        for i in range(1, len(k)):
            if k[i-1] < d[i-1] and k[i] > d[i]:  # K crosses above D
                bullish_crosses += 1

        # Should have at least one crossover in a reasonable sample
        assert bullish_crosses > 0, \
            f"Expected to find bullish crossovers, got {bullish_crosses}"

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 3: GOLDEN/DEATH CROSS ALERTS
# ─────────────────────────────────────────────────────────────────────────────

class TestGoldenDeathCrossAlerts:
    """
    Feature: Golden Cross (20-SMA > 50-SMA) and Death Cross (20-SMA < 50-SMA) alerts
    Priority: P0 — Core trend confirmation signal

    User Story:
      As a swing trader,
      I want to get alerted when Golden/Death Cross happens,
      So that I can enter/exit trades based on trend changes.
    """

    async def test_create_golden_cross_alert(self, client: AsyncClient, auth_headers: dict):
        """
        User can create a Golden Cross alert for a symbol.
        """
        resp = await client.post(
            "/api/alerts",
            json={
                "symbol": "AAPL",
                "alert_type": "GOLDEN_CROSS",
                "condition": None,  # Pattern-based, no numeric condition
                "value": None,
                "channel": "telegram",
            },
            headers=auth_headers,
        )

        assert resp.status_code == 201, f"Failed to create alert: {resp.text}"
        alert = resp.json()

        assert alert["symbol"] == "AAPL"
        assert alert["alert_type"] == "GOLDEN_CROSS"
        assert alert["is_active"] is True

    async def test_create_death_cross_alert(self, client: AsyncClient, auth_headers: dict):
        """
        User can create a Death Cross alert for a symbol.
        """
        resp = await client.post(
            "/api/alerts",
            json={
                "symbol": "TSLA",
                "alert_type": "DEATH_CROSS",
                "condition": None,
                "value": None,
                "channel": "in_app",
            },
            headers=auth_headers,
        )

        assert resp.status_code == 201
        alert = resp.json()

        assert alert["symbol"] == "TSLA"
        assert alert["alert_type"] == "DEATH_CROSS"

    async def test_golden_cross_alert_triggers(self, client: AsyncClient, auth_headers: dict):
        """
        When 20-SMA crosses above 50-SMA:
        - Alert should be marked as triggered
        - triggered_at timestamp should be set
        - Notification should be sent (or queued)
        """
        # Create alert
        resp = await client.post(
            "/api/alerts",
            json={
                "symbol": "AAPL",
                "alert_type": "GOLDEN_CROSS",
                "channel": "in_app",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

        # In real scenario, Celery worker would check for golden cross
        # For testing, we'd need to mock price data or use a test fixture
        # that simulates the golden cross condition

        # Get alert status
        resp = await client.get("/api/alerts", headers=auth_headers)
        alerts = resp.json()

        # Find our alert
        gc_alert = [a for a in alerts if a["alert_type"] == "GOLDEN_CROSS" and a["symbol"] == "AAPL"]
        assert len(gc_alert) > 0, "Golden Cross alert not found"

        # WILL FAIL until golden cross detection is implemented
        # assert gc_alert[0]["triggered_at"] is not None, "Alert should be triggered"

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 4: VOLUME SPIKE ALERTS
# ─────────────────────────────────────────────────────────────────────────────

class TestVolumeSpikeAlerts:
    """
    Feature: Volume Spike alert (volume > 2x or 3x average)
    Priority: P0 — Breakout confirmation signal

    User Story:
      As a breakout trader,
      I want to be alerted when volume spikes 3x average,
      So that I can confirm the breakout is real.
    """

    async def test_create_volume_spike_alert(self, client: AsyncClient, auth_headers: dict):
        """
        User can create a volume spike alert with multiplier (2x, 3x, etc).
        """
        resp = await client.post(
            "/api/alerts",
            json={
                "symbol": "NVDA",
                "alert_type": "VOLUME_SPIKE",
                "condition": "3x",  # 3x average volume
                "value": None,
                "channel": "telegram",
            },
            headers=auth_headers,
        )

        assert resp.status_code == 201
        alert = resp.json()

        assert alert["symbol"] == "NVDA"
        assert alert["alert_type"] == "VOLUME_SPIKE"
        assert alert["condition"] == "3x"

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 5: SCREENER FILTERS
# ─────────────────────────────────────────────────────────────────────────────

class TestScreenerFilters:
    """
    Feature: Enhanced screener with indicator-based filters
    Priority: P0 — Enable strategy-based scanning

    User Story:
      As a trader,
      I want to screen stocks using my strategy patterns,
      So that I can quickly find setups matching my criteria.
    """

    async def test_screener_golden_cross_filter(self, client: AsyncClient, auth_headers: dict):
        """
        GET /api/screener/run?market=US&filter=golden_cross

        Returns list of stocks where 20-SMA > 50-SMA (bullish signal)
        """
        resp = await client.post(
            "/api/screener/run",
            json={
                "market": "US",
                "filters": {
                    "golden_cross": True,
                },
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200, f"Screener failed: {resp.text}"
        data = resp.json()

        assert "results" in data
        assert isinstance(data["results"], list)

        # Each result should have symbol and screening data
        if len(data["results"]) > 0:
            result = data["results"][0]
            assert "symbol" in result
            assert "price" in result
            assert "change_pct" in result

    async def test_screener_stochastic_oversold_filter(self, client: AsyncClient, auth_headers: dict):
        """
        Screen for stocks with Stochastic %K < 20 (oversold, mean reversion setup)
        """
        resp = await client.post(
            "/api/screener/run",
            json={
                "market": "SET",
                "filters": {
                    "stochastic_oversold": True,
                },
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()

        assert "results" in data
        assert isinstance(data["results"], list)

    async def test_screener_donchian_breakout_filter(self, client: AsyncClient, auth_headers: dict):
        """
        Screen for stocks breaking above Donchian 20-bar high
        """
        resp = await client.post(
            "/api/screener/run",
            json={
                "market": "US",
                "filters": {
                    "donchian_breakout": True,
                    "volume_spike": "2x",
                },
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()

        assert "results" in data

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 6: DASHBOARD REALIZED P&L CARD
# ─────────────────────────────────────────────────────────────────────────────

class TestDashboardRealizedPL:
    """
    Feature: Dashboard card showing daily realized P&L
    Priority: P1 — Daily performance visibility

    User Story:
      As a trader reviewing my day,
      I want to see my realized P&L on the dashboard,
      So that I can quickly assess my trading performance.
    """

    async def test_dashboard_includes_realized_pl_card(self, client: AsyncClient, auth_headers: dict):
        """
        GET /api/dashboard

        Response should include realized_pl_today and realized_pl_ytd
        """
        resp = await client.get("/api/dashboard", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()

        # Dashboard should include realized P&L
        assert "realized_pl_today" in data or "portfolio" in data, \
            "Dashboard missing realized P&L data"

        if "portfolio" in data:
            assert "realized_pl" in data["portfolio"], \
                "Portfolio section missing realized_pl"

    async def test_dashboard_realized_pl_accuracy(self, client: AsyncClient, auth_headers: dict):
        """
        Dashboard realized P&L should match portfolio analytics realized_pl.
        """
        # Create some test trades
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "AAPL", "type": "BUY", "qty": 100, "price": 150, "fee": 0, "date": date.today().isoformat()},
            headers=auth_headers,
        )
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "AAPL", "type": "SELL", "qty": 100, "price": 160, "fee": 0, "date": date.today().isoformat()},
            headers=auth_headers,
        )

        # Get dashboard
        resp = await client.get("/api/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        dashboard_data = resp.json()

        # Get portfolio analytics
        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        portfolio_data = resp.json()

        # Dashboard P&L should match portfolio realized_pl
        dashboard_pl = dashboard_data.get("portfolio", {}).get("realized_pl")
        portfolio_pl = portfolio_data.get("realized_pl")

        if dashboard_pl is not None and portfolio_pl is not None:
            assert dashboard_pl == pytest.approx(portfolio_pl, abs=0.01), \
                f"Dashboard P&L {dashboard_pl} should match portfolio P&L {portfolio_pl}"

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 7: ADX INDICATOR
# ─────────────────────────────────────────────────────────────────────────────

class TestADXIndicator:
    """
    Feature: Average Directional Index (ADX) for trend strength
    Priority: P1 — Trend confirmation filter

    User Story:
      As a trend trader,
      I want to see ADX on my chart,
      So that I only trade when the trend is strong (ADX > 25).
    """

    async def test_adx_api_returns_adx_values(self, client: AsyncClient, auth_headers: dict):
        """
        GET /api/stocks/{symbol}/indicators?indicator=adx

        Response should include:
        - adx: array of ADX values (0-100)
        - plus_di: +DI line
        - minus_di: -DI line
        """
        resp = await client.get(
            "/api/stocks/AAPL/indicators?indicator=adx&period=14",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()

        assert "adx" in data, "Response missing 'adx'"
        assert isinstance(data["adx"], list), "adx should be a list"
        assert all(0 <= v <= 100 for v in data["adx"] if v is not None), \
            "ADX values should be 0-100"

    async def test_adx_trend_strength_filter(self, client: AsyncClient, auth_headers: dict):
        """
        Screener should have ADX > 25 filter (strong trend).
        """
        resp = await client.post(
            "/api/screener/run",
            json={
                "market": "US",
                "filters": {
                    "adx_above": 25,
                },
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()

        assert "results" in data

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 8: ALERT HISTORY
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertHistory:
    """
    Feature: Track when alerts trigger with timestamp and price
    Priority: P1 — Audit trail and performance analysis

    User Story:
      As a trader analyzing my alerts,
      I want to see when each alert triggered and what the price was,
      So that I can assess alert quality and trading performance.
    """

    async def test_alert_history_endpoint(self, client: AsyncClient, auth_headers: dict):
        """
        GET /api/alerts/{alert_id}/history

        Returns list of trigger events with timestamp, price, triggered.
        """
        # Create an alert
        resp = await client.post(
            "/api/alerts",
            json={
                "symbol": "AAPL",
                "alert_type": "PRICE_ABOVE",
                "condition": None,
                "value": 150.0,
                "channel": "in_app",
            },
            headers=auth_headers,
        )
        alert_id = resp.json()["id"]

        # Get history
        resp = await client.get(
            f"/api/alerts/{alert_id}/history",
            headers=auth_headers,
        )

        # WILL FAIL until alert history is implemented
        # assert resp.status_code == 200
        # data = resp.json()
        # assert isinstance(data, list)
        # if len(data) > 0:
        #     event = data[0]
        #     assert "triggered_at" in event
        #     assert "price" in event

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 9: TELEGRAM ALERT DELIVERY
# ─────────────────────────────────────────────────────────────────────────────

class TestTelegramAlertDelivery:
    """
    Feature: Send alerts to Telegram Bot
    Priority: P1 — Make alerts actionable

    User Story:
      As a trader on the go,
      I want my alerts delivered to Telegram,
      So that I can react to setups even when away from my computer.
    """

    async def test_telegram_delivery_queue(self, client: AsyncClient, auth_headers: dict):
        """
        When alert is triggered with channel=telegram:
        - Alert should be queued for delivery
        - Telegram bot should send message to user's chat_id
        """
        # This test requires:
        # 1. User has Telegram bot enabled (stored chat_id in DB)
        # 2. Celery task to deliver messages
        # 3. Mock Telegram API for testing

        # Create alert
        resp = await client.post(
            "/api/alerts",
            json={
                "symbol": "AAPL",
                "alert_type": "PRICE_ABOVE",
                "value": 180.0,
                "channel": "telegram",
            },
            headers=auth_headers,
        )

        # WILL FAIL until Telegram integration complete
        # assert resp.status_code == 201

# ─────────────────────────────────────────────────────────────────────────────
# PERFORMANCE & INTEGRATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestPerformanceAndIntegration:
    """
    Integration tests ensuring features work together and meet performance targets.
    """

    async def test_full_trading_workflow(self, client: AsyncClient, auth_headers: dict):
        """
        Full workflow:
        1. Create buy/sell transactions
        2. Check realized P&L
        3. Run screener with Golden Cross filter
        4. Create alert for next opportunity
        5. Check dashboard
        """
        # 1. Add transactions
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "AAPL", "type": "BUY", "qty": 100, "price": 150, "fee": 10, "date": "2026-01-01"},
            headers=auth_headers,
        )
        await client.post(
            "/api/portfolio/transactions",
            json={"symbol": "AAPL", "type": "SELL", "qty": 100, "price": 160, "fee": 10, "date": "2026-01-05"},
            headers=auth_headers,
        )

        # 2. Check P&L
        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["realized_pl"] == 980.0

        # 3. Run screener
        resp = await client.post(
            "/api/screener/run",
            json={"market": "US", "filters": {"golden_cross": True}},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # 4. Create alert
        resp = await client.post(
            "/api/alerts",
            json={"symbol": "TSLA", "alert_type": "GOLDEN_CROSS", "channel": "telegram"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

        # 5. Check dashboard
        resp = await client.get("/api/dashboard", headers=auth_headers)
        assert resp.status_code == 200

    async def test_portfolio_analytics_performance_p95_under_1s(self, client: AsyncClient, auth_headers: dict):
        """
        Portfolio analytics endpoint should return < 1 second (P95).
        With 50+ holdings, this requires efficient caching and batch queries.
        """
        import time

        # Create diverse portfolio
        for i in range(20):
            await client.post(
                "/api/portfolio/transactions",
                json={
                    "symbol": f"SYM{i:02d}",
                    "type": "BUY",
                    "qty": 100.0,
                    "price": 100.0 + i,
                    "fee": 0.0,
                    "date": "2026-01-01",
                },
                headers=auth_headers,
            )

        # Measure analytics fetch time
        start = time.time()
        resp = await client.get("/api/portfolio/analytics", headers=auth_headers)
        elapsed = time.time() - start

        assert resp.status_code == 200
        # WILL FAIL until caching is optimized
        # assert elapsed < 1.0, f"Analytics took {elapsed:.2f}s, should be < 1s"

    async def test_screener_with_multiple_filters_performance(self, client: AsyncClient, auth_headers: dict):
        """
        Screener with 3+ filters should complete in < 2 seconds.
        """
        import time

        start = time.time()
        resp = await client.post(
            "/api/screener/run",
            json={
                "market": "US",
                "filters": {
                    "golden_cross": True,
                    "adx_above": 25,
                    "stochastic_oversold": True,
                    "volume_spike": "2x",
                },
            },
            headers=auth_headers,
        )
        elapsed = time.time() - start

        assert resp.status_code == 200
        # WILL FAIL until screener is optimized
        # assert elapsed < 2.0, f"Screener took {elapsed:.2f}s, should be < 2s"

# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES (assumes pytest-asyncio + httpx async client)
# ─────────────────────────────────────────────────────────────────────────────

# These fixtures should be defined in conftest.py:
# @pytest.fixture
# async def client() -> AsyncClient:
#     async with AsyncClient(app=app, base_url="http://test") as ac:
#         yield ac
#
# @pytest.fixture
# async def auth_headers(client: AsyncClient) -> dict:
#     # Register + login user, return auth headers with JWT token
#     ...

# ─────────────────────────────────────────────────────────────────────────────
# End of Test Suite
# ─────────────────────────────────────────────────────────────────────────────
