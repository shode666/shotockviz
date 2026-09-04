"""bd:features-2026-09 slice B §4.5 — downstream guards for CRYPTO market
symbols, test-proven per Tara's DoD ("must have a test that proves it, not
'should work'"):

  - fund_fetcher's Thai NAV path must never pick up market='CRYPTO' rows
    (it queries `market = 'FUND'` exactly — CRYPTO can never match that,
    verified here by reading the actual SQL text so a future edit that
    widens the filter gets caught).
  - fundamentals_fetcher must skip CRYPTO (no PE/PB/EPS for BTC) the same
    way it already skips FUND.
"""
import inspect

from workers import fund_fetcher, fundamentals_fetcher


class TestFundFetcherNeverMatchesCrypto:
    def test_fund_fetcher_query_is_exact_fund_match(self):
        src = inspect.getsource(fund_fetcher.fetch_thai_fund_navs)
        assert "market = 'FUND'" in src, (
            "fund_fetcher must query market = 'FUND' (exact match) so a "
            "market='CRYPTO' row can never be picked up by the Thai NAV path"
        )
        assert "CRYPTO" not in src


class TestFundamentalsFetcherSkipsCrypto:
    def test_fundamentals_query_excludes_crypto(self):
        src = inspect.getsource(fundamentals_fetcher.prefetch_fundamentals)
        assert "CRYPTO" in src, "fundamentals_fetcher must exclude market='CRYPTO' rows"
        assert "NOT IN ('FUND', 'CRYPTO')" in src or "NOT IN ('CRYPTO', 'FUND')" in src
