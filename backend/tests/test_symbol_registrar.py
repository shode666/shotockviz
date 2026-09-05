"""Unit tests for workers.symbol_registrar._classify_market — pure function,
no I/O (see module docstring: "Determine market type for a symbol").

bd:features-2026-09 slice B — regression test for the bug documented in
09-sara-autopivot-crypto-spec.md §0: `_THAI_FUND_PATTERNS`'s
`^[A-Z]+-[A-Z]+` regex (K-CHINA/B-INCOME pattern) also matches "BTC-USD"/
"ETH-USD", which — before the fix — would misclassify crypto symbols as
FUND. The fix adds an `is_crypto()` check as the FIRST branch of
`_classify_market()`, before `_THAI_FUND_PATTERNS` is ever consulted.
"""
import pytest
from workers.symbol_registrar import _classify_market, _should_register


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


# ── bd:shotockviz-m6q — bare Thai fund-prefix collisions must not become
# a confident FUND guess. SCB/TISCO/ASP/MFC are real SET tickers too; the
# app requires an explicit ".BK" (accepted convention) so a bare form is
# ambiguous, not FUND. ─────────────────────────────────────────────────────

class TestClassifyMarketAmbiguousBareThaiPrefix:
    def test_bare_scb_is_ambiguous_not_fund(self):
        assert _classify_market("SCB") == "AMBIGUOUS"

    def test_bare_tisco_is_ambiguous_not_fund(self):
        assert _classify_market("TISCO") == "AMBIGUOUS"

    def test_bare_asp_is_ambiguous_not_fund(self):
        assert _classify_market("ASP") == "AMBIGUOUS"

    def test_bare_mfc_is_ambiguous_not_fund(self):
        """MFC.BK is itself a real SET-listed company (MFC Asset
        Management) and "MFC" bare also resolves to an unrelated real US
        stock (Manulife Financial Corp, NYQ) — verified via live yfinance
        2026-09-05, see symbol_utils.py THAI_FUND_HOUSE_TICKER_COLLISIONS."""
        assert _classify_market("MFC") == "AMBIGUOUS"

    def test_scb_with_bk_suffix_is_set_unaffected(self):
        """The suffixed form is unambiguous and must be completely
        unaffected by this fix — still resolves via the .BK branch."""
        assert _classify_market("SCB.BK") == "SET"

    def test_yfinance_confirmed_price_still_passes_through(self):
        """Pre-existing behavior (not what m6q reports) is untouched: if
        yfinance genuinely reports a live price for the bare symbol, it
        still falls through to SET/US detection instead of being treated
        as ambiguous."""
        yf_info = {"regularMarketPrice": 123.45, "exchange": "NMS"}
        assert _classify_market("SCB", yf_info) == "US"

    def test_k_china_and_b_income_regex_path_unaffected(self):
        """These hit the earlier, unambiguous `_THAI_FUND_PATTERNS` regex
        branch (dash-joined fund-code shape) — never reach the prefix
        check, so must still classify FUND exactly as before."""
        assert _classify_market("K-CHINA") == "FUND"
        assert _classify_market("B-INCOME") == "FUND"


# ── bd:shotockviz-3p6 — the m6q fix over-corrected: prefix *matches* that
# are not exact ticker collisions are real fund codes and must classify as
# FUND (the pre-m6q, and correct, behavior), not AMBIGUOUS. ─────────────────

class TestClassifyMarketFundPrefixNotAmbiguous:
    @pytest.mark.parametrize("symbol,expected", [
        ("TISCOGF", "FUND"),    # Tisco Global Equity Fund — real fund code
        ("SCBLT1", "FUND"),     # SCB Long-Term Equity Fund 1 — real fund code
        ("KFLTFDIV", "FUND"),   # Krungsri LTF Dividend — real fund code
        ("K-CHINA", "FUND"),    # real fund code (dash-regex path, unaffected)
        ("B-INNOTECH", "FUND"),  # real fund code (dash-regex path, unaffected)
    ])
    def test_fund_codes_classify_as_fund_not_ambiguous(self, symbol, expected):
        assert _classify_market(symbol) == expected

    def test_fund_prefix_still_defers_to_confirmed_live_price(self):
        """Mirrors the exact-collision branch: a confirmed live yfinance
        price for a prefix-shaped symbol still wins over the FUND guess."""
        yf_info = {"regularMarketPrice": 42.0, "exchange": "NMS"}
        assert _classify_market("KFLTFDIV", yf_info) == "US"


class TestShouldRegister:
    def test_ambiguous_market_is_not_registered(self):
        assert _should_register("AMBIGUOUS") is False

    @pytest.mark.parametrize("market", ["SET", "US", "FUND", "CRYPTO"])
    def test_known_markets_are_registered(self, market):
        assert _should_register(market) is True
