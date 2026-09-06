"""bd:shotockviz-cjb — the screener must not render 'nan' as a price.

Seen live on 2026-09-06: GOOGL and GLD came back from `GET /api/v1/screener`
with `price: "nan"` and `chg: "nan%"`, and rendered that way in the browser.
Origin: yfinance returned a 2026-09-04 daily row with a real `volume` but NaN
open/high/low/close for both symbols, and the writer persisted it verbatim.
Because it was the NEWEST bar, `closes[-1]` was NaN.

RSI still read as a plausible 47.8 / 54.9, which is why nobody noticed: Wilder
smoothing over the earlier window never touches the last close. A row that
looks like a result and cannot be acted on is worse than a row that is absent.

⚠️ Auditing note: `SELECT ... WHERE close != close` does NOT find these rows.
Postgres treats NaN as equal to itself and greater than every other float,
unlike IEEE 754 and unlike Python. The first sweep for this bug reported 0
affected rows for that reason. Use `close = 'NaN'::float8`.
"""
import math
from types import SimpleNamespace

import pytest

from api.routes.screener import _bar_has_finite_prices, _evaluate_symbol


def _bar(close, *, symbol="GLD", volume=1_000_000.0, o=None, h=None, l=None):
    return SimpleNamespace(
        symbol=symbol,
        open=o if o is not None else close,
        high=h if h is not None else close,
        low=l if l is not None else close,
        close=close,
        volume=volume,
        time_unix=1788494400,
        timeframe="1D",
    )


# ── the predicate ───────────────────────────────────────────────────────────

def test_a_normal_bar_is_finite():
    assert _bar_has_finite_prices(_bar(410.22)) is True


def test_the_real_shape_that_broke_it_is_rejected():
    """A real volume with NaN prices — exactly the GLD/GOOGL row."""
    nan = float("nan")
    bar = SimpleNamespace(
        symbol="GLD", open=nan, high=nan, low=nan, close=nan,
        volume=9_693_614.0, time_unix=1788494400, timeframe="1D",
    )
    assert _bar_has_finite_prices(bar) is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), None])
def test_non_finite_or_missing_prices_are_rejected(bad):
    assert _bar_has_finite_prices(_bar(bad)) is False


def test_a_non_finite_value_in_any_ohlc_field_rejects_the_bar():
    """Not just close — a NaN high poisons range-based work just as well."""
    assert _bar_has_finite_prices(_bar(410.22, h=float("nan"))) is False
    assert _bar_has_finite_prices(_bar(410.22, l=float("nan"))) is False
    assert _bar_has_finite_prices(_bar(410.22, o=float("nan"))) is False


# ── the symptom ─────────────────────────────────────────────────────────────

def _series(n=60, start=400.0):
    return [_bar(start + i * 0.5) for i in range(n)]


def test_a_clean_series_still_produces_a_real_price():
    """The guard must not turn the screener into a no-op."""
    row = _evaluate_symbol(_series(), "SPDR Gold Shares", "any", "any", "any", "any")
    assert row is not None
    assert "nan" not in row["price"]
    assert "nan" not in row["chg"]
    assert float(row["price"]) > 0


def test_a_trailing_nan_bar_would_have_produced_nan_before_the_guard():
    """Demonstrates the defect against the same evaluation function: feed the
    NaN bar straight to `_evaluate_symbol` (which is downstream of the drop)
    and the formatted output really is the string 'nan'. That is what
    `_fetch_symbol_bars` now prevents from ever reaching here."""
    bars = _series()
    nan = float("nan")
    bars.append(SimpleNamespace(
        symbol="GLD", open=nan, high=nan, low=nan, close=nan,
        volume=9_693_614.0, time_unix=1788580800, timeframe="1D",
    ))
    row = _evaluate_symbol(bars, "SPDR Gold Shares", "any", "any", "any", "any")
    assert row is not None
    assert row["price"] == "nan", "premise: an unfiltered NaN bar formats as 'nan'"
    assert "nan" in row["chg"]


def test_the_ts_reported_is_the_bar_actually_used():
    """bd:shotockviz-f14.1 says the row's `ts` is the newest bar its numbers
    came from. Dropping a bar must move that `ts` back, not leave it pointing
    at a bar with no prices."""
    bars = _series()
    row = _evaluate_symbol(bars, "SPDR Gold Shares", "any", "any", "any", "any")
    assert row["ts"] == bars[-1].time_unix
