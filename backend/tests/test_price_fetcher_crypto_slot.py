"""bd:features-2026-09 slice B — price_fetcher Crypto slot regression tests.

Pure-function tests only (no yfinance/Redis I/O) — mirrors the existing
test_symbol_utils.py style.
"""
from workers.price_fetcher import _is_us, MARKET_SLOTS, NUM_SLOTS, _always
from core.symbol_utils import is_crypto


class TestIsUsExcludesCrypto:
    def test_btc_usd_not_us_slot(self):
        assert _is_us("BTC-USD") is False

    def test_eth_usd_not_us_slot(self):
        assert _is_us("ETH-USD") is False

    def test_gld_is_us_slot(self):
        """GLD needs zero special-case code — plain US ETF ticker."""
        assert _is_us("GLD") is True

    def test_aapl_still_us_slot(self):
        assert _is_us("AAPL") is True

    def test_thai_stock_not_us_slot(self):
        assert _is_us("PTT.BK") is False


class TestCryptoSlotRegistered:
    def test_slot_count_is_six(self):
        assert NUM_SLOTS == 6
        assert len(MARKET_SLOTS) == 6

    def test_crypto_slot_present_reuses_always(self):
        labels = [s[0] for s in MARKET_SLOTS]
        assert "Crypto" in labels
        label, filter_fn, hours_fn = next(s for s in MARKET_SLOTS if s[0] == "Crypto")
        assert filter_fn is is_crypto
        assert hours_fn is _always  # 24/7, no new market-hours model (Tara/Sara mandate)

    def test_no_symbol_double_slotted_between_us_and_crypto(self):
        """BTC-USD/ETH-USD must match exactly one of the US/Crypto filters,
        never both — the exact bug the R-3 risk register warns about."""
        for sym in ("BTC-USD", "ETH-USD", "AAPL", "GLD"):
            us_slot = next(s for s in MARKET_SLOTS if s[0] == "US")
            crypto_slot = next(s for s in MARKET_SLOTS if s[0] == "Crypto")
            in_us = us_slot[1](sym)
            in_crypto = crypto_slot[1](sym)
            assert not (in_us and in_crypto), f"{sym} matched both US and Crypto slots"
