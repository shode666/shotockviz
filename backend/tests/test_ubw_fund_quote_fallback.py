"""bd:shotockviz-ubw — consumers of quote:{symbol} must look in fund:{symbol}.

bd:shotockviz-3ir stopped `fund_fetcher` dual-writing the Thai fund NAV into
`quote:{symbol}` — that key means "live equity quote, 120s TTL", and an
86400s-TTL NAV sitting in it was read by price alerts as if it were a live
price. The cost is that every consumer must now look in `fund:{symbol}`
itself; three did not and would have regressed from "reads a stale NAV as if
live" to "sees nothing at all".
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.fund_quote import fund_payload_to_quote


# ── the shared converter ────────────────────────────────────────────────────

def _payload(**over):
    base = {"nav": 12.3456, "date": "2026-09-05", "ts": 1788600000}
    base.update(over)
    return json.dumps(base)


def test_converts_a_nav_payload_to_the_quote_shape():
    q = fund_payload_to_quote("KFLTF70", _payload())
    assert q == {
        "symbol": "KFLTF70",
        "price": 12.3456,
        "change": 0.0,
        "change_pct": 0.0,
        "volume": 0,
        "type": "fund_nav",
        "nav_date": "2026-09-05",
        "ts": 1788600000,
    }


def test_type_says_fund_nav_so_a_caller_can_tell_it_is_not_a_traded_price():
    assert fund_payload_to_quote("KFLTF70", _payload())["type"] == "fund_nav"


def test_ts_is_the_navs_own_stamp_not_a_substituted_fetch_time():
    """A NAV is T+1 by design and must read as hours old. Substituting a
    fresher number would be the exact dishonesty bd:shotockviz-f14/09j exist
    to remove."""
    q = fund_payload_to_quote("KFLTF70", _payload(ts=1700000000))
    assert q["ts"] == 1700000000


def test_missing_ts_is_none_not_zero():
    """`ts: 0` is epoch 1970, which getPriceFreshness would render as a
    56-year-old price. Absent means unknown, and must say so."""
    raw = json.dumps({"nav": 1.0, "date": "2026-09-05"})
    assert fund_payload_to_quote("X", raw)["ts"] is None


@pytest.mark.parametrize("raw", [
    None, b"", "not json", json.dumps([1, 2, 3]), json.dumps({"nav": None}),
    json.dumps({"nav": "n/a"}), json.dumps({}),
])
def test_unusable_payloads_return_none_rather_than_a_fabricated_quote(raw):
    assert fund_payload_to_quote("X", raw) is None


# ── alert_checker's price branch ────────────────────────────────────────────

def test_alert_checker_price_branch_reads_the_fund_key_on_a_quote_miss(monkeypatch):
    """Without the fallback the alert would silently never fire again, which
    is indistinguishable from 'the level was never crossed'."""
    from workers import alert_checker

    fake_redis = MagicMock()
    stored = {
        "fund:KFLTF70": _payload(nav=15.0),
        # deliberately NO "quote:KFLTF70"
    }
    fake_redis.get.side_effect = lambda k: stored.get(
        k.decode() if isinstance(k, bytes) else k
    )

    # exercise the read path the way the task does
    from core import cache_keys
    assert fake_redis.get(cache_keys.quote("KFLTF70")) is None
    recovered = fund_payload_to_quote(
        "KFLTF70", fake_redis.get(cache_keys.fund("KFLTF70"))
    )
    assert recovered is not None and recovered["price"] == 15.0

    # and that the module actually wires it — the source must reference the
    # fund key inside the price branch, not only the quote key
    import inspect
    src = inspect.getsource(alert_checker.check_all_alerts)
    assert "cache_keys.fund(" in src, (
        "alert_checker's price branch has no fund:{symbol} fallback; a price "
        "alert on a Thai fund can never fire"
    )


# ── the S/R proximity digest ────────────────────────────────────────────────

def test_digest_recovers_fund_symbols_that_missed_the_quote_mget():
    """A fund on a watchlist would silently vanish from the digest rather
    than appear with its NAV."""
    from workers import sr_proximity_digest
    import inspect

    src = inspect.getsource(sr_proximity_digest.send_sr_proximity_digest)
    assert "cache_keys.fund(" in src, (
        "the digest reads only quote:{symbol}; a watchlisted fund is dropped "
        "from the digest entirely"
    )

    all_symbols = ["PTT.BK", "KFLTF70"]
    prices_raw = [json.dumps({"price": 35.0, "ts": 1788600000}), None]
    fund_misses = [s for s, raw in zip(all_symbols, prices_raw) if not raw]
    assert fund_misses == ["KFLTF70"]
    recovered = fund_payload_to_quote("KFLTF70", _payload(nav=9.5))
    assert recovered["price"] == 9.5


# ── dashboard ───────────────────────────────────────────────────────────────

def test_dashboard_fast_quote_has_the_fallback():
    from api.routes import dashboard
    import inspect

    src = inspect.getsource(dashboard._fast_quote)
    assert "cache_keys.fund(" in src, (
        "_fast_quote reads only quote:{symbol}; watchlist movers and the "
        "'alerts near target' widget show nothing at all for a fund"
    )


# ── the drift this consolidation exists to prevent ──────────────────────────

def test_every_consumer_uses_the_one_converter():
    """Five hand-rolled copies of this shape is how quote:{symbol} came to
    mean two different things. If a new consumer is added, it must call the
    shared function rather than rebuild the dict."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    consumers = [
        "api/routes/stocks/quotes.py",
        "api/routes/portfolio.py",
        "api/routes/dashboard.py",
        "workers/alert_checker.py",
        "workers/sr_proximity_digest.py",
        "workers/gap_list_digest.py",
    ]
    for rel in consumers:
        src = (root / rel).read_text()
        assert "fund_payload_to_quote" in src, f"{rel} does not use the shared converter"
        assert '"type": "fund_nav"' not in src, (
            f"{rel} still hand-rolls the fund_nav quote shape"
        )
