"""Unit tests for core.symbol_utils — pure functions, no I/O."""
import pytest
from core.symbol_utils import (
    normalize_for_yahoo,
    denormalize_from_yahoo,
    detect_market,
    is_thai_stock,
    is_fund,
    is_crypto,
    is_ambiguous_bare_thai_symbol,
    partition_by_market,
    deduplicate,
    YAHOO_SYMBOL_MAP,
    SUFFIX_TO_MARKET,
    THAI_FUND_PREFIXES,
    THAI_FUND_HOUSE_TICKER_COLLISIONS,
)


# ── normalize_for_yahoo ──────────────────────────────────────────────────────

class TestNormalizeForYahoo:
    def test_known_mapping(self):
        assert normalize_for_yahoo("BRK.B") == "BRK-B"
        assert normalize_for_yahoo("BRK.A") == "BRK-A"
        assert normalize_for_yahoo("BF.B") == "BF-B"
        assert normalize_for_yahoo("BF.A") == "BF-A"

    def test_unknown_passthrough(self):
        assert normalize_for_yahoo("AAPL") == "AAPL"
        assert normalize_for_yahoo("PTT.BK") == "PTT.BK"
        assert normalize_for_yahoo("7203.T") == "7203.T"

    def test_empty_string(self):
        assert normalize_for_yahoo("") == ""


# ── denormalize_from_yahoo ────────────────────────────────────────────────────

class TestDenormalizeFromYahoo:
    def test_known_reverse(self):
        assert denormalize_from_yahoo("BRK-B") == "BRK.B"
        assert denormalize_from_yahoo("BRK-A") == "BRK.A"

    def test_unknown_passthrough(self):
        assert denormalize_from_yahoo("AAPL") == "AAPL"
        assert denormalize_from_yahoo("NVDA") == "NVDA"

    def test_roundtrip(self):
        for internal, yahoo in YAHOO_SYMBOL_MAP.items():
            assert denormalize_from_yahoo(normalize_for_yahoo(internal)) == internal


# ── detect_market ─────────────────────────────────────────────────────────────

class TestDetectMarket:
    @pytest.mark.parametrize("symbol,expected", [
        ("PTT.BK", "SET"),
        ("ADVANC.BK", "SET"),
        ("7203.T", "JP"),
        ("0700.HK", "HK"),
        ("600519.SS", "CN"),
        ("000858.SZ", "CN"),
        ("HSBA.L", "UK"),
        ("SAP.DE", "DE"),
        ("MC.PA", "FR"),
        ("ASML.AS", "NL"),
        ("ENI.MI", "IT"),
        ("SHOP.TO", "CA"),
        ("BHP.AX", "AU"),
        ("005930.KS", "KR"),
        ("2330.TW", "TW"),
        ("D05.SI", "SG"),
    ])
    def test_suffix_detection(self, symbol, expected):
        assert detect_market(symbol) == expected

    def test_us_default(self):
        """Symbols without known suffix default to US."""
        assert detect_market("AAPL") == "US"
        assert detect_market("NVDA") == "US"
        assert detect_market("TSLA") == "US"
        assert detect_market("^GSPC") == "US"

    def test_all_suffixes_covered(self):
        """Every suffix in SUFFIX_TO_MARKET is detected correctly."""
        for suffix, market in SUFFIX_TO_MARKET.items():
            assert detect_market(f"TEST{suffix}") == market


# ── is_thai_stock ─────────────────────────────────────────────────────────────

class TestIsThaiStock:
    def test_bk_suffix(self):
        assert is_thai_stock("PTT.BK") is True
        assert is_thai_stock("ADVANC.BK") is True

    def test_mai_suffix(self):
        assert is_thai_stock("MINT.MAI") is True

    def test_non_thai(self):
        assert is_thai_stock("AAPL") is False
        assert is_thai_stock("7203.T") is False
        assert is_thai_stock("0700.HK") is False


# ── is_fund ───────────────────────────────────────────────────────────────────

class TestIsFund:
    def test_ampersand(self):
        assert is_fund("SCBS&P500") is True

    def test_space(self):
        assert is_fund("PRINCIPAL iPROP-D") is True

    def test_normal_stock(self):
        assert is_fund("AAPL") is False
        assert is_fund("PTT.BK") is False


# ── partition_by_market ───────────────────────────────────────────────────────

class TestPartitionByMarket:
    def test_mixed_symbols(self):
        thai, other = partition_by_market(["PTT.BK", "AAPL", "ADVANC.BK", "NVDA"])
        assert thai == ["PTT.BK", "ADVANC.BK"]
        assert other == ["AAPL", "NVDA"]

    def test_all_thai(self):
        thai, other = partition_by_market(["PTT.BK", "ADVANC.BK"])
        assert thai == ["PTT.BK", "ADVANC.BK"]
        assert other == []

    def test_all_us(self):
        thai, other = partition_by_market(["AAPL", "NVDA"])
        assert thai == []
        assert other == ["AAPL", "NVDA"]

    def test_empty(self):
        thai, other = partition_by_market([])
        assert thai == []
        assert other == []

    def test_deduplication(self):
        thai, other = partition_by_market(["PTT.BK", "PTT.BK", "AAPL", "AAPL"])
        assert thai == ["PTT.BK"]
        assert other == ["AAPL"]


