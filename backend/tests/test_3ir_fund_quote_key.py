"""bd:shotockviz-3ir — fund_fetcher must not dual-write Thai fund NAV data
into quote:{symbol}, the same key namespace price_fetcher/cache_publisher
use for live equity quotes with a very different staleness contract
(120s TTL there vs. 86400s here — see core/cache_keys.py's `quote()`
docstring and workers/fund_fetcher.py's comment at the fund_payload
setex site for the full reasoning and the consumers this deliberately
leaves for follow-up).

RED-proof: with backend/workers/fund_fetcher.py's bd:shotockviz-3ir diff
reverted (`git stash` just that file, or check out the parent commit),
running this file failed:
  - test_only_fund_key_is_written_not_quote_key
    -> AssertionError: bd:shotockviz-3ir — fund_fetcher must NOT also
       write quote:{symbol} ...
    because `quote_key in written` was True, with a payload carrying
    `{"type": "fund_nav", "price": 12.34, ...}` under an 86400s TTL — the
    exact deceptive dual-write this bd removes.
  - test_no_writer_uses_quote_key_builder_for_fund_data
    -> AssertionError: assert 'cache_keys.quote(' not in source
    because the old source literally contained
    `redis_client.setex(cache_keys.quote(symbol), 86400, ...)`.
Restoring the fix turned both green.
"""
import json
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, text

from core import cache_keys
from core.database import Base
from workers import fund_fetcher


def _seed_one_fund_symbol(tmp_path, symbol: str) -> str:
    """Seed a throwaway sqlite DB with one active market='FUND' row and
    return its URL — same seeding pattern as
    test_crypto_downstream_guards.py / test_alert_checker_indicator_types.py."""
    db_path = tmp_path / "fund_fetcher_3ir.db"
    sqlite_url = f"sqlite:///{db_path}"
    engine = create_engine(sqlite_url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO stocks (symbol, name, market, is_active) "
                "VALUES (:symbol, :name, 'FUND', true)"
            ),
            {"symbol": symbol, "name": "Test Fund"},
        )
    engine.dispose()
    return sqlite_url


class TestFundFetcherDoesNotDualWriteQuoteKey:
    def test_only_fund_key_is_written_not_quote_key(self, tmp_path):
        symbol = "KFSDIV"
        sqlite_url = _seed_one_fund_symbol(tmp_path, symbol)

        fake_redis = MagicMock()
        written: dict[str, tuple[int, str]] = {}
        fake_redis.setex.side_effect = lambda key, ttl, value: written.__setitem__(key, (ttl, value))
        fake_redis.get.return_value = None  # no cached proj_id map — irrelevant on the Finnomena path

        with (
            patch("core.config.settings.database_url", sqlite_url),
            patch("core.config.settings.sec_fund_factsheet_key", ""),
            patch("core.config.settings.sec_fund_daily_info_key", ""),
            patch("redis.from_url", return_value=fake_redis),
            patch(
                "workers.fund_fetcher._fetch_nav_finnomena",
                return_value={"nav": 12.34, "date": "2026-09-05", "fund_name": "Test Fund"},
            ),
        ):
            fund_fetcher.fetch_thai_fund_navs()

        fund_key = cache_keys.fund(symbol)
        quote_key = cache_keys.quote(symbol)

        assert fund_key in written, "fund NAV must still be cached under fund:{symbol}"
        ttl, payload_raw = written[fund_key]
        assert ttl == 86400
        payload = json.loads(payload_raw)
        assert payload["nav"] == 12.34
        assert payload["symbol"] == symbol

        assert quote_key not in written, (
            "bd:shotockviz-3ir — fund_fetcher must NOT also write "
            "quote:{symbol}; that key namespace belongs to "
            "price_fetcher/cache_publisher's live-quote contract "
            "(120s TTL), not a once-daily NAV (86400s TTL)."
        )

    def test_no_writer_uses_quote_key_builder_for_fund_data(self):
        """Static guard, independent of the Redis-level test above: the
        task's own source must not contain a setex call keyed off
        cache_keys.quote() — catches a future re-introduction (e.g.
        copy-pasted from price_fetcher) even if a test's mocking happened
        to miss it. Checks for the actual call pattern, not just the
        substring "cache_keys.quote(" — this module's own explanatory
        comment about the bd:shotockviz-3ir fix legitimately quotes that
        old call for context."""
        import inspect

        source = inspect.getsource(fund_fetcher.fetch_thai_fund_navs)
        assert "setex(cache_keys.quote(" not in source


class TestQuoteKeyDocumentsTheContract:
    """core/cache_keys.py's quote() docstring is the single place this
    contract (live equity quote, ~120s staleness) is written down —
    guard against it silently regressing back to a bare one-liner that
    invites the next accidental dual-write."""

    def test_quote_docstring_names_the_3ir_contract(self):
        assert "3ir" in cache_keys.quote.__doc__
        assert "fund" in cache_keys.quote.__doc__.lower()
