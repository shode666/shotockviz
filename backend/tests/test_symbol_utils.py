"""Unit tests for core.symbol_utils — pure functions, no I/O."""
import pytest
from core.symbol_utils import (
    normalize_for_yahoo,
    denormalize_from_yahoo,
    detect_market,
    is_thai_stock,
    is_fund,
    partition_by_market,
    deduplicate,
    YAHOO_SYMBOL_MAP,
    SUFFIX_TO_MARKET,
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