# ── is_crypto (bd:features-2026-09 slice B) ──────────────────────────────────

class TestIsCrypto:
    @pytest.mark.parametrize("symbol,expected", [
        ("BTC-USD", True),
        ("ETH-USD", True),
        ("btc-usd", True),   # case-insensitive
        ("BRK-B", False),    # suffix "-B", not "-USD"
        ("BF-B", False),
        ("BF-A", False),
        ("GLD", False),      # plain US ETF ticker, no dash at all
        ("PTT.BK", False),
        ("THBUSD=X", False),  # ends "=X", not "-USD"
        ("K-CHINA", False),
        ("AAPL", False),
    ])
    def test_allowlist_and_edge_cases(self, symbol, expected):
        assert is_crypto(symbol) is expected


# ── is_ambiguous_bare_thai_symbol (bd:shotockviz-m6q, tightened bd:shotockviz-3p6) ─
#
# bd:shotockviz-3p6 — the original m6q version used `startswith` against the
# whole THAI_FUND_PREFIXES list, which flagged every genuine fund code
# (TISCOGF, SCBLT1, KFLTFDIV, K-CHINA, B-INNOTECH, ...) as ambiguous too.
# Ambiguity is real only for the small set of strings that are *exactly*
# both a live SET ticker and a fund-house name — see
# THAI_FUND_HOUSE_TICKER_COLLISIONS in symbol_utils.py for how each of
# SCB/TISCO/ASP/MFC was verified against live Yahoo Finance data, and why
# TMB/DAOL/PHATRA were checked and excluded.

class TestIsAmbiguousBareThaiSymbol:
    @pytest.mark.parametrize("symbol", [
        "SCB",       # Siam Commercial Bank ticker AND a fund-house prefix
        "scb",       # case-insensitive
        "TISCO",     # Tisco Financial Group ticker AND a fund-house prefix
        "ASP",       # Asia Plus Group Holdings AND a fund-house prefix
        "MFC",       # MFC Asset Management (itself SET-listed) AND a fund-house prefix
    ])
    def test_exact_ticker_collision_is_ambiguous(self, symbol):
        assert is_ambiguous_bare_thai_symbol(symbol) is True

    @pytest.mark.parametrize("symbol", [
        "SCB.BK",    # explicit suffix disambiguates — never ambiguous
        "TISCO.BK",
        "AAPL",      # no collision at all
        "PTT.BK",
        "BTC-USD",
        "K-",        # bare prefix fragment — never a whole ticker, not ambiguous
        "B-",
        "SCBX",      # starts with a prefix but is not an exact collision
        "TISCOGF",   # real fund code (SCB.. Tisco Global Equity Fund) — not ambiguous
        "SCBLT1",    # real fund code (SCB Long-Term Equity Fund 1) — not ambiguous
        "KFLTFDIV",  # real fund code (Krungsri LTF Dividend) — not ambiguous
        "K-CHINA",   # real fund code — not ambiguous
        "B-INNOTECH",  # real fund code — not ambiguous
        "TMB",       # verified NOT a live SET ticker on Yahoo — excluded from collisions
        "DAOL",      # verified no Yahoo data at all — excluded from collisions
        "PHATRA",    # verified no Yahoo data at all — excluded from collisions
    ])
    def test_fund_codes_and_unrelated_symbols_are_not_ambiguous(self, symbol):
        assert is_ambiguous_bare_thai_symbol(symbol) is False

    def test_prefix_list_is_nonempty_and_uppercase(self):
        assert THAI_FUND_PREFIXES
        assert all(p == p.upper() for p in THAI_FUND_PREFIXES)

    def test_collision_set_is_small_exact_subset_of_prefixes(self):
        """Every verified collision must itself be one of the fund-house
        prefixes (it's a stricter subset, not an unrelated list) — and the
        set must stay small/explicit, never a blanket 'all prefixes'."""
        assert THAI_FUND_HOUSE_TICKER_COLLISIONS
        assert THAI_FUND_HOUSE_TICKER_COLLISIONS == {"SCB", "TISCO", "ASP", "MFC"}
        for ticker in THAI_FUND_HOUSE_TICKER_COLLISIONS:
            assert any(ticker.startswith(p) or p == ticker for p in THAI_FUND_PREFIXES)


# ── deduplicate ───────────────────────────────────────────────────────────────

class TestDeduplicate:
    def test_preserves_order(self):
        assert deduplicate(["C", "A", "B", "A", "C"]) == ["C", "A", "B"]

    def test_no_duplicates(self):
        assert deduplicate(["A", "B", "C"]) == ["A", "B", "C"]

    def test_empty(self):
        assert deduplicate([]) == []

    def test_single(self):
        assert deduplicate(["X"]) == ["X"]
