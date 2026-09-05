"""Shared holdings + valuation computation for the portfolio book.

Single source of truth for BOTH `api/routes/portfolio.py` (`/portfolio/analytics`)
and `api/routes/dashboard.py` (`_build_portfolio_summary`). Before this module the
two routes each rebuilt the same book with different rules and disagreed on the
same instant — bd:shotockviz-msg (Tara, outputs/backlog-2026-09/10-tara-value.md N4).

Accounting rules pinned here (state them once, apply everywhere):

1. bd:shotockviz-fww — commission.
   BUY : the fee is capitalised into cost basis  -> cost += qty*price + fee,
         so `avg_cost` is the trader's real breakeven price.
   SELL: the fee reduces *proceeds*, i.e. it belongs to REALIZED P&L, not to the
         cost basis of the shares still held. It is accumulated on
         `Holding.realized_fees` and deliberately NOT folded into the open
         position — charging a closed lot's cost to the remaining shares would
         distort avg cost. Realized P&L itself is not reported by this product
         yet (Tara N9, separate bead); `realized_fees` is the hook for it.
   Cost basis removed on a SELL is `qty_sold * avg_cost` (weighted average,
   avg taken BEFORE the qty is reduced) — unchanged from the previous code.

2. bd:shotockviz-2w8 — a position with no usable quote is excluded from BOTH
   sides of the total (see `summarize`). It is never valued at zero, because a
   zero valuation against a full cost basis fabricates a loss equal to the whole
   position — the normal state for a Thai book after 16:30 ICT, i.e. exactly
   when the user looks. Unpriced positions are still returned as rows (with
   `current_price=None`) and listed in `PortfolioTotals.unpriced_symbols` so the
   caller can flag "price unavailable".

3. A quote counts as usable only when `price is not None and price > 0`
   (`usable_price`). A quote of exactly 0.0 is bad data, not a market price;
   treating it as real is the same fabricated-loss failure mode as (2).
   Note this is a *deliberate* test, not the old truthiness test — `if price:`
   and `if current_value:` also swallowed legitimate zero values.

4. bd:shotockviz-fnn / bd:shotockviz-sbe — FX. The book has ONE base currency
   (`BASE_CURRENCY` = THB); every total this module produces is in that base.
   Adding THB and USD raw (what `/portfolio/analytics` used to do) is not a
   rounding problem, it is a meaningless number.

   FX-1 rate capture. A transaction may carry `fx_rate` = units of base per 1
   unit of its own currency, observed when the trade was recorded
   (`api/routes/portfolio.py::add_transaction`). For a base-currency
   transaction the rate is 1.0 *by definition* and is never read off the
   market — so the entire existing THB book is FX-complete without a backfill.
   A non-base transaction with no stored rate stays FX-incomplete forever: the
   user's decision is that historical rates are NOT backfilled, and inventing
   one is the same class of bug as the 33.0 constant this bead removes.

   FX-2 conversion. Value is always converted at the CURRENT rate. Cost is
   converted at the rate stored per transaction when every open lot of that
   position has one (`Holding.fx_complete`), which is what makes the currency
   component separable:

       value_n·Rc − Σ(cost_i·R_i) = (value_n − cost_n)·Rc + Σ cost_i·(Rc − R_i)
                                    └── market component ──┘ └── FX component ──┘

   When a lot has no stored rate we fall back to converting cost at the current
   rate (the old behaviour, which structurally hides FX return) and say so:
   `cost_basis_source = "current_rate"` and `fx_pl_base = None`. Never 0.0 —
   zero is a claim that the currency did not move, and we do not know that.

   FX-3 no silent constant. A rate that is not `live` is marked `estimated`
   everywhere it is used, and the fallback chain is explicit:
   live quote → the user's own last recorded rate → `FX_FALLBACK_RATES`.
   A live quote outside `FX_PLAUSIBLE_RANGE` is treated as bad data, not as a
   rate — inverting a mis-quoted pair silently scales the whole US book by 1000.

Money is `float` here only because `models/portfolio.py:33-35` stores qty/price/fee
as `Float`. The Decimal/Numeric migration is a separate bead (Tara N8) and is NOT
started here. The arithmetic below adds exactly one new term per BUY (`+ fee`),
so it introduces no new rounding behaviour beyond that term.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

# Positions below this size are treated as fully closed. Also used as the
# float-drift guard after a SELL (the previous code used 1e-6 in portfolio.py
# and a *different* 0.001 "active" threshold in dashboard.py — unified here).
QTY_EPSILON = 1e-6

# The one currency every total in this module is stated in.
BASE_CURRENCY = "THB"

# Yahoo symbol carrying the rate. It quotes "1 THB in USD" (e.g. 0.0317), so the
# THB-per-USD rate is its reciprocal — see `live_rate_from_thbusd`.
FX_QUOTE_SYMBOL = "THBUSD=X"

# Last-resort rate, used ONLY when there is no live quote and the user's own book
# has never recorded one. Always surfaced as source="fallback" / estimated=True;
# it is never written to a transaction.
FX_FALLBACK_RATES = {"USD": 33.0}

# Sanity band for a base-per-unit rate. A quote that lands outside it is bad data
# (e.g. the pair delivered the other way up), not a market rate.
FX_PLAUSIBLE_RANGE = {"USD": (10.0, 100.0)}


def _currency_str(value) -> str:
    """Normalise a `Currency` enum / str / None to a plain upper-case code."""
    if value is None:
        return "THB"
    raw = getattr(value, "value", value)
    return str(raw).upper() or "THB"


@dataclass
class FxRate:
    """A currency→base rate together with how honest it is (rule 4, FX-3)."""

    currency: str
    rate: float
    source: str  # "identity" | "live" | "last_known" | "fallback"
    as_of: str | None = None  # ISO date of a "last_known" observation
    base: str = BASE_CURRENCY

    @property
    def estimated(self) -> bool:
        """True when the rate is not an observed current market rate."""
        return self.source not in ("identity", "live")


FxResolver = Callable[[str], "FxRate | None"]


def live_rate_from_thbusd(quote: Mapping | None) -> float | None:
    """THB-per-USD from a cached `THBUSD=X` quote, or None if not usable.

    The quote is "1 THB in USD", so the rate we want is its reciprocal. A price
    that is missing / non-numeric / non-positive, or a reciprocal outside
    `FX_PLAUSIBLE_RANGE["USD"]`, returns None — the caller then falls back and
    marks the result estimated instead of scaling the US book by a wrong power
    of ten.
    """
    price = usable_price(quote)
    if price is None:
        return None
    rate = 1.0 / price
    lo, hi = FX_PLAUSIBLE_RANGE["USD"]
    return rate if lo <= rate <= hi else None


def last_known_rate(txns: Iterable, currency: str) -> tuple[float, str | None] | None:
    """Most recently *dated* rate the user's own book has recorded for `currency`.

    Preferred over `FX_FALLBACK_RATES` because it is a rate this user actually
    transacted at, not a constant frozen in source. Still `estimated`.
    """
    currency = currency.upper()
    best = None
    for t in txns:
        if _currency_str(getattr(t, "currency", None)) != currency:
            continue
        rate = getattr(t, "fx_rate", None)
        if rate is None:
            continue
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            continue
        if rate <= 0:
            continue
        when = getattr(t, "date", None)
        key = (when.isoformat() if hasattr(when, "isoformat") else str(when or ""))
        if best is None or key >= best[1]:
            best = (rate, key)
    if best is None:
        return None
    return best[0], (best[1] or None)


def resolve_fx(
    currency: str,
    live_rate: float | None = None,
    last_known: tuple[float, str | None] | None = None,
) -> FxRate | None:
    """Pick the most honest rate available for `currency`, labelled with its source."""
    currency = currency.upper()
    if currency == BASE_CURRENCY:
        return FxRate(currency=currency, rate=1.0, source="identity")
    if live_rate is not None and live_rate > 0:
        return FxRate(currency=currency, rate=live_rate, source="live")
    if last_known is not None and last_known[0] > 0:
        return FxRate(currency=currency, rate=last_known[0], source="last_known",
                      as_of=last_known[1])
    fallback = FX_FALLBACK_RATES.get(currency)
    if fallback:
        return FxRate(currency=currency, rate=fallback, source="fallback")
    return None  # unknown currency — the caller must decline, not guess


def fx_resolver(rates: Mapping[str, FxRate]) -> FxResolver:
    """Build the `fx` callable `value_holdings` takes, from a currency->FxRate map."""
    def _resolve(currency: str) -> FxRate | None:
        currency = _currency_str(currency)
        if currency == BASE_CURRENCY:
            return FxRate(currency=BASE_CURRENCY, rate=1.0, source="identity")
        return rates.get(currency)
    return _resolve


def build_fx_rates(txns: Sequence, fx_quote: Mapping | None = None) -> dict[str, FxRate]:
    """The one place both screens get their rates from, so they cannot disagree.

    `fx_quote` is the cached `THBUSD=X` blob (None when the cache is cold — the
    normal state off-hours, which is exactly when the old 33.0 constant fired).
    """
    live = live_rate_from_thbusd(fx_quote)
    currencies = {
        _currency_str(getattr(t, "currency", None)) for t in txns
    } - {BASE_CURRENCY}

    rates: dict[str, FxRate] = {}
    for currency in sorted(currencies):
        resolved = resolve_fx(
            currency,
            live_rate=live if currency == "USD" else None,
            last_known=last_known_rate(txns, currency),
        )
        if resolved is not None:
            rates[currency] = resolved
    return rates


def default_fx(currency: str) -> FxRate | None:
    """No FX context: only the base currency is expressible; everything else is
    honestly unknown (and gets excluded from the totals, never added raw)."""
    return fx_resolver({})(currency)


@dataclass
class Holding:
    """Net open position for one symbol, built from raw transactions."""

    symbol: str
    qty: float = 0.0
    cost_basis: float = 0.0  # includes BUY commission (rule 1), NATIVE currency
    currency: str = "THB"
    realized_fees: float = 0.0  # SELL commission — realized side, not cost basis
    # Rule 4 / FX-2: same cost basis, each lot converted at ITS OWN stored rate.
    # Only meaningful while `fx_complete` is True.
    cost_basis_base: float = 0.0
    fx_complete: bool = True

    @property
    def avg_cost(self) -> float:
        return self.cost_basis / self.qty if self.qty > QTY_EPSILON else 0.0

    @property
    def avg_fx_rate(self) -> float | None:
        """Weighted average rate the open cost basis was actually bought at."""
        if not self.fx_complete or self.cost_basis <= 0:
            return None
        return self.cost_basis_base / self.cost_basis


@dataclass
class ValuedHolding:
    """A `Holding` priced against one quote. `current_*` are None when unpriced.

    `*_base` fields are the same position stated in `BASE_CURRENCY`; they are
    None when no rate is available for the position's currency at all.
    """

    symbol: str
    qty: float
    avg_cost: float
    cost_basis: float
    currency: str
    current_price: float | None = None
    current_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None
    # ── rule 4: base-currency view ───────────────────────────────────────────
    base_currency: str = BASE_CURRENCY
    fx_rate: float | None = None          # current rate used for the VALUE side
    fx_source: str | None = None          # identity | live | last_known | fallback
    fx_as_of: str | None = None           # observation date of a "last_known" rate
    fx_estimated: bool = False
    cost_basis_base: float | None = None
    cost_basis_source: str | None = None  # identity | historical | current_rate
    current_value_base: float | None = None
    unrealized_pl_base: float | None = None
    unrealized_pl_pct_base: float | None = None
    market_pl_base: float | None = None   # market move, converted at current rate
    fx_pl_base: float | None = None       # currency move on the cost basis
    avg_fx_rate: float | None = None      # weighted rate the cost was bought at

    @property
    def priced(self) -> bool:
        return self.current_price is not None

    @property
    def convertible(self) -> bool:
        """A rate exists, so this position can enter a base-currency total."""
        return self.fx_rate is not None


@dataclass
class PortfolioTotals:
    total_value: float = 0.0
    total_cost: float = 0.0
    unrealized_pl: float = 0.0
    unrealized_pl_pct: float = 0.0
    priced_symbols: list[str] = field(default_factory=list)
    unpriced_symbols: list[str] = field(default_factory=list)
    # ── rule 4 ───────────────────────────────────────────────────────────────
    base_currency: str = BASE_CURRENCY
    market_pl: float = 0.0
    # None (not 0.0) as soon as ONE included position cannot separate its FX
    # component — "unknown", never "the currency did not move".
    fx_pl: float | None = 0.0
    fx_estimated: bool = False          # some rate in use is not a live quote
    cost_basis_estimated: bool = False  # some cost converted at the current rate
    fx_rates: dict[str, FxRate] = field(default_factory=dict)
    # Priced, but no rate for its currency -> excluded from the totals rather
    # than added raw (that raw addition was bd:shotockviz-sbe).
    fx_unavailable_symbols: list[str] = field(default_factory=list)


def build_holdings(txns: Iterable) -> dict[str, Holding]:
    """Fold transactions (chronological order) into net positions per symbol."""
    holdings: dict[str, Holding] = {}

    for t in txns:
        symbol = t.symbol
        if symbol not in holdings:
            holdings[symbol] = Holding(
                symbol=symbol,
                currency=_currency_str(getattr(t, "currency", None)),
            )
        h = holdings[symbol]

        qty = float(t.qty or 0.0)
        price = float(t.price or 0.0)
        fee = float(getattr(t, "fee", 0.0) or 0.0)
        txn_type = getattr(t.type, "value", t.type)
        rate = _txn_fx_rate(t)  # rule 4 / FX-1; 1.0 for a base-currency txn

        if txn_type == "BUY":
            h.qty += qty
            lot_cost = qty * price + fee  # rule 1: buy fee -> cost basis
            h.cost_basis += lot_cost
            if rate is None:
                # No rate for this lot and none may be invented -> this position
                # can never state a historical base cost or an FX return.
                h.fx_complete = False
            else:
                h.cost_basis_base += lot_cost * rate
        else:  # SELL
            avg = h.avg_cost  # avg BEFORE reducing qty
            avg_base = (h.cost_basis_base / h.qty) if h.qty > QTY_EPSILON else 0.0
            h.qty -= qty
            h.cost_basis -= qty * avg
            # Same weighted-average removal on the base side; the SELL's own rate
            # is irrelevant to the shares still held (it belongs to realized P&L).
            h.cost_basis_base -= qty * avg_base
            h.realized_fees += fee  # rule 1: sell fee -> realized, not cost basis
            if abs(h.qty) < QTY_EPSILON:  # float-drift guard
                h.qty = 0.0
                h.cost_basis = 0.0
                h.cost_basis_base = 0.0

    return holdings


def _txn_fx_rate(t) -> float | None:
    """Rate to convert this transaction into `BASE_CURRENCY` (rule 4 / FX-1).

    A base-currency transaction is 1.0 by definition — that is what keeps the
    whole pre-existing THB book FX-complete with no backfill. Anything else must
    come from a rate stored on the row; absent (or nonsense) means unknown.
    """
    if _currency_str(getattr(t, "currency", None)) == BASE_CURRENCY:
        return 1.0
    raw = getattr(t, "fx_rate", None)
    if raw is None:
        return None
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def active_holdings(holdings: Mapping[str, Holding]) -> dict[str, Holding]:
    """Positions still open (fully-sold symbols dropped)."""
    return {s: h for s, h in holdings.items() if h.qty > QTY_EPSILON}


def usable_price(quote: Mapping | None) -> float | None:
    """Extract a usable market price from a cached quote blob, else None.

    Rule 3: `None`, a non-numeric, or a non-positive price all mean
    "no price available" — never "the position is worth nothing".
    """
    if not quote:
        return None
    raw = quote.get("price")
    if raw is None:
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def value_holdings(
    holdings: Mapping[str, Holding],
    quotes: Mapping[str, Mapping | None],
    fx: FxResolver | None = None,
) -> list[ValuedHolding]:
    """Price each holding against `quotes` (cache blobs keyed by symbol).

    `fx` resolves a currency to the current `FxRate`. Default: only the base
    currency resolves — a foreign position then reports native numbers only and
    is left out of the base totals (rule 4), which is the honest answer when
    nobody could tell us a rate.
    """
    resolve = fx or default_fx
    valued: list[ValuedHolding] = []

    for symbol, h in holdings.items():
        price = usable_price(quotes.get(symbol))
        value = price * h.qty if price is not None else None
        pl = (value - h.cost_basis) if value is not None else None
        pl_pct = (pl / h.cost_basis * 100) if (pl is not None and h.cost_basis) else None

        v = ValuedHolding(
            symbol=symbol,
            qty=h.qty,
            avg_cost=h.avg_cost,
            cost_basis=h.cost_basis,
            currency=h.currency,
            current_price=price,
            current_value=value,
            unrealized_pl=pl,
            unrealized_pl_pct=pl_pct,
        )

        rate = resolve(h.currency)
        if rate is not None:
            v.fx_rate = rate.rate
            v.fx_source = rate.source
            v.fx_as_of = rate.as_of
            v.fx_estimated = rate.estimated
            v.avg_fx_rate = h.avg_fx_rate

            # Cost side (FX-2): each lot at its own stored rate when we have
            # them all, otherwise the current rate — and say which.
            if h.fx_complete:
                v.cost_basis_base = h.cost_basis_base
                v.cost_basis_source = (
                    "identity" if rate.source == "identity" else "historical"
                )
            else:
                v.cost_basis_base = h.cost_basis * rate.rate
                v.cost_basis_source = "current_rate"

            # Value side: always the current rate.
            if value is not None:
                v.current_value_base = value * rate.rate
                v.unrealized_pl_base = v.current_value_base - v.cost_basis_base
                v.unrealized_pl_pct_base = (
                    v.unrealized_pl_base / v.cost_basis_base * 100
                    if v.cost_basis_base else None
                )
                v.market_pl_base = (pl or 0.0) * rate.rate
                # FX component = cost_native·Rc − Σ(cost_i·R_i); unknown, not
                # zero, when the cost had to be converted at the current rate.
                v.fx_pl_base = (
                    h.cost_basis * rate.rate - v.cost_basis_base
                    if v.cost_basis_source != "current_rate" else None
                )

        valued.append(v)

    return valued


def summarize(valued: Sequence[ValuedHolding]) -> PortfolioTotals:
    """Aggregate priced, convertible positions — always in `BASE_CURRENCY`.

    Exclusions (both are "we do not know", never "it is worth nothing"):
      * no usable quote        -> `unpriced_symbols`        (rule 2)
      * no rate for its currency -> `fx_unavailable_symbols` (rule 4)

    The FX split is carried through: `market_pl + fx_pl == unrealized_pl` whenever
    `fx_pl` is not None. `fx_pl` goes None the moment one included position cannot
    separate its currency component, because summing "unknown" as 0 is exactly the
    silent number bd:shotockviz-fnn is about.

    Conversion itself happened in `value_holdings` — this function never applies a
    rate of its own, so a caller cannot accidentally aggregate mixed currencies raw
    (bd:shotockviz-sbe).
    """
    totals = PortfolioTotals()

    for v in valued:
        if not v.priced:
            totals.unpriced_symbols.append(v.symbol)
            continue
        if not v.convertible:
            totals.fx_unavailable_symbols.append(v.symbol)
            continue

        totals.total_value += v.current_value_base or 0.0
        totals.total_cost += v.cost_basis_base or 0.0
        totals.market_pl += v.market_pl_base or 0.0
        totals.priced_symbols.append(v.symbol)

        if v.fx_estimated:
            totals.fx_estimated = True
        if v.cost_basis_source == "current_rate":
            totals.cost_basis_estimated = True
        if v.fx_pl_base is None:
            totals.fx_pl = None
        elif totals.fx_pl is not None:
            totals.fx_pl += v.fx_pl_base
        if v.fx_source and v.currency.upper() not in totals.fx_rates:
            totals.fx_rates[v.currency.upper()] = FxRate(
                currency=v.currency.upper(),
                rate=v.fx_rate,
                source=v.fx_source,
                as_of=v.fx_as_of,
            )

    totals.unrealized_pl = totals.total_value - totals.total_cost
    totals.unrealized_pl_pct = (
        totals.unrealized_pl / totals.total_cost * 100 if totals.total_cost else 0.0
    )
    return totals
