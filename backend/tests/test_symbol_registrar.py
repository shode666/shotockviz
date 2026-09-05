"""Unit tests for workers.symbol_registrar._classify_market — pure function,
no I/O (see module docstring: "Determine market type for a symbol").

bd:features-2026-09 slice B — regression test for the bug documented in
09-sara-autopivot-crypto-spec.md §0: `_THAI_FUND_PATTERNS`'s
`^[A-Z]+-[A-Z]+` regex (K-CHINA/B-INCOME pattern) also matches "BTC-USD"/
"ETH-USD", which — before the fix — would misclassify crypto symbols as
FUND. The fix adds an `is_crypto()` check as the FIRST branch of
`_classify_market()`, before `_THAI_FUND_PATTERNS` is ever consulted.
"""
from workers.symbol_registrar import _classify_market


# ── Regression: crypto must classify as CRYPTO, not FUND ────────────────────

class TestClassifyMarketCrypto:
    def test_btc_usd_is_crypto_not_fund(self):
        assert _classify_market("BTC-USD") == "CRYPTO"

    def test_eth_usd_is_crypto_not_fund(self):
        assert _classify_market("ETH-USD") == "CRYPTO"

    def test_lowercase_input_still_detected(self):
        assert _classify_market("btc-usd") == "CRYPTO"


# ── No regression: symbols that used to pass must still classify the same ───

class TestClassifyMarketNoRegression:
    def test_set_stock(self):
        assert _classify_market("PTT.BK") == "SET"

    def test_brk_b_classification_unchanged_by_this_fix(self):
        """DISCOVERED (out of scope, not fixed here): BRK-B also matches the
        `^[A-Z]+-[A-Z]+` regex shape (same as BTC-USD) and is classified
        FUND — this is a PRE-EXISTING bug in `_THAI_FUND_PATTERNS`, not
        something introduced or touched by the crypto fix. is_crypto("BRK-B")
        is False (suffix is "-B", not "-USD"; see symbol_utils.py), so it
        does NOT hit the new crypto branch and falls through to the same
        regex check as before — behavior is unchanged pre/post this slice.
        Tara/Sara's spec (06/09-*.md) scopes the fix to BTC-USD/ETH-USD only;
        fixing this separate bug here would be undeclared scope expansion —
        flagged for a follow-up bd instead (see hand-off)."""
        assert _classify_market("BRK-B") == "FUND"

    def test_bf_b_classification_unchanged_by_this_fix(self):
        assert _classify_market("BF-B") == "FUND"

    def test_k_china_is_fund(self):
        """K-CHINA is exactly the pattern _THAI_FUND_PATTERNS was written for
        — must still be caught by that regex, unaffected by the is_crypto()
        check placed ahead of it."""
        assert _classify_market("K-CHINA") == "FUND"

    def test_b_income_is_fund(self):
        assert _classify_market("B-INCOME") == "FUND"

    def test_us_stock_default(self):
        assert _classify_market("AAPL") == "US"

    def test_fund_with_ampersand(self):
        assert _classify_market("SCBS&P500") == "FUND"

    def test_gld_is_us(self):
        """GLD (the gold ETF slice, Tara §2.2) needs zero classifier changes
        — plain US ticker, no suffix, no dash."""
        assert _classify_market("GLD") == "US"
