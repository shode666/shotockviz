"""bd:shotockviz-cjb (writer half) — a priceless bar must never be persisted.

The read-side guard in `api/routes/screener.py` stopped the visible symptom.
This covers the rule that keeps it out of the database and the daily-bar cache
in the first place, because every downstream reader inherits a bad row:
`alert_checker`'s 5 indicator alert types and `sr_auto_pivot`'s level
computation both read these bars.
"""
import inspect
import pathlib

import pytest

from services.bar_hygiene import drop_non_finite_bars, is_finite_bar

NAN = float("nan")


def _bar(**over):
    b = {"time_unix": 1788494400, "time": "2026-09-04",
         "open": 410.0, "high": 412.0, "low": 409.0, "close": 410.22,
         "volume": 9_693_614.0}
    b.update(over)
    return b


class _Row:
    """An ORM-ish row — the shape the screener reads from PostgreSQL."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ── the predicate handles both shapes ───────────────────────────────────────

def test_dicts_and_orm_rows_are_both_accepted():
    assert is_finite_bar(_bar()) is True
    assert is_finite_bar(_Row(**_bar())) is True


def test_the_exact_row_that_reached_production_is_rejected_in_both_shapes():
    bad = _bar(open=NAN, high=NAN, low=NAN, close=NAN)
    assert is_finite_bar(bad) is False
    assert is_finite_bar(_Row(**bad)) is False


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
@pytest.mark.parametrize("value", [NAN, float("inf"), float("-inf"), None])
def test_any_non_finite_price_field_rejects_the_bar(field, value):
    assert is_finite_bar(_bar(**{field: value})) is False


def test_zero_volume_is_kept_because_it_is_a_real_fact():
    """A halt or an illiquid Thai small-cap genuinely trades zero. Dropping
    those would discard real sessions, which is a different bug."""
    assert is_finite_bar(_bar(volume=0)) is True


def test_a_missing_price_key_is_rejected_rather_than_crashing():
    bar = _bar()
    del bar["close"]
    assert is_finite_bar(bar) is False


# ── the filter reports what it dropped ──────────────────────────────────────

def test_drop_returns_the_count_so_callers_can_log_it():
    bars = [_bar(), _bar(close=NAN), _bar(), _bar(open=NAN)]
    usable, dropped = drop_non_finite_bars(bars)
    assert dropped == 2
    assert len(usable) == 2


def test_order_is_preserved():
    bars = [_bar(time="d1"), _bar(time="d2", close=NAN), _bar(time="d3")]
    usable, _ = drop_non_finite_bars(bars)
    assert [b["time"] for b in usable] == ["d1", "d3"]


def test_a_clean_list_is_untouched():
    bars = [_bar(), _bar()]
    usable, dropped = drop_non_finite_bars(bars)
    assert dropped == 0 and usable == bars


# ── nobody writes bars without going through it ─────────────────────────────

def test_every_module_that_inserts_ohlcv_bars_filters_first():
    """The screener guard alone was not enough — it only protects one reader.
    If a new writer appears, it must filter too, or the NaN is back in the DB
    for `alert_checker` and `sr_auto_pivot` to read."""
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in list(root.glob("workers/*.py")) + list(root.glob("services/*.py")):
        src = path.read_text()
        if "INSERT INTO ohlcv_bars" in src and "drop_non_finite_bars" not in src:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], (
        f"{offenders} insert OHLCV bars without dropping non-finite ones first"
    )


def test_the_screener_reuses_the_shared_predicate_rather_than_a_second_copy():
    from api.routes import screener
    assert screener._bar_has_finite_prices is is_finite_bar


def test_volume_is_deliberately_excluded_from_the_checked_fields():
    """Guards the decision, so it cannot be 'tidied' into checking volume too
    and start discarding real zero-volume sessions."""
    from services import bar_hygiene
    assert "volume" not in bar_hygiene._PRICE_FIELDS
    assert set(bar_hygiene._PRICE_FIELDS) == {"open", "high", "low", "close"}
