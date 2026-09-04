"""Property-based tests — bd:features-2026-09 iter5, Chris review H1
(10-chris-crypto-autopivot-review.md): mandatory per house Test Quality
gate for pure functions. Complements the fixed-fixture example tests in
test_sr_auto_pivot.py / test_symbol_utils.py; does not replace them.

Properties covered (per Chris's H1 "Fix" list):
  - is_crypto: any string ending "-USD" (case-insensitive) -> True; else False.
  - cluster_pivots: order-invariance, sum(strengths) == len(input), output
    sorted ascending by mean.
  - classify_and_select: len(rows) <= 2*top_n, every row's price is on the
    correct side of the dead band, tag numbers are contiguous 1..len(selected)
    per side.
"""
from __future__ import annotations

from hypothesis import given, assume, settings, strategies as st

from core.symbol_utils import is_crypto
from workers.sr_auto_pivot import (
    DEAD_BAND,
    classify_and_select,
    cluster_pivots,
)


# ─────────────────────────────────────────────────────────────────────────────
# is_crypto
# ─────────────────────────────────────────────────────────────────────────────

# Printable-ish symbol charset — letters, digits, dash, dot, caret, equals
# (covers real symbol shapes: PTT.BK, BRK-B, ^GSPC, THBUSD=X, BTC-USD).
_SYMBOL_ALPHABET = st.characters(
    whitelist_categories=("Lu", "Ll", "Nd"),
    whitelist_characters=".-^=",
)


@given(prefix=st.text(alphabet=_SYMBOL_ALPHABET, min_size=0, max_size=15))
def test_is_crypto_true_for_any_prefix_plus_dash_usd_suffix(prefix):
    """Any string ending in '-USD' (any case) must be True — the allowlist
    is suffix-based, not tied to BTC/ETH specifically."""
    for suffix in ("-USD", "-usd", "-Usd"):
        assert is_crypto(f"{prefix}{suffix}") is True


@given(symbol=st.text(alphabet=_SYMBOL_ALPHABET, min_size=0, max_size=20))
def test_is_crypto_false_when_not_ending_dash_usd(symbol):
    assume(not symbol.upper().endswith("-USD"))
    assert is_crypto(symbol) is False


@given(symbol=st.text(alphabet=_SYMBOL_ALPHABET, min_size=0, max_size=20))
def test_is_crypto_case_insensitive(symbol):
    """Upper/lower/mixed-case input must classify identically."""
    assert is_crypto(symbol) == is_crypto(symbol.upper()) == is_crypto(symbol.lower())


# ─────────────────────────────────────────────────────────────────────────────
# cluster_pivots
# ─────────────────────────────────────────────────────────────────────────────

_PRICE = st.floats(
    min_value=0.01, max_value=1_000_000, allow_nan=False, allow_infinity=False
)


@given(prices=st.lists(_PRICE, min_size=1, max_size=30))
@settings(max_examples=200)
def test_cluster_pivots_strength_sums_to_input_length(prices):
    """Every input price ends up in exactly one cluster — no price lost or
    double-counted."""
    clusters = cluster_pivots(prices)
    assert sum(strength for _, strength in clusters) == len(prices)


@given(prices=st.lists(_PRICE, min_size=1, max_size=30))
@settings(max_examples=200)
def test_cluster_pivots_output_sorted_ascending_by_mean(prices):
    clusters = cluster_pivots(prices)
    means = [mean for mean, _ in clusters]
    assert means == sorted(means)


@given(prices=st.lists(_PRICE, min_size=1, max_size=15))
@settings(max_examples=200)
def test_cluster_pivots_is_order_invariant(prices):
    """Clustering result must not depend on the order prices were passed in
    (the function sorts internally) — shuffled input, same output."""
    import random

    shuffled = list(prices)
    random.Random(42).shuffle(shuffled)
    assert cluster_pivots(prices) == cluster_pivots(shuffled)


@given(prices=st.lists(_PRICE, min_size=1, max_size=30))
@settings(max_examples=200)
def test_cluster_pivots_every_cluster_has_positive_strength(prices):
    clusters = cluster_pivots(prices)
    assert all(strength >= 1 for _, strength in clusters)


def test_cluster_pivots_empty_input_is_empty_output():
    assert cluster_pivots([]) == []


# ─────────────────────────────────────────────────────────────────────────────
# classify_and_select
# ─────────────────────────────────────────────────────────────────────────────

_CLUSTER = st.tuples(_PRICE, st.integers(min_value=1, max_value=50))


@given(
    clusters_hi=st.lists(_CLUSTER, min_size=0, max_size=10),
    clusters_lo=st.lists(_CLUSTER, min_size=0, max_size=10),
    close=_PRICE,
)
@settings(max_examples=300)
def test_classify_and_select_never_exceeds_2n_rows(clusters_hi, clusters_lo, close):
    rows = classify_and_select(clusters_hi, clusters_lo, close, top_n=3)
    assert len(rows) <= 6


@given(
    clusters_hi=st.lists(_CLUSTER, min_size=0, max_size=10),
    clusters_lo=st.lists(_CLUSTER, min_size=0, max_size=10),
    close=_PRICE,
)
@settings(max_examples=300)
def test_classify_and_select_every_row_is_on_the_correct_side_of_dead_band(
    clusters_hi, clusters_lo, close
):
    rows = classify_and_select(clusters_hi, clusters_lo, close, top_n=3)
    for row in rows:
        if row["level_type"] == "support":
            assert row["price"] < close * (1 - DEAD_BAND)
        else:
            assert row["level_type"] == "resistance"
            assert row["price"] > close * (1 + DEAD_BAND)


@given(
    clusters_hi=st.lists(_CLUSTER, min_size=0, max_size=10),
    clusters_lo=st.lists(_CLUSTER, min_size=0, max_size=10),
    close=_PRICE,
)
@settings(max_examples=300)
def test_classify_and_select_tag_numbers_contiguous_per_side(clusters_hi, clusters_lo, close):
    """Tag numbers for each side must be a contiguous 1..N sequence (no
    gaps, no duplicates) — N = however many were actually selected for that
    side (0..top_n)."""
    rows = classify_and_select(clusters_hi, clusters_lo, close, top_n=3)

    support_nums = sorted(
        int(r["tag"].removeprefix("AUTO S")) for r in rows if r["level_type"] == "support"
    )
    resistance_nums = sorted(
        int(r["tag"].removeprefix("AUTO R")) for r in rows if r["level_type"] == "resistance"
    )

    assert support_nums == list(range(1, len(support_nums) + 1))
    assert resistance_nums == list(range(1, len(resistance_nums) + 1))


@given(
    clusters_hi=st.lists(_CLUSTER, min_size=0, max_size=10),
    clusters_lo=st.lists(_CLUSTER, min_size=0, max_size=10),
    close=_PRICE,
)
@settings(max_examples=300)
def test_classify_and_select_no_side_exceeds_top_n(clusters_hi, clusters_lo, close):
    rows = classify_and_select(clusters_hi, clusters_lo, close, top_n=3)
    support_count = sum(1 for r in rows if r["level_type"] == "support")
    resistance_count = sum(1 for r in rows if r["level_type"] == "resistance")
    assert support_count <= 3
    assert resistance_count <= 3
