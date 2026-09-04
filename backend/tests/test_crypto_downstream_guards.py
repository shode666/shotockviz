"""bd:features-2026-09 slice B §4.5 — downstream guards for CRYPTO market
symbols, test-proven per Tara's DoD ("must have a test that proves it, not
'should work'"):

  - fund_fetcher's Thai NAV path must never pick up market='CRYPTO' rows.
  - fundamentals_fetcher must skip CRYPTO (no PE/PB/EPS for BTC) the same
    way it already skips FUND.

bd:features-2026-09 iter5 — Chris review M2
(10-chris-crypto-autopivot-review.md): the original version of this file
asserted on `inspect.getsource(...)` substrings — proving the SQL *string*
contains certain tokens, not that a `market='CRYPTO'` row is actually
excluded from a real query result. Rewritten to seed an in-memory SQLite
`stocks` table (same pattern as test_sr_auto_pivot.py's sync_sqlite_engine
fixture / test_import_sr_levels.py) and execute the ACTUAL query constants
(`fund_fetcher.FUND_SYMBOLS_QUERY`, `fundamentals_fetcher.FUNDAMENTALS_SYMBOLS_QUERY`
— pulled out of the task functions as named constants specifically so tests
can run the real query, not a copy of it) against seeded CRYPTO/US/FUND rows.
"""
from sqlalchemy import create_engine, text

from core.database import Base
from models.stock import Stock, MarketType
from workers import fund_fetcher, fundamentals_fetcher


def _seeded_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO stocks (symbol, name, market, is_active) VALUES "
            "(:symbol, :name, :market, true)"
        ), [
            {"symbol": "BTC-USD", "name": "Bitcoin", "market": "CRYPTO"},
            {"symbol": "ETH-USD", "name": "Ethereum", "market": "CRYPTO"},
            {"symbol": "AAPL", "name": "Apple", "market": "US"},
            {"symbol": "K-CHINA", "name": "K China Fund", "market": "FUND"},
        ])
    return engine


class TestFundFetcherNeverMatchesCrypto:
    def test_crypto_rows_absent_from_fund_query_result(self):
        """Behavioral: run the ACTUAL fund_fetcher query against seeded
        CRYPTO + US + FUND rows — CRYPTO must never appear, FUND must."""
        engine = _seeded_engine()
        with engine.connect() as conn:
            rows = conn.execute(text(fund_fetcher.FUND_SYMBOLS_QUERY)).fetchall()

        symbols = {r[0] for r in rows}
        assert symbols == {"K-CHINA"}
        assert "BTC-USD" not in symbols
        assert "ETH-USD" not in symbols


class TestFundamentalsFetcherSkipsCrypto:
    def test_crypto_rows_absent_from_fundamentals_query_result(self):
        """Behavioral: run the ACTUAL fundamentals_fetcher query against
        seeded CRYPTO + US + FUND rows — CRYPTO and FUND must both be
        excluded, US must be included."""
        engine = _seeded_engine()
        with engine.connect() as conn:
            rows = conn.execute(text(fundamentals_fetcher.FUNDAMENTALS_SYMBOLS_QUERY)).fetchall()

        symbols = {r[0] for r in rows}
        assert symbols == {"AAPL"}
        assert "BTC-USD" not in symbols
        assert "ETH-USD" not in symbols
        assert "K-CHINA" not in symbols
